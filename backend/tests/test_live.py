import importlib
import threading
import time
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.inference.base import Proposal
from app.main import create_app
from app.media.base import Frame
from app.media.rtsp_source import AudioChunk, RTSPSource
from app.schemas import AnalysisSettings, Classification, DetectorResult, Review, VisualEvent
from app.schemas_live import LiveStart
from app.services.live import LiveService
from tests.test_worker import media, runner


def source(cancel: threading.Event, **kwargs: object) -> RTSPSource:
    return RTSPSource(
        "rtsp://private-user:private-secret@camera.invalid/stream1",
        cancel,
        time.monotonic(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        **kwargs,
    )


def test_live_request_credentials_are_encoded_and_never_echoed(tmp_path: Path) -> None:
    request = LiveStart(
        url="rtsp://camera.test:554/stream1", username="local user", password="p@ss:word"
    )
    assert "local%20user:p%40ss%3Aword@camera.test" in request.connection_url()
    assert "p@ss:word" not in repr(request)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        invalid = client.post(
            "/api/live/start",
            json={
                "url": "rtsp://local-user:private-secret@camera.test/stream1",
                "password": "second-secret",
            },
        )
        assert invalid.status_code == 422
        assert "private-secret" not in invalid.text
        assert "local-user" not in invalid.text
        assert "second-secret" not in invalid.text
        assert "separate" in invalid.text
        assert (
            client.post("/api/live/start", json={"url": "file:///private-secret"}).status_code
            == 422
        )
        assert client.get("/api/live/state").json()["status"] == "idle"
        assert client.get("/api/live/preview.jpg").status_code == 503


def test_latest_frame_mailbox_drops_backlog_and_cancel_unblocks() -> None:
    cancel = threading.Event()
    capture = source(cancel)
    stream = capture.frames(5)
    for sequence in range(1, 21):
        capture.latest = Frame(sequence * 100, np.zeros((8, 12, 3), dtype=np.uint8))
        capture.sequence = sequence
    assert next(stream).timestamp_ms == 2000
    cancel.set()
    assert list(stream) == []


def test_audio_capture_continues_while_video_preview_is_blocked() -> None:
    cancel = threading.Event()
    preview_started, audio_received = threading.Event(), threading.Event()
    requested: list[str] = []

    class Packet:
        def __init__(self, frame: av.VideoFrame | av.AudioFrame):
            self.frame = frame

        def decode(self) -> list[av.VideoFrame | av.AudioFrame]:
            return [self.frame]

    class Container:
        def __init__(self, media: str):
            self.media = media
            self.streams = SimpleNamespace(
                video=[SimpleNamespace()],
                audio=[SimpleNamespace(codec_context=SimpleNamespace(name="pcm_s16le"))],
            )

        def __enter__(self) -> "Container":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def demux(self, stream: object):  # type: ignore[no-untyped-def]
            if self.media == "video":
                yield Packet(
                    av.VideoFrame.from_ndarray(np.zeros((8, 8, 3), dtype=np.uint8), format="rgb24")
                )
            else:
                assert preview_started.wait(2)
                for index in range(430):
                    frame = av.AudioFrame.from_ndarray(
                        np.zeros((1, 1024), dtype=np.int16), format="s16", layout="mono"
                    )
                    frame.sample_rate = 48000
                    frame.time_base = Fraction(1, 48000)
                    frame.pts = index * 1024
                    yield Packet(frame)
                    if cancel.is_set():
                        return

    def opened(*args: object, **kwargs: object) -> Container:
        media = kwargs["options"]["allowed_media_types"]  # type: ignore[index]
        requested.append(media)
        return Container(media)

    capture = source(cancel, open_container=opened)

    def preview(frame: Frame) -> None:
        preview_started.set()
        assert audio_received.wait(2), "Audio was blocked behind video preview"
        cancel.set()

    capture.preview = preview
    capture.audio = lambda chunk: audio_received.set()
    worker = threading.Thread(target=capture.run)
    worker.start()
    worker.join(4)
    cancel.set()
    assert not worker.is_alive()
    assert audio_received.is_set()
    assert set(requested) == {"video", "audio"}


def test_audio_fallback_decodes_g711_rate_without_echoing_native_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel = threading.Event()
    requested: list[str] = []
    messages: list[str] = []
    chunks: list[AudioChunk] = []
    monkeypatch.setattr(cancel, "wait", lambda timeout: cancel.is_set())

    class Packet:
        def __init__(self, index: int):
            self.index = index

        def decode(self) -> list[av.AudioFrame]:
            frame = av.AudioFrame.from_ndarray(
                np.zeros((1, 160), dtype=np.int16), format="s16", layout="mono"
            )
            frame.sample_rate = 8000
            frame.time_base = Fraction(1, 8000)
            # Derived presentation timestamps can jump despite uninterrupted
            # decoded samples. Real resampling must still complete a window.
            frame.pts = self.index * 160 + (8000 if (self.index // 5) % 2 else 0)
            return [frame]

    def demux(media: str):  # type: ignore[no-untyped-def]
        if media == "audio":
            raise TimeoutError(110, "rtsp://private-user:private-secret@camera.test")
        yield from (Packet(index) for index in range(500))

    @contextmanager
    def opened(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        media = kwargs["options"]["allowed_media_types"]  # type: ignore[index]
        requested.append(media)
        yield SimpleNamespace(
            streams=SimpleNamespace(
                audio=[SimpleNamespace(codec_context=SimpleNamespace(name="pcm_alaw"))]
            ),
            demux=lambda stream: demux(media),
        )

    capture = source(cancel, open_container=opened)
    capture.audio_status = messages.append

    def received(chunk: AudioChunk) -> None:
        chunks.append(chunk)
        cancel.set()

    capture.audio = received
    capture._audio_loop()
    assert requested == ["audio", "video+audio"]
    assert capture.audio_transport_mode == "combined tracks; audio decoding only"
    assert capture.audio_codec == "pcm_alaw"
    assert len(chunks) == 1 and chunks[0].duration_ms == 9000
    assert len(chunks[0].pcm) == 864000
    assert capture.audio_clock.pts_jumps > 0
    assert capture.audio_discontinuities == 0
    assert "PTS jumps observed" in chunks[0].timing_note
    assert "private-secret" not in repr(messages)
    assert "private-user" not in repr(messages)
    collecting = next(index for index, message in enumerate(messages) if "listening:" in message)
    assert any("compatible track setup" in message for message in messages[:collecting])
    assert capture.audio_error == ""


def test_audio_fallback_is_bounded_and_reports_safe_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel = threading.Event()
    requested: list[str] = []
    monkeypatch.setattr(cancel, "wait", lambda timeout: cancel.is_set())

    def failed_demux(stream: object) -> None:
        raise TimeoutError(110, "camera-password-in-native-message")

    @contextmanager
    def opened(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        media = kwargs["options"]["allowed_media_types"]  # type: ignore[index]
        requested.append(media)
        if len(requested) >= 3:
            cancel.set()
        yield SimpleNamespace(
            streams=SimpleNamespace(
                audio=[SimpleNamespace(codec_context=SimpleNamespace(name="pcm_alaw"))]
            ),
            demux=failed_demux,
        )

    capture = source(cancel, open_container=opened)
    capture._audio_loop()
    assert requested == ["audio", "video+audio", "video+audio"]
    assert capture.audio_error == "TimeoutError (code 110)"
    assert capture.audio_stage == "waiting for audio packets"
    assert "camera-password" not in repr(capture.audio_status.call_args_list)


def test_capture_connection_failure_redacts_credentials(capfd: pytest.CaptureFixture[str]) -> None:
    cancel = threading.Event()
    av.logging.restore_default_callback()  # Same global state left by FileSource.

    def failed_open(*args: object, **kwargs: object) -> None:
        av.logging.log(av.logging.ERROR, "rtsp", "private-user:private-secret")
        raise RuntimeError("rtsp://private-user:private-secret@camera.invalid/stream1")

    capture = source(cancel, open_container=failed_open)
    observed: list[tuple[str, str | None]] = []

    def status(value: str, message: str | None) -> None:
        observed.append((value, message))
        if value == "reconnecting":
            cancel.set()

    capture.status = status
    capture.run()
    assert capture.reconnects == 1
    assert capture._url == ""
    assert "private-secret" not in repr(observed)
    assert "private-user" not in repr(observed)
    output = capfd.readouterr()
    assert "private-secret" not in output.out + output.err


def test_live_cancel_keeps_heavy_job_lease_until_model_load_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The lease assertion measures worker coordination, not a cold dependency
    # import. LiveService imports this before starting capture/model loading.
    importlib.import_module("torchvision.io")
    worker, competitor = runner(tmp_path), runner(tmp_path)
    live = LiveService(worker)
    entered, release = threading.Event(), threading.Event()

    def capture(self: RTSPSource) -> None:
        with self.condition:
            self.latest = Frame(0, np.zeros((8, 8, 3), dtype=np.uint8))
            self.sequence += 1
            self.condition.notify_all()
        self.cancel.wait(5)

    def loading(*args: object) -> tuple[Mock, Mock]:
        entered.set()
        assert release.wait(4)
        return Mock(), Mock()

    monkeypatch.setattr(RTSPSource, "run", capture)
    worker.registry.load = Mock(side_effect=loading)
    result = live.start(
        LiveStart(url="rtsp://camera.test/stream1", config=AnalysisSettings(audio_enabled=False))
    )
    assert result.status == "connecting" and entered.wait(2)
    assert live.stop().status == "stopping"
    assert worker.lock.locked()
    with pytest.raises(RuntimeError, match="Another analysis"):
        live.start(LiveStart(url="rtsp://camera.test/stream1"))
    with pytest.raises(RuntimeError, match="Another app"):
        competitor.start(tmp_path / "fixture.mp4", media(), AnalysisSettings())
    release.set()
    assert live.stop(wait=True).status == "stopped"
    assert not worker.lock.locked()
    assert "camera.test" not in live.state().model_dump_json()


def test_live_stale_boxes_preview_and_audio_queue_are_bounded(tmp_path: Path) -> None:
    live = LiveService(runner(tmp_path))
    live._started = time.monotonic() - 10
    live._state.status = "live"
    live._state.preview_timestamp_ms = 10000
    live._state.visual = [
        VisualEvent(
            job_id="session",
            source_id="live-session",
            source_filename="Camera",
            timestamp_ms=1000,
            duration_ms=500,
            track_id="track",
            bbox_norm=(0, 0, 1, 1),
            detector=DetectorResult(label="animal", score=0.9, model="test"),
            classification=Classification(),
            models={},
        )
    ]
    live._preview = b"jpeg"
    live._last_frame_at = time.monotonic() - 10
    assert live.state().visual == []
    assert live.jpeg() is None
    live._state.metrics["dropped_audio_chunks"] = 0
    for timestamp in range(20):
        live._chunk(AudioChunk(timestamp, b"\0" * 960))
    assert live._audio_queue.qsize() == 1
    assert live._audio_queue.get_nowait().start_ms == 19
    assert live.state().metrics["dropped_audio_chunks"] == 19


def test_live_audio_temporary_windows_cleaned_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = runner(tmp_path)
    (tmp_path / "temp").mkdir()
    live = LiveService(worker)
    live._state.metrics.update({"audio_chunks_analyzed": 0, "audio_detections": 0})
    live._chunk(AudioChunk(1000, b"\0" * 960))

    def fail(*args: object, **kwargs: object) -> None:
        live._cancel.set()
        raise RuntimeError("synthetic audio failure")

    monkeypatch.setattr("app.services.live.BirdNET.analyze", fail)
    live._listen(AnalysisSettings(), worker.taxa.read(), "session", "source", "Camera")
    assert list((tmp_path / "temp").iterdir()) == []
    assert "failed" in live.state().audio_status


def test_live_first_positive_frame_persists_with_valid_source_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = runner(tmp_path)
    live = LiveService(worker)
    detected = threading.Event()
    detector = Mock()
    detector.detect.return_value = [Proposal((0.1, 0.1, 0.9, 0.9), 0.9)]
    classifier = Mock()
    classifier.scores.return_value = np.array([[0.8, 0.2, 0.1, 0.05, 0.01]], dtype=np.float32)
    worker.registry.load = Mock(return_value=(detector, classifier))
    worker.registry.device = "cpu"
    real_append = worker.events.append

    def recorded(event: VisualEvent) -> None:
        real_append(event)
        detected.set()

    worker.events.append = Mock(side_effect=recorded)

    def capture(self: RTSPSource) -> None:
        frame = Frame(10, np.random.default_rng(9).integers(0, 255, (120, 160, 3), dtype=np.uint8))
        with self.condition:
            self.latest = frame
            self.sequence += 1
            self.condition.notify_all()
        self.preview(frame)
        self.status("live", None)
        self.cancel.wait(5)

    monkeypatch.setattr(RTSPSource, "run", capture)
    started = live.start(
        LiveStart(url="rtsp://camera.test/stream1", config=AnalysisSettings(audio_enabled=False))
    )
    assert detected.wait(3), live.state().model_dump()
    assert started.session_id
    source_id = started.session_id.replace("-", "")[:24]
    events = worker.events.read(source_id)
    assert len(events) == 1 and events[0].detector.score == 0.9
    assert events[0].source_filename == "Backyard camera"
    assert events[0].environment.status == "not_connected"
    assert "camera.test" not in events[0].model_dump_json()
    live.update_review(events[0].event_id, Review(status="false_positive", notes="Fixture"))
    assert live._state.visual[0].review.status == "false_positive"
    assert live.stop(wait=True).status == "stopped"
