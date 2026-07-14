"""Acceptance tests for the 2026-07-11 canonical-model additions
(CANONICAL_DATA_MODEL.md): order_records / order_item_records record-grain
views, the campaign->order->city join path (Scenario B in
mcp_query_capability_catalogue.md), and the new P0 metrics batch. Mirrors the
conventions in test_query_planner.py — see that file for the base cases
(date math, single-view enforcement, breakdown guard) this file does not repeat.
"""

from __future__ import annotations

from datetime import date

import pytest

from seleric_mcp.app.models import FilterSpec, PlanError, QueryRequest, TimeRange
from seleric_mcp.app.query_planner import QueryPlanner


@pytest.fixture()
def planner(catalogue, fake_cube, result_store):
    return QueryPlanner(catalogue, fake_cube, result_store)


# ---------- Scenario B: campaign -> order -> city ----------


# ---------- new P0 commerce metrics (audit §4/§5.2: previously uncatalogued) ----------

async def test_order_status_breakdown_metrics_share_commerce_orders_view(planner, fake_cube):
    """active_orders/cancelled_orders/refunded_orders/prepaid_orders/cod_orders
    were measures that existed on commerce_orders but had no catalogue entry —
    the exact failure class observed live before this refactor. Confirm they
    resolve and can be queried alongside 'orders'. Since the per-metric time
    axis fix (2026-07-14), placement-axis metrics (order_date) and event-axis
    metrics (event_date: cancelled/refunded) run as SEPARATE composed parts —
    one date filter must never span both axes."""
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "10"}]
    req = QueryRequest(
        measures=["orders", "active_orders", "cancelled_orders", "refunded_orders",
                  "prepaid_orders", "cod_orders"],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    assert out["composed"] is True
    assert out["composition"] == "multi_time_axis"
    by_axis = {
        q["timeDimensions"][0]["dimension"]: set(q["measures"]) for q in fake_cube.queries
    }
    assert by_axis["commerce_orders.order_date"] == {
        "commerce_orders.orders",
        "commerce_orders.active_orders",
        "commerce_orders.prepaid_orders",
        "commerce_orders.cod_orders",
    }
    assert by_axis["commerce_orders.event_date"] == {
        "commerce_orders.cancelled_orders",
        "commerce_orders.returned_orders",
    }
    assert all(p["provenance"]["cube_view"] == "commerce_orders" for p in out["parts"])


# ---------- primary-key hygiene (audit §2: 8 cubes previously had none) ----------

def test_serve_cubes_declare_primary_keys():
    """Every serve cube must declare its grain via primary_key dimensions
    (post-slim model: the 4 serve_* cubes are the whole physical surface)."""
    import yaml

    from seleric_mcp.config import cube_model_dir

    expected_keys = {
        "serve_commerce_orders.yml": {"brand_id", "order_id"},
        "serve_commerce_order_events.yml": {"brand_id", "order_id", "event_type"},
        "serve_commerce_performance_daily.yml": {"brand_id"},
        "serve_product_performance.yml": {"brand_id", "order_id", "line_item_id"},
    }
    cubes_dir = cube_model_dir() / "cubes"
    for filename, keys in expected_keys.items():
        doc = yaml.safe_load((cubes_dir / filename).read_text(encoding="utf-8"))
        dims = doc["cubes"][0]["dimensions"]
        pk = {d["name"] for d in dims if d.get("primary_key") is True}
        assert keys <= pk, f"{filename}: primary keys {pk} missing {keys - pk}"


def test_all_serve_cubes_are_non_public():
    """Every raw cube must be public:false; only views are queryable."""
    import yaml

    from seleric_mcp.config import cube_model_dir

    cubes_dir = cube_model_dir() / "cubes"
    cube_files = sorted(cubes_dir.glob("serve_*.yml"))
    assert len(cube_files) >= 4
    not_private = []
    for f in cube_files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        for cube in doc.get("cubes", []):
            if cube.get("public") is not False:
                not_private.append(cube.get("name"))
    assert not_private == [], f"cubes missing public:false: {not_private}"


# ---------- filter-value resolution (the "Meta" vs "meta" live failure) ----------
# A live query for lt_platform="Meta" (capitalized) silently returned zero rows
# instead of erroring, because ClickHouse string equality is case-sensitive and
# the real stored value is lowercase "meta" — evidenced across gold_channel_pnl,
# gold_meta_campaign_attribution, gold_neurohack_attribution's SQL, all of which
# filter/emit lt_platform/platform as 'meta'/'google'/'organic'. Fixed by
# DimensionDef.allowed_values + QueryPlanner._resolve_filter_values: exact match
# passes, case-insensitive match auto-corrects with a recorded warning, anything
# else is a hard PlanError with the real values as suggestions — never another
# silent empty result.

async def test_case_mismatched_filter_value_is_corrected_not_silently_empty(planner, fake_cube):
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "500"}]
    req = QueryRequest(
        measures=["orders"],
        filters=[FilterSpec(dimension="payment_bucket", values=["COD"])],  # wrong case, as sent live
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    # corrected to the real stored value before it ever reaches Cube
    assert {
        "member": "commerce_orders.payment_bucket",
        "operator": "equals",
        "values": ["cod"],
    } in q["filters"]
    assert any("case-corrected" in w for w in out["warnings"])
    assert any("case-corrected" in w for w in out["provenance"]["warnings"])


async def test_unknown_filter_value_rejected_with_real_suggestions(planner):
    req = QueryRequest(
        measures=["orders"],
        filters=[FilterSpec(dimension="payment_bucket", values=["bank transfer"])],  # not a bucket
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError) as exc:
        await planner.run(req)
    assert "not a known value" in str(exc.value)
    assert set(exc.value.suggestions) == {"online", "cod", "paytm card machine", "manual"}


async def test_filter_value_without_allowed_values_passes_through_unchanged(planner, fake_cube):
    """Dimensions with no declared allowed_values (the overwhelming majority —
    SKUs, cities, product titles, etc.) must never be validated against a
    fabricated enum; any string is legitimate data."""
    fake_cube.by_prefix["product_performance"] = [
        {"product_performance.net_line_revenue_ex_gst": "1"}
    ]
    req = QueryRequest(
        measures=["product_net_revenue"],
        filters=[FilterSpec(dimension="sku", values=["TH-149-SCRATCHLOUNGE"])],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    sku_filters = [f for f in q["filters"] if f["member"] == "product_performance.sku"]
    assert sku_filters[0]["values"] == ["TH-149-SCRATCHLOUNGE"]
    assert out["warnings"] == []


# ---------- sort / top-N ----------

async def test_sort_by_measure_overrides_default_date_order(planner, fake_cube):
    fake_cube.by_prefix["product_performance"] = [
        {"product_performance.product_title": "A",
         "product_performance.net_line_revenue_ex_gst": "900"}
    ]
    req = QueryRequest(
        measures=["product_net_revenue"],
        dimensions=["product_title"],
        time_range=TimeRange(preset="last_7d"),
        sort=[{"field": "product_net_revenue", "direction": "desc"}],
        limit=5,
    )
    await planner.run(req)
    q = fake_cube.queries[0]
    assert q["order"] == {"product_performance.net_line_revenue_ex_gst": "desc"}
    assert q["limit"] == 5


async def test_sort_by_dimension(planner, fake_cube):
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "1"}]
    req = QueryRequest(
        measures=["orders"],
        dimensions=["payment_method"],
        time_range=TimeRange(preset="last_7d"),
        sort=[{"field": "payment_method", "direction": "asc"}],
    )
    await planner.run(req)
    q = fake_cube.queries[0]
    assert q["order"] == {"commerce_orders.payment_method": "asc"}


