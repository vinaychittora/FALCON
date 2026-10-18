import hashlib
import threading
import time
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import av
import numpy as np
import pytest

from app.media.base import Frame
from app.media.evidence_recorder import EvidenceRecorder
from app.media.rtsp_source import RTSPSource


def recording(
    path: Path, seconds: int = 12, fps: int | Fraction = 30, codec: str = "libx264",
) -> Path:
    with av.open(str(path), "w") as output:
        stream = output.add_stream(codec, rate=fps)
        stream.width, stream.height = 64, 48
        stream.pix_fmt = "yuv420p"
        stream.codec_context.gop_size = int(fps)
        stream.codec_context.max_b_frames = 2
        stream.options = {"preset": "ultrafast", "crf": "15"}
        if codec == "libx265":
            stream.options["x265-params"] = "log-level=error:pools=1:frame-threads=1"
        for index in range(int(seconds * fps)):
            pixels = np.zeros((48, 64, 3), dtype=np.uint8)
            pixels[:, :, 0] = (index * 3) % 220
            pixels[:, :, 1] = int(index // fps * 10) % 220
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = index, 1 / Fraction(fps)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    return path


class Results:
    def __init__(self) -> None:
        self.finished = threading.Event()
        self.values: dict[str, dict[str, Any]] = {}

    def __call__(self, identity: str, result: dict[str, Any]) -> None:
        self.values[identity] = result
        self.finished.set()


def feed(
    recorder: EvidenceRecorder, path: Path, *, trigger: float,
    request_at: float | None = None, evidence_id: str = "test-clip", stop_at: float | None = None,
    request_start_ms: int | None = None,
) -> tuple[str, str]:
    pin_id = ""
    with av.open(str(path)) as source:
        generation = recorder.start_generation(source.streams.video[0])
        for packet in source.demux(video=0):
            recorder.append_packet(packet)
            for decoded in packet.decode():
                timestamp = float(decoded.pts * decoded.time_base)
                if not pin_id and timestamp >= trigger:
                    frame = Frame(
                        round(timestamp * 1000) + 10000,
                        np.zeros((1, 1, 3), dtype=np.uint8),
                        recording_generation=generation, recording_timestamp_s=timestamp,
                    )
                    pin_id = recorder.pin(frame) or ""
                if pin_id and request_at is not None and timestamp >= request_at:
                    recorder.request(pin_id, evidence_id, start_ms=request_start_ms)
                    recorder.release(pin_id)
                    request_at = None
                if stop_at is not None and timestamp >= stop_at:
                    return pin_id, generation
    return pin_id, generation


def test_full_rate_five_seconds_survives_slow_classification(tmp_path: Path) -> None:
    source = recording(tmp_path / "source.mp4", seconds=28)
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    try:
        pin_id, _ = feed(recorder, source, trigger=4)
        # The selected interval left the 15-second ring long before the result.
        recorder.request(pin_id, "late-result")
        recorder.release(pin_id)
        assert results.finished.wait(10)
        result = results.values["late-result"]
        assert result["status"] == "ready"
        assert result["duration_ms"] == 5000
        assert (result["actual_start_ms"], result["actual_end_ms"]) == (12000, 17000)
        clip = tmp_path / "evidence" / result["relative_path"]
        assert result["sha256"] == hashlib.sha256(clip.read_bytes()).hexdigest()
        with av.open(str(clip)) as output:
            frames = list(output.decode(video=0))
            assert len(frames) == 150  # camera 30 FPS, not the five-FPS preview
            assert abs(float(output.duration / av.time_base) - 5) < 0.01
            assert not output.streams.audio
            assert float(frames[-1].pts * frames[-1].time_base) > 4.9
    finally:
        recorder.close()


def test_request_retains_postroll_after_context_release(tmp_path: Path) -> None:
    source = recording(tmp_path / "source.mp4")
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    try:
        feed(recorder, source, trigger=4, request_at=4)
        assert results.finished.wait(10)
        assert results.values["test-clip"]["status"] == "ready"
        assert results.values["test-clip"]["duration_ms"] == 5000
    finally:
        recorder.close()


@pytest.mark.parametrize("trigger,stop_at,expected", [(0.5, 6.0, 3500), (4.0, 5.0, None)])
def test_start_and_disconnect_have_real_partial_duration(
    tmp_path: Path, trigger: float, stop_at: float, expected: int | None,
) -> None:
    source = recording(tmp_path / "source.mp4")
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    pin_id, _ = feed(recorder, source, trigger=trigger, stop_at=stop_at)
    recorder.request(pin_id, "partial")
    recorder.end_generation()
    recorder.close()
    result = results.values["partial"]
    assert result["status"] == "partial"
    assert 0 < result["duration_ms"] < 5000
    if expected:
        assert result["duration_ms"] == expected
    with av.open(str(tmp_path / "evidence" / "partial.mp4")) as output:
        assert abs(output.duration / 1000 - result["duration_ms"]) < 2


def test_new_generation_cannot_supply_old_missing_postroll(tmp_path: Path) -> None:
    source = recording(tmp_path / "source.mp4")
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    pin_id, original = feed(recorder, source, trigger=4, stop_at=4.5)
    recorder.end_generation()
    _, new = feed(recorder, source, trigger=4)
    assert new != original
    recorder.request(pin_id, "old-generation")
    recorder.close()
    result = results.values["old-generation"]
    assert result["status"] == "partial"
    assert result["actual_end_ms"] < 15000


def test_storage_reserve_fails_without_deleting_previous_evidence(tmp_path: Path) -> None:
    source = recording(tmp_path / "source.mp4")
    root = tmp_path / "evidence"
    root.mkdir()
    existing = root / "previous.mp4"
    existing.write_bytes(b"preserved")
    results = Results()
    recorder = EvidenceRecorder(root, results, reserve_bytes=2**63)
    pin_id, _ = feed(recorder, source, trigger=4)
    recorder.request(pin_id, "no-space")
    recorder.close()
    assert results.values["no-space"]["status"] == "failed"
    assert existing.read_bytes() == b"preserved"
    assert sorted(p.name for p in root.iterdir()) == ["previous.mp4"]
    assert recorder.metrics()["evidence_recording_fault"]


def test_unrequested_release_frees_pin_and_memory_is_bounded(tmp_path: Path) -> None:
    source = recording(tmp_path / "source.mp4")
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0, max_bytes=2048)
    pin_id, _ = feed(recorder, source, trigger=4)
    assert recorder.metrics()["evidence_buffer_bytes"] <= 2048
    recorder.release(pin_id)
    assert recorder.metrics()["evidence_pending_clips"] == 0
    recorder.close()
    assert not results.values


