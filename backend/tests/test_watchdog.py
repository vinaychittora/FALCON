import asyncio
import os
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.media.base import Frame
from app.services.live import LiveService
from app.services.watchdog import SystemdHeartbeat, notify


def test_notify_is_silent_without_systemd() -> None:
    assert notify("WATCHDOG=1", {}) is False
    assert SystemdHeartbeat(lambda: True, {}).interval is None


def test_heartbeat_pings_only_while_healthy(tmp_path: Path) -> None:
    address = str(tmp_path / "notify.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
        receiver.bind(address)
        receiver.settimeout(2)
        environ = {"NOTIFY_SOCKET": address, "WATCHDOG_USEC": "3000000", "WATCHDOG_PID": str(os.getpid())}
        healthy = [True]
        heartbeat = SystemdHeartbeat(lambda: healthy[0], environ)
        assert heartbeat.interval == 1.0

        async def exercise() -> None:
            task = asyncio.create_task(heartbeat.run())
            await asyncio.sleep(0.05)
            healthy[0] = False
            await asyncio.sleep(1.2)
            task.cancel()

        asyncio.run(exercise())
        assert receiver.recv(64) == b"WATCHDOG=1"
        receiver.settimeout(0.05)
        try:
            extra = receiver.recv(64)
        except TimeoutError:
            extra = None
        assert extra is None


def test_heartbeat_ignores_a_watchdog_meant_for_another_process(tmp_path: Path) -> None:
    environ = {"NOTIFY_SOCKET": str(tmp_path / "x"), "WATCHDOG_USEC": "3000000", "WATCHDOG_PID": "1"}
    assert SystemdHeartbeat(lambda: True, environ).interval is None


def test_live_stuck_clock_ignores_outages_and_restarts_on_reconnect() -> None:
    analyzer = SimpleNamespace(lock=threading.Lock())
    live = LiveService(analyzer)  # type: ignore[arg-type]
    live._state.status = "live"
    live._state.metrics["inference_status"] = "processing"
    live._progress_at = time.monotonic() - 200
    assert live.stuck_for() >= 199
    live._status("reconnecting", "camera offline")
    assert live.stuck_for() == 0
    live._status("live", None)
    assert live.stuck_for() < 1
    live._frame(Frame(0, np.zeros((4, 4, 3), dtype=np.uint8)))
    assert live.stuck_for() < 1


def test_clock_status_is_unknown_without_timedatectl(monkeypatch) -> None:
    from app.services import clock

    monkeypatch.setattr(clock.shutil, "which", lambda _: None)
    assert clock.system_clock_synchronized() is None
