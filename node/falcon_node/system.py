# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Host health, clock state and power actions for the sensor node."""

import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def run(command: list[str], timeout: float = 5) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def board_model() -> str:
    model = _read("/proc/device-tree/model")
    return model.rstrip("\x00") if model else (socket.gethostname() or "Linux computer")


def is_raspberry_pi() -> bool:
    return "raspberry pi" in board_model().lower()


def boot_id() -> str:
    return _read("/proc/sys/kernel/random/boot_id") or "unknown"


def ntp_synchronized() -> bool | None:
    result = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    value = result.stdout.strip().lower() if result else ""
    return True if value == "yes" else False if value == "no" else None


def set_clock(unix_time: float) -> bool:
    """Needs CAP_SYS_TIME (granted by falcon-node.service). Returns False when refused."""
    try:
        time.clock_settime(time.CLOCK_REALTIME, unix_time)
        return True
    except (OSError, AttributeError):
        return False


def throttling() -> dict[str, Any] | None:
    """Raspberry Pi firmware flags: under-voltage and thermal throttling, now and since boot."""
    result = run(["vcgencmd", "get_throttled"])
    match = re.search(r"0x([0-9a-fA-F]+)", result.stdout if result else "")
    if not match:
        return None
    flags = int(match.group(1), 16)
    return {
        "under_voltage_now": bool(flags & 0x1), "throttled_now": bool(flags & 0x4),
        "under_voltage_since_boot": bool(flags & 0x10000), "throttled_since_boot": bool(flags & 0x40000),
        # The firmware's own heat protection: clock capped (0x2) and soft limit at 80 °C (0x8).
        "frequency_capped_now": bool(flags & 0x2), "soft_temp_limit_now": bool(flags & 0x8),
        "soft_temp_limit_since_boot": bool(flags & 0x80000),
    }


def wifi_signal_dbm() -> int | None:
    text = _read("/proc/net/wireless")
    for line in (text or "").splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 4:
            try:
                return int(float(parts[3].rstrip(".")))
            except ValueError:
                return None
    return None


def addresses() -> list[str]:
    result = run(["hostname", "-I"])
    return [value for value in (result.stdout.split() if result else []) if ":" not in value][:4]


def health(data_dir: Path) -> dict[str, Any]:
    temperature = _read("/sys/class/thermal/thermal_zone0/temp")
    memory: dict[str, int] = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        name, _, value = line.partition(":")
        if name in {"MemTotal", "MemAvailable"}:
            memory[name] = int(value.split()[0]) * 1024
    uptime = _read("/proc/uptime")
    disk = shutil.disk_usage(data_dir if data_dir.exists() else "/")
    total = memory.get("MemTotal", 0)
    return {
        "board": board_model(),
        "hostname": socket.gethostname(),
        "addresses": addresses(),
        "uptime_seconds": round(float(uptime.split()[0])) if uptime else None,
        "cpu_temperature_c": round(int(temperature) / 1000, 1) if temperature and temperature.isdigit() else None,
        "load_1m": round(os.getloadavg()[0], 2),
        "cpu_count": os.cpu_count() or 1,
        "memory_used_percent": round(100 * (1 - memory.get("MemAvailable", 0) / total), 1) if total else None,
        "memory_total_bytes": total or None,
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "wifi_signal_dbm": wifi_signal_dbm(),
        "power": throttling(),
    }


def power(action: str) -> None:
    """Reboot or shut down through logind; polkit allows the falcon-node user (see install.sh)."""
    command = {"reboot": ["systemctl", "reboot"], "shutdown": ["systemctl", "poweroff"]}[action]
    # Delay slightly so the HTTP reply reaches the inference node first.
    subprocess.Popen(["sh", "-c", "sleep 2; exec \"$@\"", "falcon-power", *command])
