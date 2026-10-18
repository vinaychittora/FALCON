"""Camera and microphone capture, published as one RTSP stream through MediaMTX.

Camera Module 3 (rpicam-vid, hardware H.264 on a Pi 4), a USB webcam (V4L2)
or an existing IP camera (RTSP relay) provides video; an ALSA device such as
the DA7212 audio HAT provides sound. ffmpeg combines them and publishes
rtsp://<node>:8554/falcon, which only the paired inference node can read.
"""

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import IO, Any

from falcon_node.system import run

log = logging.getLogger("falcon-node.media")
STREAM_PATH = "falcon"

RESOLUTIONS = {
    "rpicam": ["1920x1080", "1536x864", "1280x720", "960x540"],
    "v4l2": ["1920x1080", "1280x720", "960x540", "640x480"],
}
CHOICES: dict[str, tuple[str, ...]] = {
    "focus_mode": ("continuous", "manual", "auto"),
    "exposure": ("normal", "sport", "long"),
    "awb": ("auto", "daylight", "cloudy", "tungsten", "fluorescent", "indoor", "incandescent"),
    "metering": ("centre", "spot", "average"),
    "denoise": ("auto", "off", "cdn_off", "cdn_fast", "cdn_hq"),
    "audio_channel": ("average", "left", "right"),
}
RANGES: dict[str, tuple[float, float]] = {
    "framerate": (2, 30), "bitrate_kbps": (500, 10000), "lens_position": (0, 10), "ev": (-4, 4),
    "brightness": (-1, 1), "contrast": (0, 2), "saturation": (0, 2), "sharpness": (0, 4),
    "shutter_us": (0, 2_000_000), "gain": (0, 16), "audio_gain_percent": (0, 100),
}
# Settings each camera type can apply. The UI shows only these.
CONTROLS = {
    "rpicam": [
        "resolution", "framerate", "bitrate_kbps", "focus_mode", "lens_position", "exposure", "ev",
        "shutter_us", "gain", "awb", "metering", "brightness", "contrast", "saturation", "sharpness",
        "denoise", "hdr", "hflip", "vflip",
    ],
    "v4l2": ["resolution", "framerate", "bitrate_kbps"],
    "rtsp": [],
}


@dataclass(frozen=True)
class CameraSettings:
    resolution: str = "1920x1080"
    framerate: int = 15
    bitrate_kbps: int = 4000
    focus_mode: str = "continuous"
    lens_position: float = 0.5
    exposure: str = "normal"
    ev: float = 0.0
    shutter_us: int = 0
    gain: float = 0.0
    awb: str = "auto"
    metering: str = "centre"
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    sharpness: float = 1.0
    denoise: str = "auto"
    hdr: bool = False
    hflip: bool = False
    vflip: bool = False

    def updated(self, changes: dict[str, Any], kind: str = "rpicam") -> "CameraSettings":
        known = {item.name: item.type for item in fields(self)}
        values: dict[str, Any] = {}
        for name, value in changes.items():
            if name not in known:
                raise ValueError(f"Unknown camera setting: {name}")
            current = getattr(self, name)
            if isinstance(current, bool):
                if not isinstance(value, bool):
                    raise ValueError(f"{name} must be true or false")
            elif isinstance(current, (int, float)):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{name} must be a number")
                low, high = RANGES[name]
                if not low <= value <= high:
                    raise ValueError(f"{name} must be between {low:g} and {high:g}")
                value = int(value) if isinstance(current, int) else float(value)
            elif name == "resolution":
                allowed = RESOLUTIONS.get(kind) or sorted({size for sizes in RESOLUTIONS.values() for size in sizes})
                if value not in allowed:
                    raise ValueError("Choose one of the listed resolutions")
            elif value not in CHOICES[name]:
                raise ValueError(f"{name} must be one of: {', '.join(CHOICES[name])}")
            values[name] = value
        return replace(self, **values)

    @property
    def size(self) -> tuple[int, int]:
        width, height = self.resolution.split("x")
        return int(width), int(height)

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MicrophoneSettings:
    audio_channel: str = "average"
    audio_gain_percent: int | None = None

    def updated(self, changes: dict[str, Any]) -> "MicrophoneSettings":
        values: dict[str, Any] = {}
        for name, value in changes.items():
            if name == "audio_channel":
                if value not in CHOICES[name]:
                    raise ValueError("audio_channel must be average, left or right")
            elif name == "audio_gain_percent":
                if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100):
                    raise ValueError("audio_gain_percent must be a whole number from 0 to 100")
            else:
                raise ValueError(f"Unknown microphone setting: {name}")
            values[name] = value
        return replace(self, **values)


