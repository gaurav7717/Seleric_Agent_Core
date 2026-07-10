"""MCP gateway: the only surface any LLM client talks to. Registers identical
tool schemas regardless of transport (stdio or streamable-http) — no
client-specific branches, which is what keeps this model-agnostic.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from ..actions.broker import ActionBroker
from ..actions.executors.pipeboard import PipeboardExecutor
from ..actions.stores import ActionStore, IdempotencyStore
from ..app.insight_engine import explain as insight_explain
from ..app.models import FilterSpec, PlanError, QueryRequest, TimeRange
from ..app.query_planner import QueryPlanner
from ..app.result_store import ResultStore
from ..catalogue_service.loader import load_catalogue
from ..catalogue_service.service import CatalogueService
from ..config import Settings
from ..observability.audit import AuditLog
from ..observability.logging import new_trace_id
from ..semantic_layer.cube_client import CubeClient
from ..storage.db import Database
from . import prompts as prompt_templates

logger = structlog.get_logger()


class AppContext:
    """Wires every layer once; shared by all tools. All behavior tunables come
    from Settings (env-overridable) — nothing is fixed here."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.catalogue = CatalogueService(
            load_catalogue(settings.catalogue_dir),
            auto_threshold=settings.resolve_auto_threshold,
            ambiguous_threshold=settings.resolve_ambiguous_threshold,
            runner_up_margin=settings.resolve_runner_up_margin,
        )
        self.cube = CubeClient(settings)
        self.result_store = ResultStore(
            self.db, ttl=timedelta(minutes=settings.result_ttl_minutes)
        )
        self.planner = QueryPlanner(self.catalogue, self.cube, self.result_store)
        self.audit = AuditLog(self.db)
        self.broker = ActionBroker(
            settings=settings,
            catalogue=self.catalogue,
            cube=self.cube,
            executors={"pipeboard": PipeboardExecutor(settings)},
            action_store=ActionStore(self.db),
            idempotency=IdempotencyStore(
                self.db, window=timedelta(hours=settings.idempotency_window_hours)
            ),
            audit=self.audit,
        )
        self._freshness_cache: tuple[float, dict] | None = None

    @property
    def actor(self) -> str:
        # Single shared service token for MVP => single logical actor.
        return "service-token"

    async def freshness_report(self) -> dict:
        ttl = self.settings.freshness_cache_ttl_seconds
        if self._freshness_cache and time.monotonic() - self._freshness_cache[0] < ttl:
            return self._freshness_cache[1]
        report: dict[str, Any] = {}
        for name, view in self.catalogue.cat.views.items():
            entry: dict[str, Any] = {"expected": view.freshness.model_dump()}
            if view.date_dimension:
                try:
                    res = await self.cube.load(
                        {
                            "dimensions": [f"{name}.{view.date_dimension}"],
                            "order": {f"{name}.{view.date_dimension}": "desc"},
                            "limit": 1,
                        }
                    )
                    if res.data:
                        entry["latest_data_at"] = res.data[0].get(f"{name}.{view.date_dimension}")
                    entry["cube_last_refresh"] = res.last_refresh_time
                except Exception as exc:
                    entry["error"] = f"unavailable: {exc}"
            report[name] = entry
        payload = {"views": report, "catalogue_version": self.catalogue.version}
        self._freshness_cache = (time.monotonic(), payload)
        return payload


