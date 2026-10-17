"""FALCON local application."""

import os

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
