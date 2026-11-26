# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Sensor-node pairing, control and reading collection against a real node server."""

import sys
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.nodes.client import NodeClient, NodeError
from app.nodes.service import NodeManager
from app.nodes.signing import display_key, rtsp_password, signature
from app.nodes.store import NodeStore, normalize_address
from app.schemas import AnalysisSettings
from app.services.appliance import AppliancePreferences
from app.services.sensors import SensorHistoryProvider
from app.storage.cameras import CameraStore
from app.storage.database import Database

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "node"))
from falcon_node import media  # noqa: E402
from falcon_node.agent import Agent  # noqa: E402
from falcon_node.config import NodeConfig  # noqa: E402
from falcon_node.sensors import build_reading  # noqa: E402
from falcon_node.server import serve  # noqa: E402

KEY = "ABCD-EFGH-IJKL-MNOP-QRST-UVWX"


def test_signature_vector_matches_the_sensor_node() -> None:
    assert signature(KEY, "POST", "/api/v1/stream", b'{"action":"start"}', "1760772000.000", "0" * 32) == (
        "52f2b692cfe943b35e63b48cc8dc3ad482566c2eb2d88b9cbb77d1b67b76d185"
    )
    assert rtsp_password(KEY) == "b8c3ec2b8746fd781ca4ee1f40d6a76c"
    assert display_key("abcdefghijklmnopqrstuvwx") == KEY


@pytest.mark.parametrize(("value", "expected"), [
    ("192.0.2.60", "http://192.0.2.60:8780"),
    ("falcon-node.local", "http://falcon-node.local:8780"),
    ("http://192.0.2.5:9000/", "http://192.0.2.5:9000"),
    ("[fe80::1]", "http://[fe80::1]:8780"),
])
def test_addresses_are_normalized(value: str, expected: str) -> None:
    assert normalize_address(value) == expected


