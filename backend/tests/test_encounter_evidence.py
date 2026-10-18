"""Encounter integration uses synthetic pixels/PCM and a real temporary database."""

import hashlib
import threading
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from app.inference.base import Proposal
from app.inference.pipeline import Cancelled, visual_pipeline
from app.media.base import Frame
from app.media.rtsp_source import AudioChunk
from app.schemas import (
    AnalysisSettings,
    AudioEvent,
    Classification,
    DetectorResult,
    EnvironmentReading,
    Video,
    VisualEvent,
)
from app.services import encounter_evidence as module
from app.services.encounter_evidence import EncounterEvidence
from app.storage.database import Database
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import EventStore
from app.taxonomy.inaturalist import TaxaCache, Taxon

SOURCE = "a" * 24
SESSION = "fixture-live-session"
START = datetime(2026, 1, 1, tzinfo=UTC)


class Recorder:
    def __init__(self, root, complete, **kwargs):
        self.complete = complete
        self.actions = []
        self.pins = set()
        self.requests = []
        self.starts = []
        self.pin_error = self.release_error = self.request_error = False

    def pin(self, frame):
        if self.pin_error:
            raise OSError("fixture storage unavailable")
        token = f"pin-{len(self.actions)}"
        self.actions.append(("pin", token))
        self.pins.add(token)
        return token

    def request(self, token, evidence_id, *, start_ms=None):
        if self.request_error:
            raise OSError("fixture queue unavailable")
        assert token in self.pins
        self.requests.append((token, evidence_id))
        self.starts.append(start_ms)

    def release(self, token):
        self.actions.append(("release", token))
        self.pins.discard(token)
        if self.release_error:
            raise OSError("fixture cleanup unavailable")

    def metrics(self):
        return {}

    def close(self):
        self.actions.append(("close", None))


