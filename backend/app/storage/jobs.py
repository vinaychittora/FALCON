import fcntl
import hashlib
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas import Job
from app.storage.database import Database, database_for
from app.storage.lifecycle import lifecycle_lock
from app.taxonomy.cache import atomic_json

logger = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(UTC).isoformat()


class AnalysisCheckpoint(BaseModel):
    """Private resume state; never included in public jobs or JSONL exports."""

    config: dict[str, object] = Field(default_factory=dict)
    source_id: str
    size_bytes: int | None = None
    mtime_ns: int | None = None
    taxa_version: str | None = None
    last_frame_ms: int = -1
    next_sample_s: float = 0
    visual_complete: bool = False
    audio_complete: bool = False
    segment: int = 0
    legacy_boundary: bool = False


class JobStore:
    def __init__(self, directory: Path, database: Database | None = None):
        self.directory = directory
        self.lock = threading.RLock()
        self.database = database or database_for(directory)
        with lifecycle_lock(self.database.path.parent):
            self._migrate()
            self._recover_interrupted()

    def _recover_interrupted(self) -> None:
        # A second app instance can be initialized before its listen port fails.
        # Never relabel work still owned by another worker as interrupted.
        lease_path = self.database.path.parent / "analysis.lock"
        with lease_path.open("ab") as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with self.database.connection() as connection:
                rows = connection.execute("SELECT payload FROM jobs").fetchall()
            for row in rows:
                job = Job.model_validate_json(row["payload"])
                if job.status in {"queued", "running", "pausing"}:
                    job.status = "paused" if self.checkpoint(job.job_id) else "interrupted"
                    job.error = (
                        "Application stopped before this analysis finished; partial results remain."
                    )
                    if job.status == "paused":
                        job.stage = "paused after application restart"
                    job.finished_at = now()
                    self.put(job)

    def _migrate(self) -> None:
        with self.database.connection() as connection:
            for path in sorted(self.directory.glob("*.json")):
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                previous = connection.execute(
                    "SELECT digest FROM legacy_imports WHERE path=?", (str(path.resolve()),)
                ).fetchone()
                if previous and previous["digest"] == digest:
                    continue
                try:
                    job = Job.model_validate_json(raw)
                except ValueError as exc:
                    raise ValueError(f"Malformed job in {path.name}; original preserved") from exc
                connection.execute(
                    "INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?)",
                    (job.job_id, job.source_id, job.created_at, job.model_dump_json()),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO legacy_imports VALUES (?, ?)",
                    (str(path.resolve()), digest),
                )

    def put(self, job: Job) -> None:
        with self.lock:
            with self.database.connection() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?)",
                    (job.job_id, job.source_id, job.created_at, job.model_dump_json()),
                )
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                atomic_json(self.directory / f"{job.job_id}.json", job.model_dump())
            except OSError:
                logger.warning("Job is saved in SQLite; its JSON export could not be updated")

    def get(self, job_id: str) -> Job:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return Job.model_validate_json(row["payload"])

    def checkpoint(self, job_id: str) -> AnalysisCheckpoint | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM analysis_checkpoints WHERE job_id=?", (job_id,)
            ).fetchone()
        return AnalysisCheckpoint.model_validate_json(row["payload"]) if row else None

    def save_checkpoint(self, job: Job, checkpoint: AnalysisCheckpoint) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?)",
                (job.job_id, job.source_id, job.created_at, job.model_dump_json()),
            )
            connection.execute(
                "INSERT OR REPLACE INTO analysis_checkpoints VALUES (?, ?)",
                (job.job_id, json.dumps(checkpoint.model_dump(mode="json"))),
            )

    def active(self) -> Job | None:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return next(
            (
                job
                for row in rows
                if (job := Job.model_validate_json(row["payload"])).status
                in {"queued", "running", "pausing"}
            ),
            None,
        )

    def for_source(self, source_id: str) -> list[Job]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM jobs WHERE source_id=? ORDER BY created_at DESC",
                (source_id,),
            ).fetchall()
        return [Job.model_validate_json(row["payload"]) for row in rows]
