"""Group repeated sound detections of one species into a single visit (a "bout").

BirdNET reports every window in which a species is heard, so a bird singing for five
minutes used to become dozens of separate entries. A bout stays open while the same
species is heard again within ``gap_ms`` of its last call, up to ``max_ms`` in total;
after that the next call starts a new bout. Every window is still stored (its clip and
confidence stay reviewable); the shared ``bout_id`` makes them one visit in the lists.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import uuid4

from app.schemas import AudioEvent


@dataclass
class _Bout:
    bout_id: str
    start_ms: int
    last_end_ms: int


class SoundBouts:
    def __init__(self, gap_ms: int = 120_000, max_ms: int = 900_000):
        self.gap_ms = max(0, gap_ms)
        self.max_ms = max(1, max_ms)
        self._open: dict[str, _Bout] = {}

    def assign(self, event: AudioEvent) -> bool:
        """Set ``event.bout_id``; True when the event starts a new bout."""
        key = event.scientific_name
        bout = self._open.get(key)
        if (
            bout is not None
            and event.start_ms - bout.last_end_ms <= self.gap_ms
            and event.end_ms - bout.start_ms <= self.max_ms
        ):
            bout.last_end_ms = max(bout.last_end_ms, event.end_ms)
            event.bout_id = bout.bout_id
            return False
        bout = _Bout(f"bout-{uuid4().hex[:12]}", event.start_ms, event.end_ms)
        self._open[key] = bout
        event.bout_id = bout.bout_id
        return True

    def assign_all(self, events: Iterable[AudioEvent]) -> list[AudioEvent]:
        ordered = sorted(events, key=lambda item: (item.start_ms, item.scientific_name))
        for event in ordered:
            self.assign(event)
        return ordered

    def close(self) -> None:
        """Forget open bouts, e.g. when a session stops."""
        self._open.clear()
