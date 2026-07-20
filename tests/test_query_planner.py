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
    fake_cube.by_prefix["product_performance"] = [
        {"product_performance.net_line_revenue_ex_gst": "100"}
    ]
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "7"}]
    req = QueryRequest(
        measures=["product_net_revenue", "orders"], time_range=TimeRange(preset="last_7d")
    )
    out = await planner.run(req)
    assert out["composed"] is True
    assert out["composition"] == "multi_view"
    assert len(out["parts"]) == 2
    views = {p["provenance"]["cube_view"] for p in out["parts"]}
    assert views == {"product_performance", "commerce_orders"}
    assert len(fake_cube.queries) == 2
    assert all(p["query_id"].startswith("q_") for p in out["parts"])
    assert out["query_id"].startswith("q_")


async def test_multi_view_dimension_must_work_on_each_part(planner):
    """A dimension invalid for one of the views still fails (no silent drop)."""
    req = QueryRequest(
        measures=["product_net_revenue", "orders"],
        dimensions=["utm_source"],  # commerce only
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError, match="not supported"):
        await planner.run(req)


async def test_unsupported_dimension_suggests_alternate_metrics(planner):
    # aov does not support sku; suggestions must name metrics that do.
    req = QueryRequest(
        measures=["aov"],
        dimensions=["sku"],
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError) as exc:
        await planner.run(req)
    assert any("product" in s.lower() or "net_revenue" in s for s in (exc.value.suggestions or []))


async def test_pnl_cancel_revenue_geo_suggests_event_metric(planner):
    # canonical_pnl.cancel_revenue has no geo; hint must prefer event_cancel_revenue.
    req = QueryRequest(
        measures=["cancel_revenue"],
        dimensions=["shipping_region"],
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError) as exc:
        await planner.run(req)
    assert "event_cancel_revenue" in (exc.value.suggestions or [])


async def test_shipping_region_filter_is_uppercased(planner, fake_cube):
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "10"}]
    req = QueryRequest(
        measures=["orders"],
        filters=[FilterSpec(dimension="shipping_region", values=["Maharashtra"])],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert {
        "member": "commerce_orders.shipping_region",
        "operator": "equals",
        "values": ["MAHARASHTRA"],
    } in q["filters"]
    assert any("uppercased" in w for w in out["warnings"])


async def test_filter_dimension_must_be_on_view(planner):
    req = QueryRequest(
        measures=["product_net_revenue"],
        filters=[FilterSpec(dimension="utm_campaign", values=["summer"])],  # commerce only
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
    fake_cube.by_prefix["product_performance"] = [
        {"product_performance.gross_profit_ex_gst": "100",
         "product_performance.net_line_revenue_ex_gst": "500",
         "product_performance.product_gross_margin_pct": "20"}
    ]
    req = QueryRequest(
        measures=["product_gross_margin_pct"],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    # ratio components auto-included for period recomputation
    assert "product_performance.gross_profit_ex_gst" in q["measures"]
    assert "product_performance.net_line_revenue_ex_gst" in q["measures"]
    assert q["timezone"] == "Asia/Kolkata"
    assert q["timeDimensions"][0]["dateRange"] == ["2026-06-01", "2026-06-30"]
    prov = out["provenance"]
    assert prov["metric_ids"] == ["product_gross_margin_pct"]
    assert prov["cube_view"] == "product_performance"
    assert prov["freshness"]["cube_last_refresh"] == "2026-07-10T04:00:00Z"
    assert prov["catalogue_version"]
    assert out["query_id"].startswith("q_")


async def test_compare_period_fires_two_loads(planner, fake_cube):
    fake_cube.by_prefix["commerce_performance"] = [
        {"commerce_performance.commerce_net_revenue": "10"}
    ]
    req = QueryRequest(
        measures=["commerce_net_revenue"],
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


# ---------- per-metric time axis (cube_mapping.time_dimension) ----------
# Live failure 2026-07-14: "cancelled/returned orders last month" filtered the
# PLACEMENT axis (order_date) because the planner always used the view's
# date_dimension — answering "June-placed orders that ever cancelled/returned"
# (57/108) instead of "cancel/return events in June" (59/211, the dashboard
# card). Event-axis metrics declare cube_mapping.time_dimension; the planner
# must apply the date range there, and must NOT share one date filter across
# metrics on different axes.

async def test_event_axis_metric_filters_on_event_date(planner, fake_cube):
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.cancelled_orders": "59"}]
    req = QueryRequest(
        measures=["cancelled_orders"],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
    )
    out = await planner.run(req)
    td = fake_cube.queries[0]["timeDimensions"][0]
    assert td["dimension"] == "commerce_orders.event_date"
    assert td["dateRange"] == ["2026-06-01", "2026-06-30"]
    assert "error" not in out


async def test_mixed_time_axes_on_one_view_compose_as_parts(planner, fake_cube):
    """orders (placement) + cancelled_orders (event) must run as two Cube
    queries with their own date filters, not one query with a single axis."""
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "1849"}]
    req = QueryRequest(
        measures=["orders", "cancelled_orders", "refunded_orders"],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
    )
    out = await planner.run(req)
    assert out["composed"] is True
    assert out["composition"] == "multi_time_axis"
    assert len(out["parts"]) == 2
    axes = {q["timeDimensions"][0]["dimension"] for q in fake_cube.queries}
    assert axes == {"commerce_orders.order_date", "commerce_orders.event_date"}
    # Event-axis part carries both event metrics together.
    part_metrics = sorted(
        tuple(sorted(p["provenance"]["metric_ids"])) for p in out["parts"]
    )
    assert part_metrics == [("cancelled_orders", "refunded_orders"), ("orders",)]


# ---------- default brand scope injection ----------

async def test_default_brand_scope_injected_when_no_brand_filter(
    catalogue, fake_cube, result_store
):
    planner = QueryPlanner(catalogue, fake_cube, result_store, default_brand_id="20")
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "1849"}]
    req = QueryRequest(
        measures=["orders"],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
    )
    out = await planner.run(req)
    brand_filters = [
        f for f in fake_cube.queries[0].get("filters", [])
        if f["member"] == "commerce_orders.brand_id"
    ]
    assert brand_filters == [
        {"member": "commerce_orders.brand_id", "operator": "equals", "values": ["20"]}
    ]
    assert any("default brand" in w or "brand_id=20" in w for w in out["warnings"])


