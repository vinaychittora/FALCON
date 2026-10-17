"""Explicit ownership and expiry of future temporary media tests."""

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from app.config import Settings
from app.media.probe import VideoLibrary
from app.schemas import AnalysisSettings, Job, Video
from app.services.analyzer import Analyzer
from app.storage.lifecycle import lifecycle_lock


class TestSession(BaseModel):
    __test__ = False
    session_id: str
    status: Literal["active", "ending", "ended"]
    created_at: str
    expires_at: str
    message: str = "Temporary uploads and new analysis results are discarded when this session ends."


class TestSessionService:
    __test__ = False

    def __init__(self, settings: Settings, analyzer: Analyzer, library: VideoLibrary):
        self.settings, self.analyzer, self.library = settings, analyzer, library
        self._data_root, self._samples_root = settings.data_dir.resolve(), library.directory.resolve()
        self._temp_root = (self._data_root / "temp").resolve()
        if not self._samples_root.is_relative_to(self._data_root):
            raise ValueError("Temporary tests require a media directory inside application data")
        self.database = analyzer.jobs.database
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._cleaning: set[str] = set()
        with self.database.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS media_test_sessions (
                    session_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, message TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS media_test_jobs (
                    job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, source_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS media_test_jobs_session ON media_test_jobs(session_id);
                CREATE TABLE IF NOT EXISTS media_test_sources (
                    session_id TEXT NOT NULL, source_id TEXT NOT NULL,
                    PRIMARY KEY(session_id, source_id)
                );
                CREATE TABLE IF NOT EXISTS media_test_uploads (
                    path TEXT PRIMARY KEY, session_id TEXT NOT NULL, source_id TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS media_test_partial_uploads (
                    path TEXT PRIMARY KEY, session_id TEXT NOT NULL
                );
            """)

    def create(self) -> TestSession:
        now = datetime.now(UTC)
        session = TestSession(
            session_id=uuid4().hex, status="active", created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=24)).isoformat(),
        )
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO media_test_sessions VALUES (?, ?, ?, ?, ?)",
                (session.session_id, session.status, session.created_at, session.expires_at, session.message),
            )
        return session

    def get(self, identity: str) -> TestSession:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM media_test_sessions WHERE session_id=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return TestSession(**dict(row))

    def require_active(self, identity: str) -> TestSession:
        session = self.get(identity)
        if session.status != "active" or datetime.fromisoformat(session.expires_at) <= datetime.now(UTC):
            raise ValueError("This temporary media session has ended or expired")
        return session

    @contextmanager
    def operation(self, identity: str | None) -> Iterator[None]:
        with lifecycle_lock(self._data_root), self._lock:
            if identity:
                self.require_active(identity)
            yield

    def heartbeat(self, identity: str) -> TestSession:
        with self.operation(identity), self.database.connection() as connection:
            connection.execute(
                "UPDATE media_test_sessions SET expires_at=? WHERE session_id=?",
                ((datetime.now(UTC) + timedelta(hours=24)).isoformat(), identity),
            )
        return self.get(identity)

    def borrow_source(self, identity: str, source_id: str) -> None:
        with self.operation(identity), self.database.connection() as connection:
            connection.execute("INSERT OR IGNORE INTO media_test_sources VALUES (?, ?)", (identity, source_id))

    def reserve_upload(self, identity: str, path: Path, source_id: str, information: os.stat_result) -> None:
        if path.parent.resolve() != self._samples_root:
            raise ValueError("Temporary uploads must remain inside the media directory")
        with self.operation(identity), self.database.connection() as connection:
            connection.execute(
                "INSERT INTO media_test_uploads VALUES (?, ?, ?, ?, ?)",
                (str(path.absolute()), identity, source_id, information.st_size, information.st_mtime_ns),
            )
        self.borrow_source(identity, source_id)

    def keep_source(self, source_id: str) -> None:
        """An explicitly persistent upload can adopt an existing temporary file."""
        with self.operation(None), self.database.connection() as connection:
            connection.execute("DELETE FROM media_test_uploads WHERE source_id=?", (source_id,))

    def reserve_partial_upload(self, identity: str, path: Path) -> None:
        if path.parent.resolve() != self._temp_root or path.exists():
            raise ValueError("Temporary upload path is unavailable")
        with self.operation(identity), self.database.connection() as connection:
            connection.execute("INSERT INTO media_test_partial_uploads VALUES (?, ?)", (str(path.absolute()), identity))

    def forget_partial_upload(self, identity: str, path: Path) -> None:
        with self.database.connection() as connection:
            connection.execute("DELETE FROM media_test_partial_uploads WHERE path=? AND session_id=?", (str(path.absolute()), identity))

    def forget_upload_reservation(self, identity: str, path: Path) -> None:
        with self.operation(identity), self.database.connection() as connection:
            connection.execute("DELETE FROM media_test_uploads WHERE path=? AND session_id=?", (str(path.absolute()), identity))

    def start_analysis(self, identity: str, path: Path, video: Video, config: AnalysisSettings) -> Job:
        with self.operation(identity):
            job_id = str(uuid4())
            with self.database.connection() as connection:
                connection.execute("INSERT INTO media_test_jobs VALUES (?, ?, ?)", (job_id, identity, video.source_id))
            self.borrow_source(identity, video.source_id)
            # Ownership is durable before a worker can persist any results.
            return self.analyzer.start(path, video, config, job_id=job_id)

    def authorize_resume(self, job_id: str, identity: str | None) -> None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT session_id FROM media_test_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row and row["session_id"] != identity:
            raise ValueError("Reopen the owning temporary session before resuming this analysis")
        if identity:
            self.require_active(identity)
        # Legacy runs are never adopted or deleted, even when resumed in a tab
        # that also has an active temporary test session.

    def end(self, identity: str) -> TestSession:
        with self.operation(None):
            session = self.get(identity)
            if session.status == "ended":
                return session
            with self.database.connection() as connection:
                connection.execute(
                    "UPDATE media_test_sessions SET status='ending', message=? WHERE session_id=?",
                    ("Stopping this session's analysis before discarding its temporary data.", identity),
                )
            if identity not in self._cleaning:
                self._cleaning.add(identity)
                threading.Thread(target=self._finish, args=(identity,), daemon=True, name="falcon-test-cleanup").start()
        return self.get(identity)

    def startup(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._reap, daemon=True, name="falcon-test-expiry")
        self._worker.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=2)

    def _reap(self) -> None:
        while not self._stop.is_set():
            with self.database.connection() as connection:
                rows = connection.execute(
                    "SELECT session_id FROM media_test_sessions WHERE status='ending' "
                    "OR (status='active' AND expires_at<=?)", (datetime.now(UTC).isoformat(),),
                ).fetchall()
            for row in rows:
                with self.operation(None):
                    current = self.get(row["session_id"])
                    if current.status == "ending" or datetime.fromisoformat(current.expires_at) <= datetime.now(UTC):
                        self.end(row["session_id"])
            self._stop.wait(60)

    def _finish(self, identity: str) -> None:
        try:
            with self.database.connection() as connection:
                rows = connection.execute("SELECT job_id, source_id FROM media_test_jobs WHERE session_id=?", (identity,)).fetchall()
            job_ids = {row["job_id"] for row in rows}
            while True:
                busy = False
                for job_id in job_ids:
                    if cancellation := self.analyzer.cancellations.get(job_id):
                        cancellation.set()
                        busy = True
                    else:
                        try:
                            busy = busy or self.analyzer.jobs.get(job_id).status in {"queued", "running", "pausing"}
                        except KeyError:
                            pass
                if not busy:
                    break
                if self._stop.wait(0.1):
                    return
            self._discard(identity, job_ids, {row["source_id"] for row in rows})
        except Exception:
            with self.database.connection() as connection:
                connection.execute(
                    "UPDATE media_test_sessions SET status='ending', message=? WHERE session_id=?",
                    ("Cleanup could not finish safely. Temporary data is retained and cleanup will retry.", identity),
                )
        finally:
            with self._lock:
                self._cleaning.discard(identity)

    def _safe_path(self, path: Path) -> None:
        if not path.parent.resolve().is_relative_to(self._data_root) or path.is_symlink():
            raise ValueError("Temporary test cleanup cannot leave application data")

    def _replace_lines(self, path: Path, lines: list[str]) -> None:
        self._safe_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x") as output:
                output.writelines(line.rstrip("\n") + "\n" for line in lines)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _discard(self, identity: str, job_ids: set[str], source_ids: set[str]) -> None:
        events = self.analyzer.events
        with self.operation(None), events.lock, self.analyzer.jobs.lock:
            with self.database.connection() as connection:
                owned_events = {
                    row["event_id"] for row in connection.execute(
                        "SELECT event_id FROM observations WHERE job_id IN "
                        "(SELECT job_id FROM media_test_jobs WHERE session_id=?)", (identity,),
                    )
                }
            # Rewrite mirrors first. A crash before SQLite deletion leaves the
            # authoritative records intact; it cannot resurrect deleted results.
            for source_id in source_ids:
                self._safe_path(events.path(source_id))
                with events._source_lock(source_id):
                    retained = [event for event in events.read(source_id) if event.job_id not in job_ids]
                    self._replace_lines(events.path(source_id), [event.model_dump_json() for event in retained])
            reviews = events.directory / "reviews.jsonl"
            self._safe_path(reviews)
            if reviews.exists():
                retained_lines = [line for line in reviews.read_text().splitlines() if line.strip() and json.loads(line).get("event_id") not in owned_events]
                self._replace_lines(reviews, retained_lines)
            for job_id in job_ids:
                # These IDs were generated by this service, never supplied by a client.
                for path in (
                    self.analyzer.jobs.directory / f"{job_id}.json",
                    self.settings.data_dir / "temp" / f"debug-audio-{job_id}.wav",
                ):
                    self._safe_path(path)
                    path.unlink(missing_ok=True)
            with self.database.connection() as connection:
                partial_uploads = connection.execute("SELECT path FROM media_test_partial_uploads WHERE session_id=?", (identity,)).fetchall()
            for row in partial_uploads:
                path = Path(row["path"])
                if path.parent.resolve() == self._temp_root and not path.is_symlink():
                    path.unlink(missing_ok=True)
                self.forget_partial_upload(identity, path)
            with self.database.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                arguments = (identity,)
                subquery = "SELECT job_id FROM media_test_jobs WHERE session_id=?"
                event_query = f"SELECT event_id FROM observations WHERE job_id IN ({subquery})"
                if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_links'").fetchone():
                    connection.execute(f"DELETE FROM evidence_links WHERE event_id IN ({event_query})", arguments)
                connection.execute(f"DELETE FROM review_audit WHERE event_id IN ({event_query})", arguments)
                connection.execute(f"DELETE FROM observations WHERE job_id IN ({subquery})", arguments)
                connection.execute(f"DELETE FROM analysis_checkpoints WHERE job_id IN ({subquery})", arguments)
                connection.execute(f"DELETE FROM jobs WHERE job_id IN ({subquery})", arguments)
                connection.execute("DELETE FROM media_test_jobs WHERE session_id=?", arguments)
                connection.execute("DELETE FROM media_test_sources WHERE session_id=?", arguments)
            preserved = self._discard_unused_uploads()
            with self.database.connection() as connection:
                connection.execute(
                    "UPDATE media_test_sessions SET status='ended', message=? WHERE session_id=?",
                    (
                        "Temporary results discarded; files changed outside this session were retained."
                        if preserved else "Temporary media tests discarded. Earlier saved records and field observations are retained.",
                        identity,
                    ),
                )

    def _discard_unused_uploads(self) -> int:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT u.* FROM media_test_uploads u JOIN media_test_sessions s USING(session_id) "
                "WHERE s.status IN ('ending', 'ended') AND NOT EXISTS (SELECT 1 FROM media_test_sources r WHERE r.source_id=u.source_id) "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.source_id=u.source_id)"
            ).fetchall()
        preserved = 0
        for row in rows:
            path = Path(row["path"])
            if path.parent.resolve() != self._samples_root or path.is_symlink():
                with self.database.connection() as connection:
                    connection.execute("DELETE FROM media_test_uploads WHERE path=?", (row["path"],))
                preserved += 1
                continue
            if path.exists():
                information = path.stat()
                if information.st_size != row["size_bytes"] or information.st_mtime_ns != row["mtime_ns"]:
                    with self.database.connection() as connection:
                        connection.execute("DELETE FROM media_test_uploads WHERE path=?", (row["path"],))
                    preserved += 1
                    continue
                path.unlink()
            with self.database.connection() as connection:
                connection.execute("DELETE FROM media WHERE path=?", (str(path.absolute()),))
                connection.execute("DELETE FROM media_test_uploads WHERE path=?", (str(path.absolute()),))
            self.library.paths.pop(row["source_id"], None)
        return preserved
