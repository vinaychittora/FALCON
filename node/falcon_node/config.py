"""Node configuration (/etc/falcon-node/node.conf) and persisted runtime state."""

import json
import os
import re
import socket
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from falcon_node.auth import normalize_key
from falcon_node.media import CameraSettings, MicrophoneSettings

COMPONENTS = ("camera", "microphone", "climate", "rain")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")


def parse_conf(text: str) -> dict[str, str]:
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"Line {number} is not KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key.strip().upper()] = value
    return values


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    name: str
    pairing_key: str
    api_port: int = 8780
    rtsp_port: int = 8554
    mediamtx_api_port: int = 9997
    camera: str = "auto"
    # USB webcam (V4L2) controls applied at every stream start, e.g. "sharpness=12".
    camera_controls: str = ""
    microphone: str = "auto"
    microphone_channels: int = 2
    climate: str = "auto"
    rain: str = "auto"
    rain_wet_when_low: bool = True
    reading_interval: float = 30.0
    # Thermal protection (°C): pause the stream just below the Pi's rated maximum and
    # resume once cooled. Set THERMAL_STOP_C above THERMAL_PAUSE_C to pause only the
    # camera first (sound carries on). 0 disables a level.
    thermal_pause_c: float = 84.0
    thermal_stop_c: float = 84.0
    thermal_resume_c: float = 75.0
    mediamtx: str = "/opt/falcon-node/mediamtx/mediamtx"
    ffmpeg: str = "ffmpeg"
    mixer_state: str = "/opt/falcon-node/audio/da7212-onboard-mic1.state"
    state_dir: Path = field(default=Path("/var/lib/falcon-node"))

    @classmethod
    def load(cls, path: Path | None, environ: dict[str, str] | None = None, state_dir: Path | None = None) -> "NodeConfig":
        values = parse_conf(path.read_text()) if path else {}
        env = os.environ if environ is None else environ
        values.update({key[7:]: value for key, value in env.items() if key.startswith("FALCON_") and key != "FALCON_"})
        key = values.get("PAIRING_KEY", "")
        try:
            normalize_key(key)
        except ValueError:
            raise SystemExit("Set PAIRING_KEY in node.conf (the installer generates one).") from None
        node_id = values.get("NODE_ID") or socket.gethostname()
        if not IDENTIFIER.match(node_id):
            raise SystemExit("NODE_ID may contain letters, digits and . _ : - (up to 100 characters).")
        pause = float(values.get("THERMAL_PAUSE_C", 84))
        stop = float(values.get("THERMAL_STOP_C", pause))
        stop = max(pause, stop) if stop > 0 and pause > 0 else 0.0
        resume = min(pause - 2, float(values.get("THERMAL_RESUME_C", 75))) if pause > 0 else 0.0
        return cls(
            node_id=node_id,
            name=(values.get("NODE_NAME") or "FALCON sensor node")[:80],
            pairing_key=key,
            api_port=int(values.get("API_PORT", 8780)),
            rtsp_port=int(values.get("RTSP_PORT", 8554)),
            mediamtx_api_port=int(values.get("MEDIAMTX_API_PORT", 9997)),
            camera=values.get("CAMERA", "auto"),
            camera_controls=values.get("CAMERA_CONTROLS", ""),
            microphone=values.get("MICROPHONE", "auto"),
            microphone_channels=max(1, min(8, int(values.get("MICROPHONE_CHANNELS", 2)))),
            climate=values.get("CLIMATE", "auto"),
            rain=values.get("RAIN", "auto"),
            rain_wet_when_low=_flag(values.get("RAIN_WET_WHEN_LOW", "true")),
            reading_interval=max(5.0, float(values.get("READING_INTERVAL_SECONDS", 30))),
            thermal_pause_c=pause,
            thermal_stop_c=stop,
            thermal_resume_c=resume,
            mediamtx=values.get("MEDIAMTX", cls.mediamtx),
            ffmpeg=values.get("FFMPEG", "ffmpeg"),
            mixer_state=values.get("MIXER_STATE", cls.mixer_state),
            state_dir=state_dir or Path(values.get("STATE_DIR", "/var/lib/falcon-node")),
        )


class NodeState:
    """Settings changed from FALCON's web UI; survive restarts and reboots."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.stream_enabled = True
        self.components = dict.fromkeys(COMPONENTS, True)
        self.camera = CameraSettings()
        self.microphone = MicrophoneSettings()
        # USB webcam picture controls set from FALCON (name -> value), applied at every start.
        self.picture: dict[str, int] = {}
        # Optional extras (hotspot, bluetooth) the node starts itself at boot.
        self.extras_at_boot: dict[str, bool] = {}
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        try:
            self.stream_enabled = bool(data.get("stream_enabled", True))
            self.components.update({
                name: bool(value) for name, value in data.get("components", {}).items() if name in COMPONENTS
            })
            self.camera = CameraSettings().updated(data.get("camera", {}), kind="any")
            self.microphone = MicrophoneSettings().updated(data.get("microphone", {}))
            self.picture = {
                str(name): int(value) for name, value in data.get("picture", {}).items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
            self.extras_at_boot = {
                str(name): value for name, value in data.get("extras_at_boot", {}).items()
                if isinstance(value, bool)
            }
        except (ValueError, TypeError, AttributeError):
            pass  # A damaged state file falls back to defaults rather than stopping the node.

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stream_enabled": self.stream_enabled, "components": dict(self.components),
                "camera": self.camera.public(), "microphone": asdict(self.microphone),
                "picture": dict(self.picture), "extras_at_boot": dict(self.extras_at_boot),
            }

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
            with os.fdopen(descriptor, "w") as file:
                json.dump(self.snapshot(), file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
