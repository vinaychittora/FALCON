from types import SimpleNamespace
from typing import Any

import pytest

from falcon_node import extras
from falcon_node.agent import Agent
from falcon_node.config import NodeState
from tests import test_media_and_api
from tests.test_media_and_api import call

node = test_media_and_api.node  # the running-node pytest fixture


class FakePi:
    """nmcli and systemctl as seen on the node, with the hotspot and bluetooth set up."""

    def __init__(self, allowed: bool = True) -> None:
        self.hotspot = True
        self.bluetooth = False
        self.allowed = allowed
        self.commands: list[list[str]] = []

    def run(self, command: list[str], timeout: float = 5) -> Any:
        self.commands.append(command)
        ok = SimpleNamespace(returncode=0, stdout="")
        if command[:2] == ["nmcli", "-t"]:
            names = ["Wired connection 1"] + (["falcon-hotspot"] if "--active" not in command or self.hotspot else [])
            return SimpleNamespace(returncode=0, stdout="\n".join(names) + "\n")
        if command[:2] == ["nmcli", "connection"]:
            if not self.allowed:
                return SimpleNamespace(returncode=4, stdout="")
            self.hotspot = command[2] == "up"
            return ok
        if command[:2] == ["systemctl", "is-active"]:
            return SimpleNamespace(returncode=0, stdout="active\n" if self.bluetooth else "inactive\n")
        if command[:2] == ["systemctl", "cat"]:
            return ok
        if command[0] == "systemctl" and command[1] in {"start", "stop"}:
            self.bluetooth = command[1] == "start"
            return ok
        raise AssertionError(command)


@pytest.fixture
def pi(monkeypatch: pytest.MonkeyPatch) -> FakePi:
    fake = FakePi()
    monkeypatch.setattr(extras, "run", fake.run)
    monkeypatch.setattr(extras.shutil, "which", lambda name: "/usr/bin/" + name)
    return fake


def test_extras_report_state_and_switch_on_demand(node: tuple[Agent, str], pi: FakePi) -> None:
    agent, base = node
    status, body = call(base, "GET", "/api/v1/system/extras")
    items = {item["name"]: item for item in body["extras"]}
    assert status == 200 and items["hotspot"]["on"] and not items["bluetooth"]["on"]
    assert "disconnects any phone" in items["hotspot"]["note"] and "thermal" in body
    status, body = call(base, "PUT", "/api/v1/system/extras", {"name": "hotspot", "on": False})
    assert status == 200 and not pi.hotspot and ["nmcli", "connection", "down", "falcon-hotspot"] in pi.commands
    status, body = call(base, "PUT", "/api/v1/system/extras", {"name": "bluetooth", "on": True, "at_boot": True})
    assert status == 200 and pi.bluetooth
    assert NodeState(agent.config.state_dir / "state.json").extras_at_boot == {"bluetooth": True}
    for bad in ({"name": "hdmi", "on": True}, {"name": "hotspot"}, {"name": "hotspot", "on": "yes"}):
        status, _ = call(base, "PUT", "/api/v1/system/extras", bad)
        assert status == 422
    status, _ = call(base, "GET", "/api/v1/system/extras", key="ZZZZ-EFGH-IJKL-MNOP-QRST-UVWX")
    assert status == 401


def test_missing_permission_gives_a_clear_message(node: tuple[Agent, str], pi: FakePi) -> None:
    _, base = node
    pi.allowed = False
    status, body = call(base, "PUT", "/api/v1/system/extras", {"name": "hotspot", "on": False})
    assert status == 422 and "Re-run the node installer" in body["detail"]


def test_extras_chosen_for_boot_start_but_are_never_switched_off(node: tuple[Agent, str], pi: FakePi) -> None:
    agent, _ = node
    pi.hotspot = False
    agent.state.extras_at_boot = {"hotspot": True, "bluetooth": False}
    agent._start_extras()
    assert pi.hotspot and not any(command[:2] == ["systemctl", "stop"] for command in pi.commands)
