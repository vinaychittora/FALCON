"""Visits formed by the Phase 1 rules: one row per visit, updated when it starts, is
promoted and closes. Records carry the visit_id; Review and Live read the hidden
reason from here (CANDIDATE / GLIMPSE / STILL / UNIDENTIFIED / SMALL, or shown)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.storage.database import Database


class VisitStore:
    def __init__(self, database: Database):
        self.database = database

    def upsert(self, visit_id: str, job_id: str, hidden_reason: str | None, **payload: Any) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connection() as connection:
            row = connection.execute("SELECT payload FROM visits WHERE visit_id=?", (visit_id,)).fetchone()
            merged = {**(json.loads(row["payload"]) if row else {}), **payload}
            connection.execute(
                "INSERT INTO visits(visit_id, job_id, hidden_reason, updated_at, payload) VALUES (?,?,?,?,?) "
                "ON CONFLICT(visit_id) DO UPDATE SET hidden_reason=excluded.hidden_reason, "
                "updated_at=excluded.updated_at, payload=excluded.payload",
                (visit_id, job_id, hidden_reason, now, json.dumps(merged)),
            )

    def get(self, visit_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT hidden_reason, payload FROM visits WHERE visit_id=?", (visit_id,)
            ).fetchone()
        return None if row is None else {"hidden_reason": row["hidden_reason"], **json.loads(row["payload"])}
