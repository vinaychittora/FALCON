# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from pathlib import Path
from typing import Any

import pytest

from falcon_node import media
from falcon_node.agent import Agent
from falcon_node.config import NodeState
from tests import test_media_and_api
from tests.test_media_and_api import call

node = test_media_and_api.node  # the running-node pytest fixture

# `v4l2-ctl --list-ctrls-menus` from the Microdia/Arducam USB webcam on the test node.
LISTING = """
User Controls

                     brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=0 flags=has-min-max
                       contrast 0x00980901 (int)    : min=0 max=64 step=1 default=32 value=32 flags=has-min-max
                     saturation 0x00980902 (int)    : min=0 max=128 step=1 default=64 value=64 flags=has-min-max
                            hue 0x00980903 (int)    : min=-40 max=40 step=1 default=0 value=0 flags=has-min-max
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1
                          gamma 0x00980910 (int)    : min=72 max=500 step=1 default=100 value=100 flags=has-min-max
                           gain 0x00980913 (int)    : min=0 max=100 step=1 default=0 value=0 flags=has-min-max
           power_line_frequency 0x00980918 (menu)   : min=0 max=2 default=1 value=1 (50 Hz)
				0: Disabled
				1: 50 Hz
				2: 60 Hz
      white_balance_temperature 0x0098091a (int)    : min=2800 max=6500 step=1 default=4600 value=4600 flags=inactive, has-min-max
                      sharpness 0x0098091b (int)    : min=0 max=14 step=1 default=10 value=12 flags=has-min-max
         backlight_compensation 0x0098091c (int)    : min=0 max=160 step=1 default=80 value=80 flags=has-min-max

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3 (Aperture Priority Mode)
				1: Manual Mode
				3: Aperture Priority Mode
         exposure_time_absolute 0x009a0902 (int)    : min=1 max=5000 step=1 default=157 value=157 flags=inactive, has-min-max
     exposure_dynamic_framerate 0x009a0903 (bool)   : default=0 value=1
"""

FORMATS = """
	[0]: 'MJPG' (Motion-JPEG, compressed)
		Size: Discrete 1920x1080
		Size: Discrete 1280x720
		Size: Discrete 800x600
	[1]: 'YUYV' (YUYV 4:2:2)
		Size: Discrete 640x480
		Size: Discrete 1280x720
"""

WEBCAM = media.Camera("v4l2", "/dev/video0", "USB Camera", "mjpeg", ("1920x1080", "1280x720", "800x600"))


def test_webcam_controls_are_parsed_with_menus_and_inactive_flags() -> None:
    controls = {item["name"]: item for item in media.parse_v4l2_controls(LISTING)}
    assert list(controls)[:3] == ["brightness", "contrast", "saturation"]
    assert controls["sharpness"] == {
        "name": "sharpness", "type": "int", "min": 0, "max": 14, "step": 1, "default": 10, "value": 12,
        "inactive": False,
    }
    assert controls["power_line_frequency"]["menu"] == [[0, "Disabled"], [1, "50 Hz"], [2, "60 Hz"]]
    assert controls["auto_exposure"]["menu"] == [[1, "Manual Mode"], [3, "Aperture Priority Mode"]]
    assert controls["white_balance_temperature"]["inactive"] and controls["exposure_time_absolute"]["inactive"]
    assert controls["white_balance_automatic"]["type"] == "bool" and controls["white_balance_automatic"]["max"] == 1
    assert len(controls) == 14


def test_only_the_webcams_own_sizes_are_offered() -> None:
    assert media.parse_v4l2_sizes(FORMATS, "mjpeg") == ("1920x1080", "1280x720", "800x600")
    assert media.parse_v4l2_sizes(FORMATS, "") == ("1920x1080", "1280x720", "800x600")  # first format
    assert media.resolutions(WEBCAM) == ["1920x1080", "1280x720", "800x600"]
    assert "960x540" not in media.resolutions(WEBCAM)