def test_evidence_id_cannot_escape_storage(tmp_path: Path) -> None:
    recorder = EvidenceRecorder(tmp_path / "evidence", Results(), reserve_bytes=0)
    try:
        with pytest.raises(ValueError, match="evidence ID"):
            recorder.request("missing", "../../escape")
    finally:
        recorder.close()


@pytest.mark.parametrize("codec,fps", [
    ("libx265", 12),
    ("libx264", Fraction(30000, 1001)),
    ("libx265", Fraction(60000, 1001)),
])
def test_hevc_and_fractional_frame_rates_keep_real_timing(
    tmp_path: Path, codec: str, fps: int | Fraction,
) -> None:
    source = recording(tmp_path / "source.mp4", seconds=10, fps=fps, codec=codec)
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    pin_id, _ = feed(recorder, source, trigger=4)
    recorder.request(pin_id, "native-timing")
    recorder.close()
    result = results.values["native-timing"]
    assert result["status"] == "ready"
    assert result["duration_ms"] == 5000
    with av.open(str(tmp_path / "evidence" / "native-timing.mp4")) as output:
        frames = list(output.decode(video=0))
        assert abs(len(frames) - float(fps) * 5) <= 1
        stream = output.streams.video[0]
        assert stream.duration * stream.time_base == 5
        assert output.duration == 5 * av.time_base


def test_unsupported_camera_codec_is_explicit(tmp_path: Path) -> None:
    recorder = EvidenceRecorder(tmp_path / "evidence", Results())
    generation = recorder.start_generation(SimpleNamespace(
        codec_context=SimpleNamespace(name="mjpeg", extradata=None), average_rate=30,
    ))
    try:
        assert recorder.pin(Frame(
            4000, np.zeros((1, 1, 3), dtype=np.uint8),
            recording_generation=generation, recording_timestamp_s=4,
        )) is None
        assert recorder.metrics()["evidence_recorder_status"] == "unsupported codec"
    finally:
        recorder.close()


