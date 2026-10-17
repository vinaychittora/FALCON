"""Read-time source identity and capture time; never substitute ingestion timestamps."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast

from app.schemas import AudioEvent, VisualEvent

Observation = TypeVar("Observation", bound=VisualEvent | AudioEvent)


def tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def session_start_sql(available: set[str], alias: str = "e") -> str:
    if "evidence_sessions" not in available:
        return "NULL"
    return (
        f"(SELECT s.started_at FROM evidence_sessions s WHERE s.session_id={alias}.job_id "
        f"AND s.source_id={alias}.source_id)"
    )


def origin_sql(available: set[str], alias: str = "e") -> str:
    explicit = f"json_extract({alias}.payload,'$.source_kind')"
    session = session_start_sql(available, alias)
    return (
        f"CASE WHEN {explicit} IN ('live','file') THEN {explicit} "
        f"WHEN {session} IS NOT NULL THEN 'live' "
        f"WHEN EXISTS(SELECT 1 FROM jobs j WHERE j.job_id={alias}.job_id AND j.source_id={alias}.source_id) "
        f"OR EXISTS(SELECT 1 FROM media m WHERE m.source_id={alias}.source_id) THEN 'file' "
        f"WHEN lower(COALESCE(json_extract({alias}.payload,'$.models.source'),'')) LIKE 'live%' "
        f"OR lower(COALESCE(json_extract({alias}.payload,'$.models.source_clock'),'')) LIKE 'session receive%' "
        "THEN 'live' ELSE 'unknown' END"
    )


def capture_time_sql(available: set[str], alias: str = "e") -> str:
    session = session_start_sql(available, alias)
    return (
        f"COALESCE(json_extract({alias}.payload,'$.captured_at'), "
        f"strftime('%Y-%m-%dT%H:%M:%fZ', {session}, '+' || ({alias}.timestamp_ms / 1000.0) || ' seconds'))"
    )


def enrich_events(
    connection: sqlite3.Connection, events: Sequence[Observation],
    *, available: set[str] | None = None,
) -> list[Observation]:
    if not events:
        return []
    available = tables(connection) if available is None else available
    summaries = "'[]'"
    if {"evidence", "evidence_links"} <= available:
        fields = ("media_kind", "status", "duration_ms", "captured_at", "audio_present", "mime_type", "message", "actual_start_ms", "actual_end_ms")
        entries = ",".join(f"'{name}',json_extract(v.payload,'$.{name}')" for name in fields)
        summaries = (
            "(SELECT json_group_array(json_object('evidence_id',v.evidence_id," + entries + ")) "
            "FROM evidence_links l JOIN evidence v ON v.evidence_id=l.evidence_id "
            "WHERE l.event_id=e.event_id)"
        )
    placeholders = ",".join("?" for _ in events)
    rows = connection.execute(
        f"SELECT e.event_id, {origin_sql(available)} AS source_kind, "
        f"{session_start_sql(available)} AS session_started_at, {summaries} AS evidence_summaries "
        f"FROM observations e WHERE e.event_id IN ({placeholders})",
        [event.event_id for event in events],
    ).fetchall()
    contexts = {row["event_id"]: row for row in rows}
    result = []
    for event in events:
        context = contexts.get(event.event_id)
        if context is None:
            result.append(event)
            continue
        kind = context["source_kind"]
        captured_at = event.captured_at
        time_basis = event.time_basis
        if not captured_at and context["session_started_at"]:
            start = datetime.fromisoformat(context["session_started_at"])
            offset = event.timestamp_ms if isinstance(event, VisualEvent) else event.start_ms
            if start.tzinfo is not None:
                captured_at = (start.astimezone(UTC) + timedelta(milliseconds=offset)).isoformat()
                time_basis = "server_receive_time"
        if not captured_at:
            time_basis = "source_relative_time_only" if kind == "file" else "unknown"
        summaries_data = json.loads(context["evidence_summaries"])
        summaries_data.sort(key=lambda value: (value["captured_at"], value["evidence_id"]))
        updated = type(event).model_validate({
            **event.model_dump(), "source_kind": kind, "captured_at": captured_at,
            "time_basis": time_basis, "evidence_summaries": summaries_data,
        })
        result.append(cast(Observation, updated))
    return result
