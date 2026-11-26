# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Service tests render isolated files and mock systemctl; never alter host services."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.test_server import server

spec = importlib.util.spec_from_file_location(
    "falcon_systemd_installer", Path(__file__).resolve().parents[2] / "scripts" / "systemd_service.py"
)
assert spec and spec.loader
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def fixture_installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "installation"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "serve.sh").write_text("#!/bin/bash\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return root


def test_unit_supervises_foreground_server_and_restarts_without_secrets(tmp_path: Path) -> None:
    root = tmp_path / 'field $camera %north "mark"'
    unit = service.render(root)
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit
    assert "UMask=0077" in unit
    assert "NoNewPrivileges=true" in unit
    assert "KillMode=control-group" in unit
    assert " serve.sh" not in unit
    assert 'serve.sh" run' in unit
    assert "$$camera" in unit and "%%north" in unit
    assert '\\"mark\\"' in unit
    assert "password" not in unit.lower()
    assert "Type=exec" in unit
    assert "WatchdogSec=600" in unit and "NotifyAccess=main" in unit
    with pytest.raises(SystemExit, match="control characters"):
        service.render(tmp_path / "bad\npath")


def test_enable_installs_private_unit_without_starting_or_stopping_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fixture_installation(tmp_path, monkeypatch)
    commands = Mock(return_value=SimpleNamespace(stdout="", returncode=0))
    monkeypatch.setattr(service, "systemctl", commands)
    path = service.install(root, enable=True)
    assert path.stat().st_mode & 0o777 == 0o600
    assert service.owned(root)
    actions = [call.args[0] for call in commands.call_args_list]
    assert actions == ["show", "show", "daemon-reload", "enable"]
    assert not any("--now" in call.args for call in commands.call_args_list)
    assert not service.owned(root / "different")


def test_existing_unowned_unit_and_replacement_link_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fixture_installation(tmp_path, monkeypatch)
    path = service.unit_path()
    path.parent.mkdir(parents=True)
    path.write_text("An unrelated application")
    command = Mock()
    monkeypatch.setattr(service, "systemctl", command)
    with pytest.raises(SystemExit, match="not replaced"):
        service.install(root, enable=True)
    assert path.read_text() == "An unrelated application"
    command.assert_not_called()
    path.unlink()
    outside = tmp_path / "outside"
    outside.write_text("keep")
    path.symlink_to(outside)
    with pytest.raises(SystemExit, match="not replaced"):
        service.install(root)
    assert outside.read_text() == "keep"


def test_install_refuses_a_different_loaded_unit_and_symlinked_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fixture_installation(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "fragment_path", lambda: "/tmp/another/falcon.service")
    with pytest.raises(SystemExit, match="already exists"):
        service.install(root)
    monkeypatch.setattr(service, "fragment_path", lambda: "")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "config").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit, match="must not be a symlink"):
        service.install(root)
    assert list(outside.iterdir()) == []


def test_control_requires_matching_installed_and_loaded_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fixture_installation(tmp_path, monkeypatch)
    path = service.unit_path()
    path.parent.mkdir(parents=True)
    path.write_text(service.render(root))
    monkeypatch.setattr(service, "fragment_path", lambda: "/tmp/other/falcon.service")
    command = Mock()
    monkeypatch.setattr(service, "systemctl", command)
    with pytest.raises(SystemExit, match="No service was changed"):
        service.control(root, "stop")
    command.assert_not_called()
    monkeypatch.setattr(service, "fragment_path", lambda: str(path))
    assert service.control(root, "disable") == 0
    command.assert_called_once_with("disable", "falcon.service")


def test_foreground_exec_uses_same_pid_and_disables_proxy_header_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "owned_pid", lambda _: None)
    monkeypatch.setattr(server, "ensure_startable", Mock())
    execute = Mock()
    monkeypatch.setattr(server.os, "execv", execute)
    assert server.run_foreground(tmp_path, tmp_path / "frontend") == 0
    command = execute.call_args.args[1]
    assert "--no-proxy-headers" in command
    # All interfaces; the application's own middleware refuses other devices by default.
    assert command[command.index("--host") + 1] == server.HOST
    assert json.loads((tmp_path / "server.json").read_text())["pid"] == os.getpid()
    assert (tmp_path / "server.json").stat().st_mode & 0o777 == 0o600


def test_failed_foreground_exec_cleans_ownership_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "owned_pid", lambda _: None)
    monkeypatch.setattr(server, "ensure_startable", Mock())
    monkeypatch.setattr(server.os, "execv", Mock(side_effect=OSError("fixture")))
    with pytest.raises(SystemExit, match="Could not execute"):
        server.run_foreground(tmp_path, tmp_path)
    assert not (tmp_path / "server.json").exists()


def test_enabling_service_does_not_take_over_manual_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = SimpleNamespace(
        status=Mock(return_value={"ActiveState": "inactive", "MainPID": "0"}),
        control=Mock(),
    )
    monkeypatch.setitem(sys.modules, "systemd_service", controller)
    monkeypatch.setattr(server, "owned_pid", lambda _: 1234)
    monkeypatch.setattr(server, "ready", lambda *_: True)
    monkeypatch.setattr(server, "health", lambda: {})
    assert server.service_action("start", tmp_path) == 0
    controller.control.assert_not_called()
    manual_stop = Mock(return_value=0)
    monkeypatch.setattr(server, "stop", manual_stop)
    assert server.service_action("stop", tmp_path) == 0
    manual_stop.assert_called_once_with(tmp_path)
    controller.control.assert_not_called()


def test_running_service_is_stopped_through_systemd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = SimpleNamespace(
        status=Mock(return_value={"ActiveState": "active", "MainPID": "1234"}),
        control=Mock(),
    )
    monkeypatch.setitem(sys.modules, "systemd_service", controller)
    monkeypatch.setattr(server, "owned_pid", lambda _: 1234)
    manual_stop = Mock()
    monkeypatch.setattr(server, "stop", manual_stop)
    assert server.service_action("stop", tmp_path) == 0
    controller.control.assert_called_once_with(server.ROOT, "stop")
    manual_stop.assert_not_called()
