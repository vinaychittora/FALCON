import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import AnalysisSettings
from app.schemas_live import CameraProfileWrite, LiveStart, LiveState
from app.services.appliance import AppliancePreferences, ApplianceService
from app.storage.cameras import CameraStore
from app.storage.database import Database
from app.taxonomy.cache import atomic_json


class Camera:
    def __init__(self, status: str = "live"):
        self.analyzer = SimpleNamespace(lock=threading.Lock())
        self.status = status
        self.requests: list[LiveStart] = []
        self.stopped: list[str | None] = []
        self.current = LiveState()

    def start(self, request: LiveStart) -> LiveState:
        self.requests.append(request)
        self.current = LiveState(status=self.status, session_id=f"session-{len(self.requests)}")
        return self.state()

    def state(self) -> LiveState:
        return self.current.model_copy(deep=True)

    def stop(self, wait: bool = False) -> LiveState:
        self.stopped.append(self.current.session_id)
        self.current.status = "stopped"
        return self.state()


def setup(tmp_path: Path, camera: Camera | None = None) -> tuple[ApplianceService, CameraStore, Camera]:
    settings = Settings(data_dir=tmp_path, model_dir=tmp_path / "models")
    settings.prepare()
    cameras = CameraStore(Database(tmp_path / "falcon.sqlite3"), tmp_path / "private" / "camera.key")
    camera = camera or Camera()
    service = ApplianceService(
        settings, cameras, camera, connect_timeout=0.02, retry_delay=0.01
    )
    return service, cameras, camera


def save(cameras: CameraStore, audio_enabled: bool = True) -> None:
    cameras.save(CameraProfileWrite(
        url="rtsp://camera.test/stream1", username="fixture-user", password="fixture-secret",
        audio_enabled=audio_enabled,
    ))


def wait_for(service: ApplianceService, state: str) -> None:
    deadline = time.monotonic() + 3
    while service.status().state != state and time.monotonic() < deadline:
        time.sleep(0.005)
    assert service.status().state == state


def joined(service: ApplianceService) -> None:
    if service._worker:
        service._worker.join(timeout=3)
        assert not service._worker.is_alive()


def test_default_off_and_enabling_requires_saved_camera(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path)
    service.startup()
    assert service.status().auto_observe is False and not camera.requests
    with pytest.raises(ValueError, match="Save a camera"):
        service.configure(AppliancePreferences(auto_observe=True))
    assert not service.path.exists()
    save(cameras)
    status = service.configure(AppliancePreferences(auto_observe=True))
    assert status.state == "scheduled" and status.camera_saved and not camera.requests
    assert json.loads(service.path.read_text()) == {"auto_observe": True}
    assert service.path.stat().st_mode & 0o777 == 0o600


def test_startup_uses_saved_credentials_and_saved_analysis_configuration(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path)
    save(cameras, audio_enabled=False)
    service.configure(AppliancePreferences(auto_observe=True))
    settings = AnalysisSettings(detector_threshold=0.43, audio_enabled=False)
    atomic_json(tmp_path / "settings.json", settings.model_dump(mode="json"))
    # A fresh service represents a later application startup.
    restored = ApplianceService(service.settings, cameras, camera)
    restored.startup()
    wait_for(restored, "observing")
    joined(restored)
    assert len(camera.requests) == 1
    assert camera.requests[0].password.get_secret_value() == "fixture-secret"
    assert camera.requests[0].config == settings
    assert not camera.requests[0].save_profile
    public = restored.status().model_dump_json()
    assert "fixture-secret" not in public and "fixture-user" not in public and "rtsp://" not in public
    # Turning startup off does not stop an already established live session.
    restored.configure(AppliancePreferences(auto_observe=False))
    assert not camera.stopped


def test_terminal_camera_failure_retries_are_bounded(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path, Camera("failed"))
    save(cameras)
    service.configure(AppliancePreferences(auto_observe=True))
    service.startup()
    wait_for(service, "failed")
    joined(service)
    assert len(camera.requests) == 3
    assert camera.stopped == ["session-1", "session-2", "session-3"]


@pytest.mark.parametrize("action", ["manual_stop", "disable", "shutdown"])
def test_pending_retry_is_cancelled_without_restarting_camera(tmp_path: Path, action: str) -> None:
    service, cameras, camera = setup(tmp_path, Camera("failed"))
    save(cameras)
    service.retry_delay = 30
    service.configure(AppliancePreferences(auto_observe=True))
    service.startup()
    wait_for(service, "waiting")
    if action == "disable":
        service.configure(AppliancePreferences(auto_observe=False))
    elif action == "shutdown":
        service.shutdown()
    else:
        service.suspend()
        camera.stop()
    joined(service)
    assert len(camera.requests) == 1
    assert service.status().state == ("disabled" if action == "disable" else "suspended")


