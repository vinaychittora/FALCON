# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""FALCON local application."""

import os
import time

# FALCON times frames, sound windows and recordings with time.monotonic(). On Linux
# that clock follows the kernel's NTP speed setting; 14 Nov under WSL something set
# that setting 8.3 % fast (adjtimex tick 10833 instead of 10000) minutes after every
# boot, so every duration ran 8 % long and saved sound had holes. The raw hardware
# clock (CLOCK_MONOTONIC_RAW) ignores that setting and measured +0.09 % against the
# sensor node. Installed before any FALCON module captures time.monotonic.
if hasattr(time, "CLOCK_MONOTONIC_RAW"):
    _RAW = time.CLOCK_MONOTONIC_RAW

    def _raw_monotonic() -> float:
        return time.clock_gettime(_RAW)

    time.monotonic = _raw_monotonic

# Apply before any inference dependencies import and cache their settings.
# FALCON performs inference locally; optional vendor analytics, connectivity
# probes and automatic package installation are not part of that operation.
# These process-local settings do not block explicit model/taxonomy downloads.
os.environ.update({
    "DO_NOT_TRACK": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "HF_HUB_DISABLE_UPDATE_CHECK": "1",
    "YOLO_OFFLINE": "true",
    "YOLO_AUTOINSTALL": "false",
})
