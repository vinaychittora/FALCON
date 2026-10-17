import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
import torch

from app.config import Settings
from app.schemas import AnalysisSettings, Job, Video
from app.services.analyzer import Analyzer
from app.storage.jobs import JobStore
from app.storage.jsonl import EventStore
from app.taxonomy.inaturalist import TaxaService
from tests.test_inference import taxa


def runner(path: Path) -> Analyzer:
    taxonomy = TaxaService(path)
    taxonomy.read = Mock(return_value=taxa())
    return Analyzer(
        Settings(data_dir=path), taxonomy, EventStore(path / "logs"), JobStore(path / "jobs")
    )


def media() -> Video:
    return Video(
        source_id="a" * 24,
        filename="fixture.mp4",
        duration_ms=1000,
        width=80,
        height=40,
        fps=30,
        codec="h264",
        audio=False,
        size_bytes=1,
    )


def finished(worker: Analyzer, job: Job) -> Job:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = worker.jobs.get(job.job_id)
        if current.status not in {"queued", "running"} and not worker.lock.locked():
            return current
        time.sleep(0.01)
    raise AssertionError("Worker did not finish within five seconds")


def test_busy_cross_process_lease_cancel_and_failure_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    one, two = runner(tmp_path), runner(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def loading(*args: object) -> tuple[Mock, Mock]:
        entered.set()
        assert release.wait(4)
        return Mock(), Mock()

    one.registry.load = Mock(side_effect=loading)
    job = one.start(tmp_path / "fixture.mp4", media(), AnalysisSettings())
    assert entered.wait(2)
    with pytest.raises(RuntimeError, match="Another analysis"):
        one.start(tmp_path / "fixture.mp4", media(), AnalysisSettings())
    with pytest.raises(RuntimeError, match="Another app"):
        two.start(tmp_path / "fixture.mp4", media(), AnalysisSettings())
    one.cancel(job.job_id)
    release.set()
    assert finished(one, job).status == "cancelled"
    two.registry.load = Mock(side_effect=RuntimeError("fixture model failure"))
    failed = two.start(tmp_path / "fixture.mp4", media(), AnalysisSettings())
    outcome = finished(two, failed)
    assert outcome.status == "failed" and "fixture model failure" in (outcome.error or "")
    assert not two.lock.locked()


def test_restart_marks_unfinished_job_interrupted(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.put(
        Job(job_id="unfinished", source_id="a" * 24, status="running", created_at="2026-01-01")
    )
    restored = JobStore(tmp_path).get("unfinished")
    assert restored.status == "interrupted"
    assert restored.finished_at and "partial results remain" in (restored.error or "")


def test_second_store_does_not_interrupt_a_live_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    worker = runner(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def loading(*args: object) -> tuple[Mock, Mock]:
        entered.set()
        assert release.wait(4)
        return Mock(), Mock()

    worker.registry.load = Mock(side_effect=loading)
    job = worker.start(tmp_path / "fixture.mp4", media(), AnalysisSettings())
    assert entered.wait(2)
    try:
        second = JobStore(tmp_path / "jobs")
        assert second.get(job.job_id).status == "running"
        assert worker.jobs.get(job.job_id).status == "running"
    finally:
        worker.cancel(job.job_id)
        release.set()
    assert finished(worker, job).status == "cancelled"
