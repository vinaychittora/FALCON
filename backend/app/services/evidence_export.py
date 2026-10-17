"""Portable FALCON evidence archive; not a Camtrap DP conformance claim."""

import csv
import hashlib
import io
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from app.schemas import Event
from app.schemas_evidence import EvidenceSession
from app.services.review_names import resolve_review_names
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import adapter
from app.storage.observation_context import enrich_events, origin_sql, tables
from app.taxonomy.inaturalist import TaxaCache, TaxaService

OBSERVATION_COLUMNS = [
    "event_id", "source_id", "session_or_job_id", "modality", "start_ms", "end_ms",
    "captured_at", "clock_basis", "source_kind", "accepted_scientific_name", "accepted_common_name",
    "identification_status", "prediction_scientific_name", "prediction_common_name",
    "model_score", "model_score_type", "detector_confidence", "review_status",
    "reviewed_at", "review_notes", "evidence_ids", "bbox_left", "bbox_top", "bbox_right",
    "bbox_bottom", "sensor_status", "sensor_id", "sensor_observed_at", "sensor_age_seconds",
    "temperature_c", "humidity_percent", "pressure_hpa", "models_json",
]
EVIDENCE_COLUMNS = [
    "evidence_id", "source_id", "session_id", "job_id", "media_kind", "status", "captured_at",
    "clock_basis", "requested_start_ms", "requested_end_ms", "actual_start_ms", "actual_end_ms",
    "duration_ms", "size_bytes", "sha256", "mime_type", "audio_present", "event_ids",
    "archive_path", "archive_status", "message",
]
SENSOR_COLUMNS = [
    "schema_version", "reading_id", "sensor_id", "observed_at", "received_at",
    "temperature_c", "humidity_percent", "pressure_hpa", "quality", "quality_note",
]


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _observation_row(
    event: Event, links: dict[str, list[str]],
) -> dict[str, Any]:
    visual = event.modality == "visual"
    start = event.timestamp_ms if event.modality == "visual" else event.start_ms
    end = start + event.duration_ms if event.modality == "visual" else event.end_ms
    scientific = event.classification.scientific_name if event.modality == "visual" else event.scientific_name
    common = event.classification.common_name if event.modality == "visual" else event.common_name
    status = event.review.status
    accepted_scientific, accepted_common = scientific, common
    identification = "reviewed" if status == "correct" else "machine_candidate"
    if status == "corrected":
        accepted_scientific = event.review.corrected_scientific_name
        accepted_common = event.review.corrected_common_name
        identification = "reviewed"
    elif status in {"unknown", "false_positive"}:
        accepted_scientific, accepted_common, identification = None, None, status
    elif event.modality == "visual" and event.classification.status != "candidate":
        accepted_scientific, accepted_common = None, None
        identification = event.classification.status
    # Unreviewed names remain predictions. Do not label them as accepted identifications.
    if identification == "machine_candidate":
        accepted_scientific, accepted_common = None, None
    captured = event.captured_at
    environment = event.environment
    row: dict[str, Any] = {
        "event_id": event.event_id, "source_id": event.source_id, "session_or_job_id": event.job_id,
        "modality": event.modality, "start_ms": start, "end_ms": end, "captured_at": captured,
        "clock_basis": event.time_basis, "source_kind": event.source_kind,
        "accepted_scientific_name": accepted_scientific, "accepted_common_name": accepted_common,
        "identification_status": identification, "prediction_scientific_name": scientific,
        "prediction_common_name": common,
        "model_score": event.classification.score if event.modality == "visual" else event.confidence,
        "model_score_type": "cosine_similarity" if visual else "birdnet_confidence",
        "detector_confidence": event.detector.score if event.modality == "visual" else None,
        "review_status": status, "reviewed_at": event.review.updated_at, "review_notes": event.review.notes,
        "evidence_ids": links.get(event.event_id, []), "sensor_status": environment.status,
        "sensor_id": environment.sensor_id, "sensor_observed_at": environment.observed_at,
        "sensor_age_seconds": environment.age_seconds, "temperature_c": environment.temperature_c,
        "humidity_percent": environment.humidity_percent, "pressure_hpa": environment.pressure_hpa,
        "models_json": event.models,
    }
    if event.modality == "visual":
        row.update(dict(zip(("bbox_left", "bbox_top", "bbox_right", "bbox_bottom"), event.bbox_norm, strict=True)))
    return row


