"""SQLite observations and review audit with backward-compatible JSONL exports."""

import fcntl
import hashlib
import json
import logging
import os
import sqlite3
import threading
import unicodedata
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import TypeAdapter

from app.schemas import Event, Job, Review
from app.storage.database import Database, database_for
from app.storage.jobs import AnalysisCheckpoint, now
from app.storage.lifecycle import lifecycle_lock
from app.storage.observation_context import capture_time_sql, enrich_events, origin_sql, tables

adapter: TypeAdapter[Event] = TypeAdapter(Event)  # type: ignore[arg-type]
# Visual similarity or acoustic confidence, for minimum-score filters.
SCORE_SQL = "COALESCE(json_extract(e.payload,'$.classification.score'), json_extract(e.payload,'$.confidence'))"
# A visual track within one session or job is one animal visit; a sound detection stands alone.
ENCOUNTER_KEY_SQL = (
    "CASE WHEN e.modality='visual' THEN e.job_id || ':' || COALESCE(json_extract(e.payload,'$.track_id'), e.event_id) "
    "ELSE e.event_id END"
)


def _captured(first: Event, enriched: Event) -> str | None:
    """Capture time of the encounter's first record, from the enriched latest record's basis."""
    if first.captured_at:
        return first.captured_at
    if not enriched.captured_at:
        return None
    offset = (enriched.timestamp_ms if enriched.modality == "visual" else enriched.start_ms) - (
        first.timestamp_ms if first.modality == "visual" else first.start_ms
    )
    return (datetime.fromisoformat(enriched.captured_at) - timedelta(milliseconds=offset)).isoformat()
logger = logging.getLogger(__name__)


def normalize(value: str) -> str:
    ascii_text = "".join(
        char
        for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )
    return " ".join("".join(char if char.isalnum() else " " for char in ascii_text).split())


def match_score(query: str, value: str) -> float:
    """Rank spelling-tolerant name matches without searching arbitrary model JSON."""
    if query == value:
        return 1.0
    if query in value:
        return 0.95
    query_words, words = query.split(), value.split()
    if not query_words or not words:
        return 0.0
    # Very short queries require literal matching; broad fuzzy matches are misleading.
    if len(query) < 3:
        return 0.0
    scores = [
        max(SequenceMatcher(None, needle, word).ratio() for word in words) for needle in query_words
    ]
    if min(scores) < 0.60:
        return 0.0
    score = sum(scores) / len(scores)
    return score * 0.90 if score >= 0.72 else 0.0


def _terms(event: Event) -> set[str]:
    values = [
        event.source_filename,
        event.review.corrected_scientific_name or "",
        event.review.corrected_common_name or "",
    ]
    if event.modality == "visual":
        values += [
            event.classification.common_name or "",
            event.classification.scientific_name or "",
            event.classification.display_label,
            event.classification.broad_group,
        ]
        candidates = [
            *event.classification.top_k,
            *(
                candidate
                for evidence in event.classification.model_evidence
                for candidate in evidence.top_k
            ),
        ]
        for candidate in candidates:
            values.extend([candidate.common_name or "", candidate.scientific_name])
    else:
        values.extend([event.common_name, event.scientific_name])
    return {normalized for value in values if (normalized := normalize(value))}


def _index_terms(connection: sqlite3.Connection, event: Event) -> None:
    connection.execute("DELETE FROM observation_terms WHERE event_id=?", (event.event_id,))
    connection.executemany(
        "INSERT INTO observation_terms VALUES (?, ?)",
        [(event.event_id, value) for value in _terms(event)],
    )


def _insert(connection: sqlite3.Connection, event: Event, recorded_at: str) -> bool:
    timestamp = event.timestamp_ms if event.modality == "visual" else event.start_ms
    cursor = connection.execute(
        "INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.event_id,
            event.source_id,
            event.job_id,
            event.source_filename,
            event.modality,
            timestamp,
            recorded_at,
            event.review.status,
            event.model_dump_json(),
        ),
    )
    if cursor.rowcount:
        _index_terms(connection, event)
        return True
    return False


