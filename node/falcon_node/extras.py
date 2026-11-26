# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
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
import ipaddress
import shutil
from typing import Any

from falcon_node.system import run

log = logging.getLogger("falcon-node.extras")

HOTSPOT = "falcon-hotspot"
EXTRAS: dict[str, dict[str, str]] = {
    "hotspot": {
        "label": "Wi-Fi hotspot \"falcon\"",
        "note": "For setting up the camera from a phone. The address of the phone page appears "
                "here once the hotspot is on. Turning it off disconnects any phone using it.",
    },
    "bluetooth": {
        "label": "Bluetooth",
        "note": "Not used by FALCON. Leave off unless another device needs it.",
    },
}


def _lines(command: list[str]) -> list[str]:
    result = run(command, timeout=15)
    return result.stdout.splitlines() if result and result.returncode == 0 else []


HOTSPOT_AFTER = " Turning it off disconnects any phone using it."


def hotspot_address() -> str | None:
    """The hotspot's own address as NetworkManager reports it (e.g. "10.42.0.1/24"), or None."""
    for line in _lines(["nmcli", "-g", "IP4.ADDRESS", "connection", "show", HOTSPOT]):
        text = line.strip().split("|")[0].split("/")[0]
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if address.version == 4:
            return str(address)
    return None


def hotspot_note(on: bool) -> str:
    """The phone page's address read at run time (only while the hotspot is on)."""
    address = hotspot_address() if on else None
    if address:
        return f"For setting up the camera from a phone (http://{address}:8780/mobile)." + HOTSPOT_AFTER
    return EXTRAS["hotspot"]["note"]


def state(name: str) -> dict[str, Any]:
    """{available, on} for one extra."""
    if name == "hotspot":
        if not shutil.which("nmcli"):
            return {"available": False, "on": False}
        available = HOTSPOT in _lines(["nmcli", "-t", "-f", "NAME", "connection", "show"])
        on = HOTSPOT in _lines(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"])
        return {"available": available, "on": on, "note": hotspot_note(on)}
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
