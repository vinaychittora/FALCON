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
    # The node offers only the ones the webcam really has (see resolutions()).
    "v4l2": ["1920x1080", "1280x1024", "1280x960", "1280x720", "1024x768", "960x540", "800x600", "640x480"],
}
CHOICES: dict[str, tuple[str, ...]] = {
    "focus_mode": ("continuous", "manual", "auto"),
    "exposure": ("normal", "sport", "long"),
    "awb": ("auto", "daylight", "cloudy", "tungsten", "fluorescent", "indoor", "incandescent"),
    "metering": ("centre", "spot", "average"),
    "denoise": ("auto", "off", "cdn_off", "cdn_fast", "cdn_hq"),
    "audio_channel": ("average", "left", "right"),
    # Night picture: webcams without an IR-cut filter turn magenta under their IR lights.
    "night_mode": ("auto", "colour", "mono"),
    # h264: the node encodes (about 150 % CPU on a Pi 4 at 1280x960). mjpeg: the webcam's own
    # JPEG frames go out untouched and FALCON decodes them on the PC (needs ~10 Mbit/s;
    # wired network recommended). In mjpeg mode the night picture is applied by FALCON.
    "video_codec": ("h264", "mjpeg"),
}
# USB webcams deliver MJPEG at this rate; pass-through keeps every n-th frame.
MJPEG_NATIVE_FPS = 30
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
        "denoise", "hdr", "hflip", "vflip", "night_mode",
    ],
    "v4l2": ["resolution", "framerate", "bitrate_kbps", "night_mode", "video_codec"],
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
    night_mode: str = "auto"
    video_codec: str = "h264"

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
    input_format: str = ""  # v4l2 only: "mjpeg" when the webcam offers it
    sizes: tuple[str, ...] = ()  # v4l2 only: frame sizes the webcam offers in that format


@dataclass(frozen=True)
class Microphone:
    device: str
    card: str
    description: str
    channels: int = 2


def rpicam_binary() -> str | None:
    return shutil.which("rpicam-vid") or shutil.which("libcamera-vid")


def v4l2_input_format(device: str) -> str:
    """USB webcams send full frame rates at 720p and above only as MJPEG, so prefer it.
    Without v4l2-ctl to check, assume MJPEG: almost every UVC webcam offers it."""
    if not shutil.which("v4l2-ctl"):
        return "mjpeg"
    listing = run(["v4l2-ctl", "-d", device, "--list-formats"], timeout=10)
    return "mjpeg" if listing is None or "'MJPG'" in listing.stdout else ""


def parse_v4l2_sizes(text: str, input_format: str) -> tuple[str, ...]:
    """Discrete frame sizes listed by `v4l2-ctl --list-formats-ext` for one pixel format
    (MJPG for "mjpeg", otherwise the first format listed)."""
    wanted = "MJPG" if input_format == "mjpeg" else None
    sizes: list[str] = []
    current = None
    for line in text.splitlines():
        if match := re.search(r"\[\d+\]:\s*'(\w+)'", line):
            current = match.group(1)
            wanted = wanted or current
        elif current == wanted and (match := re.search(r"Size: Discrete (\d+x\d+)", line)):
            if match.group(1) not in sizes:
                sizes.append(match.group(1))
    return tuple(sizes)


def v4l2_sizes(device: str, input_format: str) -> tuple[str, ...]:
    if not shutil.which("v4l2-ctl"):
        return ()
    listing = run(["v4l2-ctl", "-d", device, "--list-formats-ext"], timeout=10)
    return parse_v4l2_sizes(listing.stdout, input_format) if listing else ()


def resolutions(camera: "Camera | None") -> list[str]:
    """Resolutions FALCON may offer: the listed ones the camera really supports, when known."""
    if camera is None:
        return []
    listed = RESOLUTIONS.get(camera.kind, [])
    supported = [size for size in listed if size in camera.sizes]
    return supported or listed


