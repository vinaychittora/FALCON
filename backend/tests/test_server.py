# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Controller tests use temporary records and no application port or user data."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "falcon_server_controller", Path(__file__).resolve().parents[2] / "scripts" / "server.py"
)
assert spec and spec.loader
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_record_is_private_and_recycled_pid_is_not_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "ROOT", tmp_path)
    record = tmp_path / "server.json"
    server.save_record(record, os.getpid(), "not-the-start-time")
    assert record.stat().st_mode & 0o777 == 0o600
    assert server.owned_pid(record) is None
    assert json.loads(record.read_text())["root"] == str(tmp_path)


def test_unrelated_process_in_same_folder_cannot_be_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "ROOT", tmp_path)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        server.save_record(tmp_path / "server.json", child.pid, server.process_identity(child.pid))
        assert server.owned_pid(tmp_path / "server.json") is None
        assert server.stop(tmp_path) == 0
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_stop_rechecks_identity_after_opening_safe_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = Mock(side_effect=[1234, None])
    monkeypatch.setattr(server, "owned_pid", identity)
    descriptor = os.open("/dev/null", os.O_RDONLY)
    monkeypatch.setattr(server.os, "pidfd_open", Mock(return_value=descriptor))
    send = Mock()
    monkeypatch.setattr(server.signal, "pidfd_send_signal", send)
    assert server.stop(tmp_path) == 0
    send.assert_not_called()
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_stop_signals_only_the_pinned_managed_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "server.json"
    record.write_text("{}")
    monkeypatch.setattr(server, "owned_pid", Mock(side_effect=[1234, 1234, None]))
    descriptor = os.open("/dev/null", os.O_RDONLY)
    monkeypatch.setattr(server.os, "pidfd_open", Mock(return_value=descriptor))
    send = Mock()
    monkeypatch.setattr(server.signal, "pidfd_send_signal", send)
    assert server.stop(tmp_path) == 0
    send.assert_called_once_with(descriptor, server.signal.SIGTERM)
    assert not record.exists()


def test_ready_requires_managed_socket_and_built_falcon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "listening", lambda _: False)
    good = {"app": "falcon", "status": "ok", "frontend_ready": True}
    assert not server.ready(1234, good)
    monkeypatch.setattr(server, "listening", lambda _: True)
    assert server.ready(1234, good)
    assert not server.ready(1234, {"status": "ok"})
    assert not server.ready(1234, {**good, "frontend_ready": False})


def test_existing_starting_process_is_not_reported_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "owned_pid", lambda _: 1234)
    monkeypatch.setattr(server, "health", lambda: None)
    with pytest.raises(SystemExit, match="not ready"):
        server.start(tmp_path)


def test_busy_port_preserves_existing_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = tmp_path / "custom-ui"
    public.mkdir()
    (public / "index.html").write_text("build")
    monkeypatch.setattr(server, "owned_pid", lambda _: None)
    socket = Mock()
    socket.__enter__ = Mock(return_value=socket)
    socket.__exit__ = Mock(return_value=False)
    socket.bind.side_effect = OSError("fixture port in use")
    monkeypatch.setattr(server.socket, "socket", lambda: socket)
    launch = Mock()
    monkeypatch.setattr(server.subprocess, "Popen", launch)
    with pytest.raises(SystemExit, match="left running"):
        server.start(tmp_path, public)
    launch.assert_not_called()


def test_start_honors_custom_build_and_waits_for_its_own_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = tmp_path / "custom-ui"
    public.mkdir()
    (public / "index.html").write_text("build")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "owned_pid", lambda _: None)
    monkeypatch.setattr(server, "process_identity", lambda _: "fixture-start-time")
    socket = Mock()
    socket.__enter__ = Mock(return_value=socket)
    socket.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(server.socket, "socket", lambda: socket)
    child = SimpleNamespace(pid=1234, poll=lambda: None)
    launch = Mock(return_value=child)
    monkeypatch.setattr(server.subprocess, "Popen", launch)
    monkeypatch.setattr(
        server, "health", lambda: {"app": "falcon", "status": "ok", "frontend_ready": True}
    )
    listener = Mock(side_effect=[False, True])
    monkeypatch.setattr(server, "listening", listener)
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    assert server.start(tmp_path, public) == 0
    assert listener.call_count == 2
    assert (tmp_path / "server.log").stat().st_mode & 0o777 == 0o600
    record = json.loads((tmp_path / "server.json").read_text())
    assert record["pid"] == 1234 and record["started"] == "fixture-start-time"
    assert launch.call_args.kwargs["start_new_session"] is True
    assert "--no-access-log" in launch.call_args.args[0]


def test_control_lock_does_not_follow_replacement_links(tmp_path: Path) -> None:
    outside = tmp_path / "unrelated"
    outside.write_text("keep")
    link = tmp_path / "control.lock"
    link.symlink_to(outside)
    with pytest.raises(OSError):
        with server.control_lock(link):
            pass
    assert outside.read_text() == "keep"


def test_record_write_failure_does_not_leave_unmanaged_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.html").write_text("build")
    monkeypatch.setattr(server, "owned_pid", lambda _: None)
    monkeypatch.setattr(server, "process_identity", lambda _: "fixture-start-time")
    socket = Mock()
    socket.__enter__ = Mock(return_value=socket)
    socket.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(server.socket, "socket", lambda: socket)
    child = Mock(pid=1234)
    monkeypatch.setattr(server.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(server, "save_record", Mock(side_effect=OSError("fixture full disk")))
    with pytest.raises(SystemExit, match="startup was cancelled"):
        server.start(tmp_path, tmp_path)
    child.terminate.assert_called_once()
    child.wait.assert_called_once_with(timeout=5)