@dataclass(frozen=True)
class Camera:
    kind: str  # rpicam | v4l2 | rtsp
    device: str
    description: str


@dataclass(frozen=True)
class Microphone:
    device: str
    card: str
    description: str
    channels: int = 2


def rpicam_binary() -> str | None:
    return shutil.which("rpicam-vid") or shutil.which("libcamera-vid")


def detect_camera(spec: str) -> Camera | None:
    """spec: auto | rpicam | v4l2[:/dev/videoN] | rtsp://… | off."""
    spec = spec.strip()
    lowered = spec.lower()
    if lowered in {"off", "none", ""}:
        return None
    if lowered.startswith(("rtsp://", "rtsps://")):
        return Camera("rtsp", spec, "IP camera (relayed)")
    if lowered in {"auto", "rpicam"} and rpicam_binary():
        listing = run([rpicam_binary() or "rpicam-vid", "--list-cameras"], timeout=15)
        text = (listing.stdout + listing.stderr) if listing else ""
        match = re.search(r"^\s*0\s*:\s*(\S+)", text, re.MULTILINE)
        if match:
            sensor = match.group(1)
            name = {"imx708": "Camera Module 3", "imx708_wide": "Camera Module 3 Wide",
                    "imx477": "HQ Camera", "imx219": "Camera Module 2"}.get(sensor.split("_noir")[0], sensor)
            return Camera("rpicam", "0", f"{name} ({sensor})")
        if lowered == "rpicam":
            return None
    if lowered.startswith("v4l2") or lowered == "auto":
        device = spec.split(":", 1)[1] if ":" in spec else ""
        candidates = [device] if device else sorted(str(path) for path in Path("/dev").glob("video*"))
        for candidate in candidates:
            name = Path("/sys/class/video4linux", Path(candidate).name, "name")
            try:
                label = name.read_text().strip()
            except OSError:
                continue
            # Raspberry Pi codec and ISP nodes are not cameras.
            if label.startswith(("bcm2835-codec", "bcm2835-isp", "rpi-hevc", "pispbe", "rp1-cfe", "unicam")):
                continue
            if Path(candidate).exists():
                return Camera("v4l2", candidate, label or "USB camera")
    return None


def capture_cards() -> list[tuple[str, str]]:
    """[(card id, description)] for ALSA capture devices, from `arecord -l`."""
    listing = run(["arecord", "-l"])
    cards = []
    for line in (listing.stdout if listing else "").splitlines():
        match = re.match(r"card \d+: (\S+) \[([^\]]*)\], device (\d+):", line)
        if match:
            cards.append((f"{match.group(1)}|{match.group(3)}", match.group(2)))
    return cards


def detect_microphone(spec: str, channels: int = 2) -> Microphone | None:
    """spec: auto | alsa:<device> | off. The DA7212 audio HAT appears as card "Zero"."""
    spec = spec.strip()
    lowered = spec.lower()
    if lowered in {"off", "none", ""}:
        return None
    if lowered.startswith("alsa:"):
        device = spec.split(":", 1)[1]
        card = re.search(r"CARD=([^,]+)", device)
        return Microphone(device, card.group(1) if card else device, device, channels)
    cards = capture_cards()
    if not cards:
        return None
    # Prefer the audio HAT, then any USB microphone, then the first capture device.
    cards.sort(key=lambda item: (item[0].split("|")[0] != "Zero", "usb" not in item[1].lower()))
    card_id, description = cards[0]
    card, device = card_id.split("|")
    label = "DA7212 audio HAT" if card == "Zero" else description
    return Microphone(f"plughw:CARD={card},DEV={device}", card, label, channels)


