# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas_sensors import SensorReadingWrite
from app.storage.database import Database
from app.storage.sensors import SensorStore

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def fill(store: SensorStore, start: datetime, minutes: int, *, wet_at: set[int] = frozenset(),
         jump_at: int | None = None) -> None:
    for i in range(minutes * 2):  # one reading every 30 seconds
        at = start + timedelta(seconds=30 * i)
        store.ingest(SensorReadingWrite(
            schema_version="1.1", reading_id=f"r{int(at.timestamp())}", sensor_id="falcon-node", observed_at=at,
            temperature_c=25.0 + (3.0 if jump_at is not None and i >= jump_at else 0.0) + 0.01 * (i % 3),
            humidity_percent=60.0, pressure_hpa=980.0, surface_wet=i in wet_at,
        ), received_at=at + timedelta(seconds=1))


def count(store: SensorStore) -> int:
    with store.database.connection() as connection:
        return connection.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]


def test_old_rows_thin_to_ten_minutes_but_keep_rain_and_jumps(tmp_path: Path) -> None:
    store = SensorStore(Database(tmp_path / "falcon.sqlite3"))
    old = NOW - timedelta(days=2)
    # One hour of 30 s readings two days ago: rain on the plate at minute 20 (readings
    # 40-41), and a 3 degree jump at minute 45.
    fill(store, old, 60, wet_at={40, 41}, jump_at=90)
    recent = NOW - timedelta(hours=2)
    fill(store, recent, 30)
    backup = tmp_path / "backups" / "sensor_readings-before-thinning.sqlite3"
    before, after = store.compact(now=NOW, backup=backup)
    assert before == 120 + 60 and after == count(store)
    # Last day untouched: all 60 recent rows stay.
    recent_rows = store.history(observed_from=recent, limit=500).total
    assert recent_rows == 60
    kept = sorted(r.observed_at for r in store.history(observed_to=old + timedelta(hours=1), limit=500).readings)
    minutes = [round((t - old).total_seconds() / 60, 1) for t in kept]
    # The first row of each 10-minute step, rain starting (20.0) and stopping (21.0),
    # and the temperature jump at 45.
    assert {0.0, 10.0, 20.0, 21.0, 30.0, 40.0, 45.0, 50.0} <= set(minutes)
    assert len(kept) <= 10
    # The old table was copied once before anything was removed.
    with sqlite3.connect(backup) as copy:
        assert copy.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0] == before
    # Running again changes nothing and does not overwrite the backup.
    assert store.compact(now=NOW, backup=backup) == (after, after)


def test_series_endpoint_answers_for_each_range(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        for hours in (24, 168, 720):
            answer = client.get(f"/api/sensors/series?hours={hours}")
            assert answer.status_code == 200 and answer.json()["points"] == []
        assert client.get("/api/sensors/series?hours=5").status_code == 422


def test_series_averages_per_step_with_rain_share(tmp_path: Path) -> None:
    store = SensorStore(Database(tmp_path / "falcon.sqlite3"))
    start = NOW - timedelta(hours=1)
    fill(store, start, 20, wet_at={0, 1, 2, 3, 4})  # 40 readings, rain in the first 2.5 min
    points = store.series("falcon-node", start, NOW, 300)
    assert len(points) == 4  # 20 minutes in 5-minute steps
    assert points[0]["wet"] == 0.5 and points[1]["wet"] == 0.0
    assert 25.0 <= points[0]["temperature_c"] <= 25.02  # type: ignore[operator]
    assert points[0]["readings"] == 10 and points[0]["humidity_percent"] == 60.0
