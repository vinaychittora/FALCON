# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Opt-in Linux user service; installation never starts or stops a running server."""

import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
UNIT = "falcon.service"
HEADER = "# FALCON managed user service"


def unit_path() -> Path:
    directory = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    if not directory.is_absolute():
        raise SystemExit("XDG_CONFIG_HOME must be an absolute path.")
    return directory / "systemd" / "user" / UNIT


def marker(root: Path) -> str:
    digest = hashlib.sha256(os.fsencode(root.resolve())).hexdigest()
    return f"# Installation-ID: {digest}"


def quote(value: str, *, executable_argument: bool = False) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SystemExit("Installation paths cannot contain control characters.")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if executable_argument:
        value = value.replace("$", "$$")
    return f'"{value}"'


def render(root: Path) -> str:
    root = root.resolve()
    directory = str(root)
    if directory != directory.rstrip() or directory.endswith("\\"):
        raise SystemExit("Service installation paths cannot end in whitespace or a backslash.")
    return "\n".join([
        HEADER,
        marker(root),
        "[Unit]",
        "Description=FALCON wildlife observation",
        "StartLimitIntervalSec=300",
        "StartLimitBurst=5",
        "",
        "[Service]",
        "Type=exec",
        # This directive takes one literal path, unlike ExecStart's quoted argument list.
        f"WorkingDirectory={directory.replace('%', '%%')}",
        f"ExecStart=/bin/bash {quote(str(root / 'scripts' / 'serve.sh'), executable_argument=True)} run",
        "Restart=on-failure",
        "RestartSec=10",
        # FALCON stops its heartbeat only when live analysis is stuck beyond recovery.
        "WatchdogSec=600",
        "NotifyAccess=main",
        "TimeoutStopSec=120",
        "KillMode=control-group",
        "UMask=0077",
        "NoNewPrivileges=true",
        "Environment=PYTHONUNBUFFERED=1",
        "StandardOutput=journal",
        "StandardError=journal",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def owned(root: Path, path: Path | None = None) -> bool:
    path = path or unit_path()
    if path.is_symlink():
        return False
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeError):
        return False
    return lines[:2] == [HEADER, marker(root)]


def systemctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("systemctl")
    if binary is None:
        raise SystemExit("systemctl is unavailable; use manual launch on this Linux installation.")
    result = subprocess.run(
        [binary, "--user", *arguments], text=True, capture_output=True,
        timeout=150, check=False,
    )
    if check and result.returncode:
        raise SystemExit(
            "The systemd user-service command failed. Check your user manager and "
            "run systemctl --user status falcon.service locally."
        )
    return result


def fragment_path() -> str:
    # A working user manager is required; a file alone must not masquerade as an enabled service.
    systemctl("show", "--property=Version", "--value")
    return systemctl("show", UNIT, "--property=FragmentPath", "--value", check=False).stdout.strip()


def assert_owned(root: Path) -> Path:
    path = unit_path()
    if not owned(root, path):
        raise SystemExit("The FALCON user service does not belong to this installation.")
    fragment = fragment_path()
    if fragment != str(path):
        raise SystemExit("A different FALCON user service is loaded. No service was changed.")
    return path


def install(root: Path, *, enable: bool = False) -> Path:
    root = root.resolve()
    path = unit_path()
    if path.exists() or path.is_symlink():
        if not owned(root, path):
            raise SystemExit("An existing FALCON user-service file belongs elsewhere; it was not replaced.")
    fragment = fragment_path()
    if fragment and fragment != str(path):
        raise SystemExit("A different FALCON user service already exists; it was not replaced.")
    if not (root / "scripts" / "serve.sh").is_file():
        raise SystemExit("The FALCON launcher is missing from the installation.")
    content = render(root)
    if path.parent.resolve() != path.parent:
        raise SystemExit("The user-service directory must not be a symlink.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".falcon-{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    systemctl("daemon-reload")
    if enable:
        # Deliberately omit --now: enabling must not disturb an existing manual server.
        systemctl("enable", UNIT)
    return path


def control(root: Path, action: str) -> int:
    assert_owned(root)
    if action not in {"start", "stop", "disable"}:
        raise ValueError("Unsupported service action")
    systemctl(action, UNIT)
    return 0


def status(root: Path) -> dict[str, str]:
    assert_owned(root)
    result = systemctl(
        "show", UNIT, "--property=ActiveState,SubState,UnitFileState,MainPID"
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "disable", "status"))
    parser.add_argument("--enable", action="store_true", help="Enable future automatic startup; do not start now")
    args = parser.parse_args()
    if args.action == "install":
        install(ROOT, enable=args.enable)
        print("FALCON user service installed. Running servers were not changed.")
        if args.enable:
            print("Automatic startup is enabled for the user manager. Start it with make start.")
            print("Boot without login also requires administrator-enabled lingering; see docs/INSTALL.md.")
        return 0
    if args.enable:
        parser.error("--enable is only supported with install")
    if args.action == "disable":
        control(ROOT, "disable")
        print("Automatic startup disabled. A currently running service was left running.")
        return 0
    for key, value in status(ROOT).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
