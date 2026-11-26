# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Camera self-heal: a picture that stays damaged is restarted at the node.

16 Nov 10:12: after a node stream restart the camera sent whole JPEGs whose picture
data was damaged inside, frame after frame, until its stream was restarted. The capture
refuses such frames; this decides what to do when it keeps happening. Fixed rules:

- damaged for DAMAGE_RESTART_SECONDS (30 s): ask the node to restart its camera, at most
  once per RESTART_GAP_SECONDS (30 min);
- still damaged DAMAGE_WARN_SECONDS (2 min) after that restart: show it (amber camera
  on Live, a row on System -> Live status suggesting a node restart);
- each episode is logged with its times and counts when the picture is clean again.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DAMAGE_RESTART_SECONDS = 30.0
DAMAGE_WARN_SECONDS = 120.0
RESTART_GAP_SECONDS = 1800.0
CHECK_SECONDS = 5.0


class CameraHeal:
    def __init__(
        self, restart: Callable[[], object] | None, log_path: Path | None,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.restart = restart
        self.log_path = log_path
        self.wall = wall
        self.last_restart = -RESTART_GAP_SECONDS
        self.episode: dict[str, Any] | None = None

    def check(self, damaged_since: float | None, broken_frames: int, now: float) -> dict[str, Any]:
        """One check: returns the metrics to show (camera_damaged_since, camera_restarts)."""
        if damaged_since is None:
            if self.episode:
                self._close(broken_frames)
            return {"camera_damaged_since": ""}
        if self.episode is None:
            started = self.wall() - timedelta(seconds=max(0.0, now - damaged_since))
            self.episode = {
                "started_at": started.isoformat(timespec="seconds"), "restarts": 0,
                "first_broken": broken_frames, "restarted_at": None, "warned": False,
            }
        episode = self.episode
        lasted = now - damaged_since
        if lasted >= DAMAGE_RESTART_SECONDS and self.restart \
                and now - self.last_restart >= RESTART_GAP_SECONDS:
            self.last_restart = now
            episode["restarts"] += 1
            episode["restarted_at"] = now
            try:
                self.restart()
            except Exception:  # noqa: BLE001 - the node may be busy; the warning still follows
                pass
        restarted = episode["restarted_at"]
        if restarted is not None and now - restarted >= DAMAGE_WARN_SECONDS:
            episode["warned"] = True
        elif restarted is None and lasted >= DAMAGE_RESTART_SECONDS + DAMAGE_WARN_SECONDS:
            episode["warned"] = True  # no restart possible (gap or no node): still say so
        return {
            "camera_damaged_since": episode["started_at"] if episode["warned"] else "",
            "camera_restarts": episode["restarts"],
        }

    def _close(self, broken_frames: int) -> None:
        episode, self.episode = self.episode, None
        assert episode is not None
        record = {
            "started_at": episode["started_at"],
            "ended_at": self.wall().isoformat(timespec="seconds"),
            "damaged_frames": max(0, broken_frames - episode["first_broken"]),
            "camera_restarts": episode["restarts"],
            "warned": episode["warned"],
        }
        if self.log_path:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a") as handle:
                    handle.write(json.dumps(record) + "\n")
            except OSError:
                pass
