"""Pending-action and idempotency persistence over SQLite."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from ..storage.db import Database, utcnow_iso

DEFAULT_IDEMPOTENCY_WINDOW = timedelta(hours=24)


class ActionStore:
    def __init__(self, db: Database):
        self._db = db

    def create(
        self,
        action_request_id: str,
        action_id: str,
        payload: dict,
        p_hash: str,
        preview: dict,
        token_h: str | None,
        token_expires_at: str | None,
    ) -> None:
        self._db.execute(
            """INSERT INTO pending_actions
               (action_request_id, action_id, payload_json, payload_hash, status,
                preview_json, token_hash, token_expires_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                action_request_id,
                action_id,
                json.dumps(payload),
                p_hash,
                "PENDING",
                json.dumps(preview),
                token_h,
                token_expires_at,
                utcnow_iso(),
            ),
        )

    def get(self, action_request_id: str) -> dict | None:
        row = self._db.fetchone(
            "SELECT * FROM pending_actions WHERE action_request_id = ?", (action_request_id,)
        )
        return dict(row) if row else None

    def consume_token(self, action_request_id: str) -> bool:
        """Atomically mark the token consumed; False if already consumed/absent.
        Marked BEFORE dispatch so the token stays single-use even on a crash."""
        now = utcnow_iso()
        with self._db._lock, self._db._conn:
            cur = self._db._conn.execute(
                """UPDATE pending_actions SET token_consumed_at = ?
                   WHERE action_request_id = ? AND token_consumed_at IS NULL""",
                (now, action_request_id),
            )
            return cur.rowcount == 1

    def set_status(
        self,
        action_request_id: str,
        status: str,
        *,
        executor_response: dict | None = None,
        failure_reason: str | None = None,
        audit_ref: str | None = None,
        executed_at: str | None = None,
    ) -> None:
        self._db.execute(
            """UPDATE pending_actions
               SET status = ?, executor_response_json = ?, failure_reason = ?,
                   audit_ref = COALESCE(?, audit_ref), executed_at = COALESCE(?, executed_at)
               WHERE action_request_id = ?""",
            (
                status,
                json.dumps(executor_response) if executor_response is not None else None,
                failure_reason,
                audit_ref,
                executed_at,
                action_request_id,
            ),
        )


class IdempotencyStore:
    def __init__(self, db: Database, window: timedelta = DEFAULT_IDEMPOTENCY_WINDOW):
        self._db = db
        self._window = window

    def check_and_register(self, key: str, action_request_id: str) -> str | None:
        """Returns the prior action_request_id if the key was already executed
        inside the window, else registers it and returns None."""
        now = datetime.now(UTC)
        self._db.execute(
            "DELETE FROM idempotency_keys WHERE expires_at <= ?", (now.isoformat(),)
        )
        row = self._db.fetchone(
            "SELECT action_request_id FROM idempotency_keys WHERE idempotency_key = ?", (key,)
        )
        if row is not None:
            return row["action_request_id"]
        self._db.execute(
            """INSERT INTO idempotency_keys (idempotency_key, action_request_id, created_at, expires_at)
               VALUES (?,?,?,?)""",
            (key, action_request_id, now.isoformat(), (now + self._window).isoformat()),
        )
        return None

    def release(self, key: str) -> None:
        """Free the key after a failed dispatch so a retry isn't blocked."""
        self._db.execute("DELETE FROM idempotency_keys WHERE idempotency_key = ?", (key,))
