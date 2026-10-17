"""User-local Node and FFmpeg installation; no system packages or driver changes."""

import hashlib
import json
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".tools"
ROOT.mkdir(exist_ok=True)


def fetch(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as source, target.open("wb") as dest:
        while chunk := source.read(1024 * 1024):
            dest.write(chunk)


def install() -> None:
    if not (ROOT / "node" / "bin" / "node").exists():
        version = "v22.23.3"
        name = f"node-{version}-linux-x64.tar.xz"
        base = f"https://nodejs.org/dist/{version}/"
        archive = ROOT / name
        fetch(base + name, archive)
        with urllib.request.urlopen(base + "SHASUMS256.txt", timeout=60) as response:
            lines = response.read().decode().splitlines()
        expected = next(line.split()[0] for line in lines if line.endswith(name))
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Node archive checksum mismatch")
        with tarfile.open(archive) as tar:
            tar.extractall(ROOT, filter="data")
        (ROOT / "node").symlink_to(
            name.removesuffix(".tar.xz"), target_is_directory=True
        )
    if not (ROOT / "ffmpeg" / "bin" / "ffmpeg").exists():
        with urllib.request.urlopen(
            "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/autobuild-2026-10-16-13-04",
            timeout=60,
        ) as response:
            data = json.load(response)
        asset = next(
            a for a in data["assets"] if a["name"].endswith("linux64-gpl.tar.xz")
        )
        archive = ROOT / asset["name"]
        fetch(asset["browser_download_url"], archive)
        expected = "3d994f31aa9ee78ef56eab530a86d50d8307200cb9d1788be36c1ea9410e605c"
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Pinned FFmpeg archive checksum mismatch")
        with tarfile.open(archive) as tar:
            tar.extractall(ROOT, filter="data")
        (ROOT / "ffmpeg").symlink_to(
            asset["name"].removesuffix(".tar.xz"), target_is_directory=True
        )


if __name__ == "__main__":
    install()