class _ArchiveWriter:
    def __init__(self, archive: ZipFile):
        self.archive = archive
        self.files: dict[str, dict[str, Any]] = {}

    def content(self, name: str, value: str) -> None:
        self.stream(name, (value,))

    def stream(self, name: str, chunks: Iterable[str]) -> None:
        digest, size = hashlib.sha256(), 0
        with self.archive.open(name, "w", force_zip64=True) as target:
            for chunk in chunks:
                block = chunk.encode("utf-8")
                target.write(block)
                digest.update(block)
                size += len(block)
        self.files[name] = {"size_bytes": size, "sha256": digest.hexdigest()}

    def csv(self, name: str, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
        def chunks() -> Iterator[str]:
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            yield output.getvalue()
            for row in rows:
                output.seek(0)
                output.truncate(0)
                writer.writerow({key: _csv_value(value) for key, value in row.items()})
                yield output.getvalue()
        self.stream(name, chunks())

    def media(self, name: str, path: Path) -> tuple[int, str]:
        digest, size = hashlib.sha256(), 0
        # Video is already compressed; avoid competing with field inference to
        # recompress large recordings during an administrator's export.
        entry = ZipInfo(name)
        entry.compress_type = ZIP_STORED
        with path.open("rb") as source, self.archive.open(entry, "w", force_zip64=True) as target:
            while block := source.read(1024 * 1024):
                target.write(block)
                digest.update(block)
                size += len(block)
        value = digest.hexdigest()
        self.files[name] = {"size_bytes": size, "sha256": value}
        return size, value


class _ExportTaxonomy(TaxaService):
    """Keep both output formats on the same taxonomy snapshot during refreshes."""

    def __init__(self, source: TaxaService):
        self.snapshot = source.read()

    def read(self) -> TaxaCache:
        return self.snapshot


def _events(
    connection: sqlite3.Connection, where: str, args: tuple[str, ...],
    taxonomy: TaxaService | None,
) -> Iterator[Event]:
    cursor = connection.execute(
        "SELECT e.payload FROM observations e" + where
        + " ORDER BY e.source_id,e.job_id,e.timestamp_ms,e.event_id", args,
    )
    try:
        while batch := cursor.fetchmany(500):
            events = enrich_events(connection, [adapter.validate_json(row["payload"]) for row in batch])
            if taxonomy is not None:
                events = resolve_review_names(events, taxonomy)
            yield from events
    finally:
        cursor.close()


def _review_audit(
    connection: sqlite3.Connection, source_id: str | None, scope: Literal["live", "all"],
) -> Iterator[str]:
    conditions, args = (["o.source_id=?"], (source_id,)) if source_id else ([], ())
    if scope == "live":
        conditions.append(f"({origin_sql(tables(connection), 'o')})='live'")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    cursor = connection.execute(
        "SELECT a.payload FROM review_audit a JOIN observations o ON o.event_id=a.event_id"
        + where + " ORDER BY a.recorded_at,a.audit_id", args,
    )
    try:
        while batch := cursor.fetchmany(500):
            for row in batch:
                # Preserve the stored audit payload, including the previous decision.
                yield row["payload"] + "\n"
    finally:
        cursor.close()


def _sensor_history(
    connection: sqlite3.Connection, where: str, args: tuple[str, ...],
) -> Iterator[str]:
    cursor = connection.execute(
        "SELECT r.payload FROM sensor_readings r" + where + " ORDER BY r.observed_at,r.reading_id", args,
    )
    try:
        while batch := cursor.fetchmany(500):
            for row in batch:
                yield row["payload"] + "\n"
    finally:
        cursor.close()


def _write_sensor_history(
    writer: _ArchiveWriter, connection: sqlite3.Connection, source_id: str | None,
    sessions: list[EvidenceSession], created_at: str, warnings: list[dict[str, Any]],
    active_session_id: str | None,
) -> int:
    where = ""
    args: tuple[str, ...] = ()
    omit_reason = None
    if "sensor_readings" not in tables(connection):
        omit_reason = "Periodic sensor history is unavailable; detection-attached readings remain in observation records."
    elif source_id:
        linked = [session for session in sessions if session.settings.get("sensor_id") and (
            session.ended_at or (session.status == "running" and session.session_id == active_session_id)
        )]
        if not linked:
            omit_reason = "Periodic readings omitted: this source has no recorded session sensor ID and trustworthy time bounds."
        else:
            where = (
                " WHERE EXISTS(SELECT 1 FROM evidence_sessions s WHERE s.source_id=? "
                "AND json_extract(s.payload,'$.settings.sensor_id')=r.sensor_id "
                "AND (json_extract(s.payload,'$.ended_at') IS NOT NULL OR "
                "(s.session_id=? AND COALESCE(json_extract(s.payload,'$.status'),'running')='running')) "
                "AND julianday(r.observed_at)>=julianday(s.started_at) "
                "AND julianday(r.observed_at)<=min(julianday(COALESCE(json_extract(s.payload,'$.ended_at'),?)),julianday(?)))"
            )
            args = (source_id, active_session_id or "", created_at, created_at)
            if len(linked) < len(sessions):
                warnings.append({"component": "sensor_readings", "reason": "Some source sessions lack a recorded sensor ID or trustworthy end bound; their periodic readings were not associated or exported."})
    if omit_reason:
        warnings.append({"component": "sensor_readings", "reason": omit_reason})
        writer.csv("sensor_readings.csv", SENSOR_COLUMNS, ())
        writer.stream("sensor_readings.jsonl", ())
        return 0
    count = connection.execute("SELECT COUNT(*) FROM sensor_readings r" + where, args).fetchone()[0]
    writer.csv("sensor_readings.csv", SENSOR_COLUMNS, (
        json.loads(payload) for payload in _sensor_history(connection, where, args)
    ))
    writer.stream("sensor_readings.jsonl", _sensor_history(connection, where, args))
    return int(count)


def build_evidence_archive(
    store: EvidenceStore, *, source_id: str | None = None, taxonomy: TaxaService | None = None,
    scope: Literal["live", "all"] = "all",
    active_session_id: str | None = None,
) -> Path:
    """Build on disk in a private temporary file; caller must unlink after delivery."""
    created_at = datetime.now(UTC).isoformat()
    evidence = store.list(source_id=source_id)
    sessions = store.sessions(source_id=source_id)
    conditions, args = (["e.source_id=?"], (source_id,)) if source_id else ([], ())
    if scope == "live":
        with store.database.connection() as connection:
            conditions.append(f"({origin_sql(tables(connection))})='live'")
            live_keys = {(row["source_id"], row["job_id"]) for row in connection.execute(
                "SELECT DISTINCT e.source_id,e.job_id FROM observations e WHERE " + " AND ".join(conditions), args,
            )}
        live_keys.update((session.source_id, session.session_id) for session in sessions)
        evidence = [record for record in evidence if (record.source_id, record.session_id) in live_keys]
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    taxonomy = _ExportTaxonomy(taxonomy) if taxonomy is not None else None
    links: dict[str, list[str]] = {}
    for record in evidence:
        for event_id in record.event_ids:
            links.setdefault(event_id, []).append(record.evidence_id)
    descriptor, filename = tempfile.mkstemp(prefix="falcon-evidence-", suffix=".zip", dir=store.root)
    os.close(descriptor)
    path = Path(filename)
    try:
        with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            writer = _ArchiveWriter(archive)
            evidence_rows: list[dict[str, Any]] = []
            warnings: list[dict[str, Any]] = []
            sensor_count = 0
            for record in evidence:
                row = record.model_dump()
                row.update(archive_path=None, archive_status=record.status)
                if record.status in {"ready", "partial"}:
                    try:
                        media_path = store.media_path(record)
                    except (OSError, ValueError):
                        row["archive_status"] = "unavailable"
                        warnings.append({"evidence_id": record.evidence_id, "reason": "Evidence media was unavailable or its path was unsafe."})
                    else:
                        media_name = f"media/{record.evidence_id}{media_path.suffix.lower()}"
                        size, digest = writer.media(media_name, media_path)
                        row["archive_path"] = media_name
                        if size != record.size_bytes or digest != record.sha256:
                            row["archive_status"] = "checksum_mismatch"
                            warnings.append({"evidence_id": record.evidence_id, "reason": "Stored evidence checksum differs from exported bytes; do not treat as verified evidence."})
                evidence_rows.append(row)
            # One SQLite read snapshot keeps reviews/counts identical in both
            # formats while bounded cursor batches avoid loading the archive in RAM.
            with store.database.connection() as connection:
                connection.execute("BEGIN")
                event_count = connection.execute(
                    "SELECT COUNT(*) FROM observations e" + where, args,
                ).fetchone()[0]
                writer.csv("observations.csv", OBSERVATION_COLUMNS, (
                    _observation_row(event, links)
                    for event in _events(connection, where, args, taxonomy)
                ))
                writer.stream("observations.jsonl", (
                    event.model_dump_json() + "\n"
                    for event in _events(connection, where, args, taxonomy)
                ))
                writer.stream("review_audit.jsonl", _review_audit(connection, source_id, scope))
                if scope == "live":
                    sensor_count = _write_sensor_history(writer, connection, source_id, sessions, created_at, warnings, active_session_id)
            writer.csv("evidence.csv", EVIDENCE_COLUMNS, evidence_rows)
            writer.content("evidence.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in evidence_rows))
            writer.content("sessions.json", json.dumps([session.model_dump() for session in sessions], ensure_ascii=False, indent=2) + "\n")
            writer.content("README.txt", (
                "FALCON evidence archive version 1.0\n"
                "Developer: Vinay Chittora\n\n"
                "UTF-8 CSV and JSONL observation records with linked MP4/WAV evidence.\n"
                "This is not a validated Camtrap DP package. No data or media license is assigned.\n"
                "Receive-clock UTC times are server estimates, not synchronized camera capture times.\n"
                "Imported media without a recording date retains relative timestamps only.\n"
                "Accepted names represent human reviews; predictions retain original model output.\n"
                "review_audit.jsonl preserves each stored review change and its previous decision for the exported observations.\n"
                "Cosine similarity is not a probability. Repeated observations are not animal counts.\n"
                "Evidence status and archive_status distinguish capture failures from missing/changed files.\n"
                "Sensor values are detection-time snapshots; null or stale values are explicit.\n"
                "Field exports also include sensor_readings.csv/JSONL: independent periodic sensor records, not additional animal detections.\n"
                "Unfiltered field exports include all local sensor readings. Source-filtered exports require a recorded session sensor ID and time bounds; otherwise readings are omitted with a manifest warning.\n"
                "Only an explicitly active live session uses export time as its open interval end; historical sessions without an end time are excluded from source-specific sensor association.\n"
                "Sensor observed_at comes from the node clock; received_at is the server clock. Quality flags and explicit Celsius, percent and hPa units are retained.\n"
                "CSV text beginning with spreadsheet formula characters is prefixed with an apostrophe; JSONL retains original text.\n"
                "manifest.json lists SHA-256 checksums of all other archive files.\n"
            ))
            manifest = {
                "format": "falcon-evidence-archive", "version": "1.0", "created_at": created_at,
                "source_id": source_id, "scope": scope, "observations": event_count, "evidence_records": len(evidence),
                "periodic_sensor_readings": sensor_count,
                "camtrap_dp_validated": False, "warnings": warnings, "files": writer.files,
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