@pytest.mark.parametrize("value", ["", "ftp://node", "http://user:pw@node.test", "http://node/path", "node:99999"])
def test_bad_addresses_are_refused(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_address(value)


@pytest.fixture
def node(tmp_path: Path) -> Iterator[Agent]:
    config = replace(
        NodeConfig.load(None, environ={"FALCON_PAIRING_KEY": KEY, "FALCON_NODE_ID": "backyard-1",
                                       "FALCON_NODE_NAME": "Backyard node"}),
        api_port=0, state_dir=tmp_path / "node", mediamtx_api_port=1,
    )
    agent = Agent(config, detect=False)
    agent.camera = media.Camera("rpicam", "0", "Camera Module 3 (imx708)")
    agent.microphone = media.Microphone("plughw:CARD=Zero,DEV=0", "Zero", "DA7212 audio HAT", 2)
    server = serve(agent, host="127.0.0.1")
    agent.config = replace(config, api_port=server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield agent
    server.shutdown()


@pytest.fixture
def manager(tmp_path: Path) -> tuple[NodeManager, SensorHistoryProvider]:
    database = Database(tmp_path / "falcon.sqlite3")
    sensors = SensorHistoryProvider(database)
    store = NodeStore(database, CameraStore(database, tmp_path / "private" / "camera.key"))
    return NodeManager(store, sensors.ingest), sensors


def address(agent: Agent) -> str:
    return f"127.0.0.1:{agent.config.api_port}"


def test_pairing_stores_an_encrypted_key_and_reports_status(node: Agent, manager: tuple[NodeManager, SensorHistoryProvider]) -> None:
    nodes, _ = manager
    summary = nodes.pair(address(node), KEY.lower().replace("-", ""))
    assert summary["node_id"] == "backyard-1" and summary["name"] == "Backyard node" and summary["online"]
    assert summary["status"]["components"]["camera"]["description"] == "Camera Module 3 (imx708)"
    assert nodes.store.key("backyard-1") == KEY
    with nodes.store.database.connection() as connection:
        stored = connection.execute("SELECT key_ciphertext FROM sensor_nodes").fetchone()[0]
    assert KEY.encode() not in stored and KEY.replace("-", "").encode() not in stored


def test_wrong_key_and_unreachable_node_give_clear_errors(node: Agent, manager: tuple[NodeManager, SensorHistoryProvider]) -> None:
    nodes, _ = manager
    with pytest.raises(NodeError, match="pairing key") as wrong:
        nodes.pair(address(node), "ZZZZ-EFGH-IJKL-MNOP-QRST-UVWX")
    assert wrong.value.status == 401
    with pytest.raises(NodeError, match="not reachable") as missing:
        NodeClient("http://127.0.0.1:9", KEY, timeout=2).status()
    assert missing.value.status is None


def test_controls_change_the_node_and_refresh_the_summary(node: Agent, manager: tuple[NodeManager, SensorHistoryProvider]) -> None:
    nodes, _ = manager
    nodes.pair(address(node), KEY)
    summary = nodes.control("backyard-1", lambda client: client.stream("stop"))
    assert summary["status"]["stream"]["state"] == "off" and node.state.stream_enabled is False
    summary = nodes.control("backyard-1", lambda client: client.component("rain", False))
    assert summary["status"]["components"]["rain"]["enabled"] is False
    summary = nodes.control("backyard-1", lambda client: client.camera({"focus_mode": "manual", "lens_position": 1.5}))
    assert summary["status"]["camera_settings"]["lens_position"] == 1.5
    with pytest.raises(NodeError, match="between") as invalid:
        nodes.control("backyard-1", lambda client: client.camera({"framerate": 500}))
    assert invalid.value.status == 422


def test_readings_are_collected_validated_and_acknowledged(node: Agent, manager: tuple[NodeManager, SensorHistoryProvider]) -> None:
    nodes, sensors = manager
    nodes.pair(address(node), KEY)
    moment = datetime.now(UTC) - timedelta(minutes=5)
    for second in range(3):
        reading = build_reading("backyard-1", moment + timedelta(seconds=second), (24.5, 61.0, 1003.2), False, True)
        assert reading
        node.spool.add(reading)
    future = build_reading("backyard-1", datetime.now(UTC) + timedelta(hours=2), (24.5, 61.0, 1003.2), None, True)
    assert future
    node.spool.add(future)  # rejected by FALCON (ahead of its clock), so it must be dropped, not retried forever
    assert nodes.collect("backyard-1", nodes.client("backyard-1")) == 3
    assert len(node.spool) == 0
    history = sensors.history()
    assert history.total == 3 and history.readings[0].surface_wet is False
    assert nodes.preferred_sensor_id() == "backyard-1"
    assert sensors.session_sensor_id() == "backyard-1"  # the only sensor with readings


def test_live_request_uses_the_node_stream_with_derived_credentials(node: Agent, manager: tuple[NodeManager, SensorHistoryProvider]) -> None:
    nodes, _ = manager
    nodes.pair(address(node), KEY)
    request = nodes.live_request("backyard-1", AnalysisSettings(audio_enabled=True))
    assert request.url.get_secret_value() == "rtsp://127.0.0.1:8554/falcon"
    assert request.username and request.username.get_secret_value() == "falcon"
    assert request.password and request.password.get_secret_value() == rtsp_password(KEY)
    assert request.config.audio_enabled is True and request.name == "Backyard node"
    nodes.store.update("backyard-1", audio_analysis=False)
    assert nodes.live_request("backyard-1", AnalysisSettings(audio_enabled=True)).config.audio_enabled is False


def test_api_reads_and_changes_webcam_picture_controls(
    node: Agent, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    node.camera = media.Camera("v4l2", "/dev/video0", "USB Camera", "mjpeg", ("1280x720",))
    listing = (
        "  brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=0\n"
        "  sharpness 0x0098091b (int)    : min=0 max=14 step=1 default=10 value=10\n"
    )
    applied: list[str] = []

    class Result:
        returncode, stdout = 0, listing

    def run(command: list[str], **kwargs: object) -> Result:
        if "-c" in command:
            applied.append(command[-1])
        return Result()

    monkeypatch.setattr(media.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(media, "run", run)
    app = create_app(Settings(data_dir=tmp_path / "falcon"))
    with TestClient(app) as client:
        client.post("/api/nodes", json={"address": address(node), "pairing_key": KEY})
        controls = client.get("/api/nodes/backyard-1/camera/controls").json()
        assert [item["name"] for item in controls["controls"]] == ["brightness", "sharpness"]
        changed = client.put("/api/nodes/backyard-1/camera/controls", json={"values": {"sharpness": 12}})
        assert changed.status_code == 200 and changed.json()["saved"] == {"sharpness": 12}
        assert applied == ["sharpness=12"]
        too_high = client.put("/api/nodes/backyard-1/camera/controls", json={"values": {"sharpness": 40}})
        assert too_high.status_code == 422 and "between 0 and 14" in too_high.text
        assert client.put("/api/nodes/backyard-1/camera/controls", json={}).status_code == 422
        assert client.put("/api/nodes/backyard-1/camera/controls", json={"values": {"x": "a"}}).status_code == 422
        reset = client.put("/api/nodes/backyard-1/camera/controls", json={"reset": True})
        assert reset.status_code == 200 and reset.json()["saved"] == {}
        assert client.get("/api/nodes/unknown/camera/controls").status_code == 404


def test_api_switches_node_extras_and_reports_heat(
    node: Agent, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from falcon_node import extras

    switched: list[tuple[str, bool]] = []
    monkeypatch.setattr(extras, "state", lambda name: {"available": True, "on": name == "hotspot"})
    monkeypatch.setattr(extras, "switch", lambda name, on: switched.append((name, on)))
    app = create_app(Settings(data_dir=tmp_path / "falcon"))
    with TestClient(app) as client:
        client.post("/api/nodes", json={"address": address(node), "pairing_key": KEY})
        listing = client.get("/api/nodes/backyard-1/extras").json()
        assert [item["name"] for item in listing["extras"]] == ["hotspot", "bluetooth"]
        assert listing["thermal"]["state"] == "normal" and listing["thermal"]["stop_c"] == 84
        off = client.put("/api/nodes/backyard-1/extras", json={"name": "hotspot", "on": False})
        assert off.status_code == 200 and switched == [("hotspot", False)]
        boot = client.put("/api/nodes/backyard-1/extras", json={"name": "bluetooth", "at_boot": True})
        assert boot.status_code == 200 and node.state.extras_at_boot == {"bluetooth": True}
        assert client.put("/api/nodes/backyard-1/extras", json={"name": "hdmi", "on": True}).status_code == 422
        assert client.put("/api/nodes/backyard-1/extras", json={"name": "hotspot"}).status_code == 422
        assert client.put("/api/nodes/backyard-1/extras", json={"name": "hotspot", "on": "no"}).status_code == 422
        # The thermal guard's state reaches FALCON with the node status.
        summary = client.get("/api/nodes").json()["nodes"][0]
        assert summary["status"]["thermal"]["state"] == "normal"


def test_api_pairs_controls_and_forgets_without_echoing_the_key(node: Agent, tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "falcon"))
    with TestClient(app) as client:
        bad = client.post("/api/nodes", json={"address": address(node), "pairing_key": "ZZZZ-EFGH-IJKL-MNOP-QRST-UVWX"})
        assert bad.status_code == 422 and "ZZZZ" not in bad.text
        invalid = client.post("/api/nodes", json={"address": address(node), "pairing_key": KEY, "extra": 1})
        assert invalid.status_code == 422 and KEY not in invalid.text
        paired = client.post("/api/nodes", json={"address": address(node), "pairing_key": KEY, "name": "Pond"})
        assert paired.status_code == 201 and paired.json()["name"] == "Pond" and KEY not in paired.text
        listing = client.get("/api/nodes").json()["nodes"]
        assert [item["node_id"] for item in listing] == ["backyard-1"] and KEY not in str(listing)
        stopped = client.post("/api/nodes/backyard-1/stream", json={"action": "stop"})
        assert stopped.status_code == 200 and stopped.json()["status"]["stream"]["state"] == "off"
        toggled = client.put("/api/nodes/backyard-1/components/microphone", json={"enabled": False})
        assert toggled.json()["status"]["components"]["microphone"]["enabled"] is False
        assert client.put("/api/nodes/backyard-1/components/microphone", json={"enabled": "no"}).status_code == 422
        assert client.put("/api/nodes/backyard-1/camera", json={"ev": 9}).status_code == 422
        renamed = client.patch("/api/nodes/backyard-1", json={"name": "Pond edge", "audio_analysis": False})
        assert renamed.json()["name"] == "Pond edge" and renamed.json()["audio_analysis"] is False
        assert client.get("/api/nodes/unknown").status_code == 404
        assert app.state.sensors.session_sensor_id() == "backyard-1"
        assert app.state.appliance.configure(AppliancePreferences(source="node:backyard-1")).source_name == "Pond edge"
        assert client.delete("/api/nodes/backyard-1").json() == {"nodes": []}
        with pytest.raises(ValueError, match="Pair this sensor node"):
            app.state.appliance.configure(AppliancePreferences(auto_observe=True, source="node:backyard-1"))
