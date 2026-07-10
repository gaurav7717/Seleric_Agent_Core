from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from seleric_mcp.actions.stores import ActionStore, IdempotencyStore
from seleric_mcp.app.result_store import ResultStore
from seleric_mcp.catalogue_service.loader import load_catalogue
from seleric_mcp.catalogue_service.service import CatalogueService
from seleric_mcp.config import PROJECT_ROOT, Settings
from seleric_mcp.observability.audit import AuditLog
from seleric_mcp.semantic_layer.cube_client import CubeResult
from seleric_mcp.storage.db import Database

CATALOGUE_DIR = PROJECT_ROOT / "catalogue"


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


@pytest.fixture(scope="session")
def catalogue():
    return CatalogueService(load_catalogue(CATALOGUE_DIR))


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        cube_api_url="http://cube.test",
        seleric_api_key="test-key",
        cubejs_api_secret="",
        pipeboard_mcp_url="http://pipeboard.test",
        pipeboard_token="pb-token",
        write_enabled=False,
        mcp_service_token="svc-token",
        approval_secret="approval-secret",
        caller_scopes=frozenset({"metrics:read", "meta_ads:write:status"}),
        db_path=tmp_path / "test.db",
    )


class FakeCube:
    """Programmable Cube client double. Routes on the first measure/dimension's
    view prefix; records every query it receives."""

    def __init__(self):
        self.responses: list[list[dict]] = []
        self.by_prefix: dict[str, list[dict]] = {}
        self.queries: list[dict] = []
        self.fail = False

    async def load(self, query: dict) -> CubeResult:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("cube down")
        members = query.get("measures") or query.get("dimensions") or [""]
        prefix = members[0].split(".")[0]
        if prefix in self.by_prefix:
            data = self.by_prefix[prefix]
        elif self.responses:
            data = self.responses.pop(0)
        else:
            data = []
        return CubeResult(data=data, raw={"data": data, "lastRefreshTime": "2026-07-10T04:00:00Z"})

    async def meta(self) -> dict:
        return {"cubes": []}


class FakeExecutor:
    def __init__(self):
        self.executed: list[tuple[str, dict]] = []
        self.fail = False

    async def preview_state(self, action_type: str, payload: dict):
        return None

    async def execute(self, action_type: str, payload: dict) -> dict:
        if self.fail:
            raise RuntimeError("executor boom")
        self.executed.append((action_type, payload))
        return {"success": True, "ad_id": payload.get("ad_id"), "status": "PAUSED"}


@pytest.fixture()
def fake_cube():
    return FakeCube()


@pytest.fixture()
def fake_executor():
    return FakeExecutor()


@pytest.fixture()
def result_store(db):
    return ResultStore(db)


@pytest.fixture()
def action_store(db):
    return ActionStore(db)


@pytest.fixture()
def idempotency(db):
    return IdempotencyStore(db)


@pytest.fixture()
def audit(db):
    return AuditLog(db)
