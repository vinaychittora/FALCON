# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""FALCON sensor node: camera, microphone and weather sensors for a FALCON inference node.

The node streams video and sound over RTSP, measures temperature, humidity,
pressure and rain-plate wetness, and offers a small signed HTTP API that the
inference node uses to read status, change settings and collect readings.
Standard library only, so it runs on the system Python of Raspberry Pi OS.
"""

VERSION = "2.0.0"
API_VERSION = 1
