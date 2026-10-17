import sqlite3
import threading
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import torch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.jobs import router
from app.inference.base import Proposal
from app.inference.pipeline import visual_pipeline
from app.media.base import Frame
from app.media.file_source import FileSource
from app.schemas import AnalysisSettings, AudioEvent, Job, Review
from app.storage.jobs import AnalysisCheckpoint, JobStore
from tests.test_inference import taxa
from tests.test_persistence import event
from tests.test_worker import finished, media, runner


def test_seek_preserves_grid_when_next_frame_precedes_old_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A real pattern in LRK: 66.533 -> 67.000 s. Coverage was 67.033,
    # so using coverage as the seek/filter cutoff would skip a valid frame.
    points = [66000, 66533, 66967, 67000, 67501, 68001]
    stream = SimpleNamespace(time_base=Fraction(1, 1000), codec_context=SimpleNamespace())
    container = Mock()
    container.__enter__ = Mock(return_value=container)
    container.__exit__ = Mock(return_value=False)
    container.streams = SimpleNamespace(video=[stream])
    container.decode.return_value = [
        SimpleNamespace(
            pts=point,
            time_base=Fraction(1, 1000),
            to_ndarray=lambda **_: np.zeros((4, 4, 3), dtype=np.uint8),
        )
        for point in points
    ]
    monkeypatch.setattr("app.media.file_source.av.open", lambda *args, **kwargs: container)
    frames = list(FileSource(Path("fixture"), resume_after_ms=66533, next_sample_s=67).frames(2))
    assert [frame.timestamp_ms for frame in frames] == [67000, 67501, 68001]
    assert [frame.next_sample_s for frame in frames] == [67.5, 68, 68.5]
    container.seek.assert_called_once_with(66532, stream=stream, backward=True, any_frame=False)


def test_legacy_non_integer_grid_recovers_exact_previous_pts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = SimpleNamespace(time_base=Fraction(1, 30000), codec_context=SimpleNamespace())
    container = Mock()
    container.__enter__ = Mock(return_value=container)
    container.__exit__ = Mock(return_value=False)
    container.streams = SimpleNamespace(video=[stream])
    container.decode.return_value = [
        SimpleNamespace(
            pts=point,
            time_base=Fraction(1, 30000),
            to_ndarray=lambda **_: np.zeros((4, 4, 3), dtype=np.uint8),
        )
        for point in [0, 10000, 11000, 20000, 21000, 30000]
    ]
    monkeypatch.setattr("app.media.file_source.av.open", lambda *args, **kwargs: container)
    frames = list(FileSource(Path("fixture"), resume_after_ms=333, next_sample_s=1 / 3).frames(3))
    assert [frame.timestamp_ms for frame in frames] == [667, 1000]
    assert frames[0].next_sample_s == 1


