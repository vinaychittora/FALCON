# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import threading
import time
from types import SimpleNamespace

from app.services import live as module
from app.services.live import LiveService


def service(monkeypatch):
    monkeypatch.setattr(module, "SOUND_STALL_SECONDS", 0.3)
    monkeypatch.setattr(module, "SOUND_RESTART_GAP_SECONDS", 60)
    monkeypatch.setattr(module, "SOUND_CHECK_SECONDS", 0.05)
    live = LiveService(SimpleNamespace(settings=SimpleNamespace(data_dir=None)))
    live._cancel = threading.Event()  # noqa: SLF001
    live._started = time.monotonic()  # noqa: SLF001
    live._state.status = "live"  # noqa: SLF001
    live._message = lambda *_: None  # noqa: SLF001
    return live


def test_silent_sound_is_flagged_and_the_node_stream_restarted_once(monkeypatch):
    live = service(monkeypatch)
    restarts = []
    live.restart_stream = lambda: restarts.append(time.monotonic())
    watcher = threading.Thread(target=live._watch_sound)  # noqa: SLF001
    watcher.start()
    time.sleep(0.8)
    assert live._state.metrics.get("audio_stalled_since")  # noqa: SLF001
    assert len(restarts) == 1  # not again within the restart gap
    # Sound arrives again: the stall clears.
    live._last_chunk_at = time.monotonic()  # noqa: SLF001
    time.sleep(0.15)
    assert live._state.metrics.get("audio_stalled_since") == ""  # noqa: SLF001
    live._cancel.set()  # noqa: SLF001
    watcher.join(2)


def test_flowing_sound_never_restarts(monkeypatch):
    live = service(monkeypatch)
    restarts = []
    live.restart_stream = lambda: restarts.append(1)
    watcher = threading.Thread(target=live._watch_sound)  # noqa: SLF001
    watcher.start()
    for _ in range(10):
        live._last_chunk_at = time.monotonic()  # noqa: SLF001
        time.sleep(0.08)
    live._cancel.set()  # noqa: SLF001
    watcher.join(2)
    assert not restarts and not live._state.metrics.get("audio_stalled_since")  # noqa: SLF001
