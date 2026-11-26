# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""The saved scenery spots can be seen one by one, and one spot can be forgotten."""

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.inference.visits import Spot, VisitEngine
from app.main import create_app


def write_spots(data_dir: Path) -> None:
    now = time.time()
    engine = VisitEngine()
    engine.spots = [
        Spot(1, [0.3, 0.5, 0.6, 0.8], "scenery", now - 3600, now - 60, hits=1234),
        Spot(2, [0.1, 0.1, 0.2, 0.2], "maybe animal", now - 600, now - 30, hits=7, stale=True),
    ]
    engine.next_spot = 3
    engine.save(data_dir / "state" / "scenery.json", now)


def test_scenery_lists_each_spot_with_when_it_is_dropped(tmp_path: Path) -> None:
    write_spots(tmp_path)
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        data = client.get("/api/live/scenery").json()
    assert data["spots"] == 2 and data["stale"] == 1
    first, second = data["items"]
    assert first["id"] == 1 and first["kind"] == "scenery" and first["hits"] == 1234
    assert first["box"] == [0.3, 0.5, 0.6, 0.8] and first["stale"] is False
    assert second["kind"] == "maybe animal" and second["stale"] is True
    for item in data["items"]:
        assert item["first_seen"] < item["last_hit"] < item["drops_at"]
    # Scenery is dropped 48 h after its last match, "maybe animal" after 6 h.
    from datetime import datetime
    gap = lambda item: (datetime.fromisoformat(item["drops_at"]) - datetime.fromisoformat(item["last_hit"])).total_seconds()  # noqa: E731
    assert round(gap(first) / 3600) == 48 and round(gap(second) / 3600) == 6


def test_forget_one_spot_keeps_the_others(tmp_path: Path) -> None:
    write_spots(tmp_path)
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        assert client.post("/api/live/scenery/99/forget").status_code == 404
        data = client.post("/api/live/scenery/1/forget").json()
        assert data["spots"] == 1 and [item["id"] for item in data["items"]] == [2]
        assert [item["id"] for item in client.get("/api/live/scenery").json()["items"]] == [2]
    saved = json.loads((tmp_path / "state" / "scenery.json").read_text())
    assert [spot["spot_id"] for spot in saved["spots"]] == [2]
