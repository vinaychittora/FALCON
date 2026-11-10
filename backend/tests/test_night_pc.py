from fractions import Fraction
from types import SimpleNamespace

import numpy as np

from app.media.evidence_recorder import INTRA_ONLY, EvidenceRecorder
from app.media.night import NightPicture, colour_cast, greyscale

MAGENTA = np.zeros((96, 128, 3), dtype=np.uint8) + np.array([141, 102, 142], dtype=np.uint8)  # dusk, IR on
GARDEN = np.zeros((96, 128, 3), dtype=np.uint8) + np.array([90, 120, 80], dtype=np.uint8)


def test_cast_matches_the_node_measurement():
    assert round(colour_cast(MAGENTA), 1) == 39.5
    assert colour_cast(GARDEN) < 6


def test_auto_turns_grey_after_three_agreeing_readings_and_back():
    now = [0.0]
    night = NightPicture(lambda: "auto", clock=lambda: now[0])
    results = []
    for _ in range(4):
        picture, grey = night.apply(MAGENTA)
        results.append(grey)
        now[0] += 10
    assert results == [False, False, True, True]
    assert (picture[..., 0] == picture[..., 1]).all()
    for _ in range(3):
        night.apply(GARDEN)
        now[0] += 10
    assert night.apply(GARDEN)[1] is False  # daylight again after three agreeing readings


def test_colour_mode_and_node_applied_mode_leave_frames_alone():
    assert NightPicture(lambda: "colour").apply(MAGENTA)[1] is False
    assert NightPicture(lambda: None).apply(MAGENTA)[1] is False
    assert NightPicture(lambda: "mono").apply(GARDEN)[1] is True


def test_greyscale_keeps_brightness():
    grey = greyscale(GARDEN)
    assert grey.shape == GARDEN.shape and abs(int(grey[0, 0, 0]) - 107) <= 1


def test_recorder_accepts_mjpeg_and_treats_every_frame_as_a_keyframe(tmp_path):
    recorder = EvidenceRecorder(tmp_path, lambda *_: None, reserve_bytes=0)
    stream = SimpleNamespace(codec_context=SimpleNamespace(name="mjpeg", extradata=None), average_rate=None)
    recorder.start_generation(stream)
    assert recorder.metrics()["evidence_recorder_status"] == "buffering"
    packet = SimpleNamespace(size=10, time_base=Fraction(1, 90000), pts=9000, dts=9000, duration=9000, is_keyframe=False)
    packet.__bytes__ = lambda: b"0123456789"
    recorder.append_packet(_Packet(packet))
    assert recorder._ring[-1].keyframe  # noqa: SLF001
    assert "mjpeg" in INTRA_ONLY
    recorder.close()


def test_mjpeg_stream_gives_a_ten_second_greyscale_h264_clip(tmp_path):
    """Pass-through end to end: 10 fps MJPEG in, 5 s before + 5 s after, night picture grey."""
    import threading

    import av

    from app.media.base import Frame

    source = tmp_path / "camera.mkv"
    with av.open(str(source), "w") as output:
        stream = output.add_stream("mjpeg", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuvj420p"
        for index in range(250):  # 25 s of a magenta-ish picture
            pixels = np.zeros((48, 64, 3), dtype=np.uint8) + np.array([140, 100, 140], dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, 10)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    done, results = threading.Event(), {}

    def complete(identity, result):
        results[identity] = result
        done.set()

    recorder = EvidenceRecorder(tmp_path / "evidence", complete, reserve_bytes=0, pre_seconds=5, post_seconds=5)
    try:
        with av.open(str(source)) as camera:
            generation = recorder.start_generation(camera.streams.video[0])
            pin = ""
            for packet in camera.demux(video=0):
                recorder.append_packet(packet)
                for decoded in packet.decode():
                    timestamp = float(decoded.pts * decoded.time_base)
                    if not pin and timestamp >= 10:
                        pin = recorder.pin(Frame(
                            20000, np.zeros((1, 1, 3), dtype=np.uint8), recording_generation=generation,
                            recording_timestamp_s=timestamp, greyscale=True,
                        )) or ""
                        recorder.request(pin, "mjpeg-clip")
                        recorder.release(pin)
        assert done.wait(15)
        result = results["mjpeg-clip"]
        assert result["status"] == "ready" and result["duration_ms"] == 10000
        with av.open(str(tmp_path / "evidence" / result["relative_path"])) as clip:
            assert clip.streams.video[0].codec_context.name == "h264"  # plays in the browser
            frame = next(clip.decode(video=0)).to_ndarray(format="rgb24")
        assert abs(int(frame[10, 10, 0]) - int(frame[10, 10, 1])) <= 3  # greyscale, not magenta
    finally:
        recorder.close()


class _Packet:
    def __init__(self, fields):
        self.__dict__.update({k: v for k, v in vars(fields).items() if k != "__bytes__"})

    def __bytes__(self):
        return b"0123456789"
