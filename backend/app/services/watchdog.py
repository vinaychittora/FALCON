"""Optional systemd watchdog heartbeat; silent outside a watchdog-enabled service.

The heartbeat is sent from the event loop, so a blocked server also stops it.
It stops deliberately when live analysis has been stuck for longer than the
allowed interval, letting systemd restart a process whose engine cannot recover.
"""

import asyncio
import os
import socket
from collections.abc import Callable, Mapping

# Longer than the appliance's own session restart, so in-process recovery goes first.
STUCK_RESTART_SECONDS = 900.0


def notify(message: str, environ: Mapping[str, str] = os.environ) -> bool:
    address = environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.connect(address)
            connection.sendall(message.encode("ascii"))
    except OSError:
        return False
    return True


class SystemdHeartbeat:
    def __init__(
        self, healthy: Callable[[], bool], environ: Mapping[str, str] = os.environ,
    ):
        self.healthy, self.environ = healthy, environ
        self.interval: float | None = None
        microseconds, owner = environ.get("WATCHDOG_USEC"), environ.get("WATCHDOG_PID")
        if microseconds and environ.get("NOTIFY_SOCKET") and owner in {None, "", str(os.getpid())}:
            try:
                # systemd recommends notifying at half the timeout or more often.
                self.interval = max(1.0, int(microseconds) / 1_000_000 / 3)
            except ValueError:
                self.interval = None

    async def run(self) -> None:
        if self.interval is None:
            return
        while True:
            if self.healthy():
                notify("WATCHDOG=1", self.environ)
            await asyncio.sleep(self.interval)