@pytest.fixture
def capture(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(module, "EvidenceRecorder", Recorder)
    database = Database(tmp_path / "records.sqlite3")
    store = EvidenceStore(database, tmp_path / "evidence")
    events = EventStore(tmp_path / "events", database)
    store.register_session(SESSION, SOURCE, "Synthetic capture", START, AnalysisSettings())
    encounter = EncounterEvidence(store, SESSION, SOURCE, START.isoformat(), reserve_bytes=0)
    yield SimpleNamespace(store=store, events=events, encounter=encounter, recorder=encounter.recorder)
    encounter.close()


def frame(timestamp=4000, generation="generation-a"):
    return Frame(
        timestamp, np.random.default_rng(7).integers(0, 255, (64, 64, 3), dtype=np.uint8),
        captured_at=START + timedelta(milliseconds=timestamp),
        recording_generation=generation, recording_timestamp_s=timestamp / 1000,
    )


def visual(timestamp=4000, status="unknown"):
    return VisualEvent(
        source_id=SOURCE, job_id=SESSION, source_filename="Synthetic capture",
        timestamp_ms=timestamp, duration_ms=500, track_id="fixture-track",
        bbox_norm=(0, 0, 1, 1), detector=DetectorResult(label="animal", score=0.8, model="fixture"),
        classification=Classification(status=status), models={"source_clock": "session receive time"},
    )


def audio(start=13000):
    return AudioEvent(
        source_id=SOURCE, job_id=SESSION, source_filename="Synthetic capture",
        start_ms=start, end_ms=start + 3000, scientific_name="Pitta brachyura",
        common_name="Indian Pitta", confidence=0.8, models={"source_clock": "session receive time"},
    )


def pipeline(capture, *, detector=None, classifier=None, cancel=None):
    current = frame()
    source = SimpleNamespace(frames=lambda *_: iter([current]))
    detector = detector or Mock(detect=Mock(return_value=[Proposal((0, 0, 1, 1), 0.8)]))
    classifier = classifier or Mock(scores=Mock(return_value=np.array([[0.8, 0.1]])))
    config = AnalysisSettings(sample_fps=2, min_crop_side=16, min_sharpness=0)
    taxa = TaxaCache(taxa=[
        Taxon(taxon_id=1, scientific_name="Pitta brachyura", group="Aves", iconic_group="Aves", observation_count=1),
        Taxon(taxon_id=2, scientific_name="Copsychus saularis", group="Aves", iconic_group="Aves", observation_count=1),
    ])
    video = Video(source_id=SOURCE, filename="Synthetic capture", duration_ms=10000,
                  width=64, height=64, fps=30, codec="fixture", audio=False, size_bytes=0)
    sensors = Mock(snapshot=Mock(return_value=EnvironmentReading()))

    def emit(event):
        capture.events.append(event)
        capture.encounter.visual(event)

    result = visual_pipeline(
        source, video, SESSION, config, taxa, detector, classifier, {}, emit, lambda _: None,
        cancel or threading.Event(), sensors, frame_context=capture.encounter.frame_context,
    )
    return result, sensors


def test_pipeline_pins_before_detector_and_classifier_and_releases_after_persistence(capture):
    def detect(*_):
        assert capture.recorder.pins
        return [Proposal((0, 0, 1, 1), 0.8)]

    def scores(*_):
        assert capture.recorder.pins
        return np.array([[0.8, 0.1]])

    result, sensors = pipeline(capture, detector=Mock(detect=detect), classifier=Mock(scores=scores))
    assert result["visual_detections"] == 1
    assert not capture.recorder.pins
    assert [action[0] for action in capture.recorder.actions] == ["pin", "release"]
    record = capture.store.list()[0]
    event = capture.events.read(SOURCE)[0]
    assert record.event_ids == [event.event_id]
    assert record.clock_basis == "server_receive_time"
    assert event.environment.status == "not_connected"
    sensors.snapshot.assert_called_once_with(START + timedelta(seconds=4))


@pytest.mark.parametrize("failure", ["cancel", "classifier"])
def test_pipeline_releases_pin_when_cancelled_or_classification_fails(capture, failure):
    cancel = threading.Event()

    def detect(*_):
        assert capture.recorder.pins
        if failure == "cancel":
            cancel.set()
        return [Proposal((0, 0, 1, 1), 0.8)]

    with pytest.raises(Cancelled if failure == "cancel" else RuntimeError):
        pipeline(capture, detector=Mock(detect=detect), cancel=cancel,
                 classifier=Mock(scores=Mock(side_effect=RuntimeError("fixture classifier failure"))))
    assert not capture.recorder.pins
    assert [action[0] for action in capture.recorder.actions] == ["pin", "release"]
    assert not capture.events.read(SOURCE)


@pytest.mark.parametrize("operation", ["pin", "release"])
def test_recorder_context_failure_does_not_abort_observations(capture, operation):
    setattr(capture.recorder, f"{operation}_error", True)
    result, _ = pipeline(capture)
    assert result["visual_detections"] == 1
    assert len(capture.events.read(SOURCE)) == 1
    assert capture.encounter.metrics()["evidence_error"]
    if operation == "pin":
        assert capture.store.list()[0].status == "failed"


def test_visual_group_reuses_window_but_never_crosses_stream_generation(capture):
    ids = []
    for timestamp, generation in [(4000, "a"), (4500, "a"), (4500, "b"), (7000, "a")]:
        event = visual(timestamp)
        ids.append(event.event_id)
        capture.events.append(event)
        with capture.encounter.frame_context(frame(timestamp, generation)):
            capture.encounter.visual(event)
    assert len(capture.store.list()) == 3
    first = capture.store.list(event_id=ids[0])[0]
    assert first.event_ids == sorted(ids[:2])
    assert (first.requested_start_ms, first.requested_end_ms) == (2000, 7000)
    assert len(capture.recorder.requests) == 3
    assert capture.store.list(event_id=ids[2])[0].evidence_id != first.evidence_id


def test_visual_group_cache_is_bounded_and_non_wildlife_has_no_recording(capture):
    event = visual(status="non_wildlife")
    capture.events.append(event)
    with capture.encounter.frame_context(frame()):
        capture.encounter.visual(event)
    assert not capture.store.list()
    for index in range(40):
        event = visual(index * 6000 + 4000)
        capture.events.append(event)
        with capture.encounter.frame_context(frame(event.timestamp_ms)):
            capture.encounter.visual(event)
    assert len(capture.encounter._windows) <= 16
    assert len(capture.store.list()) == 40
    assert not capture.recorder.pins


@pytest.mark.parametrize("prior_status", ["failed", "partial"])
def test_later_visual_retries_when_previous_clip_does_not_cover_it(capture, monkeypatch, prior_status):
    first = visual(4000)
    capture.events.append(first)
    with capture.encounter.frame_context(frame(4000)):
        capture.encounter.visual(first)
    prior = capture.store.list(event_id=first.event_id)[0]
    original_get = capture.store.get
    def saved_record(identity):
        record = original_get(identity)
        if identity == prior.evidence_id:
            return record.model_copy(update={
                "status": prior_status, "actual_start_ms": 2000, "actual_end_ms": 4200,
            })
        return record
    monkeypatch.setattr(capture.store, "get", saved_record)
    later = visual(4500)
    capture.events.append(later)
    with capture.encounter.frame_context(frame(4500)):
        capture.encounter.visual(later)
    assert capture.store.list(event_id=later.event_id)[0].evidence_id != prior.evidence_id
    assert len(capture.recorder.requests) == 2


def test_recorder_request_failure_is_explicit_and_observation_survives(capture):
    capture.recorder.request_error = True
    event = visual()
    capture.events.append(event)
    with capture.encounter.frame_context(frame()):
        capture.encounter.visual(event)
    record = capture.store.list(event_id=event.event_id)[0]
    assert record.status == "failed"
    assert capture.events.read(SOURCE)[0].event_id == event.event_id
    assert capture.encounter.metrics()["evidence_error"]


def test_new_record_failure_does_not_fail_an_unrelated_pending_clip(capture, monkeypatch):
    first = visual()
    capture.events.append(first)
    with capture.encounter.frame_context(frame()):
        capture.encounter.visual(first)
    previous = capture.store.list(event_id=first.event_id)[0]
    assert previous.status == "pending"
    monkeypatch.setattr(capture.encounter, "_create", Mock(side_effect=OSError("fixture database unavailable")))
    later = visual(15000)
    capture.events.append(later)
    with capture.encounter.frame_context(frame(15000)):
        capture.encounter.visual(later)
    assert capture.store.get(previous.evidence_id).status == "pending"
    assert len(capture.events.read(SOURCE)) == 2
    assert not capture.store.list(event_id=later.event_id)
    assert capture.encounter.metrics()["evidence_error"]


def test_audio_clip_has_real_five_second_pcm_hash_and_session_offsets(capture):
    rate = 8000
    samples = np.arange(9 * rate, dtype=np.int16)
    chunk = AudioChunk(10000, samples.astype("<i2").tobytes(), sample_rate=rate)
    first, second = audio(13000), audio(13000)
    for event in (first, second):
        capture.events.append(event)
    capture.encounter.audio(chunk, [first, second])
    records = capture.store.list()
    assert len(records) == 1
    record = records[0]
    assert record.status == "ready" and record.duration_ms == 5000
    assert (record.actual_start_ms, record.actual_end_ms) == (11000, 16000)
    assert record.captured_at == (START + timedelta(seconds=11)).isoformat()
    assert record.event_ids == sorted([first.event_id, second.event_id])
    path = capture.store.safe_path(record.relative_path)
    with wave.open(str(path), "rb") as saved:
        assert (saved.getframerate(), saved.getnchannels(), saved.getsampwidth(), saved.getnframes()) == (rate, 1, 2, 5 * rate)
        assert saved.readframes(saved.getnframes()) == chunk.pcm[rate * 2:6 * rate * 2]
    assert record.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record.size_bytes == path.stat().st_size
    assert record.clock_basis == "server_receive_time" and record.audio_present
    assert capture.encounter.metrics()["audio_clips_saved"] == 1


def test_short_audio_window_is_partial_without_padding(capture):
    chunk = AudioChunk(10000, b"\x10\x00" * 24000, sample_rate=8000)
    event = audio(10000)
    capture.events.append(event)
    capture.encounter.audio(chunk, [event])
    record = capture.store.list()[0]
    assert record.status == "partial" and record.duration_ms == 3000
    assert (record.actual_start_ms, record.actual_end_ms) == (10000, 13000)
    with wave.open(str(capture.store.safe_path(record.relative_path)), "rb") as saved:
        assert saved.readframes(saved.getnframes()) == chunk.pcm


def test_disk_full_keeps_audio_observation_and_marks_evidence_failed(capture, monkeypatch):
    chunk = AudioChunk(10000, b"\x10\x00" * 72000, sample_rate=8000)
    event = audio()
    capture.events.append(event)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    capture.encounter.audio(chunk, [event])
    record = capture.store.list(event_id=event.event_id)[0]
    assert record.status == "failed" and record.relative_path is None
    assert capture.events.read(SOURCE)[0].event_id == event.event_id
    assert capture.encounter.metrics()["evidence_error"]
    assert not list(capture.store.root.glob("*.wav"))


def test_lingering_animal_gets_contiguous_not_overlapping_clips(capture):
    # One animal visible for 12 s at 2 fps.
    for timestamp in range(4000, 16000, 500):
        event = visual(timestamp)
        capture.events.append(event)
        with capture.encounter.frame_context(frame(timestamp)):
            capture.encounter.visual(event)
    windows = sorted(
        (record.requested_start_ms, record.requested_end_ms) for record in capture.store.list()
    )
    assert windows == [(2000, 7000), (7000, 10000), (10000, 13000), (13000, 16000)]
    assert capture.recorder.starts == [start for start, _ in windows]
