# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""The running sensor node: detection, stream supervision, sampling and control."""

import logging
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from falcon_node import VERSION, extras, media, system, thermal
from falcon_node.auth import Verifier, rtsp_password
from falcon_node.bme280 import BME280
from falcon_node.config import COMPONENTS, NodeConfig, NodeState
from falcon_node.sensors import RainPlate, Sampler, Spool, detect_climate

log = logging.getLogger("falcon-node")


def retry_delay(failures: int) -> float:
    """Seconds before restarting a stopped camera stream: 2 s for the first three tries
    in a row (a camera that blinks out at dawn is back almost at once), then doubling to
    a minute for a camera that is really gone."""
    return 2.0 if failures <= 3 else min(60.0, 2.0 ** min(failures - 2, 6))


def microphone_retry_delay(failures: int) -> float:
    """Gentler for the microphone: the audio HAT can go silent after quick reopenings
    (and then needs a reboot), so 5, 10, 20, 40, 60 s."""
    return min(60.0, 5.0 * 2.0 ** max(0, failures - 1))


MIC_MIN_GAP = 5.0  # never two microphone reopenings within this many seconds


class Channel:
    """One supervised capture process: the camera, or the microphone (14 Nov 2026:
    separate, so a camera dropout at dawn never reopens the microphone and the reverse)."""

    def __init__(self, name: str, delay: Any, min_gap: float = 0.0):
        self.name, self.delay, self.min_gap = name, delay, min_gap
        self.pipeline: media.Pipeline | None = None
        self.restart_requested = False
        self.failures = 0
        self.restarts = 0
        self.retry_at = 0.0
        self.started_at = -1e9
        self.since: str | None = None
        self.last_error: str | None = None

    def alive(self) -> bool:
        return self.pipeline is not None and self.pipeline.alive()

    def stop(self) -> None:
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None
            self.since = None


