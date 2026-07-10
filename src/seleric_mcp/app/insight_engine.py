"""Deterministic insight engine: deltas, % change, top movers, simple anomaly
flags. Pure functions over stored Cube result sets — the LLM only narrates the
returned numbers, it never computes any of this itself.
"""

from __future__ import annotations

import statistics
from typing import Any

from ..catalogue_service.loader import MetricDef

# Fallback defaults; runtime values come from Settings (env-overridable) via
# the keyword arguments on explain()/compute_top_movers()/compute_anomalies().
TOP_MOVERS_LIMIT = 10
ANOMALY_MIN_POINTS = 14
ANOMALY_SIGMA = 3.0


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sum_measure(rows: list[dict], measure: str) -> float | None:
    vals = [f for row in rows if (f := _to_float(row.get(measure))) is not None]
    return round(sum(vals), 4) if vals else None


def metric_total(rows: list[dict], metric: MetricDef) -> dict:
    """Period total for one metric. Additive: sum rows. Ratio: recompute from
    catalogued components when available; otherwise a flagged approximation
    (mean of row values) — never a sum of ratios."""
    measure = metric.cube_mapping.measure
    if metric.aggregation == "additive":
        return {"value": _sum_measure(rows, measure), "recomputed": True, "method": "sum"}
    if metric.ratio_components:
        num = _sum_measure(rows, metric.ratio_components.numerator)
        den = _sum_measure(rows, metric.ratio_components.denominator)
        if num is not None and den not in (None, 0):
            return {
                "value": round(num / den, 4),
                "recomputed": True,
                "method": f"sum({metric.ratio_components.numerator})/sum({metric.ratio_components.denominator})",
            }
    vals = [f for row in rows if (f := _to_float(row.get(measure))) is not None]
    return {
        "value": round(statistics.fmean(vals), 4) if vals else None,
        "recomputed": False,
        "method": "mean_of_rows_approximation",
    }


def compute_totals(
    current: list[dict], compare: list[dict] | None, metrics: list[MetricDef]
) -> list[dict]:
    out: list[dict] = []
    for m in metrics:
        cur = metric_total(current, m)
        entry: dict = {
            "metric_id": m.id,
            "aggregation": m.aggregation,
            "current": cur,
        }
        if compare is not None:
            prev = metric_total(compare, m)
            entry["compare"] = prev
            cv, pv = cur["value"], prev["value"]
            if cv is not None and pv is not None:
                delta = round(cv - pv, 4)
                entry["delta"] = delta
                entry["pct_change"] = round(delta / abs(pv) * 100, 2) if pv != 0 else None
        out.append(entry)
    return out


def _dimension_members(cube_query: dict) -> list[str]:
    return cube_query.get("dimensions", [])


def compute_top_movers(
    current: list[dict],
    compare: list[dict],
    metrics: list[MetricDef],
    cube_query: dict,
    *,
    limit: int = TOP_MOVERS_LIMIT,
) -> list[dict]:
    """Per dimension-tuple delta for the primary (first) metric; includes keys
    present in only one period (new / disappeared)."""
    dims = _dimension_members(cube_query)
    if not dims or not metrics:
        return []
    metric = metrics[0]
    measure = metric.cube_mapping.measure

    def keyed(rows: list[dict]) -> dict[tuple, float]:
        agg: dict[tuple, float] = {}
        for row in rows:
            key = tuple(str(row.get(d)) for d in dims)
            v = _to_float(row.get(measure))
            if v is not None:
                agg[key] = agg.get(key, 0.0) + v
        return agg

    cur_by_key = keyed(current)
    prev_by_key = keyed(compare)
    delta_total = sum(cur_by_key.values()) - sum(prev_by_key.values())

    movers: list[dict] = []
    for key in set(cur_by_key) | set(prev_by_key):
        cur_v = cur_by_key.get(key)
        prev_v = prev_by_key.get(key)
        delta = (cur_v or 0.0) - (prev_v or 0.0)
        movers.append(
            {
                "key": dict(zip(dims, key)),
                "metric_id": metric.id,
                "current": round(cur_v, 4) if cur_v is not None else None,
                "compare": round(prev_v, 4) if prev_v is not None else None,
                "delta": round(delta, 4),
                "pct_change": (
                    round(delta / abs(prev_v) * 100, 2) if prev_v not in (None, 0) else None
                ),
                "contribution_pct": (
                    round(delta / delta_total * 100, 2) if delta_total != 0 else None
                ),
                "status": (
                    "new" if prev_v is None else "disappeared" if cur_v is None else "existing"
                ),
            }
        )
    movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
    if metric.aggregation == "ratio":
        for m in movers:
            m["caveat"] = "ratio metric: per-key sums are approximations; verify with components"
    return movers[:limit]


