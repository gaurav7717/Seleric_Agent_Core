"""Query-result store: lets metrics_drilldown and insights_explain reference a
prior query_id without re-sending data through the LLM's context. Rows expire
after ~1h and are lazily pruned.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..storage.db import Database, utcnow_iso

DEFAULT_RESULT_TTL = timedelta(hours=1)


@dataclass
class StoredResult:
    query_id: str
    parent_query_id: str | None
    request_json: str
    cube_query_json: str
    result_json: str
    compare_result_json: str | None
    provenance_json: str


class ResultStore:
    def __init__(self, db: Database, ttl: timedelta = DEFAULT_RESULT_TTL):
        self._db = db
        self._ttl = ttl

    def save(self, r: StoredResult) -> None:
        now = datetime.now(UTC)
        self._prune(now)
        self._db.execute(
            """INSERT INTO query_results
               (query_id, parent_query_id, request_json, cube_query_json, result_json,
                compare_result_json, provenance_json, created_at, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                r.query_id,
                r.parent_query_id,
                r.request_json,
                r.cube_query_json,
                r.result_json,
                r.compare_result_json,
                r.provenance_json,
                now.isoformat(),
                (now + self._ttl).isoformat(),
            ),
        )

    def get(self, query_id: str) -> StoredResult | None:
        row = self._db.fetchone(
            "SELECT * FROM query_results WHERE query_id = ? AND expires_at > ?",
            (query_id, utcnow_iso()),
        )
        if row is None:
            return None
        return StoredResult(
            query_id=row["query_id"],
            parent_query_id=row["parent_query_id"],
            request_json=row["request_json"],
            cube_query_json=row["cube_query_json"],
            result_json=row["result_json"],
            compare_result_json=row["compare_result_json"],
            provenance_json=row["provenance_json"],
        )

    def _prune(self, now: datetime) -> None:
        self._db.execute("DELETE FROM query_results WHERE expires_at <= ?", (now.isoformat(),))