def apply_mixer(microphone: Microphone, settings: MicrophoneSettings, state_file: Path | None) -> None:
    """Restore the audio HAT mixer (onboard microphone on) and the optional capture gain."""
    if microphone.card == "Zero" and state_file and state_file.exists():
        result = run(["alsactl", "--file", str(state_file), "restore", "Zero"], timeout=10)
        if result is None or result.returncode not in (0, 99):
            log.warning("Audio HAT mixer settings could not be restored")
    if settings.audio_gain_percent is not None:
        control = "Mixin PGA" if microphone.card == "Zero" else "Capture"
        run(["amixer", "-q", "-c", microphone.card, "sset", control, f"{settings.audio_gain_percent}%"])


def _rpicam_command(binary: str, settings: CameraSettings) -> list[str]:
    width, height = settings.size
    command = [
        binary, "-t", "0", "-n", "--codec", "h264", "--inline", "--flush", "--profile", "high",
        "--width", str(width), "--height", str(height), "--framerate", str(settings.framerate),
        "--bitrate", str(settings.bitrate_kbps * 1000),
        # One keyframe per second keeps FALCON's 5-second evidence clips tight.
        "--intra", str(settings.framerate),
        "--autofocus-mode", settings.focus_mode,
        "--exposure", settings.exposure, "--ev", f"{settings.ev:g}", "--awb", settings.awb,
        "--metering", settings.metering, "--brightness", f"{settings.brightness:g}",
        "--contrast", f"{settings.contrast:g}", "--saturation", f"{settings.saturation:g}",
        "--sharpness", f"{settings.sharpness:g}", "--denoise", settings.denoise,
    ]
    if settings.focus_mode == "manual":
        command += ["--lens-position", f"{settings.lens_position:g}"]
    if settings.shutter_us:
        command += ["--shutter", str(settings.shutter_us)]
    if settings.gain:
        command += ["--gain", f"{settings.gain:g}"]
    if settings.hdr:
        command.append("--hdr")
    if settings.hflip:
        command.append("--hflip")
    if settings.vflip:
        command.append("--vflip")
    return command + ["-o", "-"]


def _audio_filter(channel: str) -> str:
    return {"average": "pan=mono|c0=0.5*c0+0.5*c1", "left": "pan=mono|c0=c0", "right": "pan=mono|c0=c1"}[channel]


def build_pipeline(
    camera: Camera | None, camera_settings: CameraSettings,
    microphone: Microphone | None, microphone_settings: MicrophoneSettings,
    publish_url: str, ffmpeg: str = "ffmpeg",
) -> list[list[str]]:
    """Return one command, or two where the first's stdout feeds the second's stdin."""
    if camera is None and microphone is None:
        return []
    commands: list[list[str]] = []
    output = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostats", "-nostdin"]
    maps: list[str] = []
    codecs: list[str] = []
    input_index = 0
    if camera is not None:
        if camera.kind == "rpicam":
            commands.append(_rpicam_command(rpicam_binary() or "rpicam-vid", camera_settings))
            output[-1:] = []  # stdin carries video
            output += [
                "-fflags", "+genpts", "-use_wallclock_as_timestamps", "1", "-thread_queue_size", "512",
                "-f", "h264", "-framerate", str(camera_settings.framerate), "-i", "pipe:0",
            ]
            codecs += ["-c:v", "copy"]
        elif camera.kind == "v4l2":
            width, height = camera_settings.size
            output += [
                "-thread_queue_size", "512", "-f", "v4l2", "-framerate", str(camera_settings.framerate),
                "-video_size", f"{width}x{height}", "-i", camera.device,
            ]
            codecs += [
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
                "-b:v", f"{camera_settings.bitrate_kbps}k", "-maxrate", f"{camera_settings.bitrate_kbps}k",
                "-bufsize", f"{camera_settings.bitrate_kbps * 2}k", "-g", str(camera_settings.framerate),
            ]
        else:
            output += ["-rtsp_transport", "tcp", "-timeout", "10000000", "-i", camera.device]
            codecs += ["-c:v", "copy"]
        maps += ["-map", f"{input_index}:v:0"]
        input_index += 1
    if microphone is not None:
        output += [
            "-thread_queue_size", "1024", "-f", "alsa", "-channels", str(microphone.channels),
            "-sample_rate", "48000", "-i", microphone.device,
        ]
        maps += ["-map", f"{input_index}:a:0"]
        audio_filter = _audio_filter(microphone_settings.audio_channel) if microphone.channels > 1 else "anull"
        codecs += ["-af", audio_filter, "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "1"]
    elif camera is not None and camera.kind == "rtsp":
        # A relayed IP camera keeps its own sound when no microphone is attached.
        maps += ["-map", "0:a:0?"]
        codecs += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "1"]
    output += maps + codecs + ["-f", "rtsp", "-rtsp_transport", "tcp", publish_url]
    commands.append(output)
    return commands


