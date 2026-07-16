"""Query planner: validated catalogue metric ids -> Cube JSON -> executed
result + provenance. Owns date-preset resolution (IST), comparison-period
derivation, multi-view composition (parallel single-view queries, never a
cross-view SQL join), and the anti-pattern guards ported from
cube_mcp/mcp_serve/server.js.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from ..catalogue_service.loader import DimensionDef, MetricDef
from ..catalogue_service.service import CatalogueService
from ..semantic_layer.cube_client import CubeClient
from .models import FilterSpec, PlanError, QueryRequest, SortSpec, TimeRange
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
    def __init__(
        self,
        catalogue: CatalogueService,
        cube: CubeClient,
        store: ResultStore,
        default_brand_id: str | None = None,
    ):
        self.catalogue = catalogue
        self.cube = cube
        self.store = store
        # When set, queries without an explicit brand_id filter are scoped to
        # this brand on views that expose a brand_id dimension (single-tenant
        # deployments must not silently aggregate other/test brands).
        self.default_brand_id = default_brand_id

    def _effective_time_dimension(self, m: MetricDef) -> str | None:
        """Fully-qualified time dimension date-range filters apply to for this
        metric: the metric's own cube_mapping.time_dimension (event-axis
        metrics) or the view's default date_dimension."""
        if m.cube_mapping.time_dimension:
            return m.cube_mapping.time_dimension
        view = m.cube_mapping.view
        view_def = self.catalogue.cat.views.get(view)
        if view_def is not None and view_def.date_dimension:
            return f"{view}.{view_def.date_dimension}"
        return None

    # ---------- validation ----------

    def _resolve_metrics(self, metric_ids: list[str]) -> list[MetricDef]:
        metrics: list[MetricDef] = []
        for mid in metric_ids:
            m = self.catalogue.get_metric(mid)
            if m is None or not m.is_queryable:
                result = self.catalogue.search(mid)
                hints = [s.id for s in result.matches] + result.suggestions
                reason = "unknown" if m is None else f"status={m.status}"
                raise PlanError(
                    f"Metric '{mid}' is not an approved catalogue metric ({reason}). "
                    "Use catalogue_search_metrics to find valid ids.",
                    suggestions=hints,
                )
            metrics.append(m)
        return metrics

    def _metrics_supporting_dimension(self, dimension_id: str, *, exclude: str | None = None) -> list[str]:
        """Catalogue ids that declare support for dimension_id (for PlanError hints)."""
        hints: list[str] = []
        for mid, m in self.catalogue.cat.metrics.items():
            if not m.is_queryable or mid == exclude:
                continue
            if dimension_id in m.supported_dimensions:
                hints.append(mid)
            if len(hints) >= 8:
                break
        return hints

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
                    alts = self._metrics_supporting_dimension(did, exclude=m.id)
                    hint = (
                        f" Metrics that support '{did}': {', '.join(alts)}."
                        if alts
                        else ""
                    )
                    raise PlanError(
                        f"Dimension '{did}' is not supported by metric '{m.id}'. "
                        f"Supported: {', '.join(m.supported_dimensions) or '(none)'}.{hint}",
                        suggestions=alts,
                    )
            if view not in dim.views:
                alts = self._metrics_supporting_dimension(did)
                raise PlanError(
                    f"Dimension '{did}' has no mapping on view '{view}'.",
                    suggestions=alts,
                )
            qualified.append(dim.views[view])
        return qualified

    def _resolve_filter_values(self, dim: DimensionDef, f: FilterSpec) -> tuple[list[str], list[str]]:
        """Case/typo-correct filter values against a dimension's declared
        allowed_values (small, stable enums only — see DimensionDef; most
        dimensions have none and pass through unchanged). Returns
        (resolved_values, warnings). Never invents a value: an exact match
        passes through silently, a case-insensitive match is corrected and
        recorded as a warning, anything else is a hard PlanError with the real
        value set as suggestions — never a silent zero-row query."""
        if dim.allowed_values is None or f.operator not in ("equals", "notEquals"):
            return f.values, []
        lower_map = {v.lower(): v for v in dim.allowed_values}
        resolved: list[str] = []
        warnings: list[str] = []
        for v in f.values:
            if v in dim.allowed_values:
                resolved.append(v)
            elif v.lower() in lower_map:
                corrected = lower_map[v.lower()]
                warnings.append(f"Filter value '{v}' on '{dim.id}' case-corrected to '{corrected}'.")
                resolved.append(corrected)
            else:
                raise PlanError(
                    f"Value '{v}' is not a known value for dimension '{dim.id}'. "
                    f"Known values: {', '.join(dim.allowed_values)}.",
                    suggestions=dim.allowed_values,
                )
        return resolved, warnings

    def _validate_filters(self, view: str, filters: list[FilterSpec]) -> tuple[list[dict], list[str]]:
        cube_filters: list[dict] = []
        warnings: list[str] = []
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
            values, value_warnings = self._resolve_filter_values(dim, f)
            warnings.extend(value_warnings)
            entry: dict = {"member": dim.views[view], "operator": f.operator}
            if values:
                entry["values"] = values
            cube_filters.append(entry)
        self._guard_breakdown(view, filters)
        return cube_filters, warnings

    def _validate_sort(self, metrics: list[MetricDef], view: str, sort: list[SortSpec]) -> dict[str, str]:
        """Returns an ordered Cube 'order' dict. A sort field must be one of
        the requested metric ids or a dimension already valid on this view —
        never an invented field, matching requirement 9."""
        order: dict[str, str] = {}
        metric_by_id = {m.id: m for m in metrics}
        for s in sort:
            if s.field in metric_by_id:
                member = metric_by_id[s.field].cube_mapping.measure
            else:
                dim = self.catalogue.cat.dimensions.get(s.field)
                if dim is None or view not in dim.views:
                    raise PlanError(
                        f"Cannot sort by '{s.field}': not one of the requested measures "
                        f"({', '.join(metric_by_id)}) and not a valid dimension on view "
                        f"'{view}'."
                    )
                member = dim.views[view]
            order[member] = s.direction
        return order

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

    @staticmethod
    def _alias_metric_ids(rows: list[dict], metrics: list[MetricDef]) -> list[dict]:
        """Copy Cube measure values onto catalogue metric id keys.

        Keeps original Cube member keys (insight_engine / drilldown still use
        them) and adds ``metric.id`` so narrators can find aliases like
        ``total_operating_cost`` even when the Cube member is shared.
        """
        if not rows:
            return rows
        aliased: list[dict] = []
        for row in rows:
            out = dict(row)
            for m in metrics:
                if m.cube_mapping.measure in row:
                    out[m.id] = row[m.cube_mapping.measure]
                if m.cube_mapping.measure_pct and m.cube_mapping.measure_pct in row:
                    out[f"{m.id}_pct"] = row[m.cube_mapping.measure_pct]
            aliased.append(out)
        return aliased

    # ---------- cube query build ----------

    def _build_cube_query(
        self,
        metrics: list[MetricDef],
        qualified_dims: list[str],
        cube_filters: list[dict],
        date_range: tuple[date, date],
        granularity: str,
        limit: int | None,
        sort_order: dict[str, str] | None = None,
        time_dimension: str | None = None,
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
        }
        if limit is not None:
            query["limit"] = limit
        if qualified_dims:
            query["dimensions"] = qualified_dims
        if cube_filters:
            query["filters"] = cube_filters

        date_dim = time_dimension or (
            f"{view}.{view_def.date_dimension}" if view_def.date_dimension else None
        )
        if date_dim:
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
        # Explicit sort (e.g. top-N: sort by a requested measure desc) always
        # wins over the default date-ascending order set above.
        if sort_order:
            query["order"] = sort_order
        return query

    # ---------- execution ----------

    async def _run_single_view(
        self,
        request: QueryRequest,
        metrics: list[MetricDef],
        parent_query_id: str | None = None,
    ) -> dict:
        """Execute one Cube load (plus optional compare) for metrics on a single view."""
        view = metrics[0].cube_mapping.view
        qualified_dims = self._validate_dimensions(metrics, request.dimensions)
        cube_filters, filter_warnings = self._validate_filters(view, request.filters)
        sort_order = self._validate_sort(metrics, view, request.sort)
        current_range = resolve_time_range(request.time_range)
        time_dimension = self._effective_time_dimension(metrics[0])

        # Default brand scope: without an explicit brand filter, aggregates on
        # brand-scoped views would silently mix other/test brands' rows.
        if self.default_brand_id and not any(f.dimension == "brand_id" for f in request.filters):
            brand_dim = self.catalogue.cat.dimensions.get("brand_id")
            member = brand_dim.views.get(view) if brand_dim else None
            if member:
                cube_filters = [
                    *cube_filters,
                    {"member": member, "operator": "equals", "values": [self.default_brand_id]},
                ]
                filter_warnings = [
                    *filter_warnings,
                    f"No brand filter given — scoped to default brand_id={self.default_brand_id}.",
                ]

        cube_query = self._build_cube_query(
            metrics, qualified_dims, cube_filters, current_range, request.granularity,
            request.limit, sort_order=sort_order, time_dimension=time_dimension,
        )

        compare_range = None
        if request.compare_period:
            compare_range = derive_compare_range(*current_range, request.compare_period)
            compare_query = self._build_cube_query(
                metrics, qualified_dims, cube_filters, compare_range,
                request.granularity, request.limit, sort_order=sort_order,
                time_dimension=time_dimension,
            )
            current_res, compare_res = await asyncio.gather(
                self.cube.load(cube_query), self.cube.load(compare_query)
            )
        else:
            current_res = await self.cube.load(cube_query)
            compare_res = None

        query_id = "q_" + uuid.uuid4().hex[:12]
        currencies = sorted({m.currency_default for m in metrics if m.currency_default})
        currency: str | list[str] | None
        if not currencies:
            currency = None
        elif len(currencies) == 1:
            currency = currencies[0]
        else:
            currency = currencies  # mixed-currency metrics in one query — report all, drop none
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
            warnings=filter_warnings,
            currency=currency,
        )

        # Expose catalogue metric ids as row keys (in addition to Cube member
        # names) so aliases like total_operating_cost → net_cogs SQL still
        # surface a column the host can narrate as "Total Operating Cost".
        rows = self._alias_metric_ids(current_res.data, metrics)
        compare_rows = (
            self._alias_metric_ids(compare_res.data, metrics) if compare_res else None
        )

        part_request = request.model_copy(update={"measures": [m.id for m in metrics]})
        self.store.save(
            StoredResult(
                query_id=query_id,
                parent_query_id=parent_query_id,
                request_json=part_request.model_dump_json(),
                cube_query_json=json.dumps(cube_query),
                result_json=json.dumps(rows),
                compare_result_json=json.dumps(compare_rows) if compare_rows else None,
                provenance_json=json.dumps(provenance),
            )
        )

        columns = sorted({k for row in rows for k in row})
        return {
            "query_id": query_id,
            "columns": columns,
            "rows": rows,
            "compare_rows": compare_rows,
            "warnings": filter_warnings,
            "provenance": provenance,
        }

    async def run(self, request: QueryRequest, parent_query_id: str | None = None) -> dict:
        """Run a metrics query. Metrics on different Cube views are executed as
        parallel single-view queries (no cross-view SQL join) and returned as
        ``composed`` parts — each part has its own rows + provenance.
        """
        metrics = self._resolve_metrics(request.measures)
        # Group by (view, effective time dimension): metrics on different views
        # can never share a Cube query, and metrics on the SAME view but a
        # different time axis (placement order_date vs event event_date) must
        # not share one date-range filter — mixing them silently answers a
        # different question (e.g. "June-placed orders that ever returned"
        # instead of "returns that happened in June").
        by_view: dict[tuple[str, str | None], list[MetricDef]] = {}
        for m in metrics:
            key = (m.cube_mapping.view, self._effective_time_dimension(m))
            by_view.setdefault(key, []).append(m)

        if len(by_view) == 1:
            return await self._run_single_view(request, metrics, parent_query_id)

        # Composition: one Cube query per (view, time axis), never a cross join.
        # Dimensions/filters must be valid on every participating view (validated
        # inside each _run_single_view); grain-unsafe mixes stay separate parts.
        parent_id = "q_" + uuid.uuid4().hex[:12]
        parts = await asyncio.gather(
            *[
                self._run_single_view(
                    request.model_copy(update={"measures": [m.id for m in ms]}),
                    ms,
                    parent_query_id=parent_id,
                )
                for _, ms in sorted(by_view.items())
            ]
        )
        part_list = list(parts)
        views = [p["provenance"]["cube_view"] for p in part_list]
        composition = "multi_view" if len(set(views)) > 1 else "multi_time_axis"
        all_metric_ids = [mid for p in part_list for mid in p["provenance"]["metric_ids"]]
        # Parent store entry so drilldown can reject with a clear message.
        self.store.save(
            StoredResult(
                query_id=parent_id,
                parent_query_id=parent_query_id,
                request_json=request.model_dump_json(),
                cube_query_json=json.dumps({"composed": True, "views": views}),
                result_json=json.dumps([{"query_id": p["query_id"]} for p in part_list]),
                compare_result_json=None,
                provenance_json=json.dumps(
                    {
                        "query_id": parent_id,
                        "composed": True,
                        "composition": composition,
                        "metric_ids": all_metric_ids,
                        "cube_views": views,
                        "part_query_ids": [p["query_id"] for p in part_list],
                        "catalogue_version": self.catalogue.version,
                    }
                ),
            )
        )
        return {
            "query_id": parent_id,
            "composed": True,
            "composition": composition,
            "parts": part_list,
            "warnings": [
                "Metrics spanned multiple Cube views or time axes (e.g. "
                "placement order_date vs event event_date); ran one query per "
                "group. Narrate each part with its own provenance — do not "
                "join or sum rows across parts (grains/axes may differ)."
            ],
            "provenance": {
                "query_id": parent_id,
                "parent_query_id": parent_query_id,
                "composed": True,
                "composition": composition,
                "metric_ids": all_metric_ids,
                "cube_views": views,
                "part_query_ids": [p["query_id"] for p in part_list],
                "catalogue_version": self.catalogue.version,
            },
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
        try:
            prov = json.loads(stored.provenance_json)
        except json.JSONDecodeError:
            prov = {}
        if prov.get("composed"):
            raise PlanError(
                f"Query '{parent_query_id}' is a multi-view composition. "
                "Call metrics_drilldown on a part query_id instead: "
                + ", ".join(prov.get("part_query_ids") or [])
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
            sort=parent.sort,
            limit=parent.limit,
        )
        return await self.run(child, parent_query_id=parent_query_id)
