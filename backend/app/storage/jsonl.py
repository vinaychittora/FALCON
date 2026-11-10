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

from app.inference.insects import LABEL as INSECT_LABEL
from app.inference.labels import counted_classification, visit_classification
from app.schemas import AnalysisSettings, Event, Job, Review
from app.storage.database import Database, database_for
from app.storage.jobs import AnalysisCheckpoint, now
from app.storage.lifecycle import lifecycle_lock
from app.storage.observation_context import capture_time_sql, enrich_events, origin_sql, tables

adapter: TypeAdapter[Event] = TypeAdapter(Event)  # type: ignore[arg-type]
# Visual similarity or acoustic confidence, for minimum-score filters.
SCORE_SQL = "COALESCE(json_extract(e.payload,'$.classification.score'), json_extract(e.payload,'$.confidence'))"
# A visual track within one session or job is one animal visit; so is a bout of repeated
# calls of one species. Older sound records without a bout stand alone.
ENCOUNTER_KEY_SQL = (
    "CASE WHEN e.modality='visual' THEN COALESCE(json_extract(e.payload,'$.visit_id'), "
    "e.job_id || ':' || COALESCE(json_extract(e.payload,'$.track_id'), e.event_id)) "
    "ELSE COALESCE(e.job_id || ':' || json_extract(e.payload,'$.bout_id'), e.event_id) END"
)
# An unreviewed visual record that says nothing useful yet: no species, no group, or a
# person/vehicle. Kept in the archive, hidden from feeds that ask for resolved records.
UNRESOLVED_SQL = (
    "(e.modality='visual' AND e.review_status='unreviewed' AND ("
    "json_extract(e.payload,'$.classification.status')='non_wildlife' OR ("
    "json_extract(e.payload,'$.classification.status')='unknown' AND "
    "COALESCE(json_extract(e.payload,'$.classification.broad_group'),'organism')='organism')))"
)
REVIEWED_SQL = "e.review_status IN ('correct','corrected','unknown','false_positive')"
# Visits formed by the Phase 1 rules (records with a visit_id): why the visit is hidden,
# CANDIDATE until promoted. Records without a visit_id keep the old rules.
VISIT_HIDDEN_SQL = (
    "(SELECT COALESCE(v.hidden_reason, '') FROM visits v WHERE v.visit_id=json_extract(e.payload,'$.visit_id'))"
)
# "Show unresolved" off: old records hide unresolved frames; new visits hide still
# records, unidentified, small and not-yet-promoted candidates. Reviewed ones always show.
RESOLVED_SQL = (
    "(CASE WHEN json_extract(e.payload,'$.visit_id') IS NULL OR e.modality!='visual' "
    f"THEN NOT {UNRESOLVED_SQL} "
    f"ELSE e.review_status!='unreviewed' OR COALESCE({VISIT_HIDDEN_SQL}, 'CANDIDATE') "
    "NOT IN ('STILL','UNIDENTIFIED','SMALL','CANDIDATE','INSECT_NIGHT') END)"
)
GLIMPSE_SQL = (
    "MIN(e.modality)='visual' AND ((MAX(json_extract(e.payload,'$.visit_id')) IS NULL AND COUNT(*)=1) "
    f"OR COALESCE(MAX({VISIT_HIDDEN_SQL}), '')='GLIMPSE')"
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
        resolved_only: bool = False,
    ) -> dict[str, Any]:
        limit, offset = min(500, max(1, limit)), max(0, offset)
        conditions: list[str] = []
        parameters: list[Any] = []
        if resolved_only:
            conditions.append(RESOLVED_SQL)
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
        resolved_only: bool = False,
    ) -> tuple[list[str], list[Any]]:
        available = tables(connection)
        conditions: list[str] = []
        parameters: list[Any] = []
        if resolved_only:
            conditions.append(RESOLVED_SQL)
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
        limit: int = 50, offset: int = 0, resolved_only: bool = False,
        order: Literal["latest", "first_seen"] = "latest", hide_glimpses: bool = False,
        tiers: AnalysisSettings | None = None,
    ) -> dict[str, Any]:
        """One row per animal visit: a visual track, or a single sound detection.

        Frame-level records of the same track are grouped, so a reviewer decides once
        per encounter instead of once per analyzed frame. `order` sorts by the latest
        activity (review) or by when each visit began (a live feed that must not reorder
        while an animal lingers). With resolved_only, unresolved records are left out and
        the number of visits hidden that way is reported.
        """
        limit, offset = min(200, max(1, limit)), max(0, offset)
        with self.database.connection() as connection:
            available = tables(connection)
            conditions, parameters = self._filters(
                connection, source_id=source_id, scope=scope, review_status=review_status, modality=modality,
                captured_from=captured_from, captured_to=captured_to, min_score=min_score,
                include_discarded=include_discarded, q=q, resolved_only=resolved_only,
            )
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            hidden = 0
            if resolved_only:
                unfiltered = " WHERE " + " AND ".join(conditions[1:]) if conditions[1:] else ""
                every = connection.execute(
                    f"SELECT COUNT(DISTINCT {ENCOUNTER_KEY_SQL}) FROM observations e" + unfiltered, parameters,
                ).fetchone()[0]
                hidden = max(0, every - connection.execute(
                    f"SELECT COUNT(DISTINCT {ENCOUNTER_KEY_SQL}) FROM observations e" + where, parameters,
                ).fetchone()[0])
            capture = capture_time_sql(available)
            grouped = (
                f"SELECT {ENCOUNTER_KEY_SQL} AS encounter_id, COUNT(*) AS records, "
                f"MIN(COALESCE(julianday({capture}), julianday(e.recorded_at))) AS first_day, "
                f"MAX(COALESCE(julianday({capture}), julianday(e.recorded_at))) AS last_day, "
                "GROUP_CONCAT(DISTINCT e.review_status) AS statuses "
                "FROM observations e" + where + " GROUP BY encounter_id"
            )
            glimpses = 0
            if hide_glimpses:
                # A glimpse: a picture visit seen in one analysed frame only.
                glimpse = GLIMPSE_SQL
                glimpses = connection.execute(
                    f"SELECT COUNT(*) FROM ({grouped} HAVING {glimpse})", parameters,
                ).fetchone()[0]
                grouped += f" HAVING NOT ({glimpse})"
            total = connection.execute(f"SELECT COUNT(*) FROM ({grouped})", parameters).fetchone()[0]
            sort = "first_day DESC" if order == "first_seen" else "last_day DESC"
            groups = connection.execute(
                f"SELECT * FROM ({grouped}) ORDER BY {sort}, encounter_id LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            if not groups:
                return {"encounters": [], "total": total, "hidden_unresolved": hidden, "hidden_glimpses": glimpses}
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
        # Phase 1 visits carry their counted tier in the visits table (spec P5).
        visit_ids = [e.visit_id for key in keys for e in members.get(key, [])[-1:]
                     if e.modality == "visual" and e.visit_id]
        counted: dict[str, dict[str, Any]] = {}
        if visit_ids:
            with self.database.connection() as connection:
                for row in connection.execute(
                    f"SELECT visit_id, hidden_reason, payload FROM visits WHERE visit_id IN ({','.join('?' * len(visit_ids))})",
                    visit_ids,
                ):
                    counted[row["visit_id"]] = {**json.loads(row["payload"]), "hidden_reason": row["hidden_reason"]}
        for group in groups:
            key = group["encounter_id"]
            events = members.get(key, [])
            if not events:
                continue
            event = latest_by_key[key]
            row = counted.get(event.visit_id or "") if event.modality == "visual" else None
            if row and row.get("hidden_reason") == "INSECT_NIGHT" and event.modality == "visual" \
                    and event.review.status == "unreviewed":
                # Insects at night: never named, never Likely or Probable.
                c = event.classification.model_copy(deep=True)
                c.status, c.certainty, c.scientific_name, c.common_name = "unknown", "unknown", None, None
                c.broad_group, c.contenders, c.genus = "organism", [], None
                c.unknown_reason = c.display_label = INSECT_LABEL
                event = event.model_copy(update={"classification": c})
            elif row and row.get("tier") and event.modality == "visual" and event.review.status == "unreviewed":
                candidates = sorted(
                    {c.taxon_id: c for item in events if item.modality == "visual"
                     for c in item.classification.top_k or []}.values(),
                    key=lambda c: -c.score,
                )
                event = event.model_copy(update={
                    "classification": counted_classification(event.classification, row, candidates)})
            elif tiers is not None and event.modality == "visual" and event.review.status == "unreviewed":
                # The visit's tier comes from its best agreeing frames, not its latest one.
                tiered = visit_classification(
                    [item.classification for item in events if item.modality == "visual"],
                    event.classification, tiers,
                    boxes=[item.bbox_norm for item in events if item.modality == "visual"],
                )
                if tiered is not event.classification:
                    event = event.model_copy(update={"classification": tiered})
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
                # A sound bout is as certain as its clearest call.
                "best_confidence": best.confidence if best.modality == "audio" else None,
            })
        return {"encounters": result, "total": total, "hidden_unresolved": hidden, "hidden_glimpses": glimpses}

    def _decisive_rows(
        self, connection: sqlite3.Connection, where: str, parameters: list[Any],
    ) -> list[sqlite3.Row]:
        """One row per visit: the latest human review, else the latest machine record."""
        available = tables(connection)
        capture = capture_time_sql(available)
        base = (
            "SELECT e.event_id, e.modality, e.job_id, e.source_id, e.review_status, e.timestamp_ms, "
            f"{ENCOUNTER_KEY_SQL} AS encounter_id, {capture} AS captured_at, "
            "json_extract(e.payload,'$.review.updated_at') AS reviewed_at, "
            "json_extract(e.payload,'$.review.corrected_scientific_name') AS corrected_scientific, "
            "json_extract(e.payload,'$.review.corrected_common_name') AS corrected_common, "
            "COALESCE(json_extract(e.payload,'$.classification.scientific_name'), "
            "json_extract(e.payload,'$.scientific_name')) AS predicted_scientific, "
            "COALESCE(json_extract(e.payload,'$.classification.common_name'), "
            "json_extract(e.payload,'$.common_name')) AS predicted_common, "
            "json_extract(e.payload,'$.classification.status') AS classification_status, "
            "COALESCE(json_extract(e.payload,'$.classification.broad_group'),'') AS broad_group, "
            f"{SCORE_SQL} AS score FROM observations e" + where
        )
        ranked = (
            "SELECT *, ROW_NUMBER() OVER (PARTITION BY encounter_id ORDER BY "
            "CASE WHEN review_status IN ('correct','corrected','unknown','false_positive') THEN 0 ELSE 1 END, "
            "reviewed_at DESC, timestamp_ms DESC, event_id DESC) AS rank, "
            "COUNT(*) OVER (PARTITION BY encounter_id) AS records, "
            "MIN(captured_at) OVER (PARTITION BY encounter_id) AS first_at, "
            "MAX(captured_at) OVER (PARTITION BY encounter_id) AS last_at "
            f"FROM ({base})"
        )
        return connection.execute(f"SELECT * FROM ({ranked}) WHERE rank=1", parameters).fetchall()

    @staticmethod
    def _identity(row: sqlite3.Row) -> tuple[str, str | None, str | None, str]:
        """(kind, scientific, common, method) for a decisive row, following the review."""
        status = row["review_status"]
        if status == "false_positive":
            return "not_animal", None, None, "human"
        if status == "corrected":
            return "animal", row["corrected_scientific"], row["corrected_common"], "human"
        if status == "unknown":
            return "animal", None, None, "human"
        if status == "correct":
            return "animal", row["predicted_scientific"], row["predicted_common"], "human"
        if row["modality"] == "audio":
            return "animal", row["predicted_scientific"], row["predicted_common"], "machine"
        classification = row["classification_status"]
        if classification == "non_wildlife":
            return "not_animal", None, None, "machine"
        if classification != "candidate":
            return "animal", None, None, "machine"
        return "animal", row["predicted_scientific"], row["predicted_common"], "machine"

    def summary(
        self, *, source_id: str | None = None, scope: Literal["live", "all"] = "live",
        captured_from: datetime | None = None, captured_to: datetime | None = None,
        review: Literal["verified", "candidates", "everything"] = "candidates",
        names: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        """Counts for researchers: visits per species and per group in a period.

        A visit is one tracked animal or one sound detection; repeated visits by the
        same individual count separately. Unreviewed visits are machine suggestions.
        review: "verified" counts only visits a reviewer confirmed or corrected;
        "candidates" adds unreviewed suggestions and visits marked unsure, leaving out
        rejected detections and unreviewed people or vehicles; "everything" counts
        those too, as "not an animal".
        """
        with self.database.connection() as connection:
            conditions, parameters = self._filters(
                connection, source_id=source_id, scope=scope, review_status=None, modality=None,
                captured_from=captured_from, captured_to=captured_to, min_score=None,
                include_discarded=False, q=None,
            )
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = self._decisive_rows(connection, where, parameters)
        species: dict[str, dict[str, Any]] = {}
        groups: dict[str, int] = {}
        totals = {"visits": 0, "records": 0, "visual": 0, "audio": 0, "identified": 0,
                  "unresolved": 0, "reviewed": 0, "machine": 0, "not_animal": 0}
        for row in rows:
            kind, scientific, common, method = self._identity(row)
            reviewed = method == "human"
            status = row["review_status"]
            if review == "verified" and status not in {"correct", "corrected"}:
                continue
            if review == "candidates" and (status == "false_positive" or (kind == "not_animal" and not reviewed)):
                continue
            totals["visits"] += 1
            totals["records"] += int(row["records"])
            totals[row["modality"]] += 1
            totals["reviewed" if reviewed else "machine"] += 1
            if kind == "not_animal":
                totals["not_animal"] += 1
                continue
            if not scientific:
                totals["unresolved"] += 1
                label = row["broad_group"] or "organism"
                if row["review_status"] == "unknown":
                    label = "unknown (reviewed)"
                groups[label] = groups.get(label, 0) + 1
                continue
            totals["identified"] += 1
            if row["modality"] == "visual":
                group = row["broad_group"] or "organism"
                groups[group] = groups.get(group, 0) + 1
            else:
                groups["Aves"] = groups.get("Aves", 0) + 1
            entry = species.setdefault(scientific, {
                "scientific_name": scientific,
                "common_name": common or (names or {}).get(scientific),
                "visits": 0, "reviewed": 0, "machine": 0, "visual": 0, "audio": 0,
                "first_seen": None, "last_seen": None,
            })
            entry["visits"] += 1
            entry["reviewed" if reviewed else "machine"] += 1
            entry[row["modality"]] += 1
            if not entry["common_name"] and common:
                entry["common_name"] = common
            first, last = row["first_at"], row["last_at"]
            if first and (entry["first_seen"] is None or first < entry["first_seen"]):
                entry["first_seen"] = first
            if last and (entry["last_seen"] is None or last > entry["last_seen"]):
                entry["last_seen"] = last
        ranked = sorted(species.values(), key=lambda item: (-item["visits"], item["scientific_name"]))
        return {
            "totals": totals,
            "species_count": len(ranked),
            "species": ranked,
            "groups": [{"group": key, "visits": value} for key, value in sorted(groups.items(), key=lambda kv: -kv[1])],
        }

    def sessions_overview(
        self, *, captured_from: datetime | None = None, captured_to: datetime | None = None,
        names: dict[str, str | None] | None = None, limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Every recorded observation session (camera or node start to stop) with its counts."""
        with self.database.connection() as connection:
            available = tables(connection)
            if "evidence_sessions" not in available:
                return []
            conditions, parameters = self._filters(
                connection, source_id=None, scope="live", review_status=None, modality=None,
                captured_from=captured_from, captured_to=captured_to, min_score=None,
                include_discarded=False, q=None,
            )
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = self._decisive_rows(connection, where, parameters)
            sessions = [json.loads(row["payload"]) for row in connection.execute(
                "SELECT payload FROM evidence_sessions ORDER BY started_at DESC LIMIT ?", (limit,),
            ).fetchall()]
            clips: dict[str, int] = {}
            if "evidence" in available:
                for row in connection.execute(
                    "SELECT session_id, COUNT(*) AS count FROM evidence WHERE status IN ('ready','partial') GROUP BY session_id"
                ).fetchall():
                    clips[row["session_id"]] = row["count"]
        per_session: dict[str, dict[str, Any]] = {}
        for row in rows:
            kind, scientific, common, method = self._identity(row)
            entry = per_session.setdefault(row["job_id"], {
                "visits": 0, "records": 0, "reviewed": 0, "unresolved": 0, "species": {},
            })
            if kind == "not_animal":
                continue  # rejected detections and unreviewed people or vehicles are not visits
            entry["visits"] += 1
            entry["records"] += int(row["records"])
            if method == "human":
                entry["reviewed"] += 1
            if kind == "animal" and scientific:
                entry["species"].setdefault(scientific, {
                    "scientific_name": scientific, "common_name": common or (names or {}).get(scientific), "visits": 0,
                })["visits"] += 1
            elif kind == "animal":
                entry["unresolved"] += 1
        result = []
        for session in sessions:
            counts = per_session.get(session["session_id"], {"visits": 0, "records": 0, "reviewed": 0, "unresolved": 0, "species": {}})
            if (captured_from or captured_to) and not counts["visits"]:
                started = datetime.fromisoformat(session["started_at"])
                ended = datetime.fromisoformat(session["ended_at"]) if session.get("ended_at") else None
                if captured_to and started > captured_to:
                    continue
                if captured_from and ended and ended < captured_from:
                    continue
            species = sorted(counts["species"].values(), key=lambda item: (-item["visits"], item["scientific_name"]))
            duration = None
            if session.get("ended_at"):
                duration = round((datetime.fromisoformat(session["ended_at"]) - datetime.fromisoformat(session["started_at"])).total_seconds() * 1000)
            result.append({
                "session_id": session["session_id"], "source_id": session["source_id"], "name": session["name"],
                "started_at": session["started_at"], "ended_at": session.get("ended_at"),
                "status": session.get("status", "running"), "duration_ms": duration,
                "visits": counts["visits"], "records": counts["records"], "reviewed": counts["reviewed"],
                "unresolved": counts["unresolved"], "species_count": len(species), "species": species[:8],
                "clips": clips.get(session["session_id"], 0),
                "clock_synchronized": (session.get("settings") or {}).get("clock_synchronized"),
            })
        return result

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
