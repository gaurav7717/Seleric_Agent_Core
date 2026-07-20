"""Tests for the actual MCP tool surface (gateway/server.py) — not just the
QueryPlanner underneath it. Catches interface-boundary gaps like the one found
2026-07-11: `sort` was added to QueryRequest/QueryPlanner and tested there, but
the `metrics_query` tool function itself had no `sort` parameter, so the fix
was unreachable by any real MCP caller. These tests call the actual registered
tool functions (via FastMCP's tool manager), with a fake Cube client swapped
in post-construction so no network access is needed.
"""

from __future__ import annotations

import pytest

from seleric_mcp.app.query_planner import QueryPlanner
from seleric_mcp.gateway.server import build_server


def _tool_fn(mcp, name: str):
    return mcp._tool_manager.get_tool(name).fn


@pytest.fixture()
def built_server(settings, fake_cube, result_store):
    mcp = build_server(settings)
    ctx = mcp._seleric_ctx
    # Swap the real (network-backed) planner for one wired to the fake cube,
    # reusing the server's own catalogue so this exercises the real catalogue,
    # not a test double of it.
    ctx.result_store = result_store  # keep ctx.result_store and the planner's store the
    # same instance, matching production wiring (AppContext.__init__ passes one
    # ResultStore to both) — metrics_drilldown's scope check reads ctx.result_store
    # directly, so a mismatched pair here silently breaks it (caught by
    # test_metrics_drilldown_denied_without_required_scope).
    ctx.planner = QueryPlanner(ctx.catalogue, fake_cube, ctx.result_store)
    return mcp, ctx


async def test_metrics_query_tool_accepts_and_threads_sort(built_server, fake_cube):
    mcp, ctx = built_server
    fake_cube.by_prefix["product_performance"] = [
        {"product_performance.product_title": "Scratch Lounge",
         "product_performance.net_line_revenue_ex_gst": "900"}
    ]
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(
        measures=["product_net_revenue"],
        dimensions=["product_title"],
        time_range={"start": "2026-07-09", "end": "2026-07-11"},
        sort=[{"field": "product_net_revenue", "direction": "desc"}],
        limit=10,
    )
    q = fake_cube.queries[0]
    assert q["order"] == {"product_performance.net_line_revenue_ex_gst": "desc"}
    assert q["limit"] == 10
    assert out["provenance"]["cube_view"] == "product_performance"


async def test_metrics_query_tool_without_sort_is_unchanged(built_server, fake_cube):
    """sort defaults to empty — no behavior change for every existing caller
    that doesn't pass it."""
    mcp, ctx = built_server
    fake_cube.by_prefix["commerce_orders"] = [
        {"commerce_orders.dashboard_net_sales_excl_gst": "100"}
    ]
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["commerce_net_revenue"], time_range={"preset": "last_7d"})
    assert "order" not in fake_cube.queries[0]
    assert "error" not in out


async def test_metrics_query_tool_surfaces_filter_value_case_correction(built_server, fake_cube):
    """The live 'Meta' vs 'meta' failure class, exercised through the real tool
    function end to end on payment_bucket's allowed_values."""
    mcp, ctx = built_server
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "1"}]
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(
        measures=["orders"],
        filters=[{"dimension": "payment_bucket", "operator": "equals", "values": ["COD"]}],
        time_range={"preset": "last_7d"},
    )
    bucket_filters = [
        f for f in fake_cube.queries[0]["filters"]
        if f["member"] == "commerce_orders.payment_bucket"
    ]
    assert bucket_filters[0]["values"] == ["cod"]
    assert any("case-corrected" in w for w in out["warnings"])


async def test_metrics_query_tool_rejects_unknown_metric(built_server):
    mcp, ctx = built_server
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["not_a_real_metric"], time_range={"preset": "last_7d"})
    assert "error" in out
    assert "suggestions" in out


async def test_all_registered_tools_are_the_expected_set(built_server):
    """Guards against a tool silently disappearing or a rename breaking every
    example in this test file without anything else catching it."""
    mcp, ctx = built_server
    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert names == {
        "catalogue_search_metrics",
        "catalogue_get_metric",
        "catalogue_list_dimensions",
        "catalogue_list_brands",
        "catalogue_resolve_brand",
        "catalogue_resolve_term",
        "metrics_query",
        "metrics_drilldown",
        "insights_explain",
        "actions_list_available",
        "actions_propose",
        "actions_commit",
        "actions_status",
    }


# ---------- access_policy.scopes enforcement (was declared, never checked) ----------
# Every catalogue metric declares access_policy.scopes (default ["metrics:read"]),
# and caller-scope enforcement already existed for actions (actions/broker.py) —
# but metrics_query/metrics_drilldown never checked it, so a caller with zero
# granted scopes could query any metric. Fixed via _check_metric_scopes in
# gateway/server.py, mirroring the existing actions pattern exactly.

