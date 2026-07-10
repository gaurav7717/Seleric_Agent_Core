"""Query planner: validated catalogue metric ids -> Cube JSON -> executed
result + provenance. Owns date-preset resolution (IST), comparison-period
derivation, single-view enforcement, and the anti-pattern guards ported from
cube_mcp/mcp_serve/server.js.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from ..catalogue_service.loader import MetricDef
from ..catalogue_service.service import CatalogueService
from ..semantic_layer.cube_client import CubeClient
from .models import FilterSpec, PlanError, QueryRequest, TimeRange
from .provenance import build_provenance
from .result_store import ResultStore, StoredResult

IST = ZoneInfo("Asia/Kolkata")

# P&L-shaped measures must come from canonical_pnl (guard ported from server.js
# validatePnlQuery): if a metric's id looks like P&L but maps elsewhere, the
# catalogue is wrong — enforced at load; here we guard breakdown views.
BREAKDOWN_VIEWS = {"meta_ad_breakdown"}


def _ist_today() -> date:
    from datetime import datetime

    return datetime.now(IST).date()


def resolve_time_range(tr: TimeRange, today: date | None = None) -> tuple[date, date]:
    """Presets exclude the partial current day except 'today' itself."""
    t = today or _ist_today()
    if tr.preset is None:
        return tr.start, tr.end  # validated non-None by the model
    match tr.preset:
        case "today":
            return t, t
        case "yesterday":
            return t - timedelta(days=1), t - timedelta(days=1)
        case "last_7d":
            return t - timedelta(days=7), t - timedelta(days=1)
        case "last_30d":
            return t - timedelta(days=30), t - timedelta(days=1)
        case "last_90d":
            return t - timedelta(days=90), t - timedelta(days=1)
        case "this_month":
            return t.replace(day=1), t
        case "last_month":
            first_this = t.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            return last_prev.replace(day=1), last_prev
    raise PlanError(f"Unknown time preset: {tr.preset}")


def derive_compare_range(start: date, end: date, mode: str) -> tuple[date, date]:
    if mode == "previous_period":
        span = (end - start).days + 1
        return start - timedelta(days=span), end - timedelta(days=span)
    if mode == "previous_year":
        try:
            return start.replace(year=start.year - 1), end.replace(year=end.year - 1)
        except ValueError:  # Feb 29
            return start - timedelta(days=365), end - timedelta(days=365)
    raise PlanError(f"Unknown compare_period: {mode}")


class QueryPlanner:
    def __init__(self, catalogue: CatalogueService, cube: CubeClient, store: ResultStore):
        self.catalogue = catalogue
        self.cube = cube
        self.store = store

    # ---------- validation ----------

    def _resolve_metrics(self, metric_ids: list[str]) -> list[MetricDef]:
        metrics: list[MetricDef] = []
        for mid in metric_ids:
            m = self.catalogue.get_metric(mid)
            if m is None or m.status != "approved":
                result = self.catalogue.search(mid)
                hints = [s.id for s in result.matches] + result.suggestions
                reason = "unknown" if m is None else f"status={m.status}"
                raise PlanError(
                    f"Metric '{mid}' is not an approved catalogue metric ({reason}). "
                    "Use catalogue_search_metrics to find valid ids.",
                    suggestions=hints,
                )
            metrics.append(m)
        views = {m.cube_mapping.view for m in metrics}
        if len(views) > 1:
            raise PlanError(
                f"Requested metrics span multiple views ({', '.join(sorted(views))}). "
                "Query one view at a time — split into separate metrics_query calls."
            )
        return metrics

    def _validate_dimensions(self, metrics: list[MetricDef], dimension_ids: list[str]) -> list[str]:
        """Returns qualified cube dimension members."""
        view = metrics[0].cube_mapping.view
        qualified: list[str] = []
        for did in dimension_ids:
            dim = self.catalogue.cat.dimensions.get(did)
            if dim is None:
                raise PlanError(
                    f"Unknown dimension '{did}'.",
                    suggestions=[d.id for d in self.catalogue.list_dimensions(view)],
                )
            for m in metrics:
                if did not in m.supported_dimensions:
                    raise PlanError(
                        f"Dimension '{did}' is not supported by metric '{m.id}'. "
                        f"Supported: {', '.join(m.supported_dimensions)}"
                    )
            if view not in dim.views:
                raise PlanError(f"Dimension '{did}' has no mapping on view '{view}'.")
            qualified.append(dim.views[view])
        return qualified

    def _validate_filters(self, view: str, filters: list[FilterSpec]) -> list[dict]:
        cube_filters: list[dict] = []
        for f in filters:
            dim = self.catalogue.cat.dimensions.get(f.dimension)
            if dim is None or view not in dim.views:
                valid = [d.id for d in self.catalogue.list_dimensions(view)]
                raise PlanError(
                    f"Filter dimension '{f.dimension}' is not valid on view '{view}'.",
                    suggestions=valid,
                )
            if f.operator not in ("set", "notSet") and not f.values:
                raise PlanError(f"Filter on '{f.dimension}' requires values.")
            entry: dict = {"member": dim.views[view], "operator": f.operator}
            if f.values:
                entry["values"] = f.values
            cube_filters.append(entry)
        self._guard_breakdown(view, filters)
        return cube_filters

    def _guard_breakdown(self, view: str, filters: list[FilterSpec]) -> None:
        """Ported from server.js validateBreakdownQuery: breakdown views repeat
        the same spend once per breakdown_type slice; exactly one equals-filter
        on breakdown_type is mandatory or results multi-count ~8x."""
        if view not in BREAKDOWN_VIEWS:
            return
        bt = [
            f
            for f in filters
            if f.dimension == "breakdown_type" and f.operator == "equals" and len(f.values) == 1
        ]
        if len(bt) != 1:
            raise PlanError(
                f"View '{view}' requires exactly one equals-filter on breakdown_type "
                "(each type is a separate slice of the same spend; summing across "
                "types multi-counts ~8x). For total Meta spend use meta_spend."
            )

    # ---------- cube query build ----------

    def _build_cube_query(
        self,
        metrics: list[MetricDef],
        qualified_dims: list[str],
        cube_filters: list[dict],
        date_range: tuple[date, date],
        granularity: str,
        limit: int,
    ) -> dict:
        view = metrics[0].cube_mapping.view
        measures: list[str] = []
        for m in metrics:
            measures.append(m.cube_mapping.measure)
            if m.cube_mapping.measure_pct:
                measures.append(m.cube_mapping.measure_pct)
            if m.aggregation == "ratio" and m.ratio_components:
                for comp in (m.ratio_components.numerator, m.ratio_components.denominator):
                    if comp not in measures:
                        measures.append(comp)

        view_def = self.catalogue.cat.views[view]
        query: dict = {
            "measures": measures,
            "timezone": "Asia/Kolkata",
            "limit": limit,
        }
        if qualified_dims:
            query["dimensions"] = qualified_dims
        if cube_filters:
            query["filters"] = cube_filters

        if view_def.date_dimension:
            date_dim = f"{view}.{view_def.date_dimension}"
            td: dict = {
                "dimension": date_dim,
                "dateRange": [date_range[0].isoformat(), date_range[1].isoformat()],
            }
            if granularity != "none":
                td["granularity"] = granularity
                query["order"] = {date_dim: "asc"}
            query["timeDimensions"] = [td]
        elif granularity != "none":
            raise PlanError(
                f"View '{view}' has no time axis; granularity must be 'none' "
                "(time_range is ignored for this view)."
            )
        return query

    # ---------- execution ----------

    async def run(self, request: QueryRequest, parent_query_id: str | None = None) -> dict:
        metrics = self._resolve_metrics(request.measures)
        view = metrics[0].cube_mapping.view
        qualified_dims = self._validate_dimensions(metrics, request.dimensions)
        cube_filters = self._validate_filters(view, request.filters)
        current_range = resolve_time_range(request.time_range)

        cube_query = self._build_cube_query(
            metrics, qualified_dims, cube_filters, current_range, request.granularity, request.limit
        )

        compare_range = None
        if request.compare_period:
            compare_range = derive_compare_range(*current_range, request.compare_period)
            compare_query = self._build_cube_query(
                metrics, qualified_dims, cube_filters, compare_range,
                request.granularity, request.limit,
            )
            current_res, compare_res = await asyncio.gather(
                self.cube.load(cube_query), self.cube.load(compare_query)
            )
        else:
            current_res = await self.cube.load(cube_query)
            compare_res = None

        query_id = "q_" + uuid.uuid4().hex[:12]
        provenance = build_provenance(
            query_id=query_id,
            parent_query_id=parent_query_id,
            metric_ids=[m.id for m in metrics],
            view=view,
            cube_query=cube_query,
            filters_applied=[f.model_dump() for f in request.filters],
            time_range=current_range,
            time_preset=request.time_range.preset,
            compare_range=compare_range,
            compare_mode=request.compare_period,
            row_count=len(current_res.data),
            row_limit=request.limit,
            freshness=self.catalogue.freshness(view),
            cube_last_refresh=current_res.last_refresh_time,
            catalogue_version=self.catalogue.version,
        )

        self.store.save(
            StoredResult(
                query_id=query_id,
                parent_query_id=parent_query_id,
                request_json=request.model_dump_json(),
                cube_query_json=json.dumps(cube_query),
                result_json=json.dumps(current_res.data),
                compare_result_json=json.dumps(compare_res.data) if compare_res else None,
                provenance_json=json.dumps(provenance),
            )
        )

        columns = sorted({k for row in current_res.data for k in row})
        return {
            "query_id": query_id,
            "columns": columns,
            "rows": current_res.data,
            "compare_rows": compare_res.data if compare_res else None,
            "provenance": provenance,
        }

    async def drilldown(
        self,
        parent_query_id: str,
        target_dimensions: list[str],
        additional_filters: list[FilterSpec],
        granularity: str | None = None,
    ) -> dict:
        stored = self.store.get(parent_query_id)
        if stored is None:
            raise PlanError(
                f"Query '{parent_query_id}' not found or expired (results are kept ~1h). "
                "Re-run metrics_query and drill down from the fresh query_id."
            )
        parent = QueryRequest.model_validate_json(stored.request_json)
        # Child inherits time range, compare mode, and ALL parent filters; it may
        # only narrow (union of filters), never widen.
        child = QueryRequest(
            measures=parent.measures,
            dimensions=target_dimensions,
            filters=[*parent.filters, *additional_filters],
            time_range=parent.time_range,
            granularity=granularity if granularity is not None else parent.granularity,
            compare_period=parent.compare_period,
            limit=parent.limit,
        )
        return await self.run(child, parent_query_id=parent_query_id)