async def test_default_brand_scope_not_injected_when_brand_filter_given(
    catalogue, fake_cube, result_store
):
    planner = QueryPlanner(catalogue, fake_cube, result_store, default_brand_id="20")
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "10"}]
    req = QueryRequest(
        measures=["orders"],
        filters=[FilterSpec(dimension="brand_id", operator="equals", values=["31"])],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
    )
    await planner.run(req)
    values = [
        f["values"]
        for f in fake_cube.queries[0]["filters"]
        if f["member"] == "commerce_orders.brand_id"
    ]
    assert values == [["31"]]  # explicit filter wins; nothing injected


async def test_brand_name_filter_resolves_to_id(catalogue, fake_cube, result_store):
    planner = QueryPlanner(catalogue, fake_cube, result_store, default_brand_id="20")
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "10"}]
    req = QueryRequest(
        measures=["orders"],
        filters=[FilterSpec(dimension="brand_id", operator="equals", values=["Sniff Theory"])],
        time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
    )
    out = await planner.run(req)
    values = [
        f["values"]
        for f in fake_cube.queries[0]["filters"]
        if f["member"] == "commerce_orders.brand_id"
    ]
    assert values == [["26"]]
    assert any("brand_id=26" in w or "Sniff" in w for w in out["warnings"])


async def test_province_alias_resolves_to_shipping_region(planner, fake_cube):
    """NL synonyms province/state/region must map to shipping_region."""
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.total_sales": "100"}]
    out = await planner.run(
        QueryRequest(
            measures=["total_sales"],
            dimensions=["province"],
            time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
        )
    )
    assert "error" not in out
    assert fake_cube.queries[0]["dimensions"] == ["commerce_orders.shipping_region"]


async def test_all_channels_total_sales_by_state(planner, fake_cube):
    fake_cube.by_prefix["sales_all_channels"] = [
        {"sales_all_channels.total_sales": "4865459"}
    ]
    out = await planner.run(
        QueryRequest(
            measures=["total_sales_all_channels"],
            dimensions=["state"],
            time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
        )
    )
    assert "error" not in out
    assert fake_cube.queries[0]["dimensions"] == ["sales_all_channels.shipping_region"]