def compute_anomalies(
    current: list[dict],
    metrics: list[MetricDef],
    cube_query: dict,
    *,
    sigma: float = ANOMALY_SIGMA,
    min_points: int = ANOMALY_MIN_POINTS,
) -> list[dict]:
    """Daily-series anomaly flags: sigma-based deviation from the period mean,
    and flat-zero runs (possible pipeline gap). Requires day granularity and
    at least min_points data points."""
    tds = cube_query.get("timeDimensions", [])
    if not tds or tds[0].get("granularity") != "day":
        return []
    date_member = tds[0]["dimension"]
    anomalies: list[dict] = []
    for m in metrics:
        measure = m.cube_mapping.measure
        series = [
            (row.get(date_member), _to_float(row.get(measure)))
            for row in current
            if row.get(date_member) is not None
        ]
        values = [v for _, v in series if v is not None]
        if len(values) < min_points:
            continue
        mean = statistics.fmean(values)
        stdev = statistics.pstdev(values)
        if stdev > 0:
            for day, v in series:
                if v is not None and abs(v - mean) > sigma * stdev:
                    anomalies.append(
                        {
                            "metric_id": m.id,
                            "type": "sigma_outlier",
                            "date": day,
                            "value": round(v, 4),
                            "period_mean": round(mean, 4),
                            "period_stdev": round(stdev, 4),
                            "sigma": round(abs(v - mean) / stdev, 2),
                        }
                    )
        # flat-zero run >= 3 consecutive days while the period is otherwise nonzero
        if any(v for v in values):
            run: list[Any] = []
            for day, v in series:
                if v == 0.0:
                    run.append(day)
                else:
                    if len(run) >= 3:
                        anomalies.append(
                            {
                                "metric_id": m.id,
                                "type": "flat_zero_run",
                                "dates": [run[0], run[-1]],
                                "days": len(run),
                                "note": "possible pipeline gap",
                            }
                        )
                    run = []
            if len(run) >= 3:
                anomalies.append(
                    {
                        "metric_id": m.id,
                        "type": "flat_zero_run",
                        "dates": [run[0], run[-1]],
                        "days": len(run),
                        "note": "possible pipeline gap",
                    }
                )
    return anomalies


def explain(
    current: list[dict],
    compare: list[dict] | None,
    metrics: list[MetricDef],
    cube_query: dict,
    *,
    top_movers_limit: int = TOP_MOVERS_LIMIT,
    anomaly_sigma: float = ANOMALY_SIGMA,
    anomaly_min_points: int = ANOMALY_MIN_POINTS,
) -> dict:
    report: dict = {
        "totals": compute_totals(current, compare, metrics),
        "top_movers": (
            compute_top_movers(current, compare, metrics, cube_query, limit=top_movers_limit)
            if compare
            else []
        ),
        "anomalies": compute_anomalies(
            current, metrics, cube_query, sigma=anomaly_sigma, min_points=anomaly_min_points
        ),
    }
    if compare is None:
        report["note"] = (
            "No compare_period on the source query — totals and anomalies only. "
            "Re-run metrics_query with compare_period for deltas and top movers."
        )
    return report