def test_source_timestamp_reset_recovers_without_network_reconnect(tmp_path: Path) -> None:
    source = recording(tmp_path / "source.mp4")
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    original_pin, original_generation = feed(recorder, source, trigger=4, stop_at=4.5)
    new_pin = ""
    with av.open(str(source)) as container:
        for packet in container.demux(video=0):
            recorder.append_packet(packet)
            for decoded in packet.decode():
                timestamp = float(decoded.pts * decoded.time_base)
                if timestamp >= 4 and not new_pin:
                    assert recorder.current_generation != original_generation
                    new_pin = recorder.pin(Frame(
                        14000, np.zeros((1, 1, 3), dtype=np.uint8),
                        recording_generation=recorder.current_generation,
                        recording_timestamp_s=timestamp,
                    )) or ""
    recorder.request(original_pin, "before-reset")
    recorder.request(new_pin, "after-reset")
    recorder.close()
    assert results.values["before-reset"]["status"] == "partial"
    assert results.values["after-reset"]["status"] == "ready"


def test_receive_clock_bounds_clip_to_nonnegative_session_time(tmp_path: Path) -> None:
    source = recording(tmp_path / "source.mp4")
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    pin_id = ""
    with av.open(str(source)) as container:
        generation = recorder.start_generation(container.streams.video[0])
        for packet in container.demux(video=0):
            recorder.append_packet(packet)
            for decoded in packet.decode():
                timestamp = float(decoded.pts * decoded.time_base)
                if timestamp >= 4 and not pin_id:
                    # Camera catch-up frames can arrive in a short receive burst.
                    pin_id = recorder.pin(Frame(
                        500, np.zeros((1, 1, 3), dtype=np.uint8),
                        recording_generation=generation, recording_timestamp_s=timestamp,
                    )) or ""
    recorder.request(pin_id, "receive-bound")
    recorder.close()
    result = results.values["receive-bound"]
    assert result["status"] == "partial"
    assert result["actual_start_ms"] == 0
    assert result["actual_end_ms"] == 3500
    assert result["duration_ms"] == 3500


@pytest.mark.parametrize("failed_hook", ["start", "packet", "end"])
def test_recorder_fault_does_not_interrupt_camera_preview(
    tmp_path: Path, failed_hook: str,
) -> None:
    source = recording(tmp_path / "source.mp4", seconds=1)
    cancel = threading.Event()
    frames: list[Frame] = []

    class FailingRecorder:
        current_generation = "test-generation"

        def start_generation(self, stream: Any) -> str:
            if failed_hook == "start":
                raise RuntimeError("native diagnostic must not leak")
            return self.current_generation

        def append_packet(self, packet: Any) -> None:
            if failed_hook == "packet":
                raise RuntimeError("native diagnostic must not leak")

        def end_generation(self) -> None:
            if failed_hook == "end":
                raise RuntimeError("native diagnostic must not leak")

    def preview(frame: Frame) -> None:
        frames.append(frame)
        cancel.set()

    capture = RTSPSource(
        "rtsp://camera.invalid/stream", cancel, time.monotonic(), preview,
        lambda chunk: None, lambda status, error: None, lambda status: None,
        audio_enabled=False, open_container=lambda *args, **kwargs: av.open(str(source)),
        recorder=FailingRecorder(),  # type: ignore[arg-type]
    )
    capture.run()
    assert frames
    assert capture.reconnects == 0
    assert "native diagnostic" not in repr(capture.technical_metrics())
    assert "evidence_capture_fault" in capture.technical_metrics()


def test_continuation_clip_starts_at_requested_time_and_is_complete(tmp_path: Path) -> None:
    results = Results()
    recorder = EvidenceRecorder(tmp_path / "evidence", results, reserve_bytes=0)
    # The trigger frame is session time 15000 ms; the previous clip ended at 14000.
    feed(
        recorder, recording(tmp_path / "source.mp4"), trigger=5.0, request_at=5.0,
        evidence_id="continuation", request_start_ms=14000,
    )
    assert results.finished.wait(10)
    recorder.close()
    result = results.values["continuation"]
    assert result["status"] == "ready"
    assert result["duration_ms"] == 4000
    assert (result["actual_start_ms"], result["actual_end_ms"]) == (14000, 18000)
