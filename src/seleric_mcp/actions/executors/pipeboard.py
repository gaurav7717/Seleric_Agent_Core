"""Pipeboard executor for Meta Ads actions.

Write convention ported from seleric_systems/backend/worker/src/processors/
pipeboard.ts: POST {PIPEBOARD_MCP_URL}/actions/{actionType} with Bearer
PIPEBOARD_TOKEN. NOTE (risk R1 in the plan): this REST shape is unverified
against Pipeboard's current API — their public product is an MCP server whose
pause is `update_ad(ad_id, status="PAUSED")`. This class isolates the
transport so it can be swapped without touching the broker.
"""

from __future__ import annotations

import httpx
import structlog

from ...config import Settings

logger = structlog.get_logger()


class PipeboardError(RuntimeError):
    pass


class PipeboardExecutor:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        if not self._settings.pipeboard_token:
            raise PipeboardError("PIPEBOARD_TOKEN is not configured")
        return {"Authorization": f"Bearer {self._settings.pipeboard_token}"}

    async def preview_state(self, action_type: str, payload: dict) -> dict | None:
        """Best-effort read of the ad's current state. Failures return None —
        the broker records the rule as unverifiable rather than blocking."""
        ad_id = payload.get("ad_id")
        if not ad_id:
            return None
        try:
            resp = await self._client.post(
                f"{self._settings.pipeboard_mcp_url}/tools/get_ad_details",
                json={"ad_id": ad_id},
                headers=self._headers(),
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("pipeboard_preview_unavailable", error=str(exc))
        return None

    async def execute(self, action_type: str, payload: dict) -> dict:
        resp = await self._client.post(
            f"{self._settings.pipeboard_mcp_url}/actions/{action_type}",
            json=payload,
            headers=self._headers(),
        )
        if resp.status_code >= 300:
            raise PipeboardError(
                f"Pipeboard {action_type} failed: {resp.status_code} — {resp.text[:300]}"
            )
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text[:1000]}

    async def aclose(self) -> None:
        await self._client.aclose()
