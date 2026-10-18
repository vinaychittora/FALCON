"""Local SQLite authority; JSON/JSONL files remain compatible export mirrors."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        path.chmod(0o600)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source_id, created_at);
                CREATE TABLE IF NOT EXISTS analysis_checkpoints (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id), payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    job_id TEXT NOT NULL, source_filename TEXT NOT NULL,
                    modality TEXT NOT NULL, timestamp_ms INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL, review_status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS observations_source
                    ON observations(source_id, job_id, timestamp_ms);
                CREATE INDEX IF NOT EXISTS observations_review
                    ON observations(review_status, recorded_at);
                CREATE TABLE IF NOT EXISTS observation_terms (
                    event_id TEXT NOT NULL REFERENCES observations(event_id) ON DELETE CASCADE,
                    value TEXT NOT NULL, PRIMARY KEY(event_id, value)
                );
                CREATE INDEX IF NOT EXISTS observation_terms_value ON observation_terms(value);
                CREATE TABLE IF NOT EXISTS review_audit (
                    audit_id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS review_event ON review_audit(event_id);
                CREATE TABLE IF NOT EXISTS media (
                    path TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    imported_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS media_source ON media(source_id);
                CREATE TABLE IF NOT EXISTS camera_profiles (
                    profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
                    username TEXT NOT NULL, password_ciphertext BLOB,
                    audio_enabled INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legacy_imports (
                    path TEXT PRIMARY KEY, digest TEXT NOT NULL
                );
                PRAGMA user_version=1;
                """
            )
            # Incremental mirror checks keep their byte offsets in a separate table, so a
            # database used by this version still works with older FALCON code.
            connection.execute(
                "CREATE TABLE IF NOT EXISTS legacy_import_offsets ("
                "path TEXT PRIMARY KEY, imported_bytes INTEGER NOT NULL)"
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def database_for(directory: Path) -> Database:
    root = directory.parent if directory.name in {"logs", "jobs", "samples"} else directory
    return Database(root / "falcon.sqlite3")
