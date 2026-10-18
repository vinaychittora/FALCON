"""FALCON sensor node: camera, microphone and weather sensors for a FALCON inference node.

The node streams video and sound over RTSP, measures temperature, humidity,
pressure and rain-plate wetness, and offers a small signed HTTP API that the
inference node uses to read status, change settings and collect readings.
Standard library only, so it runs on the system Python of Raspberry Pi OS.
"""

VERSION = "1.0.0"
API_VERSION = 1
