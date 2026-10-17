"""SQLite observations and review audit with backward-compatible JSONL exports."""

import fcntl
import hashlib
import json
import logging
import os
import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from app.schemas import Event, Job, Review
from app.storage.database import Database, database_for
from app.storage.jobs import AnalysisCheckpoint, now

adapter: TypeAdapter[Event] = TypeAdapter(Event)  # type: ignore[arg-type]
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


class EventStore:
    def __init__(self, directory: Path, database: Database | None = None):
        self.directory = directory
        self.lock = threading.RLock()
        self.database = database or database_for(directory)
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
        # A malformed file rolls back the import; every original remains untouched.
        with self.database.connection() as connection:
            for path in sorted(self.directory.glob("*.jsonl")):
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                previous = connection.execute(
                    "SELECT digest FROM legacy_imports WHERE path=?", (str(path.resolve()),)
                ).fetchone()
                if previous and previous["digest"] == digest:
                    continue
                recorded_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
                for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        if path.stem == "reviews":
                            item = json.loads(line)
                            Review.model_validate(item["previous"])
                            Review.model_validate(item["review"])
                            audit_id = (
                                item.get("audit_id")
                                or hashlib.sha256(
                                    f"{path.name}:{number}:{line}".encode()
                                ).hexdigest()
                            )
                            connection.execute(
                                "INSERT OR IGNORE INTO review_audit VALUES (?, ?, ?, ?)",
                                (audit_id, item["event_id"], recorded_at, line),
                            )
                        else:
                            event = adapter.validate_json(line)
                            if self.path(event.source_id).name != path.name:
                                raise ValueError("Source ID does not match the log")
                            _insert(connection, event, recorded_at)
                    except (ValueError, KeyError, TypeError) as exc:
                        raise ValueError(
                            f"Malformed JSONL record {number} in {path.name}; log preserved"
                        ) from exc
                connection.execute(
                    "INSERT OR REPLACE INTO legacy_imports VALUES (?, ?)",
                    (str(path.resolve()), digest),
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
                with path.open("a") as file:
                    file.write(event.model_dump_json() + "\n")
                    file.flush()
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
                    with self.path(job.source_id).open("a") as file:
                        file.writelines(event.model_dump_json() + "\n" for event in inserted)
                        file.flush()
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
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        base = "SELECT e.payload, e.recorded_at, e.rowid FROM observations e" + where
        search = normalize((q or "")[:200])
        with self.database.connection() as connection:
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
        return {"events": [adapter.validate_json(row["payload"]) for row in rows], "total": total}

    def sources(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT source_id, MAX(source_filename) AS source_filename, COUNT(*) AS count,"
                " MAX(recorded_at) AS latest_at, GROUP_CONCAT(DISTINCT modality) AS modalities,"
                " GROUP_CONCAT(DISTINCT job_id) AS job_ids FROM observations"
                " GROUP BY source_id ORDER BY latest_at DESC"
            ).fetchall()
        return [
            {
                **dict(row),
                "modalities": row["modalities"].split(","),
                "job_ids": row["job_ids"].split(","),
            }
            for row in rows
        ]

    def review(self, event_id: str, review: Review) -> Event:
        with self.database.connection() as connection:
            source = connection.execute(
                "SELECT source_id FROM observations WHERE event_id=?", (event_id,)
            ).fetchone()
        if source is None:
            raise KeyError(event_id)
        with self.lock, self._source_lock(source["source_id"]):
            with self.database.connection() as connection:
                # Acquire the SQLite writer lease before reading the previous review.
                # This keeps the audit chain correct across app/store instances.
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT payload FROM observations WHERE event_id=?", (event_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(event_id)
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
            # SQLite review and audit are one transaction. Export failure cannot lose either.
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.path(target.source_id)
                temporary = path.with_suffix(f".{uuid4().hex}.tmp")
                try:
                    with temporary.open("w") as file:
                        for event in self.read(target.source_id):
                            file.write(event.model_dump_json() + "\n")
                        file.flush()
                        os.fsync(file.fileno())
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
                with (self.directory / "reviews.jsonl").open("a") as audit_file:
                    audit_file.write(json.dumps(audit) + "\n")
                    audit_file.flush()
                    os.fsync(audit_file.fileno())
            except OSError:
                logger.warning(
                    "Review and audit are saved in SQLite; JSONL exports could not be updated"
                )
            return target
