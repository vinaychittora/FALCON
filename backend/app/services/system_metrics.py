# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Bounded, on-demand measurements of the environment running the server.

No network services or CUDA contexts are started by this sampler. Its response
contains measurements only, never command output, machine names or local paths.
"""

import csv
import math
import platform
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil
from pydantic import BaseModel, Field


class CpuMetrics(BaseModel):
    percent: float | None = None
    logical_count: int | None = None
    temperature_c: float | None = None


class MemoryMetrics(BaseModel):
    used_bytes: int | None = None
    total_bytes: int | None = None
    percent: float | None = None


class StorageMetrics(BaseModel):
    free_bytes: int | None = None
    total_bytes: int | None = None
    percent: float | None = None


class ProcessMetrics(BaseModel):
    uptime_seconds: float | None = None
    rss_bytes: int | None = None
    # Percentage of one logical CPU; a multithreaded process can exceed 100%.
    cpu_percent: float | None = None


class GpuDeviceMetrics(BaseModel):
    index: int
    name: str
    utilization_percent: float | None = None
    memory_used_mib: float | None = None
    memory_total_mib: float | None = None
    temperature_c: float | None = None
    power_watts: float | None = None


class GpuMetrics(BaseModel):
    available: bool = False
    devices: list[GpuDeviceMetrics] = Field(default_factory=list)


class SystemMetrics(BaseModel):
    sampled_at: str | None = None
    sample_age_seconds: float | None = None
    sampling: bool = False
    refresh_interval_seconds: float = 5
    scope: str
    scope_label: str
    cpu: CpuMetrics = Field(default_factory=CpuMetrics)
    memory: MemoryMetrics = Field(default_factory=MemoryMetrics)
    storage: StorageMetrics = Field(default_factory=StorageMetrics)
    process: ProcessMetrics = Field(default_factory=ProcessMetrics)
    gpu: GpuMetrics = Field(default_factory=GpuMetrics)
    # Linux clock source; under WSL "tsc" once ran 10 % fast (see clock_check).
    clocksource: str | None = None
    unavailable: list[str] = Field(default_factory=list)


def _number(value: object, maximum: float | None = None) -> float | None:
    """Reject unavailable, nonfinite and nonsensical readings at the boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(result) or result < 0 or (maximum is not None and result > maximum):
        return None
    return round(result, 2)


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _scope() -> tuple[str, str]:
    system = platform.system().lower()
    if system == "linux" and "microsoft" in platform.release().lower():
        return "wsl", "WSL Linux environment; CPU and RAM are not Windows host totals"
    if system == "linux":
        return "linux", "Linux server environment"
    if system == "windows":
        return "windows", "Windows server environment"
    return "other", "Server operating environment"