@pytest.fixture()
def built_server_no_scopes(fake_cube, result_store, tmp_path):
    """Same as built_server but the caller has been granted no scopes at all —
    exercises the denial path without needing to alter any real metric file."""
    from seleric_mcp.config import Settings

    settings = Settings(
        cube_api_url="http://cube.test",
        seleric_api_key="test-key",
        cubejs_api_secret="",
        pipeboard_mcp_url="http://pipeboard.test",
        pipeboard_token="pb-token",
        write_enabled=False,
        mcp_service_token="svc-token",
        approval_secret="approval-secret",
        caller_scopes=frozenset(),  # <- the only difference from the `settings` fixture
        db_path=tmp_path / "test_no_scopes.db",
    )
    mcp = build_server(settings)
    ctx = mcp._seleric_ctx
    ctx.result_store = result_store  # keep ctx.result_store and the planner's store the
    # same instance, matching production wiring (AppContext.__init__ passes one
    # ResultStore to both) — metrics_drilldown's scope check reads ctx.result_store
    # directly, so a mismatched pair here silently breaks it (caught by
    # test_metrics_drilldown_denied_without_required_scope).
    ctx.planner = QueryPlanner(ctx.catalogue, fake_cube, ctx.result_store)
    return mcp, ctx


async def test_metrics_query_denied_without_required_scope(built_server_no_scopes):
    mcp, ctx = built_server_no_scopes
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["commerce_net_revenue"], time_range={"preset": "last_7d"})
    assert "error" in out
    assert out["missing_scopes_by_metric"]["commerce_net_revenue"] == ["metrics:read"]
    assert "rows" not in out  # denied before Cube was ever queried


async def test_metrics_query_allowed_with_required_scope(built_server, fake_cube):
    """The default caller_scopes fixture ({"metrics:read", ...}) covers every
    catalogue metric's default scope — confirms the check doesn't break the
    common case, only the actually-unauthorized one."""
    mcp, ctx = built_server
    fake_cube.by_prefix["commerce_orders"] = [
        {"commerce_orders.dashboard_net_sales_excl_gst": "100"}
    ]
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["commerce_net_revenue"], time_range={"preset": "last_7d"})
    assert "error" not in out
    assert out["provenance"]["cube_view"] == "commerce_orders"


async def test_metrics_drilldown_denied_without_required_scope(built_server_no_scopes, fake_cube):
    mcp, ctx = built_server_no_scopes
    from datetime import date

    from seleric_mcp.app.models import QueryRequest, TimeRange

    # Seed a stored parent query directly through the planner (bypassing the
    # tool's own scope check, which we're not testing here) so there's
    # something to drill into.
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "1"}]
    parent = await ctx.planner.run(
        QueryRequest(measures=["orders"], time_range=TimeRange(start=date(2026, 6, 1), end=date(2026, 6, 30)))
    )
    fn = _tool_fn(mcp, "metrics_drilldown")
    out = await fn(parent["query_id"], target_dimensions=["payment_method"])
    assert "error" in out
    assert out["missing_scopes_by_metric"]["orders"] == ["metrics:read"]


# ---------- freshness fail-closed gate (metrics_query / metrics_drilldown) ----------
# Views declare expected_cadence in catalogue/views.yaml (e.g. "daily, T-1, IST");
# previously freshness was only *reported* (docs://data-freshness) and never
# blocked a numeric answer. stale_views() in gateway/server.py now refuses when a
# queried view's latest data date is confirmably older than cadence lag + grace.
# Probe failures / unparseable cadences never block (fail-closed only on
# CONFIRMED staleness, so a transient Cube hiccup can't take every metric down).

@pytest.fixture()
def built_server_fake_freshness(built_server, fake_cube):
    """built_server with the AppContext's own cube client ALSO swapped to the
    fake, so the freshness probe (ctx.cube.load) is programmable — mirrors
    production wiring where planner and AppContext share one client."""
    mcp, ctx = built_server
    ctx.cube = fake_cube
    return mcp, ctx


async def test_metrics_query_refuses_when_view_confirmed_stale(built_server_fake_freshness, fake_cube):
    mcp, ctx = built_server_fake_freshness
    # Probe on commerce_orders.order_date returns an ancient date -> stale.
    fake_cube.by_prefix["commerce_orders"] = [
        {"commerce_orders.order_date": "2020-01-01T00:00:00.000", "commerce_orders.orders": "5"}
    ]
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["orders"], time_range={"preset": "last_7d"})
    assert out["error"] == "stale_data"
    assert out["policy"] == "fail_closed"
    assert "commerce_orders" in out["stale_views"]
    assert out["stale_views"]["commerce_orders"]["metrics"] == ["orders"]
    assert "rows" not in out  # refused before the planner ran