def test_values_are_checked_and_automatic_modes_go_first() -> None:
    available = media.parse_v4l2_controls(LISTING)
    order = media.validate_picture_values(
        available, {"exposure_time_absolute": 300, "auto_exposure": 1, "brightness": 5, "white_balance_automatic": False},
    )
    assert order[:2] == [("white_balance_automatic", 0), ("auto_exposure", 1)]
    assert ("exposure_time_absolute", 300) in order and ("brightness", 5) in order
    for bad, message in (
        ({"sharpness": 15}, "between 0 and 14"), ({"zoom": 1}, "no control named zoom"),
        ({"auto_exposure": 2}, "no option 2"), ({"gain": "high"}, "whole number"),
    ):
        with pytest.raises(ValueError, match=message):
            media.validate_picture_values(available, bad)


def test_controls_change_live_are_saved_and_can_be_reset(
    node: tuple[Agent, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, base = node
    agent.camera = WEBCAM
    applied: list[list[str]] = []
    restarts: list[bool] = []
    monkeypatch.setattr(media.shutil, "which", lambda name: "/usr/bin/" + name)

    class Result:
        returncode = 0
        stdout = LISTING

    def run(command: list[str], **kwargs: Any) -> Result:
        if "-c" in command:
            applied.append(command[-1:])
        return Result()

    monkeypatch.setattr(media, "run", run)
    monkeypatch.setattr(agent.stream, "restart", lambda which="all": restarts.append(True))
    status, body = call(base, "GET", "/api/v1/camera/controls")
    assert status == 200 and len(body["controls"]) == 14 and body["saved"] == {}
    status, body = call(base, "PUT", "/api/v1/camera/controls", {"values": {"brightness": 8, "sharpness": 12}})
    assert status == 200 and applied == [["brightness=8"], ["sharpness=12"]]
    assert body["saved"] == {"brightness": 8, "sharpness": 12} and not restarts  # live: no stream restart
    assert NodeState(agent.config.state_dir / "state.json").picture == {"brightness": 8, "sharpness": 12}
    status, body = call(base, "PUT", "/api/v1/camera/controls", {"values": {"sharpness": 99}})
    assert status == 422 and "between 0 and 14" in body["detail"]
    applied.clear()
    status, body = call(base, "PUT", "/api/v1/camera/controls", {"reset": True})
    assert status == 200 and body["saved"] == {} and ["brightness=0"] in applied and ["sharpness=10"] in applied
    status, body = call(base, "GET", "/api/v1/camera/controls", key="ZZZZ-EFGH-IJKL-MNOP-QRST-UVWX")
    assert status == 401


def test_microphone_gain_alone_applies_live_without_a_restart(
    node: tuple[Agent, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, base = node
    commands: list[list[str]] = []
    restarts: list[bool] = []

    class Result:
        returncode, stdout = 0, ""

    monkeypatch.setattr(media, "run", lambda command, **kwargs: commands.append(command) or Result())
    monkeypatch.setattr(agent.stream, "restart", lambda which="all": restarts.append(which == "microphone"))
    status, _ = call(base, "PUT", "/api/v1/microphone", {"audio_gain_percent": 40})
    assert status == 200 and not restarts
    assert commands == [["amixer", "-q", "-c", "Zero", "sset", "Mixin PGA", "40%"]]
    status, _ = call(base, "PUT", "/api/v1/microphone", {"audio_channel": "right"})
    assert status == 200 and restarts == [True]  # the channel changes the microphone process only


def test_picture_controls_need_a_usb_webcam(node: tuple[Agent, str]) -> None:
    agent, base = node  # the fixture's camera is a Pi camera module
    status, body = call(base, "PUT", "/api/v1/camera/controls", {"values": {"brightness": 1}})
    assert status == 422 and "USB webcams" in body["detail"]


def test_saved_controls_survive_a_damaged_entry(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text('{"picture": {"sharpness": 12, "gain": "x", "hdr": true}}')
    assert NodeState(tmp_path / "state.json").picture == {"sharpness": 12}
