import json
import subprocess
import threading
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router
from app.remote_access import RemoteAccessMiddleware, RemoteAccessService
from app.security import LocalRequestPolicyMiddleware
from app.services import system_metrics as metrics
from app.services.system_metrics import SystemMetricsSampler


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    value = [100.0]
    monkeypatch.setattr(metrics.time, "monotonic", lambda: value[0])
    return value


@pytest.fixture
def sampler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SystemMetricsSampler:
    monkeypatch.setattr(SystemMetricsSampler, "_gpu", lambda _: metrics.GpuMetrics())
    monkeypatch.setattr(SystemMetricsSampler, "_cpu_temperature", lambda _: None)
    return SystemMetricsSampler(tmp_path)


def test_first_sample_and_cpu_delta_do_not_invent_zero_utilization(
    sampler: SystemMetricsSampler, clock: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:
    Cpu = namedtuple("Cpu", "user system idle iowait guest guest_nice")
    counters = iter((Cpu(10, 5, 80, 5, 2, 1), Cpu(16, 6, 82, 6, 3, 2)))
    monkeypatch.setattr(metrics.psutil, "cpu_times", lambda: next(counters))
    monkeypatch.setattr(metrics.psutil, "cpu_count", lambda: 4)
    first = sampler.snapshot()
    assert first.cpu.percent is None
    assert first.cpu.logical_count == 4
    assert first.cpu.temperature_c is None
    assert first.gpu.available is False and first.gpu.devices == []
    clock[0] += 5
    second = sampler.snapshot()
    assert second.cpu.percent == 70.0
    assert second.sample_age_seconds == 0
    assert second.sampled_at is not None


def test_cache_reuses_sample_and_does_not_allow_response_mutation(
    sampler: SystemMetricsSampler, clock: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect = Mock(wraps=sampler._collect)
    monkeypatch.setattr(sampler, "_collect", collect)
    first = sampler.snapshot()
    first.unavailable.append("mutated")
    clock[0] += 4
    second = sampler.snapshot()
    assert collect.call_count == 1
    assert second.sample_age_seconds == 4
    assert "mutated" not in second.unavailable
    clock[0] += 1
    sampler.snapshot()
    assert collect.call_count == 2


def test_concurrent_requests_share_one_probe(
    sampler: SystemMetricsSampler, monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = threading.Event(), threading.Event()

    def collect() -> metrics.SystemMetrics:
        started.set()
        assert release.wait(timeout=3)
        return sampler._empty()

    collect_mock = Mock(side_effect=collect)
    monkeypatch.setattr(sampler, "_collect", collect_mock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sampler.snapshot)
        assert started.wait(timeout=3)
        try:
            second = pool.submit(sampler.snapshot).result(timeout=1)
            assert second.sampling is True and second.sampled_at is None
            assert collect_mock.call_count == 1
        finally:
            release.set()
        assert first.result(timeout=2).sampling is False


def test_failed_sample_is_cached_and_never_leaks_exception_or_old_values(
    sampler: SystemMetricsSampler, clock: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:
    sampler.snapshot()
    clock[0] += 5
    collect = Mock(side_effect=RuntimeError("/private/data password=SECRET rtsp://camera.test"))
    monkeypatch.setattr(sampler, "_collect", collect)
    result = sampler.snapshot()
    sampler.snapshot()
    assert collect.call_count == 1
    assert result.memory.total_bytes is None
    assert result.unavailable == ["sampling"]
    assert "SECRET" not in result.model_dump_json()
    assert "/private" not in result.model_dump_json()
    assert "camera.test" not in result.model_dump_json()


def test_component_failure_keeps_other_metrics_and_no_exception_text(
    sampler: SystemMetricsSampler, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics.psutil, "disk_usage", Mock(side_effect=OSError("private volume path")))
    result = sampler.snapshot()
    assert result.storage.free_bytes is None
    assert "storage" in result.unavailable
    assert result.memory.total_bytes is not None
    assert "private volume path" not in result.model_dump_json()


def test_process_cpu_uses_interval_instead_of_thread_local_percent(
    sampler: SystemMetricsSampler, clock: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = [2.0]
    process = SimpleNamespace(
        cpu_times=lambda: SimpleNamespace(user=value[0], system=1),
        create_time=lambda: 90,
        memory_info=lambda: SimpleNamespace(rss=1024),
    )
    monkeypatch.setattr(metrics.psutil, "Process", lambda: process)
    monkeypatch.setattr(metrics.time, "time", lambda: 100)
    first = sampler._process()
    assert first.cpu_percent is None and first.uptime_seconds == 10 and first.rss_bytes == 1024
    value[0] += 8
    clock[0] += 4
    assert sampler._process().cpu_percent == 200


def test_memory_usage_matches_available_memory_and_storage_uses_data_volume(
    sampler: SystemMetricsSampler, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics.psutil, "virtual_memory", lambda: SimpleNamespace(total=1000, available=400, percent=60))
    disk = Mock(return_value=SimpleNamespace(total=2000, free=300, percent=85))
    monkeypatch.setattr(metrics.psutil, "disk_usage", disk)
    result = sampler.snapshot()
    assert result.memory.used_bytes == 600 and result.memory.percent == 60
    assert result.storage.free_bytes == 300 and result.storage.total_bytes == 2000
    disk.assert_called_once_with(str(tmp_path))
    assert str(tmp_path) not in result.model_dump_json()


def test_wsl_scope_does_not_claim_windows_host_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics.platform, "system", lambda: "Linux")
    monkeypatch.setattr(metrics.platform, "release", lambda: "6.6.87.2-microsoft-standard-WSL2")
    snapshot = SystemMetricsSampler(tmp_path)._empty()
    assert snapshot.scope == "wsl"
    assert "not Windows host totals" in snapshot.scope_label


@pytest.mark.parametrize("value", ["N/A", "[Not Supported]", "nan", "inf", -1, True, None, "sensitive"])
def test_invalid_measurements_are_unavailable(value: object) -> None:
    assert metrics._number(value) is None


def test_cpu_temperature_ignores_disk_and_unrelated_sensor_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics.psutil, "sensors_temperatures", lambda: {
        "nvme": [SimpleNamespace(current=90)],
        "coretemp": [SimpleNamespace(current=42), SimpleNamespace(current=float("nan"))],
    }, raising=False)
    assert SystemMetricsSampler._cpu_temperature() == 42


def test_gpu_query_has_bounded_safe_arguments_and_optional_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics.shutil, "which", lambda name: "/driver/nvidia-smi")
    run = Mock(return_value=SimpleNamespace(
        returncode=0, stdout="0, NVIDIA GeForce RTX 3060 Ti, 35.123, 2048.22, 8192, 53, [Not Supported]\n",
    ))
    monkeypatch.setattr(metrics.subprocess, "run", run)
    result = SystemMetricsSampler._gpu()
    assert result.available is True
    assert result.devices[0].utilization_percent == 35.12
    assert result.devices[0].power_watts is None
    assert result.devices[0].memory_total_mib == 8192
    args, options = run.call_args
    assert args[0][0] == "/driver/nvidia-smi"
    assert "uuid" not in args[0][1] and "serial" not in args[0][1]
    assert options["timeout"] == 2 and options["stderr"] == subprocess.DEVNULL
    assert not options.get("shell")


def test_gpu_query_unavailable_does_not_need_cuda_or_run_a_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics.shutil, "which", lambda _: None)
    monkeypatch.setattr(metrics.Path, "is_file", lambda _: False)
    run = Mock()
    monkeypatch.setattr(metrics.subprocess, "run", run)
    result = SystemMetricsSampler._gpu()
    assert result.available is False and result.devices == []
    run.assert_not_called()


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired("secret command", 2, output="secret output"),
    OSError("/private/path failed"),
])
def test_gpu_failures_are_safe_unavailable_results(failure: Exception, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics.shutil, "which", lambda _: "/driver/nvidia-smi")
    monkeypatch.setattr(metrics.subprocess, "run", Mock(side_effect=failure))
    result = SystemMetricsSampler._gpu()
    assert result.available is False
    assert "secret" not in result.model_dump_json() and "/private" not in result.model_dump_json()