def test_pause_midframe_restart_and_resume_keep_settings_events_and_tracks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"unchanged original")
    source_calls: list[dict[str, object]] = []
    entered, release = threading.Event(), threading.Event()

    class Source:
        def __init__(self, path: Path, start: float, **kwargs: object):
            self.after = int(kwargs["resume_after_ms"])
            source_calls.append(kwargs)

        def frames(self, fps: float, max_seconds: float | None = None) -> Iterator[Frame]:
            assert fps == 2 and max_seconds == 2
            for ms, next_sample in [(19, 0.5), (1033, 1.5), (1500, 2.0)]:
                if ms > self.after:
                    yield Frame(
                        ms,
                        np.random.default_rng(3).integers(0, 255, (100, 200, 3), dtype=np.uint8),
                        next_sample_s=next_sample,
                    )

    class Detector:
        def detect(self, rgb: object, threshold: float) -> list[Proposal]:
            assert threshold == 0.33
            return [Proposal((0, 0, 0.4, 1), 0.9), Proposal((0.6, 0, 1, 1), 0.8)]

    class Classifier:
        calls = 0

        def scores(self, crops: object) -> np.ndarray:
            self.calls += 1
            if self.calls == 3:
                entered.set()
                assert release.wait(4)
            return np.array([[0.4, 0.2, 0.1, 0.09, 0.08]], dtype=np.float32)

    monkeypatch.setattr("app.services.analyzer.FileSource", Source)
    worker = runner(tmp_path)
    classifier = Classifier()
    worker.registry.load = Mock(return_value=(Detector(), classifier))
    config = AnalysisSettings(
        sample_fps=2, detector_threshold=0.33, max_seconds=2, site_lat=26, site_lon=75
    )
    video = media().model_copy(update={"duration_ms": 2000})
    job = worker.start(path, video, config)
    assert entered.wait(3)
    assert worker.pause(job.job_id).status == "pausing"
    release.set()
    paused = finished(worker, job)
    assert paused.status == "paused" and paused.visual_count == 2
    assert paused.coverage_ms == 519
    previous = worker.events.read(video.source_id, job.job_id)
    assert {row.timestamp_ms for row in previous} == {19}
    checkpoint = worker.jobs.checkpoint(job.job_id)
    assert checkpoint and checkpoint.last_frame_ms == 19 and checkpoint.next_sample_s == 0.5
    assert "site_lat" not in paused.analysis_config
    assert checkpoint.config["site_lat"] == 26
    worker.events.review(previous[0].event_id, Review(status="correct", notes="Keep this"))
    # A fresh worker/store models an app restart; no volatile tracker state is reused.
    restored = runner(tmp_path)
    restored.registry.load = Mock(return_value=(Detector(), Classifier()))
    # Disable the test-only blocking point on the second worker.
    restored.registry.load.return_value[1].calls = 100
    described = restored.describe(restored.jobs.get(job.job_id), path, video)
    assert described.can_resume and described.resume_from_ms == 500
    result = finished(restored, restored.resume(job.job_id, path, video))
    assert result.status == "completed" and result.visual_count == 6
    assert result.metrics["sampled_frames"] == 3
    assert result.metrics["visual_detections"] == 6
    records = restored.events.read(video.source_id, job.job_id)
    assert [row.timestamp_ms for row in records] == [19, 19, 1033, 1033, 1500, 1500]
    assert records[0].event_id == previous[0].event_id and records[0].review.notes == "Keep this"
    assert {row.track_id for row in records[:2]}.isdisjoint({row.track_id for row in records[2:]})
    assert source_calls[-1] == {"resume_after_ms": 19, "next_sample_s": 0.5}
    loaded_config = restored.registry.load.call_args.args[0]
    assert loaded_config == config


def test_empty_frame_checkpoint_and_atomic_storage_failure(tmp_path: Path) -> None:
    worker = runner(tmp_path)
    job = Job(job_id="frame-test", source_id="a" * 24, created_at="2026-01-01")
    checkpoint = AnalysisCheckpoint(source_id=job.source_id, config=AnalysisSettings().model_dump())
    worker.jobs.save_checkpoint(job, checkpoint)
    calls = []
    source = Mock()
    source.frames.return_value = [
        Frame(500, np.zeros((20, 20, 3), dtype=np.uint8), next_sample_s=1)
    ]
    visual_pipeline(
        source,
        media(),
        job.job_id,
        AnalysisSettings(),
        taxa(),
        Mock(detect=Mock(return_value=[])),
        Mock(),
        {},
        Mock(),
        Mock(),
        threading.Event(),
        checkpoint=lambda *args: calls.append(args),
    )
    assert calls == [(500, 1, 1000)]
    checkpoint.last_frame_ms, checkpoint.next_sample_s = 500, 1
    worker.events.commit_analysis(job, checkpoint, [])
    assert worker.jobs.checkpoint(job.job_id).last_frame_ms == 500
    proposed = event().model_copy(update={"job_id": job.job_id, "timestamp_ms": 1000})
    with worker.events.database.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_checkpoint BEFORE INSERT ON analysis_checkpoints BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    checkpoint.last_frame_ms = 1000
    with pytest.raises(sqlite3.IntegrityError, match="fixture failure"):
        worker.events.commit_analysis(job, checkpoint, [proposed])
    assert worker.events.read(job.source_id, job.job_id) == []
    assert worker.jobs.checkpoint(job.job_id).last_frame_ms == 500


