# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from dataclasses import replace

from falcon_node import thermal
from falcon_node.agent import Agent
from falcon_node.config import NodeConfig
from tests.test_auth_and_sensors import KEY
from tests.test_media_and_api import HAT, PI_CAMERA


def guard(readings: list[float], stop_c: float = 0.0) -> tuple[thermal.ThermalGuard, list[int]]:
    changes: list[int] = []
    values = iter(readings)
    watcher = thermal.ThermalGuard(85, stop_c, 75, changes.append, read=lambda: next(values))
    return watcher, changes


def run(watcher: thermal.ThermalGuard, count: int) -> None:
    for _ in range(count):
        watcher.check()


def test_camera_pauses_at_85_and_resumes_only_after_cooling_to_75() -> None:
    watcher, changes = guard([84.9, 85.2, 86.0, 80.0, 76.0, 75.0, 74.5])
    run(watcher, 2)
    assert watcher.level == thermal.NORMAL  # one hot reading is not enough
    run(watcher, 1)
    assert watcher.level == thermal.CAMERA_PAUSED and changes == [thermal.CAMERA_PAUSED]
    assert watcher.status()["state"] == "camera paused" and watcher.status()["since"]
    run(watcher, 2)
    assert watcher.level == thermal.CAMERA_PAUSED  # 80 and 76 °C: still cooling down
    run(watcher, 2)
    assert watcher.level == thermal.NORMAL and changes == [thermal.CAMERA_PAUSED, thermal.NORMAL]
    assert watcher.events == 1 and watcher.status()["since"] is None


def test_a_single_spike_does_not_flap_the_stream() -> None:
    watcher, changes = guard([86.0, 70.0, 86.0, 70.0])
    run(watcher, 4)
    assert watcher.level == thermal.NORMAL and changes == []


def test_optional_hard_stop_and_disabled_guard() -> None:
    watcher, changes = guard([90.0, 90.0], stop_c=88)
    run(watcher, 2)
    assert watcher.level == thermal.STREAM_STOPPED and changes == [thermal.STREAM_STOPPED]
    off = thermal.ThermalGuard(0, 0, 0, lambda level: None, read=lambda: 99.0)
    run(off, 3)
    assert off.level == thermal.NORMAL and off.status()["enabled"] is False


def test_thresholds_come_from_node_conf_with_safe_ordering() -> None:
    defaults = NodeConfig.load(None, environ={"FALCON_PAIRING_KEY": KEY, "FALCON_NODE_ID": "n"})
    # The whole stream pauses at 84 °C and resumes at 75 °C.
    assert (defaults.thermal_pause_c, defaults.thermal_resume_c, defaults.thermal_stop_c) == (84, 75, 84)
    custom = NodeConfig.load(None, environ={
        "FALCON_PAIRING_KEY": KEY, "FALCON_NODE_ID": "n",
        "FALCON_THERMAL_PAUSE_C": "80", "FALCON_THERMAL_RESUME_C": "82", "FALCON_THERMAL_STOP_C": "70",
    })
    # Resume must be below pause, and a hard stop can never come before the pause.
    assert custom.thermal_resume_c == 78 and custom.thermal_stop_c == 80


def test_a_hot_node_streams_sound_without_the_camera(tmp_path) -> None:
    config = replace(
        NodeConfig.load(None, environ={"FALCON_PAIRING_KEY": KEY, "FALCON_NODE_ID": "n"}),
        state_dir=tmp_path, mediamtx_api_port=1,
    )
    agent = Agent(config, detect=False)
    agent.camera, agent.microphone = PI_CAMERA, HAT
    assert agent.stream.sources() == (PI_CAMERA, HAT)
    agent.thermal.level = thermal.CAMERA_PAUSED
    assert agent.stream.sources() == (None, HAT) and agent.stream.desired()
    agent.thermal.level = thermal.STREAM_STOPPED
    assert not agent.stream.desired()
    agent.media_server.path_status = lambda path="falcon": None  # type: ignore[method-assign]
    assert agent.stream.status()["state"] == "too hot"
    assert agent.status()["thermal"]["state"] == "stream stopped"