class StreamSupervisor(threading.Thread):
    """Keeps MediaMTX and the capture pipeline running as the saved state asks."""

    def __init__(self, agent: "Agent"):
        super().__init__(daemon=True, name="falcon-node-stream")
        self.agent = agent
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.camera_channel = Channel("camera", retry_delay)
        self.microphone_channel = Channel("microphone", microphone_retry_delay, MIC_MIN_GAP)
        self.channels = (self.camera_channel, self.microphone_channel)
        # Night picture (USB webcams): greyscale while the IR lights make it magenta.
        self.night_dark = False
        self.colour_cast: float | None = None
        self._night_streak = 0
        self._night_checked = 0.0

    def probe_path(self) -> str:
        # Rewritten with every frame, so it must not live on the SD card: /tmp is the
        # service's private tmpfs (PrivateTmp=yes; Debian 13 keeps /tmp in RAM).
        return "/tmp/falcon-node-colour-probe.ppm"

    def night_picture(self, camera: media.Camera | None) -> tuple[bool, str | None]:
        """(greyscale now?, colour-probe file or None) for the camera's Night picture setting."""
        mode = self.agent.state.camera.night_mode
        if camera is None or camera.kind == "rtsp":
            return False, None
        if self.passthrough(camera):
            return False, None  # FALCON applies the night picture on the PC
        probe = self.probe_path() if camera.kind == "v4l2" and mode == "auto" else None
        return mode == "mono" or (mode == "auto" and self.night_dark), probe

    def check_night(self) -> None:
        """Switch to greyscale when the colour probe turns magenta, back when it clears.
        Three readings in a row (about 30 s) must agree, so dusk does not flicker."""
        now = time.monotonic()
        if now - self._night_checked < media.PROBE_SECONDS:
            return
        self._night_checked = now
        camera, _ = self.sources()
        if camera is None or camera.kind != "v4l2" or self.agent.state.camera.night_mode != "auto":
            return
        if not self.camera_channel.alive():
            return
        try:
            cast = media.colour_cast(Path(self.probe_path()).read_bytes())
        except OSError:
            return
        if cast is None:
            return
        self.colour_cast = cast
        dark = cast > media.NIGHT_ON if not self.night_dark else cast >= media.NIGHT_OFF
        self._night_streak = self._night_streak + 1 if dark != self.night_dark else 0
        if self._night_streak >= 3:
            self.night_dark, self._night_streak = dark, 0
            log.info("Night picture: %s (colour cast %.0f)", "greyscale" if dark else "colour", cast)
            self.restart("camera")

    def sources(self) -> tuple[media.Camera | None, media.Microphone | None]:
        agent = self.agent
        cooling = agent.thermal.level >= thermal.CAMERA_PAUSED
        camera = agent.camera if agent.state.components["camera"] and not cooling else None
        microphone = agent.microphone if agent.state.components["microphone"] else None
        return camera, microphone

    def desired(self) -> bool:
        if self.agent.thermal.level >= thermal.STREAM_STOPPED:
            return False
        camera, microphone = self.sources()
        return self.agent.state.stream_enabled and (camera is not None or microphone is not None)

    # Kept for callers that predate the split (thermal guard, tests): the camera's.
    @property
    def pipeline(self) -> media.Pipeline | None:
        return self.camera_channel.pipeline

    @pipeline.setter
    def pipeline(self, value: media.Pipeline | None) -> None:
        self.camera_channel.pipeline = value

    @property
    def restarts(self) -> int:
        return sum(channel.restarts for channel in self.channels)

    @property
    def last_error(self) -> str | None:
        return self.camera_channel.last_error or self.microphone_channel.last_error

    def restart(self, which: str = "all") -> None:
        """Restart "camera", "microphone" or "all" capture processes."""
        with self.lock:
            for channel in self.channels:
                if which in {"all", channel.name}:
                    channel.restart_requested = True
                    channel.failures, channel.retry_at = 0, 0.0
        self.wake.set()

    def separate_microphone(self) -> bool:
        """The microphone has its own process and path (unless only an IP camera's own
        sound is relayed, which stays with its picture)."""
        _, microphone = self.sources()
        return microphone is not None

    def _start(self, channel: Channel) -> None:
        agent = self.agent
        camera, microphone = self.sources()
        base = f"rtsp://127.0.0.1:{agent.config.rtsp_port}/"
        if channel is self.microphone_channel:
            if microphone is None:
                return
            media.apply_mixer(microphone, agent.state.microphone, Path(agent.config.mixer_state))
            commands = media.build_microphone_pipeline(
                microphone, agent.state.microphone, base + media.AUDIO_PATH, agent.config.ffmpeg,
            )
            description = microphone.description
        else:
            if camera is None:
                return
            media.apply_camera_controls(camera, agent.config.camera_controls)
            if camera.kind == "v4l2" and agent.state.picture:
                try:
                    media.set_picture_controls(camera, agent.state.picture)
                except ValueError as exc:
                    log.warning("Saved picture controls not applied: %s", exc)
            mono, probe = self.night_picture(camera)
            commands = media.build_pipeline(
                camera, agent.state.camera, None, agent.state.microphone,
                base + media.STREAM_PATH, agent.config.ffmpeg, mono=mono, probe_path=probe,
            )
            description = camera.description
        channel.pipeline = media.Pipeline(commands)
        channel.started_at = time.monotonic()
        channel.since = datetime.now(UTC).isoformat()
        log.info("Stream started: %s (%s)", channel.name, description)

    def _stop_pipeline(self) -> None:
        for channel in self.channels:
            channel.stop()

    def _wanted(self, channel: Channel) -> bool:
        camera, microphone = self.sources()
        return self.desired() and (camera if channel is self.camera_channel else microphone) is not None

    def step(self) -> None:
        agent = self.agent
        try:
            agent.media_server.ensure_running()
        except OSError as exc:
            self.camera_channel.last_error = (
                f"Stream server could not start ({type(exc).__name__}). Is MediaMTX installed?"
            )
            return
        for channel in self.channels:
            self._step(channel)

    def _step(self, channel: Channel) -> None:
        with self.lock:
            restart, channel.restart_requested = channel.restart_requested, False
        wanted = self._wanted(channel)
        if restart or not wanted:
            channel.stop()
        if not wanted:
            channel.failures = 0
            return
        if channel.alive():
            if channel.pipeline is not None and time.monotonic() - channel.pipeline.started > 60:
                channel.failures = 0
            return
        now = time.monotonic()
        if channel.pipeline is not None:
            errors = list(channel.pipeline.errors)
            channel.last_error = errors[-1] if errors else "The capture process stopped."
            # Why it stopped: which process, its exit code and its last messages (the
            # camera drops out at dawn and dusk while its day/night filter switches).
            for line in channel.pipeline.exit_report():
                log.warning("Stream stopped (%s): %s", channel.name, line)
            channel.stop()
            channel.failures += 1
            channel.restarts += 1
            channel.retry_at = now + channel.delay(channel.failures)
        if now < channel.retry_at or now - channel.started_at < channel.min_gap:
            return
        try:
            self._start(channel)
        except OSError as exc:
            channel.last_error = f"Capture could not start ({type(exc).__name__}). Check that ffmpeg is installed."
            channel.failures += 1
            channel.retry_at = time.monotonic() + channel.delay(channel.failures)

    def status(self) -> dict[str, Any]:
        camera, microphone = self.sources()
        path = self.agent.media_server.path_status()
        audio_path = self.agent.media_server.path_status(media.AUDIO_PATH) if microphone is not None else None
        channels = [c for c in self.channels if self._wanted(c)]
        alive = bool(channels) and all(c.alive() for c in channels)
        ready = (camera is None or path is None or path["ready"]) and (
            microphone is None or audio_path is None or audio_path["ready"]
        )
        if not self.agent.state.stream_enabled:
            state = "off"
        elif self.agent.thermal.level >= thermal.STREAM_STOPPED:
            state = "too hot"
        elif camera is None and microphone is None:
            state = "no sources"
        elif alive and ready:
            state = "streaming"
        elif alive:
            state = "starting"
        else:
            state = "retrying" if any(c.failures for c in channels) else "starting"
        since = max((c.since for c in channels if c.since), default=None)
        tracks = (path["tracks"] if path and camera is not None else []) + (audio_path["tracks"] if audio_path else [])
        return {
            "state": state, "since": since if alive else None, "restarts": self.restarts,
            "error": self.last_error if state in {"retrying", "starting", "no sources"} and self.last_error else None,
            "rtsp_port": self.agent.config.rtsp_port, "rtsp_path": media.STREAM_PATH,
            # The microphone on its own path (FALCON reads sound from here when present).
            "audio_path": media.AUDIO_PATH if microphone is not None else None,
            "channels": {c.name: {"alive": c.alive(), "restarts": c.restarts} for c in self.channels},
            "video": camera is not None, "audio": microphone is not None or bool(camera and camera.kind == "rtsp"),
            "tracks": tracks, "readers": (path["readers"] if path else 0) + (audio_path["readers"] if audio_path else 0),
            "night": {
                "mode": self.agent.state.camera.night_mode,
                "greyscale": self.night_picture(camera)[0],
                "colour_cast": round(self.colour_cast, 1) if self.colour_cast is not None else None,
                # In pass-through the node sends colour frames; FALCON applies the mode.
                "applied_by": "falcon" if self.passthrough(camera) else "node",
            },
            "video_codec": "mjpeg" if self.passthrough(camera) else ("h264" if camera else None),
        }

    def passthrough(self, camera: media.Camera | None) -> bool:
        """The webcam's MJPEG frames go out untouched (decoded by FALCON on the PC)."""
        return bool(
            camera and camera.kind == "v4l2" and camera.input_format == "mjpeg"
            and self.agent.state.camera.video_codec == "mjpeg"
        )

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.step()
                self.check_night()
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
        self.thermal = thermal.ThermalGuard(
            config.thermal_pause_c, config.thermal_stop_c, config.thermal_resume_c,
            lambda level: self.stream.restart(),
        )
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
                "resolutions": media.resolutions(self.camera),
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
            "thermal": self.thermal.status(),
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
        if action not in {"start", "stop", "restart", "restart_microphone", "restart_camera"}:
            raise ValueError("action must be start, stop, restart, restart_microphone or restart_camera")
        if action.startswith("restart"):
            self.state.stream_enabled = True
            # FALCON's sound self-heal restarts only the microphone.
            self.stream.restart({"restart": "all", "restart_microphone": "microphone",
                                 "restart_camera": "camera"}[action])
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
            self.stream.restart(name)

    def update_camera(self, changes: dict[str, Any]) -> None:
        if self.camera is None:
            raise ValueError("No camera is connected to this node")
        allowed = set(media.CONTROLS.get(self.camera.kind, []))
        unsupported = sorted(set(changes) - allowed)
        if unsupported:
            raise ValueError(f"This camera does not support: {', '.join(unsupported)}")
        if "resolution" in changes and changes["resolution"] not in media.resolutions(self.camera):
            raise ValueError("This camera does not offer that resolution")
        self.state.camera = self.state.camera.updated(changes, self.camera.kind)
        self.state.save()
        self.stream.restart("camera")

    def camera_picture(self) -> dict[str, Any]:
        """The webcam's adjustable picture controls with their current values."""
        return {"controls": media.picture_controls(self.camera), "saved": dict(self.state.picture)}

    def update_camera_picture(self, data: dict[str, Any]) -> dict[str, Any]:
        """Change picture controls live (no stream restart) and remember them.
        {"values": {name: number}} or {"reset": true} for the camera's defaults."""
        if self.camera is None or self.camera.kind != "v4l2":
            raise ValueError("Picture controls are available for USB webcams only")
        if data.get("reset") is True:
            defaults = {item["name"]: item["default"] for item in media.picture_controls(self.camera)}
            media.set_picture_controls(self.camera, defaults)
            self.state.picture = {}
        else:
            values = data.get("values")
            if not isinstance(values, dict) or not values or len(values) > 20:
                raise ValueError("Send values as an object of control names and numbers")
            media.set_picture_controls(self.camera, values)
            self.state.picture = {**self.state.picture, **{str(k): int(v) for k, v in values.items()}}
        self.state.save()
        return self.camera_picture()

    def update_microphone(self, changes: dict[str, Any]) -> None:
        self.state.microphone = self.state.microphone.updated(changes)
        self.state.save()
        gain = self.state.microphone.audio_gain_percent
        # A gain change alone applies live, so someone listening hears it while
        # dragging; restarting the stream would cut the sound (and can stall the HAT).
        if set(changes) == {"audio_gain_percent"} and self.microphone is not None and gain is not None:
            if media.apply_gain(self.microphone, gain):
                return
        self.stream.restart("microphone")

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
        self.thermal.start()
        self.stream.start()
        threading.Thread(target=self._start_extras, daemon=True, name="falcon-node-extras").start()

    def _start_extras(self) -> None:
        # Extras chosen to "start at boot". Never switched off here: a node restart
        # must not drop a phone that is using the hotspot.
        for name, wanted in self.state.extras_at_boot.items():
            if wanted and name in extras.EXTRAS:
                try:
                    if not extras.state(name)["on"]:
                        extras.switch(name, True)
                except (ValueError, KeyError) as exc:
                    log.warning("%s not started at boot: %s", name, exc)

    def extras_status(self) -> dict[str, Any]:
        """Optional extras (hotspot, bluetooth), with heat and power facts for the UI."""
        items = []
        for name, meta in extras.EXTRAS.items():
            items.append({
                "name": name, **meta, **extras.state(name),
                "at_boot": self.state.extras_at_boot.get(name, False),
            })
        return {
            "extras": items, "thermal": self.thermal.status(),
            "cpu_temperature_c": thermal.cpu_temperature(), "power": system.throttling(),
        }

    def update_extra(self, data: dict[str, Any]) -> dict[str, Any]:
        """{"name": "hotspot", "on": true|false, "at_boot": true|false} (either or both)."""
        name = data.get("name")
        if name not in extras.EXTRAS:
            raise ValueError("Choose hotspot or bluetooth")
        on, at_boot = data.get("on"), data.get("at_boot")
        if on is None and at_boot is None:
            raise ValueError("Send on and/or at_boot")
        for value in (on, at_boot):
            if value is not None and not isinstance(value, bool):
                raise ValueError("on and at_boot must be true or false")
        if at_boot is not None:
            self.state.extras_at_boot[name] = at_boot
            self.state.save()
        if on is not None:
            extras.switch(name, on)
        return self.extras_status()

    def stop(self) -> None:
        self.thermal.stop_event.set()
        self.sampler.stop_event.set()
        self.stream.stop_event.set()
        self.stream.wake.set()
        self.stream.join(timeout=10)
