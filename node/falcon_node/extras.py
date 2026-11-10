"""Optional Raspberry Pi extras that cost power and heat, switched on only when wanted.

The node keeps only what it needs running. These extras are off by default and can be
started and stopped from FALCON (or the phone page):

* hotspot: the "falcon-hotspot" Wi-Fi network for setting up the camera from a phone
  (created by setup-hotspot.sh). Turning it off disconnects any phone using it.
* bluetooth: the Bluetooth service.

"Start at boot" is the node's own setting (the installer turns NetworkManager's own
autoconnect off), so the node only needs permission to bring a connection up or down
and to start or stop bluetooth.service. install.sh grants exactly that through polkit.
"""

import logging
import shutil
from typing import Any

from falcon_node.system import run

log = logging.getLogger("falcon-node.extras")

HOTSPOT = "falcon-hotspot"
EXTRAS: dict[str, dict[str, str]] = {
    "hotspot": {
        "label": "Wi-Fi hotspot \"falcon\"",
        "note": "For setting up the camera from a phone (http://10.42.0.1:8780/mobile). "
                "Turning it off disconnects any phone using it.",
    },
    "bluetooth": {
        "label": "Bluetooth",
        "note": "Not used by FALCON. Leave off unless another device needs it.",
    },
}


def _lines(command: list[str]) -> list[str]:
    result = run(command, timeout=15)
    return result.stdout.splitlines() if result and result.returncode == 0 else []


def state(name: str) -> dict[str, Any]:
    """{available, on} for one extra."""
    if name == "hotspot":
        if not shutil.which("nmcli"):
            return {"available": False, "on": False}
        available = HOTSPOT in _lines(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        on = HOTSPOT in _lines(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
        return {"available": available, "on": on}
    if name == "bluetooth":
        result = run(["systemctl", "is-active", "bluetooth.service"], timeout=10)
        enabled = run(["systemctl", "cat", "bluetooth.service"], timeout=10)
        available = bool(enabled and enabled.returncode == 0)
        return {"available": available, "on": bool(result and result.stdout.strip() == "active")}
    raise KeyError(name)


def switch(name: str, on: bool) -> None:
    """Start or stop one extra now. Raises ValueError with a message for the web UI."""
    if name == "hotspot":
        command = ["nmcli", "connection", "up" if on else "down", HOTSPOT]
    elif name == "bluetooth":
        command = ["systemctl", "start" if on else "stop", "--no-ask-password", "bluetooth.service"]
    else:
        raise KeyError(name)
    if not state(name)["available"]:
        raise ValueError(f"{EXTRAS[name]['label']} is not set up on this node")
    result = run(command, timeout=30)
    if result is None or result.returncode != 0:
        raise ValueError(
            f"{EXTRAS[name]['label']} could not be switched {'on' if on else 'off'}. "
            "Re-run the node installer so it may control it."
        )
    log.info("%s switched %s", name, "on" if on else "off")