# USB webcam picture controls FALCON shows (when the camera has them), in display order.
PICTURE_CONTROLS = (
    "brightness", "contrast", "saturation", "hue", "gamma", "sharpness", "gain",
    "backlight_compensation", "white_balance_automatic", "white_balance_temperature",
    "auto_exposure", "exposure_time_absolute", "exposure_dynamic_framerate", "power_line_frequency",
)
# Automatic modes are applied first, so the manual value that depends on them is accepted.
_AUTO_FIRST = ("white_balance_automatic", "auto_exposure")
_CONTROL_LINE = re.compile(r"^\s*(\w+)\s+0x[0-9a-fA-F]+\s+\((int|bool|menu)\)\s*:\s*(.*)$")
_MENU_LINE = re.compile(r"^\s*(\d+):\s*(.+?)\s*$")


def parse_v4l2_controls(text: str) -> list[dict[str, Any]]:
    """Picture controls from `v4l2-ctl --list-ctrls-menus`, in PICTURE_CONTROLS order."""
    found: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if match := _CONTROL_LINE.match(line):
            name, kind, rest = match.groups()
            fields = {key: int(value) for key, value in re.findall(r"(min|max|step|default|value)=(-?\d+)", rest)}
            current = None
            if name not in PICTURE_CONTROLS:
                continue
            current = {
                "name": name, "type": kind,
                "min": fields.get("min", 0), "max": fields.get("max", 1), "step": fields.get("step", 1) or 1,
                "default": fields.get("default", 0), "value": fields.get("value", 0),
                "inactive": "inactive" in rest,
            }
            if kind == "menu":
                current["menu"] = []
            found[name] = current
        elif current is not None and current["type"] == "menu" and (item := _MENU_LINE.match(line)):
            current["menu"].append([int(item.group(1)), item.group(2)])
    return [found[name] for name in PICTURE_CONTROLS if name in found]


def picture_controls(camera: "Camera | None") -> list[dict[str, Any]]:
    if camera is None or camera.kind != "v4l2" or not shutil.which("v4l2-ctl"):
        return []
    listing = run(["v4l2-ctl", "-d", camera.device, "--list-ctrls-menus"], timeout=10)
    return parse_v4l2_controls(listing.stdout) if listing and listing.returncode == 0 else []


def validate_picture_values(
    available: list[dict[str, Any]], values: dict[str, Any],
) -> list[tuple[str, int]]:
    """Checked (name, value) pairs in the order they must be applied."""
    by_name = {item["name"]: item for item in available}
    checked: list[tuple[str, int]] = []
    for name, value in values.items():
        item = by_name.get(name)
        if item is None:
            raise ValueError(f"This camera has no control named {name}")
        if isinstance(value, bool):
            value = int(value)
        if not isinstance(value, int):
            raise ValueError(f"{name} must be a whole number")
        if not item["min"] <= value <= item["max"]:
            raise ValueError(f"{name} must be between {item['min']} and {item['max']}")
        if item["type"] == "menu" and value not in {entry[0] for entry in item["menu"]}:
            raise ValueError(f"{name} has no option {value}")
        checked.append((name, value))
    checked.sort(key=lambda pair: (pair[0] not in _AUTO_FIRST, PICTURE_CONTROLS.index(pair[0])))
    return checked