def append_lines(path: Path, lines: Iterable[str], *, durable: bool = False) -> None:
    """Append complete records, first terminating a record torn by a power cut."""
    with path.open("a+b") as file:
        if file.seek(0, os.SEEK_END):
            file.seek(-1, os.SEEK_END)
            if file.read(1) != b"\n":
                # Keep the torn bytes, but never let them merge with a new record.
                file.write(b"\n")
        file.write("".join(line + "\n" for line in lines).encode("utf-8"))
        file.flush()
        if durable:
            os.fsync(file.fileno())


class EventStore:
    def __init__(self, directory: Path, database: Database | None = None):
        self.directory = directory
        self.lock = threading.RLock()
        self.database = database or database_for(directory)
        with lifecycle_lock(self.database.path.parent):
            self._migrate()

    def path(self, source_id: str) -> Path:
        if len(source_id) != 24 or any(c not in "0123456789abcdef" for c in source_id):
            raise ValueError("Invalid source ID")
        return self.directory / f"{source_id}.jsonl"

    @contextmanager
    def _source_lock(self, source_id: str) -> Iterator[None]:
        # Protect legacy mirrors across separate store instances/processes, too.
        self.path(source_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.directory / f".{source_id}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "ab") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _migrate(self) -> None:
        # SQLite is the authority. A damaged compatibility mirror must never stop
        # the field application from starting: its import is rolled back, the file
        # is left untouched, and other mirrors are still checked.
        for path in sorted(self.directory.glob("*.jsonl")):
            try:
                self._import_mirror(path)
            except (OSError, ValueError, sqlite3.Error):
                logger.warning("Compatibility log %s could not be checked; it is preserved", path.name)

    def _import_mirror(self, path: Path) -> None:
        """Import complete records added since the last startup, in one transaction.

        Live mirrors grow continuously, so only bytes after the previously imported
        prefix are parsed when that prefix is unchanged. An unterminated final line
        (for example after a power cut during an append) is left for a later check;
        the application always commits to SQLite before writing its mirror line.
        """
        key = str(path.resolve())
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT i.digest, o.imported_bytes FROM legacy_imports i "
                "LEFT JOIN legacy_import_offsets o USING(path) WHERE i.path=?", (key,)
            ).fetchone()
            with path.open("rb") as source:
                digest, offset = hashlib.sha256(), 0
                if previous is not None:
                    known = previous["imported_bytes"]
                    prefix = hashlib.sha256()
                    if known is None:
                        # Databases from before incremental checks stored whole-file digests.
                        while block := source.read(1024 * 1024):
                            prefix.update(block)
                        if prefix.hexdigest() == previous["digest"]:
                            connection.execute(
                                "INSERT OR REPLACE INTO legacy_import_offsets VALUES (?, ?)",
                                (key, source.tell()),
                            )
                            return
                    else:
                        remaining = known
                        while remaining > 0 and (block := source.read(min(remaining, 1024 * 1024))):
                            prefix.update(block)
                            remaining -= len(block)
                        if remaining == 0 and prefix.hexdigest() == previous["digest"]:
                            digest, offset = prefix, known
                    if offset == 0:
                        # The file was replaced or truncated; check it again from the start.
                        source.seek(0)
                recorded_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
                start = offset
                for number, raw in enumerate(source, 1):
                    if not raw.endswith(b"\n"):
                        logger.warning(
                            "Ignoring an incomplete final record in %s; it is retained in the file",
                            path.name,
                        )
                        break
                    digest.update(raw)
                    offset += len(raw)
                    try:
                        line = raw.decode("utf-8")
                        if not line.strip():
                            continue
                        if path.stem == "reviews":
                            item = json.loads(line)
                            Review.model_validate(item["previous"])
                            Review.model_validate(item["review"])
                            audit_id = (
                                item.get("audit_id")
                                or hashlib.sha256(
                                    f"{path.name}:{number}:{line.rstrip(chr(10))}".encode()
                                ).hexdigest()
                            )
                            connection.execute(
                                "INSERT OR IGNORE INTO review_audit VALUES (?, ?, ?, ?)",
                                (audit_id, item["event_id"], recorded_at, line.rstrip("\n")),
                            )
                        else:
                            event = adapter.validate_json(line)
                            if self.path(event.source_id).name != path.name:
                                raise ValueError("Source ID does not match the log")
                            _insert(connection, event, recorded_at)
                    except (ValueError, KeyError, TypeError):
                        # One bad line (for example a torn record terminated by a later
                        # append) must not hide the rest. The file itself is never changed.
                        position = f"record {number} after byte {start}" if start else f"record {number}"
                        logger.warning(
                            "Skipped malformed JSONL %s in %s; the log is preserved", position, path.name
                        )
            connection.execute(
                "INSERT OR REPLACE INTO legacy_imports VALUES (?, ?)", (key, digest.hexdigest())
            )
            connection.execute(
                "INSERT OR REPLACE INTO legacy_import_offsets VALUES (?, ?)", (key, offset)
            )

    def append(self, event: Event) -> None:
        path = self.path(event.source_id)
        with self.lock, self._source_lock(event.source_id):
            with self.database.connection() as connection:
                inserted = _insert(connection, event, now())
            if not inserted:
                return
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                append_lines(path, [event.model_dump_json()])
            except OSError:
                logger.warning(
                    "Observation is saved in SQLite; its JSONL export could not be updated"
                )

    def commit_analysis(
        self,
        job: Job,
        checkpoint: AnalysisCheckpoint,
        events: list[Event],
        *,
        deduplicate_boundary: bool = False,
    ) -> None:
        """Commit a complete visual frame or audio stage and its cursor together.

        Legacy workers could persist only part of a frame/stage. Replaying that
        boundary retains matching original event IDs and every existing review.
        """
        inserted: list[Event] = []
        with self.lock, self._source_lock(job.source_id):
            with self.database.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing: list[Event] = []
                if deduplicate_boundary or any(e.modality == "audio" for e in events):
                    rows = connection.execute(
                        "SELECT payload FROM observations WHERE source_id=? AND job_id=?",
                        (job.source_id, job.job_id),
                    ).fetchall()
                    existing = [adapter.validate_json(row["payload"]) for row in rows]
                for event in events:
                    duplicate = False
                    for prior in existing:
                        if event.modality == "audio" and prior.modality == "audio":
                            duplicate = (
                                event.start_ms == prior.start_ms
                                and event.end_ms == prior.end_ms
                                and event.scientific_name == prior.scientific_name
                            )
                        elif event.modality == "visual" and prior.modality == "visual":
                            a, b = event.bbox_norm, prior.bbox_norm
                            overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
                                0, min(a[3], b[3]) - max(a[1], b[1])
                            )
                            union = (
                                (a[2] - a[0]) * (a[3] - a[1])
                                + (b[2] - b[0]) * (b[3] - b[1])
                                - overlap
                            )
                            duplicate = (
                                event.timestamp_ms == prior.timestamp_ms
                                and event.detector.label == prior.detector.label
                                and union > 0
                                and overlap / union >= 0.98
                            )
                        if duplicate:
                            break
                    if not duplicate and _insert(connection, event, now()):
                        inserted.append(event)
                        existing.append(event)
                counts = connection.execute(
                    "SELECT modality, COUNT(*) AS count FROM observations "
                    "WHERE source_id=? AND job_id=? GROUP BY modality",
                    (job.source_id, job.job_id),
                ).fetchall()
                totals = {row["modality"]: row["count"] for row in counts}
                job.visual_count, job.audio_count = totals.get("visual", 0), totals.get("audio", 0)
                connection.execute(
                    "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?)",
                    (job.job_id, job.source_id, job.created_at, job.model_dump_json()),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO analysis_checkpoints VALUES (?, ?)",
                    (job.job_id, checkpoint.model_dump_json()),
                )
            try:
                if inserted:
                    append_lines(self.path(job.source_id), [event.model_dump_json() for event in inserted])
            except OSError:
                logger.warning("Analysis checkpoint is saved in SQLite; JSONL export failed")

    def read(self, source_id: str, job_id: str | None = None) -> list[Event]:
        self.path(source_id)
        query = "SELECT payload FROM observations WHERE source_id=?"
        parameters: list[Any] = [source_id]
        if job_id is not None:
            query += " AND job_id=?"
            parameters.append(job_id)
        query += " ORDER BY rowid"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [adapter.validate_json(row["payload"]) for row in rows]

    def query(
        self,
        source_id: str | None = None,
        job_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        q: str | None = None,
        review_status: str | None = None,
        modality: str | None = None,
        name_aliases: dict[str, float] | None = None,
        scope: Literal["live", "all"] = "all",
        captured_from: datetime | None = None,
        captured_to: datetime | None = None,
        min_score: float | None = None,
        include_discarded: bool = False,
    ) -> dict[str, Any]:
        limit, offset = min(500, max(1, limit)), max(0, offset)
        conditions: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("source_id", source_id),
            ("job_id", job_id),
            ("review_status", review_status),
            ("modality", modality),
        ):
            if value:
                conditions.append(f"e.{column}=?")
                parameters.append(value)
        if not include_discarded and review_status != "discarded":
            # Discarded records stay in the audit trail but leave the working archive.
            conditions.append("e.review_status!='discarded'")
        if min_score is not None:
            conditions.append(f"{SCORE_SQL}>=?")
            parameters.append(min_score)
        search = normalize((q or "")[:200])
        with self.database.connection() as connection:
            available = tables(connection)
            if scope == "live":
                conditions.append(f"({origin_sql(available)})='live'")
            for operator, moment in ((">=", captured_from), ("<=", captured_to)):
                if moment is not None:
                    conditions.append(f"julianday({capture_time_sql(available)}){operator}julianday(?)")
                    parameters.append(moment.astimezone(UTC).isoformat())
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            base = "SELECT e.payload, e.recorded_at, e.rowid FROM observations e" + where
            if search:
                values = connection.execute(
                    "SELECT DISTINCT value FROM observation_terms"
                ).fetchall()
                matches = [
                    (row["value"], score)
                    for row in values
                    if (
                        score := max(
                            match_score(search, row["value"]),
                            (name_aliases or {}).get(row["value"], 0.0),
                        )
                    )
                    > 0
                ]
                if not matches:
                    return {"events": [], "total": 0}
                # A temporary relation keeps this bounded by names, not event count,
                # and avoids SQLite parameter limits for large observation libraries.
                connection.execute(
                    "CREATE TEMP TABLE search_matches(value TEXT PRIMARY KEY, score REAL)"
                )
                connection.executemany("INSERT INTO search_matches VALUES (?, ?)", matches)
                base = (
                    "SELECT e.payload, e.recorded_at, e.rowid, MAX(m.score) AS relevance "
                    "FROM observations e JOIN observation_terms t ON t.event_id=e.event_id "
                    "JOIN search_matches m ON m.value=t.value" + where + " GROUP BY e.event_id"
                )
            total = connection.execute(f"SELECT COUNT(*) FROM ({base})", parameters).fetchone()[0]
            order = "relevance DESC, " if search else ""
            rows = connection.execute(
                f"SELECT * FROM ({base}) ORDER BY {order}recorded_at DESC, rowid DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            events = enrich_events(connection, [adapter.validate_json(row["payload"]) for row in rows], available=available)
        return {"events": events, "total": total}

    def read_ids(self, event_ids: list[str]) -> list[Event]:
        if not event_ids:
            return []
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT payload FROM observations WHERE event_id IN ({','.join('?' * len(event_ids))})", event_ids,
            ).fetchall()
        return [adapter.validate_json(row["payload"]) for row in rows]

    def _filters(
        self, connection: sqlite3.Connection, *, source_id: str | None, scope: Literal["live", "all"],
        review_status: str | None, modality: str | None, captured_from: datetime | None,
        captured_to: datetime | None, min_score: float | None, include_discarded: bool, q: str | None,
    ) -> tuple[list[str], list[Any]]:
        available = tables(connection)
        conditions: list[str] = []
        parameters: list[Any] = []
        for column, value in (("source_id", source_id), ("modality", modality)):
            if value:
                conditions.append(f"e.{column}=?")
                parameters.append(value)
        if review_status == "mixed":
            review_status = None
        if review_status:
            conditions.append("e.review_status=?")
            parameters.append(review_status)
        elif not include_discarded:
            conditions.append("e.review_status!='discarded'")
        if scope == "live":
            conditions.append(f"({origin_sql(available)})='live'")
        if min_score is not None:
            conditions.append(f"{SCORE_SQL}>=?")
            parameters.append(min_score)
        for operator, moment in ((">=", captured_from), ("<=", captured_to)):
            if moment is not None:
                conditions.append(f"julianday({capture_time_sql(available)}){operator}julianday(?)")
                parameters.append(moment.astimezone(UTC).isoformat())
        search = normalize((q or "")[:200])
        if search:
            conditions.append("e.event_id IN (SELECT event_id FROM observation_terms WHERE value LIKE ?)")
            parameters.append(f"%{search}%")
        return conditions, parameters

    def encounters(
        self, *, source_id: str | None = None, scope: Literal["live", "all"] = "all",
        review_status: str | None = None, modality: str | None = None,
        captured_from: datetime | None = None, captured_to: datetime | None = None,
        min_score: float | None = None, include_discarded: bool = False, q: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        """One row per animal visit: a visual track, or a single sound detection.

        Frame-level records of the same track are grouped, so a reviewer decides once
        per encounter instead of once per analyzed frame.
        """
        limit, offset = min(200, max(1, limit)), max(0, offset)
        with self.database.connection() as connection:
            available = tables(connection)
            conditions, parameters = self._filters(
                connection, source_id=source_id, scope=scope, review_status=review_status, modality=modality,
                captured_from=captured_from, captured_to=captured_to, min_score=min_score,
                include_discarded=include_discarded, q=q,
            )
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            capture = capture_time_sql(available)
            grouped = (
                f"SELECT {ENCOUNTER_KEY_SQL} AS encounter_id, COUNT(*) AS records, "
                f"MIN(COALESCE(julianday({capture}), julianday(e.recorded_at))) AS first_day, "
                f"MAX(COALESCE(julianday({capture}), julianday(e.recorded_at))) AS last_day, "
                "GROUP_CONCAT(DISTINCT e.review_status) AS statuses "
                "FROM observations e" + where + " GROUP BY encounter_id"
            )
            total = connection.execute(f"SELECT COUNT(*) FROM ({grouped})", parameters).fetchone()[0]
            groups = connection.execute(
                f"SELECT * FROM ({grouped}) ORDER BY last_day DESC, encounter_id LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            if not groups:
                return {"encounters": [], "total": total}
            keys = [group["encounter_id"] for group in groups]
            rows = connection.execute(
                f"SELECT e.payload, {ENCOUNTER_KEY_SQL} AS encounter_id FROM observations e"
                + where + (" AND " if where else " WHERE ")
                + f"{ENCOUNTER_KEY_SQL} IN ({','.join('?' * len(keys))}) ORDER BY e.timestamp_ms",
                [*parameters, *keys],
            ).fetchall()
            members: dict[str, list[Event]] = {}
            for row in rows:
                members.setdefault(row["encounter_id"], []).append(adapter.validate_json(row["payload"]))
            latest = enrich_events(
                connection, [members[key][-1] for key in keys if members.get(key)], available=available,
            )
        latest_by_key = {key: event for key, event in zip([k for k in keys if members.get(k)], latest, strict=True)}
        result = []
        for group in groups:
            key = group["encounter_id"]
            events = members.get(key, [])
            if not events:
                continue
            event = latest_by_key[key]
            statuses = (group["statuses"] or "").split(",")
            best = max(
                events, key=lambda item: (item.detector.score or 0) if item.modality == "visual" else item.confidence,
            )
            first, last = events[0], events[-1]
            start = first.timestamp_ms if first.modality == "visual" else first.start_ms
            end = (last.timestamp_ms + last.duration_ms) if last.modality == "visual" else last.end_ms
            result.append({
                "encounter_id": key, "modality": event.modality, "source_id": event.source_id,
                "source_filename": event.source_filename, "job_id": event.job_id,
                "track_id": event.track_id if event.modality == "visual" else None,
                "records": group["records"], "first_captured_at": _captured(first, event),
                "duration_ms": max(0, end - start), "review_status": statuses[0] if len(statuses) == 1 else "mixed",
                "thumbnail_event_id": best.event_id, "event": event,
            })
        return {"encounters": result, "total": total}

    def encounter_event_ids(self, encounter_ids: list[str], *, include_discarded: bool = True) -> list[str]:
        if not encounter_ids:
            return []
        ids: list[str] = []
        with self.database.connection() as connection:
            for start in range(0, len(encounter_ids), 400):
                chunk = encounter_ids[start:start + 400]
                ids += [row[0] for row in connection.execute(
                    f"SELECT e.event_id FROM observations e WHERE {ENCOUNTER_KEY_SQL} IN ({','.join('?' * len(chunk))})"
                    + ("" if include_discarded else " AND e.review_status!='discarded'"), chunk,
                )]
        return ids

    def sources(self, scope: Literal["live", "all"] = "all") -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            available = tables(connection)
            where = " WHERE source_kind='live'" if scope == "live" else ""
            rows = connection.execute(
                "WITH contextual AS (SELECT e.*, " + origin_sql(available) + " AS source_kind, "
                + capture_time_sql(available) + " AS capture_timestamp FROM observations e) "
                "SELECT source_id, MAX(source_filename) AS source_filename, COUNT(*) AS count,"
                " MAX(capture_timestamp) AS latest_at, GROUP_CONCAT(DISTINCT modality) AS modalities,"
                " GROUP_CONCAT(DISTINCT job_id) AS job_ids, MAX(source_kind) AS source_kind "
                "FROM contextual" + where + " GROUP BY source_id ORDER BY MAX(recorded_at) DESC"
            ).fetchall()
            sessions = connection.execute(
                "SELECT payload FROM evidence_sessions ORDER BY started_at"
            ).fetchall() if "evidence_sessions" in available else []
        session_by_source = {session["source_id"]: session for row in sessions if (session := json.loads(row["payload"]))}
        result = []
        for row in rows:
            session = session_by_source.get(row["source_id"], {})
            result.append({
                **dict(row), "source_filename": session.get("name", row["source_filename"]),
                "modalities": row["modalities"].split(","), "job_ids": row["job_ids"].split(","),
                "session_id": session.get("session_id"), "started_at": session.get("started_at"),
                "ended_at": session.get("ended_at"),
            })
        return result

    def review(self, event_id: str, review: Review) -> Event:
        updated, _ = self.review_many([event_id], review)
        if not updated:
            raise KeyError(event_id)
        return updated[0]

    def review_many(self, event_ids: list[str], review: Review) -> tuple[list[Event], list[str]]:
        """Apply one review decision to many observations in one audited transaction.

        Returns (updated observations, IDs that were not found).
        """
        unique = list(dict.fromkeys(event_ids))
        if not unique:
            return [], []
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT event_id, source_id FROM observations WHERE event_id IN ({','.join('?' * len(unique))})",
                unique,
            ).fetchall()
        sources = sorted({row["source_id"] for row in rows})
        found = {row["event_id"] for row in rows}
        missing = [event_id for event_id in unique if event_id not in found]
        updated: list[Event] = []
        audits: list[dict[str, Any]] = []
        if not found:
            return updated, missing
        with lifecycle_lock(self.database.path.parent), self.lock, ExitStack() as locks:
            for source_id in sources:
                locks.enter_context(self._source_lock(source_id))
            with self.database.connection() as connection:
                # Acquire the SQLite writer lease before reading the previous review.
                # This keeps the audit chain correct across app/store instances.
                connection.execute("BEGIN IMMEDIATE")
                for event_id in unique:
                    if event_id not in found:
                        continue
                    row = connection.execute(
                        "SELECT payload FROM observations WHERE event_id=?", (event_id,)
                    ).fetchone()
                    if row is None:
                        missing.append(event_id)
                        continue
                    target = adapter.validate_json(row["payload"])
                    audit = {
                        "audit_id": str(uuid4()),
                        "event_id": event_id,
                        "previous": target.review.model_dump(),
                        "review": review.model_dump(),
                    }
                    target.review = review.model_copy(deep=True)
                    connection.execute(
                        "UPDATE observations SET payload=?, review_status=? WHERE event_id=?",
                        (target.model_dump_json(), review.status, event_id),
                    )
                    _index_terms(connection, target)
                    connection.execute(
                        "INSERT INTO review_audit VALUES (?, ?, ?, ?)",
                        (audit["audit_id"], event_id, now(), json.dumps(audit)),
                    )
                    updated.append(target)
                    audits.append(audit)
            # SQLite review and audit are one transaction. Export failure cannot lose either.
            # The mirror is append-only: a later line with the same event_id supersedes
            # earlier ones. Rewriting the whole session here made each review cost
            # O(session size) while blocking live observation writes.
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                for source_id in sources:
                    lines = [event.model_dump_json() for event in updated if event.source_id == source_id]
                    if lines:
                        append_lines(self.path(source_id), lines, durable=True)
                append_lines(self.directory / "reviews.jsonl", [json.dumps(audit) for audit in audits], durable=True)
            except OSError:
                logger.warning(
                    "Review and audit are saved in SQLite; JSONL exports could not be updated"
                )
        return updated, missing
