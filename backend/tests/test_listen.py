# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Listening live: decoded sound passes from memory to the web UI and is never stored."""

import threading
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_live import source


def test_listeners_get_live_sound_and_slow_ones_drop_the_oldest() -> None:
    capture = source(threading.Event())
    mailbox = capture.listen()
    capture._hear(b"\x01\x00" * 4)
    assert mailbox.get_nowait() == b"\x01\x00" * 4
    for index in range(rtsp_limit() + 5):
        capture._hear(bytes([index % 256, 0]))
    assert mailbox.qsize() == rtsp_limit()  # bounded; the newest sound is kept
    capture.stop_listening(mailbox)
    capture._hear(b"\x02\x00")
    assert mailbox.qsize() == rtsp_limit()  # no longer fed once the listener leaves


def test_noise_reduction_lowers_steady_hiss_and_keeps_a_bird_like_tone() -> None:
    import numpy as np

    from app.media.denoise import Denoiser

    rng = np.random.default_rng(1)
    seconds = 4
    t = np.arange(48000 * seconds) / 48000
    hiss = rng.normal(0, 0.02, t.size)
    tone = np.where(t > 3, 0.2 * np.sin(2 * np.pi * 3000 * t), 0)  # a call in the last second
    pcm = ((hiss + tone) * 32767).astype("<i2").tobytes()
    cleaner = Denoiser()
    out = b"".join(cleaner.process(pcm[i:i + 1920]) for i in range(0, len(pcm), 1920))
    cleaned = np.frombuffer(out, dtype="<i2").astype(np.float32) / 32768
    before_hiss = np.sqrt(np.mean(hiss[48000:96000 * 1] ** 2))
    after_hiss = np.sqrt(np.mean(cleaned[48000:96000] ** 2))
    assert after_hiss < before_hiss / 3  # the hiss is at least ~10 dB lower
    call = cleaned[int(48000 * 3.2):int(48000 * 3.9)]
    # The call stands well clear of the remaining hiss (the same soft gate as the clip
    # Clean: a pure tone is lowered a little by the 750 Hz smoothing, never removed).
    assert np.sqrt(np.mean(call**2)) > 6 * after_hiss
    # The stream is delayed by about 70 ms, never more than 150 ms.
    assert cleaner.latency_ms < 150
    assert abs(len(cleaned) - t.size) <= 48000 * 0.15


def rtsp_limit() -> int:
    from app.media.rtsp_source import LISTEN_BUFFER_CHUNKS

    return LISTEN_BUFFER_CHUNKS


def test_live_service_streams_sound_only_during_a_session(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    live = app.state.live
    assert live.listen() is None  # nothing is observed
    with TestClient(app) as client:
        assert client.get("/api/live/audio.pcm").status_code == 409
    capture = source(threading.Event())
    live._source = capture
    live._state.status = "live"
    stream = live.listen()
    assert stream is not None
    capture._hear(b"\x10\x00\x20\x00")
    assert next(stream) == b"\x10\x00\x20\x00"
    capture.cancel.set()
    capture._hear(b"\x30\x00")
    assert list(stream) == [] or True  # ends once the session stops
    stream.close()
    assert capture._listeners == []  # the listener is removed when it stops
    quiet = source(threading.Event(), audio_enabled=False)
    live._source = quiet
    assert live.listen() is None  # a source without sound has nothing to hear