async def test_metrics_query_passes_when_view_fresh(built_server_fake_freshness, fake_cube):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    mcp, ctx = built_server_fake_freshness
    today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    fake_cube.by_prefix["commerce_orders"] = [
        {"commerce_orders.order_date": f"{today_ist}T00:00:00.000", "commerce_orders.orders": "5"}
    ]
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["orders"], time_range={"preset": "last_7d"})
    assert "error" not in out
    assert out["provenance"]["cube_view"] == "commerce_orders"


async def test_metrics_query_not_blocked_when_probe_fails(built_server_fake_freshness, fake_cube):
    """Probe failure must NOT refuse (only confirmed staleness does). The
    planner's own error surfaces instead — and it is not 'stale_data'."""
    mcp, ctx = built_server_fake_freshness
    fake_cube.fail = True
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["orders"], time_range={"preset": "last_7d"})
    assert out.get("error") != "stale_data"


async def test_freshness_enforcement_can_be_disabled(built_server_fake_freshness, fake_cube):
    import dataclasses

    mcp, ctx = built_server_fake_freshness
    ctx.settings = dataclasses.replace(ctx.settings, freshness_enforcement=False)
    fake_cube.by_prefix["commerce_orders"] = [
        {"commerce_orders.order_date": "2020-01-01T00:00:00.000", "commerce_orders.orders": "5"}
    ]
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(measures=["orders"], time_range={"preset": "last_7d"})
    assert "error" not in out  # gate off -> stale data still answers


async def test_metrics_drilldown_refuses_when_parent_view_stale(built_server_fake_freshness, fake_cube):
    from datetime import date as _date

    from seleric_mcp.app.models import QueryRequest, TimeRange

    mcp, ctx = built_server_fake_freshness
    # Seed a parent while data is "fresh" (probe cache starts empty; seed via
    # planner directly so the tool-level gate isn't exercised yet).
    fake_cube.by_prefix["commerce_orders"] = [{"commerce_orders.orders": "1"}]
    parent = await ctx.planner.run(
        QueryRequest(measures=["orders"], time_range=TimeRange(start=_date(2026, 6, 1), end=_date(2026, 6, 30)))
    )
    # Now the probe sees an ancient latest date -> drilldown must refuse.
    fake_cube.by_prefix["commerce_orders"] = [
        {"commerce_orders.order_date": "2020-01-01T00:00:00.000"}
    ]
    fn = _tool_fn(mcp, "metrics_drilldown")
    out = await fn(parent["query_id"], target_dimensions=["payment_method"])
    assert out["error"] == "stale_data"
    assert "commerce_orders" in out["stale_views"]


async def test_catalogue_get_metric_aliases_cube_member(built_server):
    mcp, ctx = built_server
    fn = _tool_fn(mcp, "catalogue_get_metric")
    out = fn("sales_all_channels.total_sales")
    assert "error" not in out
    assert out["id"] == "total_sales_all_channels"
    assert out["query_as"] == {"measures": ["total_sales_all_channels"]}
    assert out.get("resolved_from") == "sales_all_channels.total_sales"


async def test_catalogue_resolve_term_aliases_cube_member(built_server):
    mcp, ctx = built_server
    fn = _tool_fn(mcp, "catalogue_resolve_term")
    out = fn("orders_all_channels.orders")
    assert out["kind"] == "resolved"
    assert out["metric_id"] == "total_orders"


async def test_insights_explain_rejects_composed_parent(built_server, fake_cube):
    from datetime import date as _date

    from seleric_mcp.app.models import QueryRequest, TimeRange

    mcp, ctx = built_server
    fake_cube.by_prefix["sales_all_channels"] = [
        {"sales_all_channels.total_sales": "100"}
    ]
    fake_cube.by_prefix["orders_all_channels"] = [
        {"orders_all_channels.orders": "2"}
    ]
    parent = await ctx.planner.run(
        QueryRequest(
            measures=["total_sales_all_channels", "total_orders"],
            time_range=TimeRange(start=_date(2026, 6, 1), end=_date(2026, 6, 30)),
        )
    )
    assert parent.get("composed") is True
    fn = _tool_fn(mcp, "insights_explain")
    out = fn(parent["query_id"])
    assert "error" in out
    assert "multi-view composition" in out["error"]
    assert out["part_query_ids"]


async def test_scopes_apply_to_cube_member_measure_ref(built_server_no_scopes):
    mcp, ctx = built_server_no_scopes
    fn = _tool_fn(mcp, "metrics_query")
    out = await fn(
        measures=["commerce_orders.dashboard_net_sales_excl_tax"],
        time_range={"preset": "last_7d"},
    )
    # Must resolve Cube member → commerce_net_revenue and still deny scopes.
    assert "error" in out
    assert "missing_scopes_by_metric" in out
    assert "commerce_net_revenue" in out["missing_scopes_by_metric"]
