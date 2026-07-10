"""SQLite storage: query results, pending actions, idempotency keys, audit log.

Single-process server with low write volume, so stdlib sqlite3 in WAL mode is
sufficient. Async callers run blocking DB work via asyncio.to_thread at the
call sites that need it; individual operations are short.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS query_results (
    query_id TEXT PRIMARY KEY,
    parent_query_id TEXT,
    request_json TEXT NOT NULL,
    cube_query_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    compare_result_json TEXT,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    action_request_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('PENDING','APPROVED','REJECTED','EXECUTED','EXPIRED','FAILED')),
    preview_json TEXT,
    token_hash TEXT UNIQUE,
    token_expires_at TEXT,
    token_consumed_at TEXT,
    executor_response_json TEXT,
    failure_reason TEXT,
    audit_ref TEXT,
    created_at TEXT NOT NULL,
    executed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_actions_status ON pending_actions(status);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,
    action_request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_ref TEXT,
    event TEXT NOT NULL,
    actor TEXT NOT NULL,
    trace_id TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON audit_log(event, created_at);
"""


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Thread-safe wrapper around a single SQLite file."""

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock, self._conn:
            self._conn.executescript(_DDL)

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock, self._conn:
            self._conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
