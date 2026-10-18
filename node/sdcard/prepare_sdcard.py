#!/usr/bin/env python3
"""Put the FALCON sensor node on a freshly written Raspberry Pi OS SD card.

1. Write Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager. In Imager's
   settings choose a host name, user, Wi-Fi (or use Ethernet) and enable SSH.
2. Keep the card in this computer and run, pointing at its "bootfs" drive:

       python3 node/sdcard/prepare_sdcard.py E:\\                (Windows)
       python3 node/sdcard/prepare_sdcard.py /media/$USER/bootfs  (Linux)
       python3 node/sdcard/prepare_sdcard.py /Volumes/bootfs      (macOS)

3. Put the card in the Pi and power it on. On the first boot with internet the
   node installs itself (about 10 minutes), restarts once and starts streaming.

Prints the pairing key to enter in FALCON → Sensors → Add sensor node. Works with
Imager's first-boot script (Bookworm) and with cloud-init (Trixie and newer);
for any other card it prints the one command to run on the Pi instead.
Standard library only.
"""

import argparse
import base64
import hashlib
import re
import secrets
import shutil
import sys
import urllib.request
from pathlib import Path

NODE = Path(__file__).resolve().parents[1]
BUNDLE_NAME = "falcon-node"
HOOK = "/boot/firmware/falcon-node/sdcard/firstboot-hook.sh"
FIRSTRUN_LINE = (
    "for d in /boot/firmware /boot; do if [ -f \"$d/falcon-node/sdcard/firstboot-hook.sh\" ]; then "
    "bash \"$d/falcon-node/sdcard/firstboot-hook.sh\" || true; break; fi; done  # FALCON sensor node\n"
)
MEDIAMTX = ("v1.21.2", "arm64", "180a235374a548d9133cdd5e20f5dbd8b01317be1c86e0d7e66df585dc42ed6f")


def generate_key() -> str:
    raw = base64.b32encode(secrets.token_bytes(15)).decode("ascii")
    return "-".join(raw[index:index + 4] for index in range(0, len(raw), 4))


def check_boot_partition(boot: Path) -> None:
    if not (boot / "config.txt").is_file() or not (boot / "cmdline.txt").is_file():
        raise SystemExit(
            f"{boot} does not look like a Raspberry Pi boot partition (config.txt and cmdline.txt are missing). "
            "Point at the drive called 'bootfs' after writing Raspberry Pi OS."
        )


def copy_bundle(boot: Path) -> Path:
    target = boot / BUNDLE_NAME
    target.mkdir(exist_ok=True)
    for folder in ("falcon_node", "audio", "systemd", "sdcard"):
        shutil.rmtree(target / folder, ignore_errors=True)
        shutil.copytree(NODE / folder, target / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("install.sh", "node.conf.example", "README.md"):
        if (NODE / name).exists():
            shutil.copy2(NODE / name, target / name)
    return target


def write_config(target: Path, name: str, node_id: str | None, settings: dict[str, str]) -> str:
    """Create node.conf once; an existing key is kept so FALCON's pairing stays valid."""
    path = target / "node.conf"
    existing = path.read_text() if path.exists() else (NODE / "node.conf.example").read_text()
    key_match = re.search(r"^PAIRING_KEY=([A-Za-z2-7-]{16,})\s*$", existing, re.MULTILINE)
    key = key_match.group(1) if key_match else generate_key()
    values = {"NODE_NAME": name, "PAIRING_KEY": key, **settings}
    if node_id:
        values["NODE_ID"] = node_id
    lines = [line for line in existing.splitlines() if line.split("=", 1)[0].strip() not in values]
    lines += [f"{name_}={value}" for name_, value in values.items()]
    path.write_text("\n".join(lines) + "\n", newline="\n")
    return key


def hook_cloud_init(user_data: Path) -> bool:
    text = user_data.read_text()
    if HOOK in text:
        return True
    lines = text.splitlines()
    entry = f"[bash, {HOOK}, --now]"
    for index, line in enumerate(lines):
        if re.fullmatch(r"runcmd:\s*", line):
            indent = "  "
            following = next((item for item in lines[index + 1:] if item.strip()), "")
            match = re.match(r"(\s*)- ", following)
            if match:
                indent = match.group(1)
            lines.insert(index + 1, f"{indent}- {entry}")
            break
    else:
        lines += ["runcmd:", f"  - {entry}"]
    user_data.write_text("\n".join(lines) + "\n", newline="\n")
    return True


def hook_firstrun(firstrun: Path) -> bool:
    text = firstrun.read_text()
    if "falcon-node/sdcard/firstboot-hook.sh" in text:
        return True
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        # Imager's script deletes itself at the end; schedule FALCON just before that.
        if line.lstrip().startswith("rm -f") and "firstrun.sh" in line:
            lines.insert(index, FIRSTRUN_LINE)
            firstrun.write_text("".join(lines), newline="\n")
            return True
    return False


def add_offline_mediamtx(target: Path) -> None:
    version, arch, digest = MEDIAMTX
    name = f"mediamtx_{version}_linux_{arch}.tar.gz"
    vendor = target / "vendor"
    vendor.mkdir(exist_ok=True)
    url = f"https://github.com/bluenviron/mediamtx/releases/download/{version}/{name}"
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit("The downloaded MediaMTX archive failed its checksum; nothing was added.")
    (vendor / name).write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("boot", type=Path, help="the SD card's boot partition (the 'bootfs' drive)")
    parser.add_argument("--name", default="FALCON sensor node", help="name shown in FALCON")
    parser.add_argument("--id", dest="node_id", help="node identifier (default: the Pi's host name)")
    parser.add_argument("--camera", help="auto | rpicam | v4l2:/dev/video0 | rtsp://… | off")
    parser.add_argument("--microphone", help="auto | alsa:<device> | off")
    parser.add_argument("--climate", help="auto | bme280 | bme280:0x77 | off")
    parser.add_argument("--rain", help="auto | gpio:17 | off")
    parser.add_argument("--offline-mediamtx", action="store_true",
                        help="also copy the stream server, so only system packages need internet on the Pi")
    arguments = parser.parse_args(argv)
    boot = arguments.boot
    check_boot_partition(boot)
    target = copy_bundle(boot)
    settings = {
        key: value for key, value in {
            "CAMERA": arguments.camera, "MICROPHONE": arguments.microphone,
            "CLIMATE": arguments.climate, "RAIN": arguments.rain,
        }.items() if value
    }
    key = write_config(target, arguments.name[:80], arguments.node_id, settings)
    if arguments.offline_mediamtx:
        add_offline_mediamtx(target)
    automatic = False
    if (boot / "user-data").is_file():
        automatic = hook_cloud_init(boot / "user-data")
    elif (boot / "firstrun.sh").is_file():
        automatic = hook_firstrun(boot / "firstrun.sh")
    (target / "PAIRING.txt").write_text(
        f"FALCON sensor node: {arguments.name}\nPairing key: {key}\n\n"
        "In FALCON open Sensors -> Add sensor node, enter the node's address\n"
        "(its host name followed by .local, or its IP address) and this key.\n", newline="\n",
    )
    print(f"Copied the FALCON sensor node to {target}")
    print(f"Pairing key: {key}   (also saved in {target / 'PAIRING.txt'})")
    if automatic:
        print("First boot is set up: put the card in the Pi and power it on with internet available.")
        print("It installs itself, restarts once and starts streaming (about 10 minutes).")
    else:
        print("This card has no Imager first-boot settings. After the Pi starts, run once:")
        print(f"  sudo bash /boot/firmware/{BUNDLE_NAME}/install.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
