# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from falcon_node import auth, media
from falcon_node.agent import Agent
from falcon_node.config import NodeConfig, NodeState, parse_conf
from falcon_node.sensors import build_reading
from falcon_node.server import serve
from tests.test_auth_and_sensors import KEY, NOW

PUBLISH = "rtsp://127.0.0.1:8554/falcon"
PI_CAMERA = media.Camera("rpicam", "0", "Camera Module 3 (imx708)")
HAT = media.Microphone("plughw:CARD=Zero,DEV=0", "Zero", "DA7212 audio HAT", 2)


def test_camera_settings_validate_types_ranges_and_choices() -> None:
    settings = media.CameraSettings().updated({"framerate": 10, "focus_mode": "manual", "lens_position": 0.5, "hdr": True})
    assert (settings.framerate, settings.focus_mode, settings.hdr) == (10, "manual", True)
    for bad in ({"framerate": 120}, {"focus_mode": "macro"}, {"hdr": "yes"}, {"zoom": 2}, {"resolution": "4608x2592"}):
        with pytest.raises(ValueError):
            media.CameraSettings().updated(bad)
    assert media.CameraSettings().updated({"resolution": "640x480"}, "v4l2").size == (640, 480)


def test_pi_camera_and_audio_hat_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "rpicam_binary", lambda: "/usr/bin/rpicam-vid")
    settings = media.CameraSettings().updated({"focus_mode": "manual", "lens_position": 0.5, "vflip": True})
    capture, encoder = media.build_pipeline(PI_CAMERA, settings, HAT, media.MicrophoneSettings(), PUBLISH)
    assert capture[:3] == ["/usr/bin/rpicam-vid", "-t", "0"] and capture[-2:] == ["-o", "-"]
    assert capture[capture.index("--lens-position") + 1] == "0.5" and "--vflip" in capture
    assert capture[capture.index("--intra") + 1] == "15"  # one keyframe per second at 15 fps
    assert "pipe:0" in encoder and "plughw:CARD=Zero,DEV=0" in encoder
    assert encoder[encoder.index("-af") + 1] == "pan=mono|c0=0.5*c0+0.5*c1"
    assert encoder[-5:] == ["-f", "rtsp", "-rtsp_transport", "tcp", PUBLISH]
    assert encoder[encoder.index("-c:v") + 1] == "copy"


def test_usb_webcam_relay_and_audio_only_pipelines() -> None:
    webcam = media.Camera("v4l2", "/dev/video0", "USB camera")
    (command,) = media.build_pipeline(webcam, media.CameraSettings(), None, media.MicrophoneSettings(), PUBLISH)
    assert command[command.index("-f") + 1] == "v4l2" and "libx264" in command and "-af" not in command
    assert "-input_format" not in command
    mjpeg_webcam = media.Camera("v4l2", "/dev/video0", "USB camera", "mjpeg")
    (command,) = media.build_pipeline(mjpeg_webcam, media.CameraSettings(), None, media.MicrophoneSettings(), PUBLISH)
    assert command[command.index("-input_format") + 1] == "mjpeg"
    # The output rate is forced, since webcams may deliver more frames than requested.
    assert command[command.index("-r") + 1] == str(media.CameraSettings().framerate)
    assert command.index("-input_format") < command.index("-i")
    relay = media.Camera("rtsp", "rtsp://user:secret@camera.example/stream1", "IP camera (relayed)")
    (command,) = media.build_pipeline(relay, media.CameraSettings(), None, media.MicrophoneSettings(), PUBLISH)
    assert "0:a:0?" in command and command[command.index("-c:v") + 1] == "copy"
    (command,) = media.build_pipeline(None, media.CameraSettings(), HAT, media.MicrophoneSettings("left"), PUBLISH)
    assert "pan=mono|c0=c0" in command and "-c:v" not in command
    assert media.build_pipeline(None, media.CameraSettings(), None, media.MicrophoneSettings(), PUBLISH) == []
    assert media.redact("Connection to rtsp://user:secret@camera.example/x failed") == (
        "Connection to rtsp://***@camera.example/x failed"
    )


def test_usb_camera_controls_are_applied_only_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(media.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(media, "run", lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=0))
    webcam = media.Camera("v4l2", "/dev/video0", "USB camera", "mjpeg")
    assert media.apply_camera_controls(webcam, "sharpness=12, backlight_compensation=100")
    assert calls == [["v4l2-ctl", "-d", "/dev/video0", "-c", "sharpness=12,backlight_compensation=100"]]
    assert not media.apply_camera_controls(webcam, "sharpness=12; rm -rf /")  # malformed: ignored
    assert not media.apply_camera_controls(PI_CAMERA, "sharpness=12")  # not a USB webcam
    assert not media.apply_camera_controls(webcam, "")
    assert len(calls) == 1


def test_stream_server_config_allows_only_local_publishing_and_falcon_reading(tmp_path: Path) -> None:
    text = media.MediaServer("mediamtx", tmp_path / "m.yml", 8554, 9997, "pw").render()
    assert "rtspTransports: [tcp]" in text and "pass: pw" in text
    assert "ips: ['127.0.0.1', '::1']" in text and "apiAddress: 127.0.0.1:9997" in text
    for protocol in ("rtmp", "hls", "webrtc", "srt", "moq"):
        assert f"{protocol}: false" in text


