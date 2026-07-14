"""Live smoke check against cube-serve (default http://127.0.0.1:4001).

Run:  uv run python scripts/smoke_cube.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from seleric_mcp.catalogue_service.loader import load_catalogue
from seleric_mcp.catalogue_service.service import CatalogueService
from seleric_mcp.catalogue_service.validate import validate_against_cube
from seleric_mcp.config import PROJECT_ROOT, load_settings
from seleric_mcp.semantic_layer.cube_client import CubeClient


async def main() -> int:
    settings = load_settings()
    cube = CubeClient(settings)
    print(f"Cube API: {settings.cube_api_url}")

    ok = await cube.health()
    print(f"1. /v1/meta health: {'OK' if ok else 'FAILED'}")
    if not ok:
        print("   cube-serve unreachable — start it via cube_mcp/docker-compose.yml")
        return 1

    service = CatalogueService(load_catalogue(PROJECT_ROOT / "catalogue"))
    drift = await validate_against_cube(service, cube)
    print(f"2. catalogue drift: checked={drift['checked']} broken={drift['broken']}")

    res = await cube.load(
        {
            "measures": [
                "commerce_performance.commerce_net_revenue",
                "commerce_performance.orders",
            ],
            "timeDimensions": [
                {"dimension": "commerce_performance.report_date", "dateRange": "last 7 days"}
            ],
            "limit": 10,
        }
    )
    print(f"3. commerce_performance last-7d load: {len(res.data)} row(s)")
    if res.data:
        print(json.dumps(res.data[0], indent=2))
    await cube.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
