"""CI drift check: catalogue vs live Cube /v1/meta.

Exit 0 = no drift; 1 = broken metrics or Cube unreachable.
Run:  uv run python scripts/validate_catalogue.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from seleric_mcp.catalogue_service.loader import load_catalogue
from seleric_mcp.catalogue_service.service import CatalogueService
from seleric_mcp.catalogue_service.validate import validate_against_cube
from seleric_mcp.config import PROJECT_ROOT, load_settings
from seleric_mcp.semantic_layer.cube_client import CubeClient


async def main() -> int:
    service = CatalogueService(load_catalogue(PROJECT_ROOT / "catalogue"))
    print(f"catalogue version: {service.version} ({len(service.cat.metrics)} metrics)")
    cube = CubeClient(load_settings())
    drift = await validate_against_cube(service, cube)
    await cube.aclose()
    if drift["unreachable"]:
        print("FAIL: Cube unreachable — cannot validate")
        return 1
    if drift["broken"]:
        print(f"FAIL: drifted metrics marked broken: {drift['broken']}")
        return 1
    print(f"OK: all {drift['checked']} metrics verified against Cube meta")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
