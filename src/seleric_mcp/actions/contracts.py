"""Typed action payload contracts. Each catalogue action entry names its
payload schema here; the broker validates before anything is previewed."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PauseMetaAdPayload(BaseModel):
    ad_id: str = Field(pattern=r"^\d{5,25}$", description="Meta ad id (numeric)")
    brand_id: str = Field(min_length=1)
    reason: str = Field(
        min_length=10,
        max_length=500,
        description="Why this ad is being paused (audited)",
    )


PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "PauseMetaAdPayload": PauseMetaAdPayload,
}


class RuleResult(BaseModel):
    rule: str
    passed: bool | None  # None = unverifiable (best-effort check failed)
    detail: str


class ActionPreview(BaseModel):
    action_request_id: str
    action_id: str
    payload: dict
    current_state: dict | None
    predicted_change: str
    business_rule_results: list[RuleResult]
    eligible: bool
    confirmation_token: str | None
    token_expires_at: datetime | None
    write_enabled: bool
    note: str | None = None


class CommitResult(BaseModel):
    action_request_id: str
    status: Literal["EXECUTED", "FAILED", "REJECTED", "EXPIRED", "DUPLICATE"]
    executor_response: dict | None
    audit_ref: str | None
    executed_at: datetime | None
    detail: str | None = None