def redact(text: str) -> str:
    return re.sub(r"(rtsps?://)[^@/\s]+@", r"\1***@", text)


class Pipeline:
    """Running capture processes; stderr is kept briefly for diagnostics."""

    def __init__(self, commands: list[list[str]]):
        self.commands = commands
        self.processes: list[subprocess.Popen[bytes]] = []
        self.errors: deque[str] = deque(maxlen=12)
        self.started = time.monotonic()
        previous: IO[bytes] | None = None
        try:
            for index, command in enumerate(commands):
                last = index == len(commands) - 1
                process = subprocess.Popen(
                    command, stdin=previous if previous is not None else subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL if last else subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                if previous is not None:
                    previous.close()
                previous = process.stdout
                self.processes.append(process)
                threading.Thread(target=self._drain, args=(process,), daemon=True).start()
        except OSError:
            self.stop()
            raise

    def _drain(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stderr is not None
        for raw in process.stderr:
            line = redact(raw.decode("utf-8", "replace").strip())
            if line:
                self.errors.append(line[:300])

    def alive(self) -> bool:
        return bool(self.processes) and all(process.poll() is None for process in self.processes)

    def stop(self, timeout: float = 5) -> None:
        for process in reversed(self.processes):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    pass
        deadline = time.monotonic() + timeout
        for process in self.processes:
            try:
                process.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
                process.wait()


class MediaServer:
    """MediaMTX with FALCON's configuration: RTSP over TCP only, one protected path."""

    def __init__(self, binary: str, config_path: Path, rtsp_port: int, api_port: int, read_password: str):
        self.binary, self.config_path = binary, config_path
        self.rtsp_port, self.api_port, self.read_password = rtsp_port, api_port, read_password
        self.process: subprocess.Popen[bytes] | None = None
        self.errors: deque[str] = deque(maxlen=12)

    def render(self) -> str:
        return f"""# Generated by falcon-node; changes are overwritten at start.
logLevel: warn
logDestinations: [stdout]
readTimeout: 10s
writeTimeout: 10s
authMethod: internal
authInternalUsers:
  - user: any
    pass:
    ips: ['127.0.0.1', '::1']
    permissions:
      - action: publish
        path: {STREAM_PATH}
      - action: read
        path: {STREAM_PATH}
      - action: api
  - user: falcon
    pass: {self.read_password}
    ips: []
    permissions:
      - action: read
        path: {STREAM_PATH}
api: true
apiAddress: 127.0.0.1:{self.api_port}
metrics: false
pprof: false
playback: false
rtsp: true
rtspTransports: [tcp]
rtspAddress: :{self.rtsp_port}
rtspAuthMethods: [basic]
rtmp: false
hls: false
webrtc: false
srt: false
moq: false
paths:
  {STREAM_PATH}:
    source: publisher
"""

    def ensure_running(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(self.render())
        self.process = subprocess.Popen(
            [self.binary, str(self.config_path)], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        for raw in process.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self.errors.append(redact(line)[:300])

    def path_status(self) -> dict[str, Any] | None:
        import json
        import urllib.request

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.api_port}/v3/paths/get/{STREAM_PATH}", timeout=2,
            ) as response:
                data = json.loads(response.read())
        except Exception:
            return None
        return {
            "ready": bool(data.get("ready")),
            "tracks": data.get("tracks") or [],
            "bytes_received": data.get("bytesReceived"),
            "readers": len(data.get("readers") or []),
        }

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except OSError:
                    pass
