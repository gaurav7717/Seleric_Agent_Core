"""Typed, read-only client over Cube's REST API — the ONLY path to data.

Port of seleric_systems/backend/orchestrator/src/memory/cube_client.py:
auth is SELERIC_API_KEY bearer if set, else HS256 JWT from CUBEJS_API_SECRET.
Every query forces timezone Asia/Kolkata. No SQL API surface exists here.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import jwt
import structlog

from ..config import Settings

logger = structlog.get_logger()

_CONTINUE_WAIT_RETRIES = 3
_CONTINUE_WAIT_DELAY_S = 2.0


class CubeError(RuntimeError):
    pass


class CubeResult:
    def __init__(self, data: list[dict], raw: dict):
        self.data = data
        self.last_refresh_time: str | None = raw.get("lastRefreshTime")
        self.annotation: dict = raw.get("annotation", {})


class CubeClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._base = settings.cube_api_url
        self._client = httpx.AsyncClient(timeout=settings.cube_timeout_seconds)

    def _auth_headers(self) -> dict[str, str]:
        if self._settings.seleric_api_key:
            return {"Authorization": f"Bearer {self._settings.seleric_api_key}"}
        if self._settings.cubejs_api_secret:
            token = jwt.encode(
                {"iat": int(time.time()), "exp": int(time.time()) + 3600},
                self._settings.cubejs_api_secret,
                algorithm="HS256",
            )
            return {"Authorization": f"Bearer {token}"}
        return {}

    async def load(self, query: dict[str, Any]) -> CubeResult:
        query = dict(query)
        query.setdefault("timezone", "Asia/Kolkata")
        # Only apply a row cap when the caller set one (e.g. top-N). Do not
        # inject a default limit — that silently truncates ranked/list queries.
        if "limit" in query and query["limit"] is not None:
            limit = int(query["limit"])
            query["limit"] = min(limit, self._settings.max_row_limit)
        else:
            query.pop("limit", None)

        t0 = time.monotonic()
        body: dict = {}
        for attempt in range(_CONTINUE_WAIT_RETRIES + 1):
            resp = await self._client.post(
                f"{self._base}/cubejs-api/v1/load",
                json={"query": query},
                headers=self._auth_headers(),
            )
            if resp.status_code != 200:
                raise CubeError(f"Cube load failed: {resp.status_code} — {resp.text[:300]}")
            body = resp.json()
            # Cube returns {"error": "Continue wait"} while a query is still building.
            if body.get("error") == "Continue wait":
                if attempt == _CONTINUE_WAIT_RETRIES:
                    raise CubeError("Cube query still building after retries (Continue wait)")
                await asyncio.sleep(_CONTINUE_WAIT_DELAY_S)
                continue
            if body.get("error"):
                raise CubeError(f"Cube error: {body['error']}")
            break

        data = body.get("data", [])
        logger.info(
            "cube_load",
            rows=len(data),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
        return CubeResult(data=data, raw=body)

    async def meta(self) -> dict:
        resp = await self._client.get(
            f"{self._base}/cubejs-api/v1/meta", headers=self._auth_headers()
        )
        if resp.status_code != 200:
            raise CubeError(f"Cube meta failed: {resp.status_code} — {resp.text[:300]}")
        return resp.json()

    async def health(self) -> bool:
        try:
            await self.meta()
            return True
        except Exception as exc:
            logger.warning("cube_health_check_failed", error=str(exc))
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
