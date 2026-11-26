# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Keep optional model-library network reporting out of local inference."""

import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from app.services.downloads import download_checked


def test_dependency_imports_disable_reporting_without_blocking_model_downloads(tmp_path: Path) -> None:
    # A fresh, non-pytest interpreter is essential: Ultralytics otherwise disables
    # reporting merely because pytest is running, masking a production regression.
    script = """
import os
import socket

attempts = []
def forbidden_network(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("Dependency import attempted a network operation")

socket.getaddrinfo = forbidden_network
socket.socket.connect = forbidden_network
socket.socket.connect_ex = forbidden_network

import app
from huggingface_hub import constants
from huggingface_hub.utils import send_telemetry
from ultralytics.utils import AUTOINSTALL, ONLINE, TESTS_RUNNING
from ultralytics.utils.events import events

assert not TESTS_RUNNING, "This check must exercise production dependency behavior"
assert not ONLINE and not AUTOINSTALL and not events.enabled
assert constants.HF_HUB_DISABLE_TELEMETRY
assert constants.HF_HUB_DISABLE_IMPLICIT_TOKEN
assert constants.HF_HUB_DISABLE_UPDATE_CHECK
assert not constants.HF_HUB_OFFLINE, "Explicit public model downloads must remain available"
send_telemetry("falcon-test-no-network")
assert attempts == []
print("privacy import checks passed")
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST")}
    env.update({
        "YOLO_CONFIG_DIR": str(tmp_path / "yolo"),
        "HF_HOME": str(tmp_path / "huggingface"),
        "HF_HUB_OFFLINE": "0",
        # Simulate conflicting ambient settings: application policy must win.
        "DO_NOT_TRACK": "0",
        "HF_HUB_DISABLE_TELEMETRY": "0",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "0",
        "HF_HUB_DISABLE_UPDATE_CHECK": "0",
        "YOLO_OFFLINE": "false",
        "YOLO_AUTOINSTALL": "true",
    })
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, text=True, capture_output=True,
        timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "privacy import checks passed" in result.stdout


def test_explicit_checked_model_download_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = b"synthetic public model fixture"
    calls: list[tuple[str, str]] = []

    class Response:
        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self, chunk_size: int) -> Iterator[bytes]:
            yield data

    @contextmanager
    def stream(method: str, url: str, **kwargs: Any) -> Iterator[Response]:
        calls.append((method, url))
        yield Response()

    monkeypatch.setattr("app.services.downloads.httpx.stream", stream)
    target = tmp_path / "model.bin"
    download_checked(
        "https://models.example/fixture", target, hashlib.md5(data).hexdigest(), len(data)
    )
    assert calls == [("GET", "https://models.example/fixture")]
    assert target.read_bytes() == data
