from datetime import date

from seleric_mcp.app.provenance import build_provenance

REQUIRED_KEYS = {
    "query_id", "parent_query_id", "metric_ids", "cube_view", "cube_query",
    "filters_applied", "warnings", "currency", "time_range", "compare_period",
    "timezone", "row_count", "row_limit", "row_limit_hit", "freshness",
    "catalogue_version", "generated_at",
}


def test_provenance_block_shape():
    prov = build_provenance(
        query_id="q_abc",
        parent_query_id=None,
        metric_ids=["net_revenue"],
        view="canonical_pnl",
        cube_query={"measures": ["canonical_pnl.net_revenue_excl_tax"]},
        filters_applied=[],
        time_range=(date(2026, 6, 1), date(2026, 6, 30)),
        time_preset="last_30d",
        compare_range=(date(2026, 5, 2), date(2026, 5, 31)),
        compare_mode="previous_period",
        row_count=30,
        row_limit=500,
        freshness={"source": "gold.x", "expected_cadence": "daily"},
        cube_last_refresh="2026-07-10T04:00:00Z",
        catalogue_version="abc123",
        currency="INR",
    )
    assert set(prov) == REQUIRED_KEYS
    assert prov["time_range"] == {"start": "2026-06-01", "end": "2026-06-30", "preset": "last_30d"}
    assert prov["compare_period"]["mode"] == "previous_period"
    assert prov["row_limit_hit"] is False
    assert prov["freshness"]["cube_last_refresh"] == "2026-07-10T04:00:00Z"
    assert prov["timezone"] == "Asia/Kolkata"
    assert prov["currency"] == "INR"


def test_currency_defaults_to_none_when_not_provided():
    prov = build_provenance(
        query_id="q", parent_query_id=None, metric_ids=["orders"], view="commerce_orders",
        cube_query={}, filters_applied=[], time_range=(date(2026, 1, 1), date(2026, 1, 2)),
        time_preset=None, compare_range=None, compare_mode=None,
        row_count=0, row_limit=500, freshness=None, cube_last_refresh=None,
        catalogue_version="x",
    )
    assert prov["currency"] is None


def test_row_limit_hit_flag():
    prov = build_provenance(
        query_id="q", parent_query_id=None, metric_ids=[], view="v", cube_query={},
        filters_applied=[], time_range=(date(2026, 1, 1), date(2026, 1, 2)),
        time_preset=None, compare_range=None, compare_mode=None,
        row_count=500, row_limit=500, freshness=None, cube_last_refresh=None,
        catalogue_version="x",
    )
    assert prov["row_limit_hit"] is True
    assert prov["compare_period"] is None
