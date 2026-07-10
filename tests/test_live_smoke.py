"""Live smoke tests against a real cube-serve. Auto-skip when unreachable.

Run explicitly:  uv run pytest -m live
"""

from __future__ import annotations

import httpx
import pytest

from seleric_mcp.catalogue_service.loader import load_catalogue
from seleric_mcp.catalogue_service.service import CatalogueService
from seleric_mcp.catalogue_service.validate import validate_against_cube
from seleric_mcp.config import PROJECT_ROOT, load_settings
from seleric_mcp.semantic_layer.cube_client import CubeClient

pytestmark = pytest.mark.live


def _cube_reachable(url: str) -> bool:
    try:
        httpx.get(f"{url}/cubejs-api/v1/meta", timeout=3)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def live_settings():
    settings = load_settings()
    if not _cube_reachable(settings.cube_api_url):
        pytest.skip(f"cube-serve unreachable at {settings.cube_api_url}")
    return settings


async def test_meta_health(live_settings):
    cube = CubeClient(live_settings)
    assert await cube.health() is True
    await cube.aclose()


async def test_canonical_pnl_last_7d(live_settings):
    cube = CubeClient(live_settings)
    res = await cube.load(
        {
            "measures": ["canonical_pnl.net_profit"],
            "timeDimensions": [
                {"dimension": "canonical_pnl.report_date", "dateRange": "last 7 days"}
            ],
        }
    )
    assert isinstance(res.data, list)
    await cube.aclose()


async def test_catalogue_drift(live_settings):
    cube = CubeClient(live_settings)
    service = CatalogueService(load_catalogue(PROJECT_ROOT / "catalogue"))
    drift = await validate_against_cube(service, cube)
    assert drift["unreachable"] is False
    assert drift["broken"] == [], f"Catalogue drift: {drift['broken']}"
    await cube.aclose()