def build_server(settings: Settings) -> FastMCP:
    ctx = AppContext(settings)
    mcp = FastMCP(
        "seleric-mcp",
        instructions=prompt_templates.NO_HALLUCINATION_GUARD,
    )

    def _log_call(tool: str, **fields: Any) -> str:
        trace_id = new_trace_id()
        logger.info("tool_call", tool=tool, trace_id=trace_id, **fields)
        return trace_id

    # ---------------- catalogue tools ----------------

    @mcp.tool()
    def catalogue_search_metrics(query: str) -> dict:
        """Resolve business language (e.g. 'topline', 'MER') to canonical
        catalogue metric ids. Always call this before metrics_query when the
        user's term hasn't been resolved yet. Returns matches with the view
        and supported dimensions; unknown terms return suggestions only."""
        _log_call("catalogue_search_metrics", query=query)
        return ctx.catalogue.search(query).model_dump()

    @mcp.tool()
    def catalogue_get_metric(metric_id: str) -> dict:
        """Full catalogue definition for one metric id: formula, cube mapping,
        dimensions/filters, owner, access policy, freshness, caveats."""
        _log_call("catalogue_get_metric", metric_id=metric_id)
        m = ctx.catalogue.get_metric(metric_id)
        if m is None:
            result = ctx.catalogue.search(metric_id)
            return {
                "error": f"Unknown metric '{metric_id}'",
                "suggestions": [s.id for s in result.matches] + result.suggestions,
            }
        freshness = ctx.catalogue.freshness(m.cube_mapping.view)
        return {
            **m.model_dump(),
            "freshness": freshness,
            "catalogue_version": ctx.catalogue.version,
        }

    @mcp.tool()
    def catalogue_list_dimensions(view: str) -> dict:
        """Valid dimensions/filters for a Cube view (e.g. canonical_pnl,
        commerce_orders, meta_ad_performance, customer_ltv)."""
        _log_call("catalogue_list_dimensions", view=view)
        if view not in ctx.catalogue.cat.views:
            return {
                "error": f"Unknown view '{view}'",
                "valid_views": sorted(ctx.catalogue.cat.views),
            }
        return {
            "view": view,
            "dimensions": [d.model_dump() for d in ctx.catalogue.list_dimensions(view)],
            "catalogue_version": ctx.catalogue.version,
        }

    @mcp.tool()
    def catalogue_resolve_term(text: str) -> dict:
        """Resolve a single business term to its canonical metric. Returns a
        typed result: resolved (may be auto_resolved with a confidence score
        from normalization/fuzzy match) | definition_only | ambiguous (ranked
        candidates — pick the obvious one or ask) | unknown (suggestions).
        Weak matches are never silently resolved."""
        _log_call("catalogue_resolve_term", text=text)
        return ctx.catalogue.resolve_term(text).model_dump()

    # ---------------- metrics tools ----------------

    @mcp.tool()
    async def metrics_query(
        measures: list[str],
        time_range: dict,
        dimensions: list[str] | None = None,
        filters: list[dict] | None = None,
        granularity: str = "none",
        compare_period: str | None = None,
        limit: int = 500,
    ) -> dict:
        """THE only path to numeric data. measures = catalogue metric ids
        (from catalogue_search_metrics), not raw cube members. time_range is
        {"preset": "last_30d"} (today|yesterday|last_7d|last_30d|last_90d|
        this_month|last_month) or {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}.
        filters entries: {"dimension": <id>, "operator": "equals", "values":
        [...]}. granularity: day|week|month|none. compare_period:
        previous_period|previous_year. All metrics must live on one view.
        Returns rows plus a provenance block — quote its freshness when
        presenting numbers."""
        trace_id = _log_call("metrics_query", measures=measures)
        try:
            request = QueryRequest(
                measures=measures,
                dimensions=dimensions or [],
                filters=[FilterSpec.model_validate(f) for f in (filters or [])],
                time_range=TimeRange.model_validate(time_range),
                granularity=granularity,  # type: ignore[arg-type]
                compare_period=compare_period,  # type: ignore[arg-type]
                limit=limit,
            )
            return await ctx.planner.run(request)
        except PlanError as e:
            return e.to_payload()
        except Exception as e:
            logger.error("metrics_query_failed", trace_id=trace_id, error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    async def metrics_drilldown(
        parent_query_id: str,
        target_dimensions: list[str],
        additional_filters: list[dict] | None = None,
        granularity: str | None = None,
    ) -> dict:
        """Drill into a prior metrics_query result: same metrics, time range,
        compare mode and filters, regrouped by target_dimensions. Additional
        filters can only narrow the parent scope, never widen it."""
        trace_id = _log_call("metrics_drilldown", parent_query_id=parent_query_id)
        try:
            return await ctx.planner.drilldown(
                parent_query_id,
                target_dimensions,
                [FilterSpec.model_validate(f) for f in (additional_filters or [])],
                granularity,
            )
        except PlanError as e:
            return e.to_payload()
        except Exception as e:
            logger.error("metrics_drilldown_failed", trace_id=trace_id, error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    def insights_explain(query_id: str) -> dict:
        """Deterministic explanation of a stored metrics_query result: period
        totals, delta and % change, top movers with contribution %, and simple
        anomaly flags. All math happens here in code — narrate these numbers,
        do not compute your own."""
        _log_call("insights_explain", query_id=query_id)
        stored = ctx.result_store.get(query_id)
        if stored is None:
            return {
                "error": f"Query '{query_id}' not found or expired (results kept ~1h). "
                "Re-run metrics_query first."
            }
        request = QueryRequest.model_validate_json(stored.request_json)
        metrics = [m for mid in request.measures if (m := ctx.catalogue.get_metric(mid))]
        report = insight_explain(
            current=json.loads(stored.result_json),
            compare=json.loads(stored.compare_result_json) if stored.compare_result_json else None,
            metrics=metrics,
            cube_query=json.loads(stored.cube_query_json),
            top_movers_limit=ctx.settings.top_movers_limit,
            anomaly_sigma=ctx.settings.anomaly_sigma,
            anomaly_min_points=ctx.settings.anomaly_min_points,
        )
        report["provenance"] = json.loads(stored.provenance_json)
        return report

    # ---------------- action tools ----------------

    @mcp.tool()
    def actions_list_available(domain: str | None = None) -> dict:
        """Discover action contracts (payload schema, risk level, required
        scopes) the caller may propose. Writes never execute from this tool."""
        _log_call("actions_list_available", domain=domain)
        return {
            "actions": ctx.broker.list_available(domain, ctx.settings.caller_scopes),
            "flow": "actions_propose -> show preview to user -> user confirms -> actions_commit",
        }

    @mcp.tool()
    async def actions_propose(action_id: str, payload: dict) -> dict:
        """Validate and preview an action WITHOUT executing it. Returns the
        current state, business-rule results, and (if eligible) a single-use
        confirmation token valid ~5 minutes. Show the preview to the user and
        get an explicit yes before calling actions_commit."""
        trace_id = _log_call("actions_propose", action_id=action_id)
        try:
            preview = await ctx.broker.propose(
                action_id, payload, ctx.settings.caller_scopes, ctx.actor
            )
            return preview.model_dump(mode="json")
        except (ValueError, PermissionError) as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("actions_propose_failed", trace_id=trace_id, error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    async def actions_commit(confirmation_token: str) -> dict:
        """Execute a previously proposed action using its confirmation token.
        Only call this after the user explicitly confirmed the preview. The
        token is single-use and expires; idempotent duplicates are rejected."""
        trace_id = _log_call("actions_commit")
        try:
            result = await ctx.broker.commit(confirmation_token, ctx.actor)
            return result.model_dump(mode="json")
        except Exception as e:
            logger.error("actions_commit_failed", trace_id=trace_id, error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    def actions_status(action_request_id: str) -> dict:
        """Status and audit trail of a past action request."""
        _log_call("actions_status", action_request_id=action_request_id)
        status = ctx.broker.status(action_request_id)
        return status if status else {"error": f"Unknown action request '{action_request_id}'"}

    # ---------------- resources ----------------

    @mcp.resource("catalogue://glossary")
    def glossary_resource() -> str:
        """Browsable business glossary: term -> canonical metric."""
        lines = ["# Seleric Business Glossary", ""]
        for t in ctx.catalogue.cat.glossary:
            target = f" -> `{t.canonical_id}`" if t.canonical_id else ""
            definition = f" — {t.definition.strip()}" if t.definition else ""
            lines.append(f"- **{t.term}**{target}{definition}")
        lines.append(f"\n_catalogue version {ctx.catalogue.version}_")
        return "\n".join(lines)

    @mcp.resource("catalogue://cubes/{view}")
    def cube_view_resource(view: str) -> str:
        """Schema of one serve view: catalogued metrics and dimensions."""
        v = ctx.catalogue.cat.views.get(view)
        if v is None:
            return f"Unknown view '{view}'. Valid: {', '.join(sorted(ctx.catalogue.cat.views))}"
        metrics = [m for m in ctx.catalogue.cat.metrics.values() if m.cube_mapping.view == view]
        lines = [f"# {v.title} ({view})", "", "## Metrics"]
        for m in metrics:
            lines.append(f"- `{m.id}` ({m.aggregation}) -> {m.cube_mapping.measure}: {m.description.strip()}")
        lines.append("\n## Dimensions")
        for d in ctx.catalogue.list_dimensions(view):
            lines.append(f"- `{d.id}` -> {d.views[view]}" + (" (time)" if d.is_time else ""))
        lines.append(f"\nFreshness: {v.freshness.expected_cadence} from {v.freshness.source}")
        return "\n".join(lines)

    @mcp.resource("docs://data-freshness")
    async def freshness_resource() -> str:
        """Live freshness per view: latest data date + Cube refresh time."""
        return json.dumps(await ctx.freshness_report(), indent=2)

    # ---------------- prompts ----------------

    @mcp.prompt()
    def no_hallucination_guard() -> str:
        """Standing instruction: resolve via catalogue, never invent numbers."""
        return prompt_templates.NO_HALLUCINATION_GUARD

    @mcp.prompt()
    def explain_metric_change(query_id: str) -> str:
        """Structure a metric-change explanation strictly from insights_explain output."""
        return prompt_templates.EXPLAIN_METRIC_CHANGE.format(query_id=query_id)

    @mcp.prompt()
    def confirm_action(action_request_id: str) -> str:
        """Render an action preview as an explicit user confirmation ask."""
        return prompt_templates.CONFIRM_ACTION.format(action_request_id=action_request_id)

    # stash context for __main__ (drift check at startup, http app wiring)
    mcp._seleric_ctx = ctx  # type: ignore[attr-defined]
    return mcp