def test_configuration_file_and_saved_state(tmp_path: Path) -> None:
    values = parse_conf('# comment\nNODE_ID=backyard-1\nNODE_NAME="Backyard node"\nCAMERA=off  # no camera\n')
    assert values == {"NODE_ID": "backyard-1", "NODE_NAME": "Backyard node", "CAMERA": "off"}
    with pytest.raises(SystemExit):
        NodeConfig.load(None, environ={})
    config = NodeConfig.load(None, environ={"FALCON_PAIRING_KEY": KEY, "FALCON_NODE_ID": "n1", "FALCON_RAIN": "gpio:22"})
    assert config.node_id == "n1" and config.rain == "gpio:22"
    state = NodeState(tmp_path / "state.json")
    state.components["rain"] = False
    state.camera = state.camera.updated({"ev": 1.5})
    state.save()
    loaded = NodeState(tmp_path / "state.json")
    assert loaded.components["rain"] is False and loaded.camera.ev == 1.5
    (tmp_path / "state.json").write_text("{damaged")
    assert NodeState(tmp_path / "state.json").stream_enabled is True


@pytest.fixture
def node(tmp_path: Path) -> Iterator[tuple[Agent, str]]:
    config = replace(NodeConfig.load(None, environ={"FALCON_PAIRING_KEY": KEY, "FALCON_NODE_ID": "node-1"}),
                     api_port=0, state_dir=tmp_path, mediamtx_api_port=1)
    agent = Agent(config, detect=False)
    agent.camera, agent.microphone = PI_CAMERA, HAT
    server = serve(agent, host="127.0.0.1")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield agent, "http://127.0.0.1:" + str(server.server_address[1])
    server.shutdown()


def call(base: str, method: str, path: str, body: dict | None = None, key: str = KEY) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else b""
    request = urllib.request.Request(base + path, data=data or None, method=method, headers={
        "Content-Type": "application/json", "Authorization": auth.sign(key, method, path, data),
    })
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_public_page_and_info_reveal_no_secrets(node: tuple[Agent, str]) -> None:
    _, base = node
    with urllib.request.urlopen(base + "/") as response:
        page = response.read().decode()
    with urllib.request.urlopen(base + "/api/v1/info") as response:
        info = json.loads(response.read())
    assert "FALCON sensor node" in page and KEY not in page and auth.rtsp_password(KEY) not in page
    assert info["node_id"] == "node-1" and info["components"]["camera"] is True and KEY not in json.dumps(info)


def test_control_requires_the_pairing_key(node: tuple[Agent, str]) -> None:
    _, base = node
    status, body = call(base, "GET", "/api/v1/status", key="ZZZZ-EFGH-IJKL-MNOP-QRST-UVWX")
    assert status == 401 and "pairing key" in body["detail"]
    request = urllib.request.Request(base + "/api/v1/status")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 401


def test_status_stream_components_and_camera_controls(node: tuple[Agent, str]) -> None:
    agent, base = node
    status, body = call(base, "GET", "/api/v1/status")
    assert status == 200 and body["stream"]["rtsp_path"] == "falcon"
    assert "lens_position" in body["components"]["camera"]["controls"]
    status, body = call(base, "POST", "/api/v1/stream", {"action": "stop"})
    assert status == 200 and body["stream"]["state"] == "off" and agent.state.stream_enabled is False
    status, body = call(base, "PUT", "/api/v1/components/microphone", {"enabled": False})
    assert status == 200 and body["components"]["microphone"]["enabled"] is False
    assert call(base, "PUT", "/api/v1/components/radar", {"enabled": True})[0] == 422
    status, body = call(base, "PUT", "/api/v1/camera", {"focus_mode": "manual", "lens_position": 2})
    assert status == 200 and body["camera_settings"]["lens_position"] == 2
    status, body = call(base, "PUT", "/api/v1/camera", {"framerate": 99})
    assert status == 422 and "between" in body["detail"]
    agent.camera = media.Camera("v4l2", "/dev/video0", "USB camera")
    status, body = call(base, "PUT", "/api/v1/camera", {"ev": 1})
    assert status == 422 and "does not support" in body["detail"]
    assert json.loads((agent.config.state_dir / "state.json").read_text())["components"]["microphone"] is False


def test_readings_are_pulled_oldest_first_and_removed_when_acknowledged(node: tuple[Agent, str]) -> None:
    agent, base = node
    for second in range(3):
        reading = build_reading("node-1", NOW.replace(second=second), (20.0, 50.0, 1000.0), False, True)
        assert reading is not None
        agent.spool.add(reading)
    status, body = call(base, "POST", "/api/v1/readings/pull", {"ack": [], "limit": 2})
    assert status == 200 and body["queued"] == 3 and len(body["readings"]) == 2
    first = [item["reading_id"] for item in body["readings"]]
    status, body = call(base, "POST", "/api/v1/readings/pull", {"ack": first, "limit": 2})
    assert body["acknowledged"] == 2 and body["queued"] == 1 and body["readings"][0]["observed_at"].endswith("02.123456+00:00")
    assert call(base, "POST", "/api/v1/readings/pull", {"ack": "all"})[0] == 422


def test_unsynchronized_node_adopts_the_inference_node_clock(node: tuple[Agent, str], monkeypatch: pytest.MonkeyPatch) -> None:
    agent, _ = node
    calls: list[float] = []
    monkeypatch.setattr(agent, "ntp_synchronized", lambda: False)
    monkeypatch.setattr("falcon_node.system.set_clock", lambda value: calls.append(value) or True)
    early = build_reading("node-1", NOW.replace(year=2025), (20.0, 50.0, 1000.0), None, False)
    assert early
    agent.spool.add(early, boot_id=agent.boot, clock_ok=False)
    import time

    agent.caller_time(time.time() + 3600)
    assert calls and agent.clock_adopted_at is not None and agent.clock_synchronized() is True
    assert agent.spool.oldest(1)[0]["observed_at"].startswith("2025-10-18T07:30")