def set_picture_controls(camera: "Camera", values: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply controls to the running webcam (no stream restart) and return the new state."""
    available = picture_controls(camera)
    if not available:
        raise ValueError("This camera has no adjustable picture controls")
    checked = validate_picture_values(available, values)
    if checked:
        # One v4l2-ctl call per control so an automatic mode switches before its manual value.
        for name, value in checked:
            run(["v4l2-ctl", "-d", camera.device, "-c", f"{name}={value}"], timeout=10)
    return picture_controls(camera)


def detect_camera(spec: str) -> Camera | None:
    """spec: auto | rpicam | v4l2[:/dev/videoN] | usb[:/dev/videoN] | rtsp://… | off."""
    spec = spec.strip()
    if spec.lower().startswith("usb"):
        spec = "v4l2" + spec[3:]
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
            # A UVC webcam also creates a metadata node (index 1) that carries no video.
            index = Path("/sys/class/video4linux", Path(candidate).name, "index")
            if not device and index.exists() and index.read_text().strip() != "0":
                continue
            if Path(candidate).exists():
                input_format = v4l2_input_format(candidate)
                return Camera(
                    "v4l2", candidate, label or "USB camera", input_format, v4l2_sizes(candidate, input_format),
                )
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


CONTROL_SPEC = re.compile(r"^[a-z_]{1,40}=-?\d{1,6}(,[a-z_]{1,40}=-?\d{1,6}){0,15}$")


def apply_camera_controls(camera: Camera | None, controls: str) -> bool:
    """Apply node.conf CAMERA_CONTROLS (e.g. "sharpness=12,backlight_compensation=100") to a
    USB webcam with v4l2-ctl. Other cameras, a malformed value or a missing tool: no change."""
    controls = controls.replace(" ", "")
    if camera is None or camera.kind != "v4l2" or not controls:
        return False
    if not CONTROL_SPEC.match(controls):
        log.warning("CAMERA_CONTROLS is not in the form name=number,name=number; ignored")
        return False
    if not shutil.which("v4l2-ctl"):
        log.warning("v4l2-ctl is missing; CAMERA_CONTROLS not applied")
        return False
    result = run(["v4l2-ctl", "-d", camera.device, "-c", controls], timeout=10)
    if result is None or result.returncode != 0:
        log.warning("Some CAMERA_CONTROLS are not supported by this camera")
        return False
    return True


def apply_mixer(microphone: Microphone, settings: MicrophoneSettings, state_file: Path | None) -> None:
    """Restore the audio HAT mixer (onboard microphone on) and the optional capture gain."""
    if microphone.card == "Zero" and state_file and state_file.exists():
        result = run(["alsactl", "--file", str(state_file), "restore", "Zero"], timeout=10)
        if result is None or result.returncode not in (0, 99):
            log.warning("Audio HAT mixer settings could not be restored")
    if settings.audio_gain_percent is not None:
        apply_gain(microphone, settings.audio_gain_percent)


def apply_gain(microphone: Microphone, percent: int) -> bool:
    """Set the capture gain now; the running stream picks it up without a restart."""
    control = "Mixin PGA" if microphone.card == "Zero" else "Capture"
    result = run(["amixer", "-q", "-c", microphone.card, "sset", control, f"{percent}%"])
    return result is not None and result.returncode == 0


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


PROBE_SIZE = (32, 18)
PROBE_SECONDS = 10
# Magenta cast (mean (R+B)/2 − G of the colour probe, 0–255): a webcam without an
# IR-cut filter under its own IR lights measured +40 at dusk; daylight is near 0.
NIGHT_ON, NIGHT_OFF = 15.0, 6.0


def colour_cast(ppm: bytes) -> float | None:
    """Magenta cast of a small binary PPM (P6) image, or None when it cannot be read."""
    parts = ppm.split(b"\n", 3)
    if len(parts) != 4 or parts[0] != b"P6":
        return None
    pixels = parts[3]
    count = len(pixels) // 3
    if not count:
        return None
    red, green, blue = (sum(pixels[offset::3]) / count for offset in range(3))
    return (red + blue) / 2 - green


def build_pipeline(
    camera: Camera | None, camera_settings: CameraSettings,
    microphone: Microphone | None, microphone_settings: MicrophoneSettings,
    publish_url: str, ffmpeg: str = "ffmpeg", *, mono: bool = False, probe_path: str | None = None,
) -> list[list[str]]:
    """Return one command, or two where the first's stdout feeds the second's stdin.

    mono: send a greyscale picture (a webcam's IR night picture is magenta otherwise).
    probe_path: USB webcams also write a tiny colour thumbnail there every few seconds,
    taken before any greyscale step, so the node can tell when night falls or ends.
    """
    if camera is None and microphone is None:
        return []
    commands: list[list[str]] = []
    output = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostats", "-nostdin"]
    maps: list[str] = []
    codecs: list[str] = []
    extra_output: list[str] = []
    video_map: str | None = None
    input_index = 0
    if camera is not None:
        if camera.kind == "rpicam":
            settings = replace(camera_settings, saturation=0.0) if mono else camera_settings
            commands.append(_rpicam_command(rpicam_binary() or "rpicam-vid", settings))
            output[-1:] = []  # stdin carries video
            output += [
                "-fflags", "+genpts", "-use_wallclock_as_timestamps", "1", "-thread_queue_size", "512",
                "-f", "h264", "-framerate", str(camera_settings.framerate), "-i", "pipe:0",
            ]
            codecs += ["-c:v", "copy"]
        elif camera.kind == "v4l2" and camera_settings.video_codec == "mjpeg" and camera.input_format == "mjpeg":
            # Pass-through: the webcam's JPEG frames are sent as they are (RTP/JPEG) and
            # FALCON decodes them on the PC. No decode or encode on the node; surplus
            # frames are dropped as packets (keep every n-th) to reach the asked rate.
            # The night picture is applied by FALCON in this mode.
            width, height = camera_settings.size
            keep = max(1, round(MJPEG_NATIVE_FPS / max(1, camera_settings.framerate)))
            output += [
                "-thread_queue_size", "512", "-f", "v4l2", "-input_format", "mjpeg",
                "-framerate", str(MJPEG_NATIVE_FPS), "-video_size", f"{width}x{height}", "-i", camera.device,
            ]
            codecs += ["-c:v", "copy"]
            if keep > 1:
                codecs += ["-bsf:v", f"noise=drop=mod(n\\,{keep})"]
        elif camera.kind == "v4l2":
            width, height = camera_settings.size
            output += ["-thread_queue_size", "512", "-f", "v4l2"]
            if camera.input_format:
                output += ["-input_format", camera.input_format]
            output += [
                "-framerate", str(camera_settings.framerate), "-video_size", f"{width}x{height}", "-i", camera.device,
            ]
            codecs += [
                # Many webcams only offer MJPEG at 30 fps and ignore the requested rate;
                # drop the extra frames before encoding so the Pi encodes only what was asked.
                "-r", str(camera_settings.framerate),
                # ultrafast: about a third less CPU than veryfast on a Pi 4 (76% -> 50% of a
                # core at 960x540, 10 fps); the capped bitrate leaves ample quality.
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
                "-b:v", f"{camera_settings.bitrate_kbps}k", "-maxrate", f"{camera_settings.bitrate_kbps}k",
                "-bufsize", f"{camera_settings.bitrate_kbps * 2}k", "-g", str(camera_settings.framerate),
            ]
            if mono or probe_path:
                width_p, height_p = PROBE_SIZE
                chain = "hue=s=0" if mono else "null"
                graph = f"[{input_index}:v]{chain}[v]"
                if probe_path:
                    # The thumbnail follows every frame: an output that only gets a frame
                    # every few seconds makes ffmpeg hold the other outputs back, and the
                    # sound then reached FALCON in 10-second bursts. 32x18 pixels per
                    # frame cost almost nothing; the file lives in RAM (see agent).
                    graph = (
                        f"[{input_index}:v]split=2[main][probe];[main]{chain}[v];"
                        f"[probe]scale={width_p}:{height_p},format=rgb24[colour]"
                    )
                    extra_output = [
                        "-map", "[colour]", "-c:v", "ppm", "-f", "image2", "-update", "1", "-y", probe_path,
                    ]
                output += ["-filter_complex", graph]
                video_map = "[v]"
        else:
            output += ["-rtsp_transport", "tcp", "-timeout", "10000000", "-i", camera.device]
            codecs += ["-c:v", "copy"]
        maps += ["-map", video_map or f"{input_index}:v:0"]
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
    output += maps + codecs + ["-f", "rtsp", "-rtsp_transport", "tcp", publish_url] + extra_output
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
