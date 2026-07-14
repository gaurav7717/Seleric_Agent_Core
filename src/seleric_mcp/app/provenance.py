"""Provenance composer: the grounding block attached to every data response.
The host LLM quotes this back to the user ("as of <freshness>, using <metric>")
and it is what makes an ungrounded numeric claim detectable later.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def build_provenance(
    *,
    query_id: str,
    parent_query_id: str | None,
    metric_ids: list[str],
    view: str,
    cube_query: dict,
    filters_applied: list[dict],
    time_range: tuple[date, date],
    time_preset: str | None,
    compare_range: tuple[date, date] | None,
    compare_mode: str | None,
    row_count: int,
    row_limit: int | None,
    freshness: dict | None,
    cube_last_refresh: str | None,
    catalogue_version: str,
    warnings: list[str] | None = None,
    currency: str | list[str] | None = None,
) -> dict:
    return {
        "query_id": query_id,
        "parent_query_id": parent_query_id,
        "metric_ids": metric_ids,
        "cube_view": view,
        "cube_query": cube_query,
        "filters_applied": filters_applied,
        "warnings": warnings or [],
        "currency": currency,
        "time_range": {
            "start": time_range[0].isoformat(),
            "end": time_range[1].isoformat(),
            "preset": time_preset,
        },
        "compare_period": (
            {
                "start": compare_range[0].isoformat(),
                "end": compare_range[1].isoformat(),
                "mode": compare_mode,
            }
            if compare_range
            else None
        ),
        "timezone": "Asia/Kolkata",
        "row_count": row_count,
        "row_limit": row_limit,
        "row_limit_hit": bool(row_limit is not None and row_count >= row_limit),
        "freshness": {
            **(freshness or {}),
            "cube_last_refresh": cube_last_refresh,
        },
        "catalogue_version": catalogue_version,
        "generated_at": datetime.now(IST).isoformat(),
    }