async def test_sort_by_field_not_in_query_rejected(planner):
    """Sort target must be a requested measure or an already-valid dimension —
    never an invented field (requirement 9: no invented SQL/joins/fields)."""
    req = QueryRequest(
        measures=["orders"],
        time_range=TimeRange(preset="last_7d"),
        sort=[{"field": "net_revenue", "direction": "desc"}],  # different view entirely
    )
    with pytest.raises(PlanError, match="Cannot sort by"):
        await planner.run(req)


async def test_drilldown_inherits_sort(planner, fake_cube):
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "50"}]
    parent = await planner.run(
        QueryRequest(
            measures=["orders"],
            time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)),
            sort=[{"field": "orders", "direction": "desc"}],
        )
    )
    await planner.drilldown(parent["query_id"], target_dimensions=["payment_method"], additional_filters=[])
    q = fake_cube.queries[-1]
    assert q["order"] == {"commerce_orders.orders": "desc"}


# ---------- remaining P0 batch: amazon ads, refunds, payment-method P&L ----------


# ---------- customer purchase sequence (retention/repeat-purchase, Q226-228/235/241) ----------
# Buildable entirely from gold_fct_orders (customer_id, order_date already
# exist) — no new source data, unlike inventory/fulfilment/etc. First cube in
# this model using ClickHouse window functions; not verified against a live
# instance (no live ClickHouse access) — see the cube's own header comment.


