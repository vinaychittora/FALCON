# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from pathlib import Path

import pytest

from falcon_node import media
from falcon_node.agent import Agent
from tests import test_media_and_api

node = test_media_and_api.node  # the running-node pytest fixture
WEBCAM = media.Camera("v4l2", "/dev/video0", "USB Camera", "mjpeg", ("1280x720",))
PUBLISH = "rtsp://127.0.0.1:8554/falcon"


def ppm(red: int, green: int, blue: int) -> bytes:
    return b"P6\n32 18\n255\n" + bytes([red, green, blue]) * (32 * 18)


def test_colour_cast_tells_the_magenta_ir_picture_from_daylight() -> None:
    assert media.colour_cast(ppm(141, 102, 142)) == pytest.approx(39.5)  # measured at dusk
    assert media.colour_cast(ppm(90, 120, 80)) < media.NIGHT_OFF  # green garden by day
    assert media.colour_cast(b"not an image") is None


def test_greyscale_and_colour_probe_in_the_webcam_pipeline() -> None:
    settings = media.CameraSettings(resolution="1280x720", framerate=10)
    (plain,) = media.build_pipeline(WEBCAM, settings, None, media.MicrophoneSettings(), PUBLISH)
    assert "-filter_complex" not in plain and "0:v:0" in plain
    (night,) = media.build_pipeline(
        WEBCAM, settings, None, media.MicrophoneSettings(), PUBLISH, mono=True, probe_path="/tmp/p.ppm",
    )
    graph = night[night.index("-filter_complex") + 1]
    assert "hue=s=0" in graph and "split=2" in graph
    # No slow output: a probe that gets a frame only every few seconds made ffmpeg
    # hold the stream (and its sound) back in 10-second bursts.
    assert "fps=" not in graph
    # The stream gets the greyscale picture; the probe (before greyscale) goes to a file.
    assert night.index(PUBLISH) < night.index("[colour]") and night[-1] == "/tmp/p.ppm"
    assert night[night.index("-map") + 1] == "[v]"


def test_auto_night_switches_after_three_agreeing_readings(
    node: tuple[Agent, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    agent, _ = node
    agent.camera = WEBCAM
    supervisor = agent.stream
    restarts: list[bool] = []
    # The night picture restarts the camera process only, never the microphone.
    monkeypatch.setattr(supervisor, "restart", lambda which="all": restarts.append(which == "camera"))
    monkeypatch.setattr(supervisor, "probe_path", lambda: str(tmp_path / "probe.ppm"))
    supervisor.pipeline = type("Alive", (), {"alive": lambda self: True})()  # type: ignore[assignment]
    probe = tmp_path / "probe.ppm"

    def reading(red: int, green: int, blue: int) -> None:
        probe.write_bytes(ppm(red, green, blue))
        supervisor._night_checked = 0
        supervisor.check_night()

    for _ in range(2):
        reading(141, 102, 142)
    assert not supervisor.night_dark and not restarts  # two readings are not enough
    reading(141, 102, 142)
    assert supervisor.night_dark and restarts == [True]
    assert supervisor.night_picture(WEBCAM) == (True, str(tmp_path / "probe.ppm"))
    reading(110, 100, 110)  # cast 10: still dusk, stays greyscale (hysteresis)
    assert supervisor.night_dark
    for _ in range(3):
        reading(90, 120, 80)
    assert not supervisor.night_dark and restarts == [True, True]
    agent.state.camera = agent.state.camera.updated({"night_mode": "colour"}, "v4l2")
    assert supervisor.night_picture(WEBCAM) == (False, None)
    agent.state.camera = agent.state.camera.updated({"night_mode": "mono"}, "v4l2")
    assert supervisor.night_picture(WEBCAM) == (True, None)
    supervisor.pipeline = None
