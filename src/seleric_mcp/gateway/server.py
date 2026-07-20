"""MCP gateway: the only surface any LLM client talks to. Registers identical
tool schemas regardless of transport (stdio or streamable-http) — no
client-specific branches, which is what keeps this model-agnostic.

NOTE: Do not add ``from __future__ import annotations`` here. FastMCP 1.12
inspects parameter annotations with ``issubclass(..., Context)`` and crashes
when annotations are stringified (PEP 563).
"""

import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from mcp.server.fastmcp import FastMCP

from ..actions.broker import ActionBroker
from ..actions.executors.pipeboard import PipeboardExecutor
from ..actions.stores import ActionStore, IdempotencyStore
from ..app.insight_engine import explain as insight_explain
from ..app.models import FilterSpec, PlanError, QueryRequest, SortSpec, TimeRange
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

_CADENCE_LAG_RE = re.compile(r"T-(\d+)")


def _cadence_lag_days(cadence: str) -> int | None:
    """Expected data lag in days from a views.yaml expected_cadence string.
    'daily, T-1, IST' -> 1; hourly cadences -> 0. None means the cadence is
    unparseable and the view is never gated on freshness."""
    if not cadence:
        return None
    m = _CADENCE_LAG_RE.search(cadence)
    if m:
        return int(m.group(1))
    low = cadence.lower()
    if "hourly" in low:
        return 0
    if "daily" in low:
        return 1
    return None


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
        self.planner = QueryPlanner(
            self.catalogue,
            self.cube,
            self.result_store,
            default_brand_id=settings.default_brand_id or None,
        )
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
        self._view_latest_cache: dict[str, tuple[float, str | None]] = {}

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

    async def _latest_data_date(self, view_name: str) -> str | None:
        """Latest value of the view's date dimension via a 1-row Cube probe
        (cached per view for freshness_cache_ttl_seconds). None when the view
        has no date dimension or the probe fails."""
        ttl = self.settings.freshness_cache_ttl_seconds
        cached = self._view_latest_cache.get(view_name)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
        view = self.catalogue.cat.views.get(view_name)
        latest: str | None = None
        if view is not None and view.date_dimension:
            member = f"{view_name}.{view.date_dimension}"
            try:
                res = await self.cube.load(
                    {"dimensions": [member], "order": {member: "desc"}, "limit": 1}
                )
                if res.data:
                    latest = res.data[0].get(member)
            except Exception:
                latest = None
        self._view_latest_cache[view_name] = (time.monotonic(), latest)
        return latest

    async def stale_views(self, metric_ids: list[str]) -> dict[str, dict]:
        """Fail-closed freshness gate: map of view -> staleness detail for every
        view backing the requested metrics whose latest data date is POSITIVELY
        known to be older than its cadence allows (+ grace). Only the views
        actually queried are probed. Views whose freshness could not be
        determined (probe error, unparseable cadence, no date dimension) are
        NOT blocked — only confirmed staleness refuses, so a transient Cube
        hiccup cannot take every metric down."""
        if not self.settings.freshness_enforcement:
            return {}
        views_needed: dict[str, list[str]] = {}
        for mid in metric_ids:
            resolved = self.catalogue.resolve_metric_id(mid)
            canonical = resolved[0] if resolved else mid
            m = self.catalogue.get_metric(canonical)
            if m is not None:
                views_needed.setdefault(m.cube_mapping.view, []).append(canonical)
        if not views_needed:
            return {}
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        stale: dict[str, dict] = {}
        for view_name, mids in views_needed.items():
            view = self.catalogue.cat.views.get(view_name)
            if view is None:
                continue
            cadence = view.freshness.expected_cadence if view.freshness else ""
            lag = _cadence_lag_days(cadence)
            if lag is None:
                continue
            latest_raw = await self._latest_data_date(view_name)
            if not latest_raw:
                continue
            try:
                latest = date.fromisoformat(str(latest_raw)[:10])
            except ValueError:
                continue
            allowed = lag + self.settings.freshness_grace_days
            if (today_ist - latest).days > allowed:
                stale[view_name] = {
                    "metrics": mids,
                    "latest_data_at": str(latest_raw),
                    "expected_cadence": cadence,
                    "allowed_lag_days": allowed,
                    "days_behind": (today_ist - latest).days,
                }
        return stale


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

    def _check_metric_scopes(metric_ids: list[str]) -> dict | None:
        """Enforce access_policy.scopes (declared on every catalogue metric)
        against the caller's granted scopes — mirrors the existing check for
        actions (actions/broker.py: scopes_required <= caller_scopes), which
        previously had no metrics_query/metrics_drilldown equivalent despite
        every metric declaring a scopes list. Returns an access-denied payload
        if any requested metric requires a scope the caller doesn't have;
        None if authorized. Unknown metric ids are skipped here — QueryPlanner
        raises its own clear PlanError for those.

        NOTE: access_policy.roles_allowed (e.g. net_profit: [exec, finance])
        is NOT enforced here — this deployment is a single shared
        service-token actor (see AppContext.actor) with no per-caller role
        identity to check it against. roles_allowed stays informational/
        documentation-only until this service authenticates individual users
        rather than one shared token; only the scopes-based check below is a
        real enforcement point today.
        """
        denied: dict[str, list[str]] = {}
        for mid in metric_ids:
            resolved = ctx.catalogue.resolve_metric_id(mid)
            canonical = resolved[0] if resolved else mid
            m = ctx.catalogue.get_metric(canonical)
            if m is None:
                continue
            missing = sorted(set(m.access_policy.scopes) - ctx.settings.caller_scopes)
            if missing:
                denied[canonical] = missing
        if not denied:
            return None
        return {
            "error": "Caller lacks required scopes for one or more requested metrics.",
            "missing_scopes_by_metric": denied,
            "caller_scopes": sorted(ctx.settings.caller_scopes),
        }

    def _stale_refusal(stale: dict[str, dict]) -> dict:
        """Structured fail-closed refusal for stale data. The agent must relay
        the refusal, not invent numbers."""
        return {
            "error": "stale_data",
            "policy": "fail_closed",
            "detail": (
                "Data behind one or more requested metrics is older than its "
                "freshness SLA allows; numeric answers are refused until the "
                "pipeline catches up. Tell the user which views are stale and "
                "as-of when data is available — do not estimate values."
            ),
            "stale_views": stale,
        }

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
        dimensions/filters, owner, access policy, freshness, caveats.

        Pass a catalogue metric id (e.g. total_sales_all_channels). Cube
        members from provenance (e.g. sales_all_channels.total_sales) are
        accepted and remapped, but NEVER pass cube_mapping.measure into
        metrics_query — always use the returned metric id / query_as.measures.
        """
        _log_call("catalogue_get_metric", metric_id=metric_id)
        resolved = ctx.catalogue.resolve_metric_id(metric_id)
        if resolved is None:
            result = ctx.catalogue.search(metric_id)
            return {
                "error": f"Unknown metric '{metric_id}'",
                "suggestions": [s.id for s in result.matches] + result.suggestions,
            }
        canonical_id, alias_notice = resolved
        m = ctx.catalogue.get_metric(canonical_id)
        assert m is not None
        freshness = ctx.catalogue.freshness(m.cube_mapping.view)
        out = {
            **m.model_dump(),
            "freshness": freshness,
            "catalogue_version": ctx.catalogue.version,
            # Agent-facing: use these ids in metrics_query — not cube_mapping.
            "query_as": {"measures": [m.id]},
        }
        if alias_notice:
            out["resolved_from"] = metric_id
            out["resolution_notice"] = alias_notice
        return out

    @mcp.tool()
    def catalogue_list_dimensions(view: str) -> dict:
        """Valid dimensions/filters for a Cube view (e.g. canonical_pnl,
        commerce_orders, meta_ad_performance, customer_ltv).

        Use each dimension's catalogue ``id`` (e.g. shipping_region) in
        metrics_query dimensions/filters — not the views[view] Cube member.
        """
        _log_call("catalogue_list_dimensions", view=view)
        if view not in ctx.catalogue.cat.views:
            return {
                "error": f"Unknown view '{view}'",
                "valid_views": sorted(ctx.catalogue.cat.views),
            }
        return {
            "view": view,
            "dimensions": [d.model_dump() for d in ctx.catalogue.list_dimensions(view)],
            "note": "Pass dimension id (not views[*] Cube members) to metrics_query.",
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

    @mcp.tool()
    def catalogue_resolve_brand(text: str) -> dict:
        """Resolve a brand name/code to brand_id for metrics_query filters.
        Default brand is Tilting Heads (20) when the user does not name one.
        When they say Sniff Theory / Urthend / Mannmore / Billy / etc., resolve
        here and pass filters=[{dimension:'brand_id', operator:'equals',
        values:[brand_id]}]. Never invent a brand_id."""
        _log_call("catalogue_resolve_brand", text=text)
        return ctx.catalogue.resolve_brand(text).model_dump()

    @mcp.tool()
    def catalogue_list_brands() -> dict:
        """List active brands the agent can query (id, name, code, aliases).
        Default brand is Tilting Heads unless the user names another."""
        _log_call("catalogue_list_brands")
        default = ctx.catalogue.default_brand()
        return {
            "default_brand_id": (
                ctx.catalogue.cat.brands.default_brand_id if ctx.catalogue.cat.brands else "20"
            ),
            "default_brand_name": default.name if default else "Tilting Heads",
            "brands": [b.model_dump() for b in ctx.catalogue.list_brands()],
            "catalogue_version": ctx.catalogue.version,
        }

    # ---------------- metrics tools ----------------

    @mcp.tool()
    async def metrics_query(
        measures: list[str],
        time_range: dict,
        dimensions: list[str] | None = None,
        filters: list[dict] | None = None,
        granularity: str = "none",
        compare_period: str | None = None,
        sort: list[dict] | None = None,
        limit: int | None = None,
    ) -> dict:
        """THE only path to numeric data. measures = catalogue metric ids
        (from catalogue_search_metrics), not raw cube members. Cube members
        like sales_all_channels.total_sales are auto-mapped when possible, but
        always prefer catalogue ids (total_sales_all_channels, total_orders).
        dimensions / filters.dimension / sort.field are also catalogue ids
        (e.g. shipping_region), not view.qualified members. time_range is
        {"preset": "last_30d"} (today|yesterday|last_7d|last_30d|last_90d|
        this_month|last_month) or {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}.
        filters entries: {"dimension": <id>, "operator": "equals", "values":
        [...]}. granularity: day|week|month|none. compare_period:
        previous_period|previous_year. sort entries: {"field": <metric_id or
        dimension_id used in this query>, "direction": "asc"|"desc"} — for
        "top N" / "bottom N" questions, sort by the relevant metric desc/asc
        and set limit=N; omit limit for the full result set (no default row
        cap). Without sort, row order is unspecified except when a time
        granularity is set (defaults to ascending by date). Metrics on
        different views are run as parallel single-view queries and returned
        with composed=true and a parts[] array — narrate each part separately
        (do not join across views). Same-view metrics return the usual rows +
        provenance. For top sales by state with order count (all channels):
        measures=[total_sales_all_channels, total_orders],
        dimensions=[shipping_region], sort by total_sales_all_channels desc.
        Quote provenance freshness when presenting numbers."""
        trace_id = _log_call("metrics_query", measures=measures)
        denial = _check_metric_scopes(measures)
        if denial:
            logger.warning("metrics_query_denied", trace_id=trace_id, measures=measures)
            return denial
        stale = await ctx.stale_views(measures)
        if stale:
            logger.warning("metrics_query_stale_blocked", trace_id=trace_id, stale_views=list(stale))
            return _stale_refusal(stale)
        try:
            request = QueryRequest(
                measures=measures,
                dimensions=dimensions or [],
                filters=[FilterSpec.model_validate(f) for f in (filters or [])],
                time_range=TimeRange.model_validate(time_range),
                granularity=granularity,  # type: ignore[arg-type]
                compare_period=compare_period,  # type: ignore[arg-type]
                sort=[SortSpec.model_validate(s) for s in (sort or [])],
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
        filters can only narrow the parent scope, never widen it.
        target_dimensions and additional_filters[].dimension are catalogue
        dimension ids (e.g. shipping_region), not Cube view.member strings.
        For composed multi-view parents, pass a part query_id from
        provenance.part_query_ids — not the parent composition id."""
        trace_id = _log_call("metrics_drilldown", parent_query_id=parent_query_id)
        stored = ctx.result_store.get(parent_query_id)
        if stored is not None:
            try:
                parent_measures = QueryRequest.model_validate_json(stored.request_json).measures
            except Exception:
                parent_measures = None  # malformed/legacy stored request — let drilldown() surface its own error
            if parent_measures is not None:
                denial = _check_metric_scopes(parent_measures)
                if denial:
                    logger.warning("metrics_drilldown_denied", trace_id=trace_id, measures=parent_measures)
                    return denial
                stale = await ctx.stale_views(parent_measures)
                if stale:
                    logger.warning(
                        "metrics_drilldown_stale_blocked", trace_id=trace_id, stale_views=list(stale)
                    )
                    return _stale_refusal(stale)
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
        do not compute your own. For composed multi-view results, pass a part
        query_id from provenance.part_query_ids (not the parent composition id)."""
        _log_call("insights_explain", query_id=query_id)
        stored = ctx.result_store.get(query_id)
        if stored is None:
            return {
                "error": f"Query '{query_id}' not found or expired (results kept ~1h). "
                "Re-run metrics_query first."
            }
        try:
            prov = json.loads(stored.provenance_json)
        except json.JSONDecodeError:
            prov = {}
        if prov.get("composed"):
            parts = ", ".join(prov.get("part_query_ids") or [])
            return {
                "error": (
                    f"Query '{query_id}' is a multi-view composition. "
                    f"Call insights_explain on a part query_id instead: {parts}"
                ),
                "part_query_ids": prov.get("part_query_ids") or [],
            }
        request = QueryRequest.model_validate_json(stored.request_json)
        metrics = []
        for mid in request.measures:
            resolved = ctx.catalogue.resolve_metric_id(mid)
            canonical = resolved[0] if resolved else mid
            m = ctx.catalogue.get_metric(canonical)
            if m is not None:
                metrics.append(m)
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

    @mcp.resource("catalogue://brands")
    def brands_resource() -> str:
        """Brand registry: default Tilting Heads; filter brand_id for others."""
        lines = [
            "# Brands",
            "",
            "Default (when user does not name a brand): **Tilting Heads** (`brand_id=20`).",
            "When the user names another brand, resolve with `catalogue_resolve_brand` "
            "and pass `filters: [{dimension: brand_id, operator: equals, values: [<id>]}]`.",
            "",
        ]
        for b in ctx.catalogue.list_brands():
            aliases = ", ".join(b.aliases[:6]) if b.aliases else "—"
            mark = " ← default" if (
                ctx.catalogue.cat.brands
                and b.id == ctx.catalogue.cat.brands.default_brand_id
            ) else ""
            lines.append(f"- **{b.name}** (`{b.id}`, code `{b.code}`){mark} — aliases: {aliases}")
        lines.append(f"\n_catalogue version {ctx.catalogue.version}_")
        return "\n".join(lines)

    @mcp.resource("catalogue://openmetadata")
    def openmetadata_registry_resource() -> str:
        """OM governance crosswalk: data products, serve FQNs, metric ↔ glossary links."""
        om = ctx.catalogue.cat.openmetadata
        if om is None:
            return "OpenMetadata registry not loaded (missing catalogue/openmetadata/registry.yaml)."
        lines = [
            "# OpenMetadata registry (governance crosswalk)",
            "",
            f"Instance: {om.instance.get('base_url', 'n/a')} ({om.instance.get('version', '')})",
            f"Agent-ready tag: `{om.agent_ready_tag}`",
            "",
            "## Data products",
        ]
        for dp in om.data_products:
            views = ", ".join(f"`{v}`" for v in dp.cube_views)
            lines.append(
                f"- **{dp.name}** ({dp.domain}) — serve `{dp.primary_serve_table}` "
                f"— contract `{dp.contract}` — cube views: {views}"
            )
            if dp.notes:
                lines.append(f"  _{dp.notes.strip()}_")
        lines.append("\n## View → serve table")
        for view_name, link in sorted(om.views.items()):
            lines.append(
                f"- `{view_name}` → `{link.serve_table}` (DP: {link.data_product})"
            )
        lines.append("\n## Metric → OM entity")
        for mid, mlink in sorted(om.metrics.items()):
            gloss = ", ".join(f"`{g}`" for g in mlink.glossary) if mlink.glossary else "—"
            om_entity = mlink.om_name or "(breakdown-only)"
            lines.append(f"- `{mid}` → OM `{om_entity}` — glossary: {gloss}")
        lines.append(f"\n_catalogue version {ctx.catalogue.version}_")
        return "\n".join(lines)

    @mcp.resource("catalogue://contracts")
    def contracts_resource() -> str:
        """Data contract summaries: grain, required columns, DQ tests per certified DP."""
        om = ctx.catalogue.cat.openmetadata
        if om is None or not om.contracts:
            return "Contracts not loaded (missing catalogue/openmetadata/contracts.yaml)."
        lines = ["# Data contracts (agent-certified surfaces)", ""]
        for cid, c in sorted(om.contracts.items()):
            grain = ", ".join(f"`{g}`" for g in c.grain) if c.grain else "—"
            lines.append(f"## {cid}")
            lines.append(f"- Serve: `{c.serve_table}` — DP: **{c.data_product}** ({c.domain})")
            lines.append(f"- Grain: {grain} — time: `{c.time_dimension or 'n/a'}` — currency: {c.currency}")
            if c.required_columns:
                cols = ", ".join(f"`{col}`" for col in c.required_columns)
                lines.append(f"- Required columns: {cols}")
            if c.quality_tests:
                lines.append(f"- DQ tests: {', '.join(c.quality_tests)}")
            if c.attribution_boundary:
                lines.append(f"- Attribution: _{c.attribution_boundary.strip()}_")
            if c.notes:
                lines.append(f"- Notes: _{c.notes.strip()}_")
            lines.append("")
        lines.append(f"_catalogue version {ctx.catalogue.version}_")
        return "\n".join(lines)

    @mcp.resource("catalogue://ontology")
    def ontology_resource() -> str:
        """Business ontology: domains, entity clusters, attribution boundary."""
        om = ctx.catalogue.cat.openmetadata
        if om is None or om.ontology is None:
            return "Ontology not loaded (missing catalogue/openmetadata/ontology.yaml)."
        onto = om.ontology
        lines = ["# Business ontology", ""]
        lines.append("## Domains")
        for domain, spec in sorted(onto.domains.items()):
            gloss = spec.get("om_glossary", "—")
            lines.append(f"- **{domain}** — OM glossary `{gloss}`")
            if spec.get("cube_views"):
                views = ", ".join(f"`{v}`" for v in spec["cube_views"])
                lines.append(f"  Cube views: {views}")
        lines.append("\n## Entity clusters")
        for cluster, spec in sorted(onto.entity_clusters.items()):
            gloss = spec.get("glossary", "—")
            metrics = spec.get("catalogue_metrics", [])
            mlist = ", ".join(f"`{m}`" for m in metrics) if metrics else "—"
            lines.append(f"- **{cluster}** — `{gloss}` — metrics: {mlist}")
        ab = onto.attribution_boundary
        if ab:
            lines.append("\n## Attribution boundary")
            excluded = ab.get("excluded_from_certified", [])
            if excluded:
                lines.append("- Excluded: " + ", ".join(f"`{x}`" for x in excluded))
            if ab.get("agent_policy"):
                lines.append(f"- Policy: _{ab['agent_policy'].strip()}_")
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