class SystemMetricsSampler:
    def __init__(self, data_dir: Path, refresh_seconds: float = 5):
        self._data_dir = data_dir
        self._interval = max(2, refresh_seconds)
        self._lock = threading.Lock()
        self._sampled_monotonic: float | None = None
        self._cpu_previous: tuple[float, float] | None = None
        self._process_previous: tuple[float, float] | None = None
        scope, label = _scope()
        self._snapshot = SystemMetrics(
            scope=scope, scope_label=label, refresh_interval_seconds=self._interval,
        )

    def _empty(self) -> SystemMetrics:
        return SystemMetrics(
            scope=self._snapshot.scope, scope_label=self._snapshot.scope_label,
            refresh_interval_seconds=self._interval,
        )

    def snapshot(self) -> SystemMetrics:
        now = time.monotonic()
        due = self._sampled_monotonic is None or now - self._sampled_monotonic >= self._interval
        if due and self._lock.acquire(blocking=False):
            try:
                # A caller may have tested the old timestamp just before another
                # sampler finished. Recheck under the lock to avoid extra probes.
                now = time.monotonic()
                if self._sampled_monotonic is None or now - self._sampled_monotonic >= self._interval:
                    try:
                        snapshot = self._collect()
                    except Exception:
                        # Preserve neither an exception's potentially sensitive
                        # details nor old values falsely presented as a new sample.
                        snapshot = self._empty()
                        snapshot.unavailable = ["sampling"]
                    snapshot.sampled_at = datetime.now(UTC).isoformat()
                    self._snapshot = snapshot
                    self._sampled_monotonic = time.monotonic()
            finally:
                self._lock.release()
        result = self._snapshot.model_copy(deep=True)
        result.sample_age_seconds = (
            round(max(0, time.monotonic() - self._sampled_monotonic), 2)
            if self._sampled_monotonic is not None else None
        )
        result.sampling = self._lock.locked()
        return result

    def _collect(self) -> SystemMetrics:
        result = self._empty()
        for name, reader in (
            ("cpu", self._cpu), ("memory", self._memory),
            ("storage", self._storage), ("process", self._process),
        ):
            try:
                setattr(result, name, reader())
            except Exception:
                result.unavailable.append(name)
        try:
            result.cpu.temperature_c = self._cpu_temperature()
        except Exception:
            pass
        if result.cpu.temperature_c is None:
            result.unavailable.append("cpu_temperature")
        result.gpu = self._gpu()
        if not result.gpu.available:
            result.unavailable.append("gpu")
        try:
            source = Path("/sys/devices/system/clocksource/clocksource0/current_clocksource").read_text().strip()
            result.clocksource = source if source.replace("_", "").isalnum() and len(source) <= 40 else None
        except OSError:
            pass
        return result

    def _cpu(self) -> CpuMetrics:
        counters = psutil.cpu_times()._asdict()
        # Linux guest times are already included in user/nice.
        total = sum(value for name, value in counters.items() if name not in {"guest", "guest_nice"})
        idle = counters.get("idle", 0) + counters.get("iowait", 0)
        percent = None
        if self._cpu_previous:
            delta = total - self._cpu_previous[0]
            idle_delta = idle - self._cpu_previous[1]
            if delta > 0 and 0 <= idle_delta <= delta:
                percent = _number(100 * (delta - idle_delta) / delta, 100)
        self._cpu_previous = total, idle
        count = _integer(psutil.cpu_count())
        return CpuMetrics(percent=percent, logical_count=count if count else None)

    @staticmethod
    def _memory() -> MemoryMetrics:
        memory = psutil.virtual_memory()
        total, available = _integer(memory.total), _integer(memory.available)
        # Match psutil's usage percent: reclaimable cache is available memory.
        used = total - available if total is not None and available is not None and available <= total else None
        return MemoryMetrics(used_bytes=used, total_bytes=total, percent=_number(memory.percent, 100))

    def _storage(self) -> StorageMetrics:
        disk = psutil.disk_usage(str(self._data_dir))
        return StorageMetrics(
            free_bytes=_integer(disk.free), total_bytes=_integer(disk.total),
            percent=_number(disk.percent, 100),
        )

    def _process(self) -> ProcessMetrics:
        process = psutil.Process()
        now = time.monotonic()
        times = process.cpu_times()
        cpu_time = times.user + times.system
        percent = None
        if self._process_previous:
            elapsed = now - self._process_previous[0]
            if elapsed > 0:
                percent = _number(100 * (cpu_time - self._process_previous[1]) / elapsed)
        self._process_previous = now, cpu_time
        return ProcessMetrics(
            uptime_seconds=_number(time.time() - process.create_time()),
            rss_bytes=_integer(process.memory_info().rss), cpu_percent=percent,
        )

    @staticmethod
    def _cpu_temperature() -> float | None:
        read = getattr(psutil, "sensors_temperatures", None)
        if not read:
            return None
        # Never label arbitrary disk, motherboard or GPU temperatures as CPU.
        groups = read()
        values = [
            value
            for name in ("coretemp", "k10temp", "cpu_thermal", "cpu-thermal")
            for sensor in groups.get(name, [])
            if (value := _number(sensor.current, 150)) is not None
        ]
        return max(values) if values else None

    @staticmethod
    def _gpu() -> GpuMetrics:
        executable = shutil.which("nvidia-smi")
        if not executable:
            # WSL exposes the driver utility here without always adding it to PATH.
            wsl_binary = Path("/usr/lib/wsl/lib/nvidia-smi")
            executable = str(wsl_binary) if wsl_binary.is_file() else None
        if not executable:
            return GpuMetrics()
        try:
            response = subprocess.run(
                [executable, "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2,
                text=True, encoding="utf-8", errors="replace", check=False,
            )
            if response.returncode != 0 or len(response.stdout) > 65536:
                return GpuMetrics()
            devices: list[GpuDeviceMetrics] = []
            for row in csv.reader(response.stdout.splitlines()):
                if len(row) != 7 or len(devices) >= 16:
                    continue
                index = _number(row[0], 1024)
                name = row[1].strip()
                if index is None or not index.is_integer() or not name or len(name) > 100 or not name.isprintable():
                    continue
                devices.append(GpuDeviceMetrics(
                    index=int(index), name=name,
                    utilization_percent=_number(row[2], 100),
                    memory_used_mib=_number(row[3]), memory_total_mib=_number(row[4]),
                    temperature_c=_number(row[5], 150), power_watts=_number(row[6], 2000),
                ))
            return GpuMetrics(available=bool(devices), devices=devices)
        except (OSError, subprocess.SubprocessError, ValueError, csv.Error):
            return GpuMetrics()
