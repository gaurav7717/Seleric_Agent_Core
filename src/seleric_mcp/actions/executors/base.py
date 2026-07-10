"""Executor protocol: the broker is agnostic to which system performs an
action — the mapping lives in the action's catalogue entry (executor field),
never in the LLM's reasoning."""

from __future__ import annotations

from typing import Protocol


class ActionExecutor(Protocol):
    async def preview_state(self, action_type: str, payload: dict) -> dict | None:
        """Best-effort read of current downstream state; None if unavailable."""
        ...

    async def execute(self, action_type: str, payload: dict) -> dict:
        """Perform the action. Raises on failure."""
        ...
