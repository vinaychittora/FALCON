import threading

import pytest
from pydantic import SecretStr

from app.media.rtsp_source import RTSPSource
from app.nodes.service import NodeManager
from app.nodes.store import NodeStore
from app.schemas import AnalysisSettings
from app.schemas_live import CameraProfileWrite
from app.storage.cameras import CameraStore
from app.storage.database import Database

KEY = "ABCD-EFGH-IJKL-MNOP-QRST-UVWX"
STATUS = {"stream": {"rtsp_port": 8554, "rtsp_path": "falcon", "audio": True}}


def manager(tmp_path):
    db = Database(tmp_path / "f.sqlite3")
    store = NodeStore(db, CameraStore(db, tmp_path / "camera.key"))
    store.save("falcon-node", "falcon-node", "http://192.168.1.60:8780", KEY)
    return NodeManager(store, None), store


def test_node_camera_is_the_default(tmp_path):
    nodes, store = manager(tmp_path)
    assert store.get("falcon-node").video_source == "node"
    request = nodes.live_request("falcon-node", AnalysisSettings(), STATUS)
    assert request.url.get_secret_value() == "rtsp://192.168.1.60:8554/falcon" and request.audio_url is None


def test_ip_camera_picture_with_node_sound(tmp_path):
    nodes, store = manager(tmp_path)
    store.cameras.save(CameraProfileWrite(
        name="Waterhole", url=SecretStr("rtsp://192.168.1.50:554/stream1"),
        username=SecretStr("admin"), password=SecretStr("secret"),
    ))
    store.update("falcon-node", video_source="ip")
    request = nodes.live_request("falcon-node", AnalysisSettings(), STATUS)
    assert request.connection_url() == "rtsp://admin:secret@192.168.1.50:554/stream1"
    audio = request.audio_url.get_secret_value()
    assert audio.startswith("rtsp://falcon:") and audio.endswith("@192.168.1.60:8554/falcon")
    assert request.config.audio_enabled is True


def test_ip_camera_without_a_saved_camera_is_explained(tmp_path):
    nodes, store = manager(tmp_path)
    store.update("falcon-node", video_source="ip")
    with pytest.raises(Exception, match="no IP camera is saved"):
        nodes.live_request("falcon-node", AnalysisSettings(), STATUS)
    with pytest.raises(ValueError):
        store.update("falcon-node", video_source="usb")


def test_reader_opens_sound_from_the_node_and_picture_from_the_camera():
    opened = []

    def open_container(url, **kwargs):
        opened.append((url, kwargs["options"]["allowed_media_types"]))
        raise OSError("test: no network")

    source = RTSPSource(
        "rtsp://camera/stream1", threading.Event(), 0.0, lambda *_: None, lambda *_: None,
        lambda *_: None, lambda *_: None, open_container=open_container, audio_url="rtsp://node/falcon",
    )
    for media in ("video", "audio", "video+audio"):
        try:
            source._open(media)  # noqa: SLF001
        except OSError:
            pass
    assert opened == [
        ("rtsp://camera/stream1", "video"), ("rtsp://node/falcon", "audio"), ("rtsp://node/falcon", "video+audio"),
    ]
