"""The running sensor node: detection, stream supervision, sampling and control."""

import logging
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from falcon_node import VERSION, media, system
from falcon_node.auth import Verifier, rtsp_password
from falcon_node.bme280 import BME280
from falcon_node.config import COMPONENTS, NodeConfig, NodeState
from falcon_node.sensors import RainPlate, Sampler, Spool, detect_climate

log = logging.getLogger("falcon-node")


class StreamSupervisor(threading.Thread):
    """Keeps MediaMTX and the capture pipeline running as the saved state asks."""

    def __init__(self, agent: "Agent"):
        super().__init__(daemon=True, name="falcon-node-stream")
        self.agent = agent
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.pipeline: media.Pipeline | None = None
        self.restart_requested = False
        self.failures = 0
        self.restarts = 0
        self.retry_at = 0.0
        self.since: str | None = None
        self.last_error: str | None = None

    def sources(self) -> tuple[media.Camera | None, media.Microphone | None]:
        agent = self.agent
        camera = agent.camera if agent.state.components["camera"] else None
        microphone = agent.microphone if agent.state.components["microphone"] else None
        return camera, microphone

    def desired(self) -> bool:
        camera, microphone = self.sources()
        return self.agent.state.stream_enabled and (camera is not None or microphone is not None)

    def restart(self) -> None:
        with self.lock:
            self.restart_requested = True
            self.failures, self.retry_at = 0, 0.0
        self.wake.set()

    def _start(self) -> None:
        agent = self.agent
        camera, microphone = self.sources()
        if microphone is not None:
            media.apply_mixer(microphone, agent.state.microphone, Path(agent.config.mixer_state))
        commands = media.build_pipeline(
            camera, agent.state.camera, microphone, agent.state.microphone,
            f"rtsp://127.0.0.1:{agent.config.rtsp_port}/{media.STREAM_PATH}", agent.config.ffmpeg,
        )
        self.pipeline = media.Pipeline(commands)
        self.since = datetime.now(UTC).isoformat()
        log.info("Stream started (%s)", ", ".join(
            part for part in (camera and camera.description, microphone and microphone.description) if part
        ))

    def _stop_pipeline(self) -> None:
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None
            self.since = None

    def step(self) -> None:
        agent = self.agent
        try:
            agent.media_server.ensure_running()
        except OSError as exc:
            self.last_error = f"Stream server could not start ({type(exc).__name__}). Is MediaMTX installed?"
            return
        with self.lock:
            restart, self.restart_requested = self.restart_requested, False
        if restart or not self.desired():
            self._stop_pipeline()
        if not self.desired():
            self.failures = 0
            return
        if self.pipeline is not None and self.pipeline.alive():
            if time.monotonic() - self.pipeline.started > 60:
                self.failures = 0
            return
        if self.pipeline is not None:
            errors = list(self.pipeline.errors)
            self.last_error = errors[-1] if errors else "The capture process stopped."
            log.warning("Stream stopped: %s", self.last_error)
            self._stop_pipeline()
            self.failures += 1
            self.restarts += 1
            self.retry_at = time.monotonic() + min(60.0, 2.0 ** min(self.failures, 6))
        if time.monotonic() < self.retry_at:
            return
        try:
            self._start()
        except OSError as exc:
            self.last_error = f"Capture could not start ({type(exc).__name__}). Check that ffmpeg is installed."
            self.failures += 1
            self.retry_at = time.monotonic() + min(60.0, 2.0 ** min(self.failures, 6))

    def status(self) -> dict[str, Any]:
        camera, microphone = self.sources()
        path = self.agent.media_server.path_status()
        alive = self.pipeline is not None and self.pipeline.alive()
        if not self.agent.state.stream_enabled:
            state = "off"
        elif camera is None and microphone is None:
            state = "no sources"
        elif alive and (path is None or path["ready"]):
            state = "streaming"
        elif alive:
            state = "starting"
        else:
            state = "retrying" if self.failures else "starting"
        return {
            "state": state, "since": self.since if alive else None, "restarts": self.restarts,
            "error": self.last_error if state in {"retrying", "starting", "no sources"} and self.last_error else None,
            "rtsp_port": self.agent.config.rtsp_port, "rtsp_path": media.STREAM_PATH,
            "video": camera is not None, "audio": microphone is not None or bool(camera and camera.kind == "rtsp"),
            "tracks": path["tracks"] if path else [], "readers": path["readers"] if path else 0,
        }

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.step()
            except Exception:
                log.exception("Stream supervision failed")
            self.wake.wait(1.0)
            self.wake.clear()
        self._stop_pipeline()
        self.agent.media_server.stop()


