"""Append-only audit log. Every action event (and read-path tool call summary)
gets an immutable row; provenance shown to users is a subset of what is logged.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from ..storage.db import Database, utcnow_iso


def new_audit_ref() -> str:
    return f"AR-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:6]}"


class AuditLog:
    def __init__(self, db: Database):
        self._db = db

    def write(
        self,
        event: str,
        actor: str,
        payload: dict | None = None,
        audit_ref: str | None = None,
        trace_id: str | None = None,
    ) -> str:
        ref = audit_ref or new_audit_ref()
        self._db.execute(
            """INSERT INTO audit_log (audit_ref, event, actor, trace_id, payload_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (ref, event, actor, trace_id, json.dumps(payload or {}), utcnow_iso()),
        )
        return ref

    def for_ref(self, audit_ref: str) -> list[dict]:
        rows = self._db.fetchall(
            "SELECT * FROM audit_log WHERE audit_ref = ? ORDER BY audit_id", (audit_ref,)
        )
        return [dict(r) for r in rows]
