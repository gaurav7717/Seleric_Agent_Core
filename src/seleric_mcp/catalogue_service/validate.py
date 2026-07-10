"""Drift check: verify every catalogued cube member exists in Cube's live
/v1/meta. Metrics with missing members are marked status=broken (excluded from
the query surface) rather than silently returning wrong data. Cube being
unreachable is a warning, not a failure — stdio dev must still start.
"""

from __future__ import annotations

import structlog

from ..semantic_layer.cube_client import CubeClient
from .service import CatalogueService

logger = structlog.get_logger()


def _cube_members(meta: dict) -> set[str]:
    members: set[str] = set()
    for cube in meta.get("cubes", []):
        for kind in ("measures", "dimensions"):
            for m in cube.get(kind, []):
                members.add(m.get("name", ""))
    return members


async def validate_against_cube(service: CatalogueService, cube: CubeClient) -> dict:
    """Returns {checked, broken: [metric ids], unreachable: bool}."""
    try:
        meta = await cube.meta()
    except Exception as exc:
        logger.warning("catalogue_drift_check_skipped", error=str(exc))
        return {"checked": 0, "broken": [], "unreachable": True}

    members = _cube_members(meta)
    broken: list[str] = []
    for m in list(service.cat.metrics.values()):
        needed = [m.cube_mapping.measure]
        if m.cube_mapping.measure_pct:
            needed.append(m.cube_mapping.measure_pct)
        if m.ratio_components:
            needed += [m.ratio_components.numerator, m.ratio_components.denominator]
        for dim_id in m.supported_dimensions:
            dim = service.cat.dimensions.get(dim_id)
            if dim and m.cube_mapping.view in dim.views:
                needed.append(dim.views[m.cube_mapping.view])
        missing = [n for n in needed if n not in members]
        if missing:
            logger.warning("catalogue_metric_broken", metric=m.id, missing=missing)
            service.mark_broken(m.id)
            broken.append(m.id)
    return {"checked": len(service.cat.metrics), "broken": broken, "unreachable": False}
