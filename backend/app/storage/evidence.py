# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Persist short evidence captures independently of observation reviews."""

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import wave
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from app.schemas import AnalysisSettings
from app.schemas_evidence import EvidenceRecord, EvidenceSession, utc_timestamp
from app.storage.database import Database


def file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def safe_message(value: object) -> str | None:
    if value is None:
        return None
    # Recorder errors can contain stream credentials or absolute local paths.
    text = re.sub(r"(?:rtsps?|https?)://\S+", "[connection redacted]", str(value))
    text = re.sub(r"(?:[A-Za-z]:[\\/]|/)[^\s,;]+", "[path redacted]", text)
    return text[:1000]


def _media_duration_ms(path: Path, media_kind: str) -> int | None:
    try:
        if media_kind == "audio":
            with wave.open(str(path), "rb") as reader:
                return round(reader.getnframes() / reader.getframerate() * 1000)
        import av

        with av.open(str(path)) as container:
            if container.duration:
                return round(container.duration / 1000)
    except (EOFError, OSError, ValueError, ZeroDivisionError, wave.Error):
        return None
    except Exception:
        # PyAV raises its own error types for damaged containers.
        return None
    return None


class EvidenceStore:
    def __init__(self, database: Database, root: Path):
        self.database = database
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink():
            raise ValueError("Evidence root must not be a symbolic link")
        root.chmod(0o700)
        self.root = root.resolve()
        with database.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS evidence_sessions (
                    session_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    started_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS evidence_sessions_source
                    ON evidence_sessions(source_id, started_at);
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, captured_at TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS evidence_source ON evidence(source_id, captured_at);
                CREATE TABLE IF NOT EXISTS evidence_links (
                    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
                    event_id TEXT NOT NULL REFERENCES observations(event_id),
                    PRIMARY KEY(evidence_id, event_id)
                );
                CREATE INDEX IF NOT EXISTS evidence_event ON evidence_links(event_id);
            """)

    def register_session(
        self, session_id: str, source_id: str, name: str,
        started_at: str | datetime, settings: dict[str, Any] | BaseModel,
    ) -> EvidenceSession:
        values = settings.model_dump(mode="json") if isinstance(settings, BaseModel) else settings
        allowed = set(AnalysisSettings.model_fields)
        safe_settings = AnalysisSettings.model_validate(
            {key: value for key, value in values.items() if key in allowed}
        ).model_dump(mode="json", exclude_unset=True)
        for key in ("evidence_mode", "evidence_seconds", "clock_basis", "deployment_mode", "clock_synchronized"):
            if key in values and isinstance(values[key], (str, int, float, bool)):
                safe_settings[key] = values[key]
        if isinstance(values.get("sensor_id"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", values["sensor_id"]):
            safe_settings["sensor_id"] = values["sensor_id"]
        session = EvidenceSession(
            session_id=session_id, source_id=source_id, name=name,
            started_at=utc_timestamp(started_at),
            settings=safe_settings,
        )
        with self.database.connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO evidence_sessions VALUES (?, ?, ?, ?)",
                (session_id, source_id, session.started_at, session.model_dump_json()),
            )
            stored = connection.execute(
                "SELECT payload FROM evidence_sessions WHERE session_id=?", (session_id,),
            ).fetchone()
        result = EvidenceSession.model_validate_json(stored["payload"])
        if result.source_id != source_id:
            raise ValueError("Session belongs to another source")
        return result

    def sessions(self, source_id: str | None = None) -> list[EvidenceSession]:
        where, args = (" WHERE source_id=?", (source_id,)) if source_id else ("", ())
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM evidence_sessions" + where + " ORDER BY started_at,session_id",
                args,
            ).fetchall()
        return [EvidenceSession.model_validate_json(row["payload"]) for row in rows]

    def finish_session(
        self, session_id: str, ended_at: str | datetime, status: str,
        metrics: dict[str, Any] | None = None,
    ) -> EvidenceSession:
        if status not in {"completed", "stopped", "failed", "interrupted"}:
            raise ValueError("Invalid completed session status")
        ended = utc_timestamp(ended_at)
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM evidence_sessions WHERE session_id=?", (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Evidence session not found")
            session = EvidenceSession.model_validate_json(row["payload"])
            if datetime.fromisoformat(ended) < datetime.fromisoformat(session.started_at):
                raise ValueError("Session end precedes its start")
            safe_metrics = {
                key: value for key, value in (metrics or {}).items()
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            }
            session = session.model_copy(update={"ended_at": ended, "status": status, "metrics": safe_metrics})
            connection.execute(
                "UPDATE evidence_sessions SET payload=? WHERE session_id=?",
                (session.model_dump_json(), session_id),
            )
        return session

    def create(
        self, source_id: str, session_id: str, media_kind: Literal["video", "audio"],
        captured_at: str | datetime, requested_start_ms: int, requested_end_ms: int,
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            evidence_id=str(uuid4()), source_id=source_id, session_id=session_id, job_id=session_id,
            media_kind=media_kind, captured_at=utc_timestamp(captured_at),
            requested_start_ms=requested_start_ms, requested_end_ms=requested_end_ms,
            mime_type="video/mp4" if media_kind == "video" else "audio/wav",
            audio_present=media_kind == "audio",
        )
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?)",
                (record.evidence_id, source_id, session_id, record.captured_at,
                 record.status, record.model_dump_json()),
            )
        return record

    def link(self, evidence_id: str, event_id: str) -> None:
        with self.database.connection() as connection:
            evidence = connection.execute(
                "SELECT source_id,session_id FROM evidence WHERE evidence_id=?", (evidence_id,),
            ).fetchone()
            event = connection.execute(
                "SELECT source_id,job_id FROM observations WHERE event_id=?", (event_id,),
            ).fetchone()
            if evidence is None or event is None:
                raise KeyError("Evidence or observation not found")
            if evidence["source_id"] != event["source_id"] or evidence["session_id"] != event["job_id"]:
                raise ValueError("Evidence and observation belong to different sessions")
            connection.execute(
                "INSERT OR IGNORE INTO evidence_links VALUES (?, ?)", (evidence_id, event_id),
            )

    def list(
        self, source_id: str | None = None, event_id: str | None = None,
        *, limit: int | None = None, offset: int = 0,
    ) -> list[EvidenceRecord]:
        clauses, args = [], []
        if source_id:
            clauses.append("e.source_id=?")
            args.append(source_id)
        if event_id:
            # The whole visit, not only this record: a visit's later clips (and its stay
            # recording) are linked to later records of the same visit.
            clauses.append(
                "EXISTS (SELECT 1 FROM evidence_links l WHERE l.evidence_id=e.evidence_id AND l.event_id IN ("
                "SELECT o.event_id FROM observations o, observations s WHERE s.event_id=? "
                "AND o.source_id=s.source_id AND o.job_id=s.job_id AND (o.event_id=s.event_id OR ("
                "json_extract(s.payload,'$.visit_id') IS NOT NULL AND "
                "json_extract(o.payload,'$.visit_id')=json_extract(s.payload,'$.visit_id')))))"
            )
            args.append(event_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.database.connection() as connection:
            suffix = " LIMIT ? OFFSET ?" if limit is not None else ""
            query_args: list[object] = [*args, limit, offset] if limit is not None else list(args)
            rows = connection.execute(
                "SELECT e.payload, (SELECT json_group_array(l.event_id) FROM evidence_links l "
                "WHERE l.evidence_id=e.evidence_id) AS event_ids FROM evidence e" + where
                + " ORDER BY e.captured_at DESC,e.evidence_id" + suffix, query_args,
            ).fetchall()
        records = [EvidenceRecord.model_validate({
            **json.loads(row["payload"]), "event_ids": sorted(json.loads(row["event_ids"])),
        }) for row in rows]
        if event_id:
            # For one visit: the longest video (a whole-stay recording) first, then the
            # rest in time order.
            records.sort(key=lambda r: r.captured_at)
            videos = [r for r in records if r.media_kind == "video"]
            if videos:
                longest = max(videos, key=lambda r: (r.duration_ms or 0, r.requested_end_ms - r.requested_start_ms))
                records = [longest, *[r for r in records if r is not longest]]
        return records

    def recover_pending(self) -> int:
        """Explicit startup recovery, guarded against another process's live worker."""
        lock_path = self.database.path.parent / "analysis.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "ab") as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            return self._recover_pending_locked()

    def _recover_pending_locked(self) -> int:
        self._remove_interrupted_temporaries()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT evidence_id,payload FROM evidence WHERE status='pending'").fetchall()
            for row in rows:
                record = EvidenceRecord.model_validate_json(row["payload"])
                record = self._recovered_file(record) or record.model_copy(update={
                    "status": "failed", "message": "Capture interrupted before completion; no verified clip is available.",
                })
                connection.execute(
                    "UPDATE evidence SET status=?,payload=? WHERE evidence_id=?",
                    (record.status, record.model_dump_json(), record.evidence_id),
                )
        return len(rows)

    def _remove_interrupted_temporaries(self) -> None:
        """Delete only this application's unfinished temporary files, never evidence."""
        patterns = (".*.part.mp4", ".audio-*.wav", "falcon-evidence-*.zip")
        for pattern in patterns:
            for path in self.root.glob(pattern):
                try:
                    if path.is_file() and not path.is_symlink():
                        path.unlink()
                except OSError:
                    pass

    def _recovered_file(self, record: EvidenceRecord) -> EvidenceRecord | None:
        """A clip is linked into place only after fsync; keep one whose record update was lost."""
        suffix = ".mp4" if record.media_kind == "video" else ".wav"
        try:
            path = self.safe_path(f"{record.evidence_id}{suffix}")
            size, digest = file_digest(path)
        except (OSError, ValueError):
            return None
        duration = _media_duration_ms(path, record.media_kind) if size else None
        if not duration:
            return None
        path.chmod(0o600)
        return record.model_copy(update={
            "status": "partial", "relative_path": path.name, "size_bytes": size, "sha256": digest,
            "duration_ms": duration, "actual_start_ms": record.requested_start_ms,
            "actual_end_ms": record.requested_start_ms + duration,
            "message": "Recovered after an interruption. The clip finished writing; its start is approximated by the requested start.",
        })

    def get(self, evidence_id: str) -> EvidenceRecord:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM evidence WHERE evidence_id=?", (evidence_id,),
            ).fetchone()
            links = connection.execute(
                "SELECT event_id FROM evidence_links WHERE evidence_id=? ORDER BY event_id", (evidence_id,),
            ).fetchall()
        if row is None:
            raise KeyError("Evidence not found")
        return EvidenceRecord.model_validate({
            **json.loads(row["payload"]), "event_ids": [link["event_id"] for link in links],
        })

    def safe_path(self, value: str | Path, *, must_exist: bool = True) -> Path:
        raw = str(value)
        if "\\" in raw or "\x00" in raw:
            raise ValueError("Invalid evidence path")
        supplied = Path(raw)
        if supplied.is_absolute():
            try:
                supplied = supplied.relative_to(self.root)
            except ValueError as exc:
                raise ValueError("Evidence path is outside its storage folder") from exc
        parts = PurePosixPath(supplied.as_posix()).parts
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("Invalid evidence path")
        result = self.root.joinpath(*parts)
        current = self.root
        for part in parts:
            current /= part
            if current.is_symlink():
                raise ValueError("Evidence paths cannot contain symbolic links")
        if not result.resolve().is_relative_to(self.root):
            raise ValueError("Evidence path is outside its storage folder")
        if must_exist and (not result.is_file() or not stat.S_ISREG(result.stat().st_mode)):
            raise FileNotFoundError("Evidence media is unavailable")
        return result

    def media_path(self, record: EvidenceRecord) -> Path:
        if record.status not in {"ready", "partial"} or not record.relative_path:
            raise FileNotFoundError("Evidence media is not available")
        return self.safe_path(record.relative_path)

    def complete(self, evidence_id: str, result: dict[str, Any]) -> EvidenceRecord:
        existing = self.get(evidence_id)
        if existing.status != "pending":
            return existing
        values = dict(result)
        for alias, canonical in {
            "path": "relative_path", "size": "size_bytes", "sha": "sha256", "duration": "duration_ms",
        }.items():
            if alias in values:
                values.setdefault(canonical, values.pop(alias))
        if "actualinterval" in values:
            values["actual_start_ms"], values["actual_end_ms"] = values.pop("actualinterval")
        if "actual_interval" in values:
            values["actual_start_ms"], values["actual_end_ms"] = values.pop("actual_interval")
        allowed = {
            "status", "relative_path", "size_bytes", "sha256", "duration_ms", "actual_start_ms",
            "actual_end_ms", "message", "audio_present", "mime_type",
        }
        if set(values) - allowed:
            raise ValueError("Unsupported evidence completion field")
        values["message"] = safe_message(values.get("message"))
        if values.get("status") not in {"ready", "partial", "failed"}:
            raise ValueError("Evidence completion must be ready, partial or failed")
        if values["status"] == "failed":
            values.update(relative_path=None, size_bytes=0, sha256=None, duration_ms=0,
                          actual_start_ms=None, actual_end_ms=None)
        else:
            path = self.safe_path(values.get("relative_path") or "")
            if path.suffix.lower() != (".mp4" if existing.media_kind == "video" else ".wav"):
                raise ValueError("Evidence file type does not match its record")
            size, digest = file_digest(path)
            if values.get("sha256") not in {None, digest} or values.get("size_bytes") not in {None, size}:
                raise ValueError("Evidence checksum or size does not match its file")
            path.chmod(0o600)
            values.update(relative_path=path.relative_to(self.root).as_posix(), size_bytes=size, sha256=digest)
            if values.get("actual_start_ms") is not None:
                values["captured_at"] = (
                    datetime.fromisoformat(existing.captured_at)
                    + timedelta(milliseconds=values["actual_start_ms"] - existing.requested_start_ms)
                ).isoformat()
        record = EvidenceRecord.model_validate({**existing.model_dump(), **values})
        payload = record.model_copy(update={"event_ids": []}).model_dump_json()
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE evidence SET payload=?,status=?,captured_at=? WHERE evidence_id=? AND status='pending'",
                (payload, record.status, record.captured_at, evidence_id),
            )
        return self.get(evidence_id)
