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

async def test_order_records_campaign_and_city_in_one_query(planner, fake_cube):
    """The exact capability that failed live before this refactor: campaign +
    shipping city on the same record-grain query, one view, no manual join."""
    fake_cube.by_prefix["order_records"] = [
        {
            "order_records.order_id": "1001",
            "order_records.lt_campaign_name": "TH-383-SUSPENDER-20JUNE",
            "order_records.shipping_city": "Mumbai",
            "order_records.orders": "3",
        }
    ]
    req = QueryRequest(
        measures=["order_record_count"],
        dimensions=["lt_campaign_name", "shipping_city"],
        filters=[FilterSpec(dimension="lt_campaign_name", values=["TH-383-SUSPENDER-20JUNE"])],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert q["dimensions"] == ["order_records.lt_campaign_name", "order_records.shipping_city"]
    assert q["filters"] == [
        {
            "member": "order_records.lt_campaign_name",
            "operator": "equals",
            "values": ["TH-383-SUSPENDER-20JUNE"],
        }
    ]
    assert out["provenance"]["cube_view"] == "order_records"


async def test_order_item_records_sku_and_campaign(planner, fake_cube):
    fake_cube.by_prefix["order_item_records"] = [
        {"order_item_records.sku": "ABC123", "order_item_records.lt_campaign_name": "X"}
    ]
    req = QueryRequest(
        measures=["order_item_record_count"],
        dimensions=["sku", "lt_campaign_name", "shipping_city"],
        time_range=TimeRange(preset="last_30d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert q["dimensions"] == [
        "order_item_records.sku",
        "order_item_records.lt_campaign_name",
        "order_item_records.shipping_city",
    ]
    assert out["provenance"]["cube_view"] == "order_item_records"


async def test_order_records_and_order_item_records_compose_as_separate_parts(
    planner, fake_cube
):
    """Grain-safety: order_records and order_item_records must never be joined
    in one Cube query. Multi-view composition keeps them as separate parts."""
    fake_cube.by_prefix["order_records"] = [{"order_records.orders": "3"}]
    fake_cube.by_prefix["order_item_records"] = [{"order_item_records.line_item_count": "9"}]
    req = QueryRequest(
        measures=["order_record_count", "order_item_record_count"],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    assert out["composed"] is True
    views = {p["provenance"]["cube_view"] for p in out["parts"]}
    assert views == {"order_records", "order_item_records"}
    # Two Cube loads, never one query listing both views' measures together
    for q in fake_cube.queries:
        joined = " ".join(q.get("measures") or [])
        assert not (
            "order_records" in joined and "order_item_records" in joined
        )


async def test_order_records_rejects_dimension_not_on_view(planner):
    # sku is order_item grain, not exposed on order_records (order grain) —
    # must be rejected, not silently dropped or fanned out.
    req = QueryRequest(
        measures=["order_record_count"],
        dimensions=["sku"],
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError, match="not supported"):
        await planner.run(req)


# ---------- new P0 commerce metrics (audit §4/§5.2: previously uncatalogued) ----------

async def test_order_status_breakdown_metrics_share_commerce_orders_view(planner, fake_cube):
    """active_orders/cancelled_orders/refunded_orders/prepaid_orders/cod_orders
    were measures that existed on commerce_orders but had no catalogue entry —
    the exact failure class observed live before this refactor. Confirm they
    now resolve and can be queried alongside the pre-existing 'orders' metric."""
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "10"}]
    req = QueryRequest(
        measures=["orders", "active_orders", "cancelled_orders", "refunded_orders",
                  "prepaid_orders", "cod_orders"],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert set(q["measures"]) == {
        "commerce_orders.orders",
        "commerce_orders.active_orders",
        "commerce_orders.cancelled_orders",
        "commerce_orders.refunded_orders",
        "commerce_orders.prepaid_orders",
        "commerce_orders.prepaid_pct",  # measure_pct auto-included, mirrors mer's ratio test
        "commerce_orders.cod_orders",
    }
    assert out["provenance"]["cube_view"] == "commerce_orders"


async def test_google_roas_ratio_components_auto_included(planner, fake_cube):
    fake_cube.by_prefix["google_ad_performance"] = [
        {"google_ad_performance.conversion_value": "500", "google_ad_performance.spend": "100",
         "google_ad_performance.roas": "5"}
    ]
    req = QueryRequest(measures=["google_roas"], time_range=TimeRange(preset="last_7d"))
    await planner.run(req)
    q = fake_cube.queries[0]
    assert "google_ad_performance.conversion_value" in q["measures"]
    assert "google_ad_performance.spend" in q["measures"]


async def test_channel_net_profit_by_platform(planner, fake_cube):
    fake_cube.by_prefix["channel_pnl"] = [
        {"channel_pnl.platform": "meta", "channel_pnl.channel_net_profit": "1000"}
    ]
    req = QueryRequest(
        measures=["channel_net_profit"],
        dimensions=["platform"],
        time_range=TimeRange(preset="last_30d"),
    )
    out = await planner.run(req)
    assert out["provenance"]["cube_view"] == "channel_pnl"


async def test_session_conversion_rate_is_ratio(catalogue):
    m = catalogue.get_metric("session_conversion_rate")
    assert m.aggregation == "ratio"
    assert m.ratio_components.numerator == "session_funnel.converted_sessions"
    assert m.ratio_components.denominator == "session_funnel.sessions"


# ---------- primary-key hygiene (audit §2: 8 cubes previously had none) ----------

def test_synthesized_keys_present_in_cube_yaml():
    """CUBE_SEMANTIC_AUDIT.md §2 found 8 inline-SQL cubes with no declared
    primary_key. Confirms the composite key was added to each, mechanically,
    without touching measures/joins."""
    import yaml

    from seleric_mcp.config import PROJECT_ROOT

    expected = {
        "gold_channel_pnl.yml": "channel_pnl_key",
        "gold_payment_method_pnl.yml": "payment_method_pnl_key",
        "gold_hourly_commerce.yml": "hourly_commerce_key",
        "gold_daily_performance.yml": "daily_performance_key",
        "gold_customer_acquisition_ltv.yml": "customer_acquisition_ltv_key",
        "gold_campaign_product_performance.yml": "campaign_product_performance_key",
        "gold_meta_campaign_attribution.yml": "meta_campaign_attribution_key",
        "gold_neurohack_attribution.yml": "neurohack_attribution_key",
    }
    cubes_dir = PROJECT_ROOT / "cube" / "model" / "cubes"
    for filename, key_name in expected.items():
        doc = yaml.safe_load((cubes_dir / filename).read_text(encoding="utf-8"))
        dims = doc["cubes"][0]["dimensions"]
        pk_dims = [d for d in dims if d.get("primary_key") is True]
        assert len(pk_dims) == 1, f"{filename}: expected exactly one primary_key dimension"
        assert pk_dims[0]["name"] == key_name, f"{filename}: unexpected key name {pk_dims[0]['name']}"


def test_all_38_cubes_are_non_public():
    """CUBE_AUDIT_REPORT.md: every raw cube must be public:false; only views
    are meant to be queryable."""
    import yaml

    from seleric_mcp.config import PROJECT_ROOT

    cubes_dir = PROJECT_ROOT / "cube" / "model" / "cubes"
    cube_files = sorted(cubes_dir.glob("gold_*.yml"))
    assert len(cube_files) >= 38
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
    fake_cube.by_prefix["order_attribution"] = [
        {"order_attribution.lt_campaign_name": "X", "order_attribution.attributed_net_revenue_ex_gst": "500"}
    ]
    req = QueryRequest(
        measures=["attributed_revenue"],
        dimensions=["lt_campaign_name"],
        filters=[FilterSpec(dimension="lt_platform", values=["Meta"])],  # wrong case, as sent live
        time_range=TimeRange(preset="last_7d"),
        sort=[{"field": "attributed_revenue", "direction": "desc"}],
        limit=10,
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    # corrected to the real stored value before it ever reaches Cube
    assert q["filters"] == [
        {"member": "order_attribution.lt_platform", "operator": "equals", "values": ["meta"]}
    ]
    assert any("case-corrected" in w for w in out["warnings"])
    assert any("case-corrected" in w for w in out["provenance"]["warnings"])


async def test_unknown_filter_value_rejected_with_real_suggestions(planner):
    req = QueryRequest(
        measures=["attributed_revenue"],
        filters=[FilterSpec(dimension="lt_platform", values=["tiktok"])],  # not a real platform
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError) as exc:
        await planner.run(req)
    assert "not a known value" in str(exc.value)
    assert set(exc.value.suggestions) == {"meta", "google", "organic"}


async def test_filter_value_without_allowed_values_passes_through_unchanged(planner, fake_cube):
    """Dimensions with no declared allowed_values (the overwhelming majority —
    campaign names, cities, SKUs, etc.) must never be validated against a
    fabricated enum; any string is legitimate data."""
    fake_cube.by_prefix["order_attribution"] = [{"order_attribution.attributed_net_revenue_ex_gst": "1"}]
    req = QueryRequest(
        measures=["attributed_revenue"],
        filters=[FilterSpec(dimension="lt_campaign_name", values=["Some-Arbitrary-Campaign"])],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert q["filters"][0]["values"] == ["Some-Arbitrary-Campaign"]
    assert out["warnings"] == []


# ---------- sort / top-N ----------

async def test_sort_by_measure_overrides_default_date_order(planner, fake_cube):
    fake_cube.by_prefix["order_attribution"] = [
        {"order_attribution.lt_campaign_name": "A", "order_attribution.attributed_net_revenue_ex_gst": "900"}
    ]
    req = QueryRequest(
        measures=["attributed_revenue"],
        dimensions=["lt_campaign_name"],
        time_range=TimeRange(preset="last_7d"),
        sort=[{"field": "attributed_revenue", "direction": "desc"}],
        limit=5,
    )
    await planner.run(req)
    q = fake_cube.queries[0]
    assert q["order"] == {"order_attribution.attributed_net_revenue_ex_gst": "desc"}
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

async def test_amazon_ads_roas_ratio_components(planner, fake_cube):
    fake_cube.by_prefix["amazon_ad_performance"] = [
        {"amazon_ad_performance.attributed_sales": "800", "amazon_ad_performance.spend": "200",
         "amazon_ad_performance.ads_roas": "4"}
    ]
    req = QueryRequest(
        measures=["amazon_ads_roas", "amazon_ad_spend"],
        dimensions=["campaign_type"],
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert "amazon_ad_performance.attributed_sales" in q["measures"]
    assert q["dimensions"] == ["amazon_ad_performance.campaign_type"]
    assert out["provenance"]["cube_view"] == "amazon_ad_performance"


async def test_amazon_campaign_type_case_corrected(planner, fake_cube):
    fake_cube.by_prefix["amazon_ad_performance"] = [{"amazon_ad_performance.spend": "1"}]
    req = QueryRequest(
        measures=["amazon_ad_spend"],
        filters=[FilterSpec(dimension="campaign_type", values=["sp"])],  # real value is 'SP', uppercase
        time_range=TimeRange(preset="last_7d"),
    )
    out = await planner.run(req)
    assert fake_cube.queries[0]["filters"][0]["values"] == ["SP"]
    assert any("case-corrected" in w for w in out["warnings"])


async def test_amazon_campaign_type_rejects_unknown_value(planner):
    req = QueryRequest(
        measures=["amazon_ad_spend"],
        filters=[FilterSpec(dimension="campaign_type", values=["DSP"])],  # not SP/SB/SD
        time_range=TimeRange(preset="last_7d"),
    )
    with pytest.raises(PlanError, match="not a known value"):
        await planner.run(req)


async def test_refund_amount_by_sku(planner, fake_cube):
    fake_cube.by_prefix["refund_events"] = [{"refund_events.sku": "ABC", "refund_events.refund_amount": "150"}]
    req = QueryRequest(
        measures=["refund_amount"],
        dimensions=["sku"],
        time_range=TimeRange(preset="last_30d"),
    )
    out = await planner.run(req)
    assert out["provenance"]["cube_view"] == "refund_events"


async def test_payment_method_net_profit_by_method(planner, fake_cube):
    fake_cube.by_prefix["payment_method_pnl"] = [
        {"payment_method_pnl.payment_method": "cod", "payment_method_pnl.net_profit": "-50"}
    ]
    req = QueryRequest(
        measures=["payment_method_net_profit"],
        dimensions=["payment_method"],
        time_range=TimeRange(preset="last_30d"),
    )
    out = await planner.run(req)
    assert out["provenance"]["cube_view"] == "payment_method_pnl"


# ---------- customer purchase sequence (retention/repeat-purchase, Q226-228/235/241) ----------
# Buildable entirely from gold_fct_orders (customer_id, order_date already
# exist) — no new source data, unlike inventory/fulfilment/etc. First cube in
# this model using ClickHouse window functions; not verified against a live
# instance (no live ClickHouse access) — see the cube's own header comment.

async def test_repeat_order_rate_by_customer(planner, fake_cube):
    fake_cube.by_prefix["customer_purchase_sequence"] = [
        {"customer_purchase_sequence.repeat_orders": "30", "customer_purchase_sequence.orders": "100",
         "customer_purchase_sequence.repeat_order_rate": "30"}
    ]
    req = QueryRequest(measures=["repeat_order_rate"], time_range=TimeRange(preset="last_90d"))
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert "customer_purchase_sequence.repeat_orders" in q["measures"]
    assert "customer_purchase_sequence.orders" in q["measures"]
    assert out["provenance"]["cube_view"] == "customer_purchase_sequence"


async def test_avg_days_between_orders_filtered_to_second_purchase(planner, fake_cube):
    fake_cube.by_prefix["customer_purchase_sequence"] = [
        {"customer_purchase_sequence.avg_days_between_orders": "18"}
    ]
    req = QueryRequest(
        measures=["avg_days_between_orders"],
        filters=[FilterSpec(dimension="order_sequence_number", values=["2"])],
        time_range=TimeRange(preset="last_90d"),
    )
    out = await planner.run(req)
    q = fake_cube.queries[0]
    assert q["filters"] == [
        {"member": "customer_purchase_sequence.order_sequence_number", "operator": "equals", "values": ["2"]}
    ]
    assert out["provenance"]["cube_view"] == "customer_purchase_sequence"


def test_customer_order_sequence_cube_is_private_with_a_key():
    import yaml

    from seleric_mcp.config import PROJECT_ROOT

    doc = yaml.safe_load(
        (PROJECT_ROOT / "cube" / "model" / "cubes" / "gold_customer_order_sequence.yml").read_text(
            encoding="utf-8"
        )
    )
    cube = doc["cubes"][0]
    assert cube.get("public") is False
    pk_dims = [d for d in cube["dimensions"] if d.get("primary_key") is True]
    assert len(pk_dims) == 1
    assert pk_dims[0]["name"] == "order_sequence_key"


# ---------- currency in provenance (requirement 10 named it explicitly; declared
# on every metric's currency_default, never surfaced in build_provenance until now) ----------

async def test_currency_metric_reports_its_currency_in_provenance(planner, fake_cube):
    fake_cube.by_prefix["canonical_pnl"] = [{"canonical_pnl.net_revenue_excl_tax": "100"}]
    out = await planner.run(QueryRequest(measures=["net_revenue"], time_range=TimeRange(preset="last_7d")))
    assert out["provenance"]["currency"] == "INR"


async def test_non_currency_metric_reports_no_currency(planner, fake_cube):
    fake_cube.by_prefix["order_attribution"] = [{"order_attribution.attributed_net_revenue_ex_gst": "1"}]
    out = await planner.run(QueryRequest(measures=["attributed_orders"], time_range=TimeRange(preset="last_7d")))
    # attributed_orders is unit: count, no currency_default
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

    from seleric_mcp.config import PROJECT_ROOT

    members: dict[str, set[str]] = {}
    for f in (PROJECT_ROOT / "cube" / "model" / "views").glob("*.yml"):
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

    from seleric_mcp.config import PROJECT_ROOT

    cubes_dir = PROJECT_ROOT / "cube" / "model" / "cubes"
    missing = []
    for f in sorted(cubes_dir.glob("gold_*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        for cube in doc.get("cubes", []):
            dims = cube.get("dimensions", [])
            if not any(d.get("primary_key") is True for d in dims):
                missing.append(cube.get("name"))
    assert missing == [], f"cubes with no primary_key dimension: {missing}"