def test_legacy_partial_boundary_keeps_review_and_fills_missing_box(tmp_path: Path) -> None:
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"fixture")
    worker = runner(tmp_path)
    job = Job(
        job_id="run-1",
        source_id="a" * 24,
        created_at="2026-01-01",
        status="cancelled",
        coverage_ms=67033,
        analysis_config=AnalysisSettings().model_dump(),
    )
    worker.jobs.put(job)
    prior = event().model_copy(update={"timestamp_ms": 67000})
    worker.events.append(prior)
    worker.events.review(prior.event_id, Review(status="unknown", notes="Human retained"))
    video = media().model_copy(update={"duration_ms": 90000})
    checkpoint = worker._resume_state(job, path, video)
    assert checkpoint.last_frame_ms == 66533 and checkpoint.next_sample_s == 67
    replay = prior.model_copy(update={"event_id": "new-prediction", "track_id": "new-segment"})
    missing = replay.model_copy(update={"event_id": "missing", "bbox_norm": (0.7, 0.2, 0.9, 0.8)})
    worker.events.commit_analysis(job, checkpoint, [replay, missing], deduplicate_boundary=True)
    records = worker.events.read(job.source_id, job.job_id)
    assert len(records) == 2 and records[0].event_id == prior.event_id
    assert records[0].review.notes == "Human retained" and job.visual_count == 2


def test_audio_resume_skips_visual_and_deduplicates_legacy_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"fixture")
    worker = runner(tmp_path)
    video = media().model_copy(update={"audio": True})
    job = Job(
        job_id="audio-resume",
        source_id=video.source_id,
        created_at="2026-01-01",
        status="interrupted",
        coverage_ms=1000,
        audio_status="running",
        analysis_config=AnalysisSettings().model_dump(),
    )
    worker.jobs.put(job)
    audio = AudioEvent(
        job_id=job.job_id,
        source_id=job.source_id,
        source_filename=video.filename,
        start_ms=0,
        end_ms=1000,
        scientific_name="Bird 0",
        common_name="Bird",
        confidence=0.9,
        models={},
    )
    worker.events.append(audio)
    worker.events.review(audio.event_id, Review(status="correct"))
    replay = audio.model_copy(update={"event_id": "replayed-audio"})
    monkeypatch.setattr(
        "app.services.analyzer.BirdNET",
        Mock(return_value=Mock(analyze=Mock(return_value=([replay], {})))),
    )
    worker.registry.load = Mock(side_effect=AssertionError("Visual models must not reload"))
    assert worker.describe(job, path, video).resume_stage == "audio"
    result = finished(worker, worker.resume(job.job_id, path, video))
    assert result.status == "completed" and result.audio_count == 1
    assert worker.events.read(job.source_id, job.job_id)[0].event_id == audio.event_id
    assert worker.jobs.checkpoint(job.job_id).audio_complete


def test_resume_busy_changed_source_taxa_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"fixture")
    worker = runner(tmp_path)
    job = Job(job_id="resume-test", source_id="a" * 24, created_at="2026-01-01", status="running")
    checkpoint = AnalysisCheckpoint(
        source_id=job.source_id,
        config=AnalysisSettings().model_dump(),
        size_bytes=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns,
        taxa_version="test",
        last_frame_ms=19,
        next_sample_s=0.5,
    )
    worker.jobs.save_checkpoint(job, checkpoint)
    restored = JobStore(tmp_path / "jobs")
    job = restored.get(job.job_id)
    assert job.status == "paused" and restored.checkpoint(job.job_id).last_frame_ms == 19
    assert worker.describe(job, path, media()).can_resume
    worker.lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another analysis"):
            worker.resume(job.job_id, path, media())
    finally:
        worker.lock.release()
    worker.taxa.read.return_value = taxa().model_copy(update={"version": "changed"})
    assert "taxa cache changed" in worker.describe(job, path, media()).resume_reason
    worker.taxa.read.return_value = taxa()
    path.write_bytes(b"changed source")
    assert "file changed" in worker.describe(job, path, media()).resume_reason
    assert not worker.lock.locked()