def test_active_manual_analysis_prevents_automatic_start(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path)
    save(cameras)
    service.configure(AppliancePreferences(auto_observe=True))
    camera.analyzer.lock.acquire()
    try:
        service.startup()
        wait_for(service, "suspended")
        joined(service)
        assert not camera.requests
    finally:
        camera.analyzer.lock.release()


def test_missing_profile_and_native_errors_are_safe(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path)
    save(cameras)
    service.configure(AppliancePreferences(auto_observe=True))
    camera.start = Mock(side_effect=ValueError("rtsp://fixture-user:fixture-secret@camera.test"))
    service.startup()
    wait_for(service, "failed")
    joined(service)
    assert "fixture-secret" not in service.status().model_dump_json()
    cameras.delete()
    service.startup()
    wait_for(service, "failed")
    joined(service)
    assert service.status().camera_saved is False
    assert camera.start.call_count == 1


def test_appliance_api_does_not_start_camera_when_enabled_and_stop_suspends_boot(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(data_dir=tmp_path, model_dir=tmp_path / "models"))
    with TestClient(app) as client:
        assert client.get("/api/appliance").json()["auto_observe"] is False
        assert client.put("/api/appliance", json={"auto_observe": True}).status_code == 422
        save(app.state.cameras)
        app.state.live.start = Mock()
        enabled = client.put("/api/appliance", json={"auto_observe": True})
        assert enabled.status_code == 200 and enabled.json()["state"] == "scheduled"
        app.state.live.start.assert_not_called()
        assert client.post("/api/live/stop").status_code == 200
        assert client.get("/api/appliance").json()["state"] == "suspended"
        assert app.state.appliance._cancel.is_set()


def test_status_reports_established_camera_failure_without_auto_restart(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path)
    save(cameras)
    service.configure(AppliancePreferences(auto_observe=True))
    service.startup()
    wait_for(service, "observing")
    joined(service)
    camera.current.status = "failed"
    assert service.status().state == "failed"
    assert len(camera.requests) == 1


def test_camera_can_arrive_after_initial_timeout_without_restart(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path, Camera("connecting"))
    save(cameras)
    service.configure(AppliancePreferences(auto_observe=True))
    service.startup()
    wait_for(service, "waiting")
    assert len(camera.requests) == 1 and not camera.stopped
    camera.current.status = "reconnecting"
    time.sleep(0.03)
    assert len(camera.requests) == 1 and not camera.stopped
    camera.current.status = "live"
    camera.current.metrics["inference_status"] = "loading models"
    wait_for(service, "observing")
    joined(service)
    assert len(camera.requests) == 1 and not camera.stopped


def test_manual_analysis_waits_for_pending_auto_camera_cleanup(tmp_path: Path) -> None:
    service, cameras, camera = setup(tmp_path, Camera("connecting"))
    save(cameras)
    service.configure(AppliancePreferences(auto_observe=True))
    service.startup()
    wait_for(service, "waiting")
    service.suspend(wait=True)
    assert service._worker and not service._worker.is_alive()
    assert camera.stopped == ["session-1"]
    assert service.status().state == "suspended"


def test_disabling_during_live_transition_preserves_camera_and_reenable_schedules(
    tmp_path: Path,
) -> None:
    service, cameras, camera = setup(tmp_path, Camera("connecting"))
    save(cameras)
    service.configure(AppliancePreferences(auto_observe=True))
    service.startup()
    wait_for(service, "waiting")
    # Hold state inspection so the preference changes after the stream turns
    # live but before the worker acknowledges that transition.
    entered, release = threading.Event(), threading.Event()
    original = camera.state

    def held_state():
        entered.set()
        assert release.wait(2)
        return original()

    camera.state = held_state
    assert entered.wait(2)
    camera.current.status = "live"
    service.configure(AppliancePreferences(auto_observe=False))
    enabled = service.configure(AppliancePreferences(auto_observe=True))
    assert enabled.auto_observe and enabled.state == "scheduled"
    release.set()
    joined(service)
    assert not camera.stopped
    assert service.status().state == "scheduled"


@pytest.mark.parametrize("audio_enabled", [True, False])
def test_startup_honors_camera_audio_preference_over_global_setting(
    tmp_path: Path, audio_enabled: bool,
) -> None:
    service, cameras, camera = setup(tmp_path)
    save(cameras, audio_enabled=audio_enabled)
    atomic_json(tmp_path / "settings.json", AnalysisSettings(
        audio_enabled=not audio_enabled
    ).model_dump(mode="json"))
    service.configure(AppliancePreferences(auto_observe=True))
    service.startup()
    wait_for(service, "observing")
    joined(service)
    assert camera.requests[0].config.audio_enabled == audio_enabled