def test_malformed_gpu_values_do_not_make_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics.shutil, "which", lambda _: "/driver/nvidia-smi")
    monkeypatch.setattr(metrics.subprocess, "run", Mock(return_value=SimpleNamespace(
        returncode=0,
        stdout="invalid line\n0, Example GPU, nan, -10, inf, 999, N/A\n1.5, Wrong index, 2, 3, 4, 5, 6\n",
    )))
    result = SystemMetricsSampler._gpu()
    assert len(result.devices) == 1
    device = result.devices[0]
    assert device.utilization_percent is None and device.temperature_c is None
    assert device.memory_used_mib is None and device.memory_total_mib is None
    json.dumps(result.model_dump(), allow_nan=False)


def test_metrics_route_inherits_local_policy_and_no_store(
    tmp_path: Path, sampler: SystemMetricsSampler,
) -> None:
    app = FastAPI()
    app.state.config = SimpleNamespace(data_dir=tmp_path)
    app.state.system_metrics = sampler
    app.include_router(router)
    app.add_middleware(LocalRequestPolicyMiddleware)
    app.add_middleware(RemoteAccessMiddleware, service=RemoteAccessService(tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/system/metrics")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["storage"]["total_bytes"] is not None
        assert client.get("/api/system/metrics", headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert client.get("/api/system/metrics", headers={"Host": "untrusted.example"}).status_code == 403
        assert client.get("/api/system/metrics", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
