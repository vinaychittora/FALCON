# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Camera and microphone as two capture processes on two paths (14 Nov 2026)."""

from falcon_node import media
from falcon_node.agent import MIC_MIN_GAP, Channel, microphone_retry_delay
from falcon_node.media import AUDIO_PATH, STREAM_PATH, Camera, CameraSettings, Microphone, MicrophoneSettings

USB = Camera("v4l2", "/dev/video0", "USB Camera", input_format="mjpeg")
HAT = Microphone("hw:Zero", "Zero", "DA7212 audio HAT", channels=2)


def test_camera_and_microphone_publish_separately_with_the_same_formats():
    settings = CameraSettings(video_codec="mjpeg")
    camera = media.build_pipeline(USB, settings, None, MicrophoneSettings(), f"rtsp://127.0.0.1:8554/{STREAM_PATH}")
    assert len(camera) == 1
    assert "alsa" not in camera[0] and "-c:v" in camera[0] and camera[0][-1].endswith(f"/{STREAM_PATH}")
    microphone = media.build_microphone_pipeline(
        HAT, MicrophoneSettings(audio_channel="right"), f"rtsp://127.0.0.1:8554/{AUDIO_PATH}",
    )
    command = microphone[0]
    assert "v4l2" not in command and command[-1].endswith(f"/{AUDIO_PATH}")
    # The same sound as before: the right channel, mono AAC 128 kbit/s at 48 kHz.
    assert "pan=mono|c0=c1" in command and command[command.index("-b:a") + 1] == "128k"
    assert command[command.index("-ar") + 1] == "48000"


def test_mediamtx_allows_both_paths():
    config = media.MediaServer("mediamtx", __import__("pathlib").Path("/tmp/x.yml"), 8554, 9997, "secret").render()
    assert f"path: {AUDIO_PATH}" in config and f"  {AUDIO_PATH}:\n    source: publisher" in config
    assert config.count(f"path: {AUDIO_PATH}") == 3  # local publish, local read, FALCON read


def test_the_microphone_restarts_gently():
    assert [microphone_retry_delay(n) for n in (1, 2, 3, 4, 5, 6)] == [5, 10, 20, 40, 60, 60]
    channel = Channel("microphone", microphone_retry_delay, MIC_MIN_GAP)
    assert channel.min_gap == 5.0 and not channel.alive()