# ---------- currency in provenance (requirement 10 named it explicitly; declared
# on every metric's currency_default, never surfaced in build_provenance until now) ----------

async def test_currency_metric_reports_its_currency_in_provenance(planner, fake_cube):
    fake_cube.by_prefix["product_performance"] = [
        {"product_performance.net_line_revenue_ex_gst": "100"}
    ]
    out = await planner.run(
        QueryRequest(measures=["product_net_revenue"], time_range=TimeRange(preset="last_7d"))
    )
    assert out["provenance"]["currency"] == "INR"


async def test_non_currency_metric_reports_no_currency(planner, fake_cube):
    fake_cube.by_prefix["product_performance"] = [{"product_performance.units_sold": "1"}]
    out = await planner.run(
        QueryRequest(measures=["units_sold"], time_range=TimeRange(preset="last_7d"))
    )
    # units_sold is unit: count, no currency_default
    assert out["provenance"]["currency"] is None


# ---------- catalogue <-> Cube view reconciliation (requirement 8/12: prevent
# double counting / validate against deterministic SQL) ----------
# _check_integrity (loader.py) only verifies a dimension has *some* entry for
# a view's name in DimensionDef.views — it never checks that the qualified
# member (e.g. "refund_events.order_id") is actually in that view's includes:
# list in cube/model/views/*.yml. That gap let two catalogue dimension
# mappings point at members refund_events never exposed (order_id,
# return_status) — invisible to every offline test, would only have surfaced
# as a live Cube 400 error. This test makes that class of bug fail offline,
# for every view/dimension/metric in the catalogue, not just the two found.

def _view_members() -> dict[str, set[str]]:
    import yaml

    from seleric_mcp.config import cube_model_dir

    members: dict[str, set[str]] = {}
    for f in (cube_model_dir() / "views").glob("*.yml"):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for v in doc.get("views", []):
            name = v.get("name")
            if not name:
                continue
            s: set[str] = set()
            for c in v.get("cubes", []):
                for inc in c.get("includes", []):
                    s.add(inc.get("alias") or inc.get("name") if isinstance(inc, dict) else inc)
            members[name] = s
    return members


def test_every_catalogue_dimension_mapping_exists_in_its_view(catalogue):
    view_members = _view_members()
    problems = []
    for d in catalogue.cat.dimensions.values():
        for view, qualified in d.views.items():
            member = qualified.split(".", 1)[1] if "." in qualified else qualified
            if view not in view_members or member not in view_members[view]:
                problems.append((d.id, view, qualified))
    assert problems == [], f"catalogue dimensions pointing at members their view doesn't expose: {problems}"


def test_every_catalogue_metric_mapping_exists_in_its_view(catalogue):
    view_members = _view_members()
    problems = []
    for m in catalogue.cat.metrics.values():
        needed = [m.cube_mapping.measure]
        if m.cube_mapping.measure_pct:
            needed.append(m.cube_mapping.measure_pct)
        if m.ratio_components:
            needed += [m.ratio_components.numerator, m.ratio_components.denominator]
        for qualified in needed:
            member = qualified.split(".", 1)[1] if "." in qualified else qualified
            view = m.cube_mapping.view
            if view not in view_members or member not in view_members[view]:
                problems.append((m.id, view, qualified))
    assert problems == [], f"catalogue metrics pointing at members their view doesn't expose: {problems}"


def test_every_cube_has_at_least_one_primary_key():
    """Sweep across all 39 cubes, not just the 8 originally found missing one
    (CUBE_SEMANTIC_AUDIT.md §2) — found a 9th, gold_refund_events, this way."""
    import yaml

    from seleric_mcp.config import cube_model_dir

    cubes_dir = cube_model_dir() / "cubes"
    missing = []
    for f in sorted(cubes_dir.glob("gold_*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        for cube in doc.get("cubes", []):
            dims = cube.get("dimensions", [])
            if not any(d.get("primary_key") is True for d in dims):
                missing.append(cube.get("name"))
    assert missing == [], f"cubes with no primary_key dimension: {missing}"