async def test_cube_member_measure_aliases_to_catalogue_id(planner, fake_cube):
    """Agents often paste provenance Cube members; map them to catalogue ids."""
    fake_cube.by_prefix["sales_all_channels"] = [
        {"sales_all_channels.total_sales": "2005553"}
    ]
    out = await planner.run(
        QueryRequest(
            measures=["sales_all_channels.total_sales"],
            dimensions=["sales_all_channels.shipping_region"],
            time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
            sort=[{"field": "sales_all_channels.total_sales", "direction": "desc"}],
            limit=5,
        )
    )
    assert "error" not in out
    assert out["provenance"]["metric_ids"] == ["total_sales_all_channels"]
    assert fake_cube.queries[0]["measures"] == ["sales_all_channels.total_sales"]
    assert fake_cube.queries[0]["dimensions"] == ["sales_all_channels.shipping_region"]
    assert fake_cube.queries[0]["order"] == {"sales_all_channels.total_sales": "desc"}
    assert any("mapped to catalogue metric id" in w for w in out["warnings"])


async def test_sales_by_state_with_order_count_composed(planner, fake_cube):
    """Top sales by state + order count: multi-view composed, sort only on sales."""
    fake_cube.by_prefix["sales_all_channels"] = [
        {
            "sales_all_channels.shipping_region": "MAHARASHTRA",
            "sales_all_channels.total_sales": "2005553",
        }
    ]
    fake_cube.by_prefix["orders_all_channels"] = [
        {
            "orders_all_channels.shipping_region": "MAHARASHTRA",
            "orders_all_channels.orders": "412",
        }
    ]
    out = await planner.run(
        QueryRequest(
            measures=["total_sales_all_channels", "total_orders"],
            dimensions=["shipping_region"],
            time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
            sort=[{"field": "total_sales_all_channels", "direction": "desc"}],
            limit=5,
        )
    )
    assert out["composed"] is True
    assert out["composition"] == "multi_view"
    assert set(out["provenance"]["metric_ids"]) == {
        "total_sales_all_channels",
        "total_orders",
    }
    assert len(fake_cube.queries) == 2
    sales_q = next(q for q in fake_cube.queries if "sales_all_channels.total_sales" in q["measures"])
    orders_q = next(q for q in fake_cube.queries if "orders_all_channels.orders" in q["measures"])
    assert sales_q["order"] == {"sales_all_channels.total_sales": "desc"}
    assert sales_q["limit"] == 5
    # Orders part must not fail because sort targeted the other view's metric.
    assert "order" not in orders_q or "orders_all_channels.orders" in (orders_q.get("order") or {})


async def test_cube_member_orders_measure_aliases(planner, fake_cube):
    fake_cube.by_prefix["orders_all_channels"] = [{"orders_all_channels.orders": "12"}]
    out = await planner.run(
        QueryRequest(
            measures=["orders_all_channels.orders"],
            dimensions=["shipping_region"],
            time_range=TimeRange(preset="today"),
        )
    )
    assert out["provenance"]["metric_ids"] == ["total_orders"]
    assert any("mapped to catalogue metric id" in w for w in out["warnings"])


async def test_cube_member_brand_filter_does_not_double_inject(planner, fake_cube):
    """Cube-qualified brand_id must count as an explicit brand filter."""
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "3"}]
    planner.default_brand_id = "20"
    out = await planner.run(
        QueryRequest(
            measures=["orders"],
            filters=[FilterSpec(dimension="commerce_orders.brand_id", values=["26"])],
            time_range=TimeRange(preset="today"),
        )
    )
    assert "error" not in out
    brand_filters = [
        f for f in fake_cube.queries[0]["filters"]
        if f["member"] == "commerce_orders.brand_id"
    ]
    assert len(brand_filters) == 1
    assert brand_filters[0]["values"] == ["26"]
    assert not any("No brand filter given" in w for w in out["warnings"])


async def test_deprecated_cube_alias_resolves(planner, fake_cube):
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "9"}]
    out = await planner.run(
        QueryRequest(
            measures=["daily_pnl.orders_created"],
            time_range=TimeRange(preset="today"),
        )
    )
    assert out["provenance"]["metric_ids"] == ["orders"]
    assert any("deprecated alias" in w for w in out["warnings"])


async def test_sort_by_ratio_component_cube_member(planner, fake_cube):
    fake_cube.by_prefix["customer_ltv"] = [
        {
            "customer_ltv.repeat_rate": "0.2",
            "customer_ltv.repeat_customers": "10",
            "customer_ltv.customers": "50",
        }
    ]
    out = await planner.run(
        QueryRequest(
            measures=["repeat_rate"],
            sort=[{"field": "customer_ltv.customers", "direction": "desc"}],
            time_range=TimeRange(preset="last_7d"),
        )
    )
    assert "error" not in out
    assert fake_cube.queries[0]["order"] == {"customer_ltv.customers": "desc"}