class Agent:
    def __init__(self, config: NodeConfig, *, detect: bool = True):
        self.config = config
        self.started = time.monotonic()
        config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state = NodeState(config.state_dir / "state.json")
        self.boot = system.boot_id()
        self._clock_lock = threading.Lock()
        self._ntp: tuple[float, bool | None] = (0.0, None)
        self.clock_adopted_at: str | None = None
        self.last_contact: float | None = None
        self.spool = Spool(config.state_dir / "spool.sqlite3")
        self.verifier = Verifier(config.pairing_key, synchronized=self.clock_trusted)
        self.media_server = media.MediaServer(
            config.mediamtx, config.state_dir / "mediamtx.yml", config.rtsp_port,
            config.mediamtx_api_port, rtsp_password(config.pairing_key),
        )
        self.camera: media.Camera | None = None
        self.microphone: media.Microphone | None = None
        self.climate: tuple[int, str] | None = None
        self.rain: RainPlate | None = None
        if detect:
            self.detect()
        self.sampler = self._sampler()
        self.stream = StreamSupervisor(self)

    # --- hardware ---
    def detect(self) -> None:
        config = self.config
        self.camera = media.detect_camera(config.camera)
        self.microphone = media.detect_microphone(config.microphone, config.microphone_channels)
        self.climate = detect_climate(config.climate)
        rain = config.rain.strip().lower()
        gpio = None
        if rain.startswith("gpio:"):
            gpio = int(rain.split(":", 1)[1])
        elif rain == "auto" and system.is_raspberry_pi() and shutil.which("pinctrl"):
            gpio = 17
        self.rain = RainPlate(gpio, config.rain_wet_when_low) if gpio is not None else None
        log.info(
            "Detected camera=%s microphone=%s climate=%s rain=%s",
            self.camera.description if self.camera else "none",
            self.microphone.description if self.microphone else "none",
            self.climate[1] if self.climate else "none", f"GPIO{gpio}" if gpio is not None else "none",
        )

    def _sampler(self) -> Sampler:
        address = self.climate[0] if self.climate else None
        factory = (lambda: BME280(1, address)) if address is not None else None
        return Sampler(
            self.config.node_id, self.spool, self.config.reading_interval, factory, self.rain,
            lambda name: self.state.components[name], self.clock_synchronized, self.boot,
        )

    def rescan(self) -> None:
        self.detect()
        old = self.sampler
        old.stop_event.set()
        self.sampler = self._sampler()
        self.sampler.start()
        self.stream.restart()

    # --- clock ---
    def ntp_synchronized(self) -> bool | None:
        checked, value = self._ntp
        if time.monotonic() - checked > 30:
            value = system.ntp_synchronized()
            self._ntp = (time.monotonic(), value)
        return value

    def clock_trusted(self) -> bool:
        return self.ntp_synchronized() is True or self.clock_adopted_at is not None

    def clock_synchronized(self) -> bool | None:
        ntp = self.ntp_synchronized()
        return True if ntp is True or self.clock_adopted_at else ntp

    def caller_time(self, ts: float) -> None:
        """Adopt the inference node's clock when this node has no synchronized time."""
        self.last_contact = time.monotonic()
        if self.ntp_synchronized() is True:
            return
        with self._clock_lock:
            delta = ts - time.time()
            if abs(delta) <= 2:
                if self.clock_adopted_at is None:
                    self.clock_adopted_at = datetime.now(UTC).isoformat()
                return
            if system.set_clock(ts):
                self.clock_adopted_at = datetime.now(UTC).isoformat()
                shifted = self.spool.correct_clock(self.boot, delta)
                log.info("Clock set from the inference node (%+.1f s); %d queued readings corrected", delta, shifted)

    # --- control ---
    def info(self) -> dict[str, Any]:
        return {
            "software": "falcon-node", "version": VERSION, "api": 1,
            "node_id": self.config.node_id, "name": self.config.name,
            "components": {
                "camera": self.camera is not None, "microphone": self.microphone is not None,
                "climate": self.climate is not None, "rain": self.rain is not None,
            },
        }

    def status(self) -> dict[str, Any]:
        sampler = self.sampler.status
        components = {
            "camera": {
                "present": self.camera is not None, "enabled": self.state.components["camera"],
                "kind": self.camera.kind if self.camera else None,
                "description": self.camera.description if self.camera else None,
                "controls": media.CONTROLS.get(self.camera.kind, []) if self.camera else [],
                "resolutions": media.RESOLUTIONS.get(self.camera.kind, []) if self.camera else [],
            },
            "microphone": {
                "present": self.microphone is not None, "enabled": self.state.components["microphone"],
                "description": self.microphone.description if self.microphone else None,
            },
            "climate": {
                "present": self.climate is not None, "enabled": self.state.components["climate"],
                "description": self.climate[1] if self.climate else None, **sampler["climate"],
            },
            "rain": {
                "present": self.rain is not None, "enabled": self.state.components["rain"],
                "description": f"Rain plate on GPIO{self.rain.gpio}" if self.rain else None, **sampler["rain"],
            },
        }
        components["climate"]["present"] = self.climate is not None
        components["rain"]["present"] = self.rain is not None
        return {
            **self.info(),
            "time": datetime.now(UTC).isoformat(),
            "clock": {
                "synchronized": self.clock_synchronized(),
                "source": "ntp" if self.ntp_synchronized() else "falcon" if self.clock_adopted_at else "none",
                "adopted_at": self.clock_adopted_at,
            },
            "agent_uptime_seconds": round(time.monotonic() - self.started),
            "system": system.health(self.config.state_dir),
            "stream": self.stream.status(),
            "components": components,
            "camera_settings": self.state.camera.public(),
            "microphone_settings": {
                "audio_channel": self.state.microphone.audio_channel,
                "audio_gain_percent": self.state.microphone.audio_gain_percent,
            },
            "last_reading": self.sampler.last_reading,
            "readings_queued": len(self.spool),
            "reading_interval_seconds": self.config.reading_interval,
        }

    def set_stream(self, action: str) -> None:
        if action not in {"start", "stop", "restart"}:
            raise ValueError("action must be start, stop or restart")
        if action == "restart":
            self.state.stream_enabled = True
            self.stream.restart()
        else:
            self.state.stream_enabled = action == "start"
        self.state.save()
        self.stream.wake.set()

    def set_component(self, name: str, enabled: bool) -> None:
        if name not in COMPONENTS:
            raise KeyError(name)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be true or false")
        self.state.components[name] = enabled
        self.state.save()
        if name in {"camera", "microphone"}:
            self.stream.restart()

    def update_camera(self, changes: dict[str, Any]) -> None:
        if self.camera is None:
            raise ValueError("No camera is connected to this node")
        allowed = set(media.CONTROLS.get(self.camera.kind, []))
        unsupported = sorted(set(changes) - allowed)
        if unsupported:
            raise ValueError(f"This camera does not support: {', '.join(unsupported)}")
        self.state.camera = self.state.camera.updated(changes, self.camera.kind)
        self.state.save()
        self.stream.restart()

    def update_microphone(self, changes: dict[str, Any]) -> None:
        self.state.microphone = self.state.microphone.updated(changes)
        self.state.save()
        self.stream.restart()

    def pull(self, ack: list[str], limit: int) -> dict[str, Any]:
        if not isinstance(ack, list) or not all(isinstance(item, str) and len(item) <= 200 for item in ack):
            raise ValueError("ack must be a list of reading IDs")
        if len(ack) > 1000:
            raise ValueError("Acknowledge at most 1000 readings at a time")
        removed = self.spool.remove(ack)
        readings = self.spool.oldest(max(1, min(500, limit)))
        return {"readings": readings, "acknowledged": removed, "queued": len(self.spool)}

    def system_action(self, action: str) -> None:
        if action == "rescan":
            self.rescan()
        elif action in {"reboot", "shutdown"}:
            system.power(action)
        else:
            raise ValueError("action must be rescan, reboot or shutdown")

    # --- lifecycle ---
    def start(self) -> None:
        self.sampler.start()
        self.stream.start()

    def stop(self) -> None:
        self.sampler.stop_event.set()
        self.stream.stop_event.set()
        self.stream.wake.set()
        self.stream.join(timeout=10)
