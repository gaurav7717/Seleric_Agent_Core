from datetime import date

import pytest

from seleric_mcp.app.models import FilterSpec, PlanError, QueryRequest, TimeRange
from seleric_mcp.app.query_planner import (
    QueryPlanner,
    derive_compare_range,
    resolve_time_range,
)

TODAY = date(2026, 7, 10)


@pytest.fixture()
def planner(catalogue, fake_cube, result_store):
    return QueryPlanner(catalogue, fake_cube, result_store)


# ---------- date math ----------

def test_presets_exclude_partial_today():
    assert resolve_time_range(TimeRange(preset="last_7d"), TODAY) == (
        date(2026, 7, 3), date(2026, 7, 9)
    )
    assert resolve_time_range(TimeRange(preset="yesterday"), TODAY) == (
        date(2026, 7, 9), date(2026, 7, 9)
    )
    assert resolve_time_range(TimeRange(preset="today"), TODAY) == (TODAY, TODAY)
    assert resolve_time_range(TimeRange(preset="last_month"), TODAY) == (
        date(2026, 6, 1), date(2026, 6, 30)
    )
    assert resolve_time_range(TimeRange(preset="this_month"), TODAY) == (
        date(2026, 7, 1), TODAY
    )


def test_explicit_range_passthrough():
    tr = TimeRange(start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert resolve_time_range(tr, TODAY) == (date(2026, 1, 1), date(2026, 1, 31))


def test_time_range_validation():
    with pytest.raises(ValueError):
        TimeRange(preset="last_7d", start=date(2026, 1, 1), end=date(2026, 1, 2))
    with pytest.raises(ValueError):
        TimeRange(start=date(2026, 1, 5), end=date(2026, 1, 1))
    with pytest.raises(ValueError):
        TimeRange()


def test_compare_previous_period():
    start, end = derive_compare_range(date(2026, 6, 10), date(2026, 7, 9), "previous_period")
    assert (start, end) == (date(2026, 5, 11), date(2026, 6, 9))


def test_compare_previous_year():
    start, end = derive_compare_range(date(2026, 6, 1), date(2026, 6, 30), "previous_year")
    assert (start, end) == (date(2025, 6, 1), date(2025, 6, 30))


# ---------- validation ----------

async def test_unknown_metric_rejected_with_suggestions(planner):
    req = QueryRequest(measures=["net_revenu"], time_range=TimeRange(preset="last_7d"))
    with pytest.raises(PlanError) as exc:
        await planner.run(req)
    assert exc.value.suggestions


async def test_multi_view_composed(planner, fake_cube):
    """Metrics on different views run as parallel single-view parts (no join)."""
    fake_cube.by_prefix["canonical_pnl"] = [{"canonical_pnl.net_revenue_excl_tax": "100"}]
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "7"}]
    req = QueryRequest(measures=["net_revenue", "orders"], time_range=TimeRange(preset="last_7d"))
    out = await planner.run(req)
    assert out["composed"] is True
    assert out["composition"] == "multi_view"
    assert len(out["parts"]) == 2
    views = {p["provenance"]["cube_view"] for p in out["parts"]}
    assert views == {"canonical_pnl", "commerce_orders"}
    assert len(fake_cube.queries) == 2
    assert all(p["query_id"].startswith("q_") for p in out["parts"])
    assert out["query_id"].startswith("q_")


async def test_multi_view_dimension_must_work_on_each_part(planner):
    """A dimension invalid for one of the views still fails (no silent drop)."""
    req = QueryRequest(
        measures=["net_revenue", "orders"],
        dimensions=["payment_method"],  # commerce only
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError, match="not supported"):
        await planner.run(req)


async def test_unsupported_dimension_suggests_alternate_metrics(planner):
    req = QueryRequest(
        measures=["net_revenue"],
        dimensions=["shipping_city"],
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError) as exc:
        await planner.run(req)
    assert "commerce_net_revenue" in (exc.value.suggestions or [])
    assert "commerce_net_revenue" in str(exc.value)


async def test_filter_dimension_must_be_on_view(planner):
    req = QueryRequest(
        measures=["net_revenue"],
        filters=[FilterSpec(dimension="campaign_name", values=["x"])],
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError, match="not valid on view"):
        await planner.run(req)


def test_breakdown_guard():
    from seleric_mcp.app.query_planner import QueryPlanner as QP

    planner = QP.__new__(QP)
    with pytest.raises(PlanError, match="breakdown_type"):
        planner._guard_breakdown("meta_ad_breakdown", [])


# ---------- execution ----------

async def test_run_builds_cube_query_and_provenance(planner, fake_cube):
    fake_cube.by_prefix["canonical_pnl"] = [
        {"canonical_pnl.net_revenue_excl_tax": "100", "canonical_pnl.total_ad_spend": "20",
         "canonical_pnl.mer": "5"}
    ]
    req = QueryRequest(
        measures=["mer"],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    # ratio components auto-included for period recomputation
    assert "canonical_pnl.net_revenue_excl_tax" in q["measures"]
    assert "canonical_pnl.total_ad_spend" in q["measures"]
    assert q["timezone"] == "Asia/Kolkata"
    assert q["timeDimensions"][0]["dateRange"] == ["2026-06-01", "2026-06-30"]
    prov = out["provenance"]
    assert prov["metric_ids"] == ["mer"]
    assert prov["cube_view"] == "canonical_pnl"
    assert prov["freshness"]["cube_last_refresh"] == "2026-07-10T04:00:00Z"
    assert prov["catalogue_version"]
    assert out["query_id"].startswith("q_")


async def test_compare_period_fires_two_loads(planner, fake_cube):
    fake_cube.by_prefix["canonical_pnl"] = [{"canonical_pnl.net_profit": "10"}]
    req = QueryRequest(
        measures=["net_profit"],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
        compare_period="previous_period",
    )
    out = await planner.run(req)
    assert len(fake_cube.queries) == 2
    ranges = [q["timeDimensions"][0]["dateRange"] for q in fake_cube.queries]
    assert ["2026-06-01", "2026-06-30"] in ranges
    assert ["2026-05-02", "2026-05-31"] in ranges
    assert out["compare_rows"] is not None
    assert out["provenance"]["compare_period"]["mode"] == "previous_period"


async def test_drilldown_inherits_and_narrows(planner, fake_cube):
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "50"}]
    parent = await planner.run(
        QueryRequest(
            measures=["orders"],
            filters=[FilterSpec(dimension="shipping_country", values=["IN"])],
            time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
        )
    )
    child = await planner.drilldown(
        parent["query_id"],
        target_dimensions=["payment_method"],
        additional_filters=[FilterSpec(dimension="shipping_region", values=["Karnataka"])],
    )
    q = fake_cube.queries[-1]
    members = [f["member"] for f in q["filters"]]
    # parent filter retained AND new filter added (narrow-only)
    assert "commerce_orders.shipping_country" in members
    assert "commerce_orders.shipping_region" in members
    assert q["dimensions"] == ["commerce_orders.payment_method"]
    assert q["timeDimensions"][0]["dateRange"] == ["2026-06-01", "2026-06-30"]
    assert child["provenance"]["parent_query_id"] == parent["query_id"]


async def test_drilldown_unknown_parent(planner):
    with pytest.raises(PlanError, match="not found or expired"):
        await planner.drilldown("q_nope", ["payment_method"], [])
