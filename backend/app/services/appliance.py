"""Opt-in startup and supervised observation using the private saved camera profile."""

import threading
import time

from pydantic import BaseModel, ConfigDict, SecretStr

from app.config import Settings
from app.schemas_live import LiveStart
from app.services.configuration import load_analysis_settings
from app.services.live import LiveService
from app.storage.cameras import CameraStore
from app.taxonomy.cache import atomic_json


class AppliancePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    auto_observe: bool = False


class ApplianceStatus(BaseModel):
    auto_observe: bool
    camera_saved: bool
    state: str
    message: str


class ApplianceService:
    def __init__(
        self, settings: Settings, cameras: CameraStore, live: LiveService,
        *, attempts: int = 3, connect_timeout: float = 30, retry_delay: float = 5,
        retry_max_delay: float = 300, stable_seconds: float = 60,
    ):
        self.settings, self.cameras, self.live = settings, cameras, live
        self.path = settings.data_dir / "private" / "appliance.json"
        self.attempts, self.connect_timeout, self.retry_delay = attempts, connect_timeout, retry_delay
        self.retry_max_delay, self.stable_seconds = retry_max_delay, stable_seconds
        self._mutex = threading.RLock()
        self._cancel = threading.Event()
        self._preserve_live_on_cancel = False
        self._worker: threading.Thread | None = None
        self._owned_session: str | None = None
        self._observing_session: str | None = None
        self._enabled = False
        self._state = "disabled"
        self._message = "Automatic observation is off."
        if self.path.exists():
            try:
                self._enabled = AppliancePreferences.model_validate_json(
                    self.path.read_text()
                ).auto_observe
                if self._enabled:
                    self._state = "scheduled"
                    self._message = "The saved camera will start when FALCON next starts."
            except (OSError, ValueError):
                self._message = "Automatic observation settings could not be read; startup is disabled."

    def status(self) -> ApplianceStatus:
        with self._mutex:
            if self._state == "observing":
                current = self.live.state()
                if current.session_id != self._observing_session:
                    self._state, self._message = "suspended", "A different camera session took over."
                elif current.status in {"failed", "stopped", "idle"} and not (
                    self._worker and self._worker.is_alive()
                ):
                    self._state, self._message = "failed", "The automatic camera session stopped. Check Sources before starting it again."
            return ApplianceStatus(
                auto_observe=self._enabled,
                camera_saved=self.cameras.public().saved,
                state=self._state,
                message=self._message,
            )

    def configure(self, preferences: AppliancePreferences) -> ApplianceStatus:
        if preferences.auto_observe and not self.cameras.public().saved:
            raise ValueError("Save a camera profile before enabling automatic observation.")
        with self._mutex:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path.parent.chmod(0o700)
            atomic_json(self.path, preferences.model_dump())
            self.path.chmod(0o600)
            self._enabled = preferences.auto_observe
            if not self._enabled:
                self._preserve_live_on_cancel = True
                self._cancel.set()
                self._state = "disabled"
                self._message = "Automatic observation is off. Any current observation can be stopped in Sources."
            elif self._cancel.is_set() or not self._worker or not self._worker.is_alive():
                self._state = "scheduled"
                self._message = "The saved camera will start when FALCON next starts."
        return self.status()

    def startup(self) -> None:
        with self._mutex:
            if not self._enabled or self._worker and self._worker.is_alive():
                return
            self._cancel = threading.Event()
            self._preserve_live_on_cancel = False
            self._state = "starting"
            self._message = "Preparing the saved camera for automatic observation."
            self._worker = threading.Thread(
                target=self._observe, daemon=True, name="falcon-auto-observe"
            )
            self._worker.start()

    def suspend(self, wait: bool = False) -> None:
        """Explicit user actions take priority for the remainder of this startup."""
        with self._mutex:
            self._preserve_live_on_cancel = False
            self._cancel.set()
            if self._enabled:
                self._state = "suspended"
                self._message = "Automatic observation is suspended until the next FALCON start."
        worker = self._worker
        if wait and worker and worker is not threading.current_thread():
            worker.join(timeout=20)

    def shutdown(self) -> None:
        self.suspend()
        worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=5)

    def _state_change(self, state: str, message: str) -> None:
        with self._mutex:
            if not self._cancel.is_set():
                self._state, self._message = state, message

    def _stop_owned_attempt(self, preserve_live: bool = False) -> None:
        # Never stop a manual session that replaced this startup attempt.
        session = self._owned_session
        self._owned_session = None
        if session:
            current = self.live.state()
            established = self._observing_session == session
            if current.session_id == session and not (
                preserve_live and (current.status == "live" or established)
            ):
                self.live.stop(wait=True)
        self._observing_session = None

    def _retry_seconds(self, failures: int) -> float:
        # A stream that briefly connects then crashes must not reset the delay.
        # Clamp even programmatic overrides so recovery never busy-spins.
        maximum = max(0.01, self.retry_max_delay)
        return min(maximum, max(0.01, self.retry_delay) * 2 ** min(max(failures - 1, 0), 16))

    def _observe(self) -> None:
        ever_connected = False
        failures = 0
        try:
            while not self._cancel.is_set():
                if self.live.analyzer.lock.locked() or self.live.state().status in {
                    "connecting", "live", "reconnecting", "stopping",
                }:
                    self._state_change(
                        "suspended", "The analysis engine is in use. Automatic startup was skipped."
                    )
                    return
                profile = self.cameras.public()
                if not profile.saved:
                    self._state_change("failed", "The saved camera profile is unavailable.")
                    return
                try:
                    request = LiveStart(
                        name=profile.name, url=SecretStr(profile.url),
                        username=SecretStr(profile.username) if profile.username else None,
                        config=load_analysis_settings(self.settings).model_copy(
                            update={"audio_enabled": profile.audio_enabled}
                        ),
                        use_saved_credentials=True, save_profile=False,
                    )
                    request = self.cameras.resolve(request)
                except Exception:
                    self._state_change(
                        "failed", "The saved camera or analysis settings could not be loaded. Check them in System and Sources."
                    )
                    return
                self._state_change(
                    "starting", "Reconnecting the saved camera after an analysis failure."
                    if ever_connected else f"Connecting the saved camera (attempt {failures + 1}/{self.attempts})."
                )
                if self._cancel.is_set():
                    return
                try:
                    started = self.live.start(request)
                except RuntimeError:
                    self._state_change(
                        "suspended", "The analysis engine is in use. Automatic startup was skipped."
                    )
                    return
                except Exception:
                    self._state_change(
                        "failed", "Automatic observation could not start. Check the camera and species library."
                    )
                    return
                self._owned_session = started.session_id
                deadline = time.monotonic() + self.connect_timeout
                waiting = False
                stable_since: float | None = None
                while not self._cancel.is_set():
                    state = self.live.state()
                    if state.session_id != self._owned_session:
                        self._owned_session = None
                        self._state_change("suspended", "A different camera session took over.")
                        return
                    if state.status == "live":
                        ever_connected = True
                        self._observing_session = self._owned_session
                        self._state_change("observing", "Automatic observation is running.")
                        if stable_since is None:
                            stable_since = time.monotonic()
                        elif time.monotonic() - stable_since >= self.stable_seconds:
                            failures = 0
                    else:
                        stable_since = None
                    if state.status == "failed":
                        if "authentication failed" in (state.error or "").casefold():
                            self._state_change(
                                "failed", "Camera authentication failed. Check its saved local account in Sources; automatic retries have stopped."
                            )
                            return
                        break
                    if state.status in {"stopping", "stopped", "idle"}:
                        # A stop is a control action, not a recoverable crash.
                        self._state_change("suspended", "The automatic camera session was stopped.")
                        return
                    if state.status == "reconnecting" and self._observing_session:
                        self._state_change(
                            "waiting", "Camera connection interrupted. The current session is reconnecting."
                        )
                    elif state.status != "live" and not waiting and time.monotonic() >= deadline:
                        waiting = True
                        self._state_change(
                            "waiting", "Waiting for the saved camera. Connection retries continue automatically."
                        )
                    self._cancel.wait(0.25)
                if self._cancel.is_set():
                    return
                self._stop_owned_attempt()
                failures += 1
                if not ever_connected and failures >= self.attempts:
                    self._state_change(
                        "failed", f"The camera did not become available after {self.attempts} attempts. Start observing manually when it is ready."
                    )
                    return
                delay = self._retry_seconds(failures)
                self._state_change(
                    "waiting", f"Camera analysis stopped. Automatic recovery will retry in {delay:g} seconds."
                )
                self._cancel.wait(delay)
        except Exception:
            # Native camera errors can contain credentials. Expose no exception text.
            self._state_change("failed", "Automatic observation stopped. Check the saved camera.")
        finally:
            self._stop_owned_attempt(preserve_live=self._preserve_live_on_cancel)
