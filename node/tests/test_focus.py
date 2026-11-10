import json
import threading
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from falcon_node import focus
from falcon_node.agent import Agent
from falcon_node.config import NodeConfig
from falcon_node.server import make_handler
from tests.test_auth_and_sensors import KEY
from tests.test_media_and_api import HAT, PI_CAMERA


def test_sharpness_peaks_on_fine_detail() -> None:
    import random

    width, height = 40, 30
    rng = random.Random(1)
    sharp = bytes(rng.choice((0, 255)) for _ in range(width * height))  # fine random detail
    soft = bytes(128 + (x % 4) for y in range(height) for x in range(width))  # gentle ramp
    flat = bytes([128]) * (width * height)
    assert focus.sharpness(sharp, width, height) > focus.sharpness(soft, width, height) > 0
    assert focus.sharpness(flat, width, height) == 0


def test_jpegs_are_split_whole_and_the_rest_is_kept() -> None:
    first, second = b"\xff\xd8one\xff\xd9", b"\xff\xd8two\xff\xd9"
    images, rest = focus.split_jpegs(first + second + b"\xff\xd8thr")
    assert images == [first, second] and rest == b"\xff\xd8thr"


def test_live_picture_is_offered_on_the_hotspot_and_this_node_only() -> None:
    assert focus.allowed("10.42.0.23") and focus.allowed("127.0.0.1") and focus.allowed("::ffff:10.42.0.9")
    assert not focus.allowed("192.168.1.20") and not focus.allowed("not-an-ip")


def test_reader_reads_the_local_stream_without_audio_and_three_outputs() -> None:
    command = focus.FocusHelper("ffmpeg", 8554).command(7, 9)
    assert "rtsp://127.0.0.1:8554/falcon" in command
    assert command.count("-map") == 3 and "pipe:1" in command and "pipe:7" in command and "pipe:9" in command
    assert "fps=2" in command[command.index("-filter_complex") + 1]


class FakeHelper:
    jpeg = b"\xff\xd8full\xff\xd9"
    zoom_jpeg = b"\xff\xd8zoom\xff\xd9"

    def __init__(self) -> None:
        self.touched = 0
        self.reset = 0

    def touch(self) -> None:
        self.touched += 1

    def reset_best(self) -> None:
        self.reset += 1

    def state(self) -> dict[str, Any]:
        return {"sharpness": 812.5, "best": 900.0, "live": True, "fps": 2.0}


@pytest.fixture
def phone(tmp_path: Path) -> Iterator[tuple[FakeHelper, str]]:
    config = replace(NodeConfig.load(None, environ={"FALCON_PAIRING_KEY": KEY, "FALCON_NODE_ID": "node-1"}),
                     api_port=0, state_dir=tmp_path, mediamtx_api_port=1)
    agent = Agent(config, detect=False)
    agent.camera, agent.microphone = PI_CAMERA, HAT
    helper = FakeHelper()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(agent, helper))  # type: ignore[arg-type]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield helper, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_phone_page_picture_score_and_reset(phone: tuple[FakeHelper, str]) -> None:
    helper, base = phone
    for path in ("/mobile", "/focus"):
        with urllib.request.urlopen(base + path) as response:
            page = response.read().decode()
        assert "Sharpness" in page and "Full screen" in page and "Zoom" in page
        assert "http" not in page.replace("http-equiv", "")  # works offline on the hotspot
    with urllib.request.urlopen(base + "/focus.jpg?t=1") as response:
        assert response.headers["Content-Type"] == "image/jpeg" and response.read() == helper.jpeg
    with urllib.request.urlopen(base + "/focus.jpg?zoom=1&t=2") as response:
        assert response.read() == helper.zoom_jpeg
    with urllib.request.urlopen(base + "/focus.json") as response:
        state = json.loads(response.read())
    assert state["sharpness"] == 812.5 and state["node"]["components"]["camera"]
    assert KEY not in json.dumps(state)
    request = urllib.request.Request(base + "/focus/reset", data=b"", method="POST")
    with urllib.request.urlopen(request) as response:
        assert response.status == 200
    assert helper.reset == 1 and helper.touched >= 5