def test_job_api_resume_metadata_active_route_and_busy_contract(tmp_path: Path) -> None:
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"fixture")
    worker = runner(tmp_path)
    job = Job(job_id="api-resume", source_id="a" * 24, created_at="2026-01-01", status="paused")
    config = AnalysisSettings(site_lat=26, site_lon=75)
    checkpoint = AnalysisCheckpoint(
        source_id=job.source_id, config=config.model_dump(), next_sample_s=67
    )
    worker.jobs.save_checkpoint(job, checkpoint)
    app = FastAPI()
    app.include_router(router)
    app.state.analyzer, app.state.jobs = worker, worker.jobs
    app.state.library = Mock(get=Mock(return_value=(path, media())))
    with TestClient(app) as client:
        assert client.get("/api/jobs/active").json() is None
        saved = client.get(f"/api/jobs/{job.job_id}").json()
        assert saved["can_resume"] and saved["resume_from_ms"] == 67000
        assert "site_lat" not in str(saved) and "site_lon" not in str(saved)
        assert client.post(f"/api/jobs/{job.job_id}/pause").json()["status"] == "paused"
        worker.lock.acquire()
        try:
            response = client.post(f"/api/jobs/{job.job_id}/resume")
            assert response.status_code == 409
        finally:
            worker.lock.release()
        assert client.post("/api/jobs/missing/resume").status_code == 404
        job.status = "pausing"
        worker.jobs.put(job)
        assert client.get("/api/jobs/active").json()["job_id"] == job.job_id


def test_failed_audio_remains_resumable_and_keeps_completed_visual_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"fixture")
    worker = runner(tmp_path)
    video = media().model_copy(update={"audio": True})
    worker.registry.load = Mock(return_value=(Mock(), Mock()))

    def visual(*args: object, **kwargs: object) -> dict[str, object]:
        # Complete one frame using the same transactional callback as inference.
        record = event().model_copy(update={"job_id": args[2], "timestamp_ms": 0})
        args[8](record)
        kwargs["checkpoint"](0, 0.5, 500)
        return {}

    pipeline = Mock(side_effect=visual)
    monkeypatch.setattr("app.services.analyzer.visual_pipeline", pipeline)
    audio = Mock(side_effect=RuntimeError("fixture audio failure"))
    monkeypatch.setattr(
        "app.services.analyzer.BirdNET", Mock(return_value=Mock(analyze=audio))
    )
    job = worker.start(path, video, AnalysisSettings())
    failed = finished(worker, job)
    assert failed.status == "failed" and failed.audio_status == "failed"
    checkpoint = worker.jobs.checkpoint(job.job_id)
    assert checkpoint and checkpoint.visual_complete and not checkpoint.audio_complete
    retained = worker.events.read(job.source_id, job.job_id)
    assert len(retained) == 1
    worker.events.review(retained[0].event_id, Review(status="correct", notes="Retain review"))
    described = worker.describe(failed, path, video)
    assert described.can_resume and described.resume_stage == "audio"
    audio.side_effect = None
    audio.return_value = ([], {})
    completed = finished(worker, worker.resume(job.job_id, path, video))
    assert completed.status == "completed" and completed.audio_status == "completed"
    assert pipeline.call_count == 1 and worker.registry.load.call_count == 1
    records = worker.events.read(job.source_id, job.job_id)
    assert len(records) == 1 and records[0].event_id == retained[0].event_id
    assert records[0].review.notes == "Retain review"
