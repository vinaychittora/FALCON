# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Independent sensor history; observations never act as the sampling clock."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas_sensors import SensorHistoryPage, SensorReading, SensorReadingWrite
from app.storage.database import Database


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Sensor times must include a timezone")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class SensorReplayConflict(ValueError):
    pass


# Thinning (10 Nov 2026): temperature and humidity move over hours, so 30-second rows
# are kept for a day (rain detail, the weather stamped on each visit) and older ones are
# thinned to one per 10 minutes plus every row where something moved fast.
KEEP_ALL_HOURS = 24
THIN_MINUTES = 10
BIG_STEP = {"temperature_c": 1.0, "humidity_percent": 5.0, "pressure_hpa": 1.0}


def keep_row(previous: dict | None, row: dict, bucket: str, previous_bucket: str | None) -> bool:
    """Keep the first row of each 10-minute bucket, and any row where rain starts or
    stops, the quality changes, or a value moved a lot since the last kept row."""
    if previous is None or bucket != previous_bucket:
        return True
    if row.get("surface_wet") != previous.get("surface_wet") or row.get("quality") != previous.get("quality"):
        return True
    for name, step in BIG_STEP.items():
        a, b = row.get(name), previous.get(name)
        if a is not None and b is not None and abs(a - b) >= step:
            return True
    return False


class SensorStore:
    def __init__(self, database: Database):
        self.database = database
        with database.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sensor_readings (
                    reading_id TEXT PRIMARY KEY,
                    sensor_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sensor_readings_time
                    ON sensor_readings(observed_at, reading_id);
                CREATE INDEX IF NOT EXISTS sensor_readings_node_time
                    ON sensor_readings(sensor_id, observed_at, reading_id);
                """
            )

    def ingest(
        self, reading: SensorReadingWrite, *, received_at: datetime | None = None,
    ) -> tuple[SensorReading, bool]:
        received_at = received_at or datetime.now(UTC)
        utc_text(received_at)
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT payload FROM sensor_readings WHERE reading_id=?", (reading.reading_id,),
            ).fetchone()
            if previous:
                stored = SensorReading.model_validate_json(previous["payload"])
                if stored.model_dump(exclude={"received_at"}) != reading.model_dump():
                    raise SensorReplayConflict("A different measurement already uses this reading ID")
                return stored, False
            if reading.observed_at > received_at + timedelta(seconds=5):
                raise ValueError("Sensor measurement time is ahead of the server clock")
            stored = SensorReading(**reading.model_dump(), received_at=received_at)
            connection.execute(
                "INSERT INTO sensor_readings VALUES (?, ?, ?, ?, ?, ?)",
                (
                    stored.reading_id, stored.sensor_id, utc_text(stored.observed_at),
                    utc_text(stored.received_at), stored.quality, stored.model_dump_json(),
                ),
            )
        return stored, True

    def node_ids(self) -> list[str]:
        # Two is enough to detect an ambiguous unconfigured deployment.
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT sensor_id FROM sensor_readings ORDER BY sensor_id LIMIT 2"
            ).fetchall()
        return [row["sensor_id"] for row in rows]

    def latest(self, sensor_id: str, at: datetime) -> SensorReading | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM sensor_readings WHERE sensor_id=? AND observed_at<=? "
                "ORDER BY observed_at DESC, received_at DESC, reading_id DESC LIMIT 1",
                (sensor_id, utc_text(at)),
            ).fetchone()
        return SensorReading.model_validate_json(row["payload"]) if row else None

    def history(
        self, *, limit: int = 100, offset: int = 0, sensor_id: str | None = None,
        observed_from: datetime | None = None, observed_to: datetime | None = None,
    ) -> SensorHistoryPage:
        limit, offset = min(500, max(1, limit)), max(0, offset)
        if observed_from and observed_to and observed_from > observed_to:
            raise ValueError("The sensor history start must precede its end")
        conditions, parameters = [], []
        if sensor_id is not None:
            conditions.append("sensor_id=?")
            parameters.append(sensor_id)
        if observed_from is not None:
            conditions.append("observed_at>=?")
            parameters.append(utc_text(observed_from))
        if observed_to is not None:
            conditions.append("observed_at<=?")
            parameters.append(utc_text(observed_to))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.database.connection() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM sensor_readings" + where, parameters,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT payload FROM sensor_readings" + where
                + " ORDER BY observed_at DESC, reading_id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
        return SensorHistoryPage(
            readings=[SensorReading.model_validate_json(row["payload"]) for row in rows],
            total=total, limit=limit, offset=offset,
        )

    def compact(self, now: datetime | None = None, backup: Path | None = None) -> tuple[int, int]:
        """Thin rows older than KEEP_ALL_HOURS. Returns (rows before, rows after).

        backup, when given and not yet present, first receives a full copy of the table
        (the one-off migration of the old 30-second history keeps everything there).
        """
        cutoff = utc_text((now or datetime.now(UTC)) - timedelta(hours=KEEP_ALL_HOURS))
        with self.database.connection() as connection:
            before = connection.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
            if backup is not None and not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                connection.execute("ATTACH DATABASE ? AS backup", (str(backup),))
                connection.execute("CREATE TABLE backup.sensor_readings AS SELECT * FROM sensor_readings")
                connection.commit()
                connection.execute("DETACH DATABASE backup")
                backup.chmod(0o600)
            rows = connection.execute(
                "SELECT reading_id, sensor_id, observed_at, payload FROM sensor_readings "
                "WHERE observed_at < ? ORDER BY sensor_id, observed_at, reading_id", (cutoff,),
            ).fetchall()
            drop: list[str] = []
            last: dict[str, tuple[dict, str]] = {}
            for row in rows:
                observed = datetime.fromisoformat(row["observed_at"])
                bucket = observed.replace(
                    minute=observed.minute - observed.minute % THIN_MINUTES, second=0, microsecond=0,
                ).isoformat()
                values = json.loads(row["payload"])
                kept = last.get(row["sensor_id"])
                if keep_row(kept[0] if kept else None, values, bucket, kept[1] if kept else None):
                    last[row["sensor_id"]] = (values, bucket)
                else:
                    drop.append(row["reading_id"])
            connection.execute("BEGIN IMMEDIATE")
            for start in range(0, len(drop), 500):
                part = drop[start:start + 500]
                connection.execute(
                    f"DELETE FROM sensor_readings WHERE reading_id IN ({','.join('?' * len(part))})", part,
                )
            connection.commit()
        return before, before - len(drop)

    def series(
        self, sensor_id: str | None, start: datetime, end: datetime, step_seconds: int,
    ) -> list[dict[str, object]]:
        """Averages per time step for the graph: temperature, humidity, pressure and the
        share of readings with a wet plate (0 to 1). Steps without readings are left out."""
        condition, parameters = "observed_at>=? AND observed_at<=? AND quality='valid'", [
            utc_text(start), utc_text(end),
        ]
        if sensor_id is not None:
            condition += " AND sensor_id=?"
            parameters.append(sensor_id)
        origin = start.timestamp()
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT CAST((strftime('%s', substr(observed_at, 1, 19)) - ?) / ? AS INTEGER) AS step, "
                "AVG(json_extract(payload, '$.temperature_c')) AS temperature_c, "
                "AVG(json_extract(payload, '$.humidity_percent')) AS humidity_percent, "
                "AVG(json_extract(payload, '$.pressure_hpa')) AS pressure_hpa, "
                "AVG(CASE json_extract(payload, '$.surface_wet') WHEN 1 THEN 1.0 WHEN 0 THEN 0.0 END) AS wet, "
                "COUNT(*) AS readings FROM sensor_readings WHERE " + condition
                + " GROUP BY step ORDER BY step",
                [origin, step_seconds, *parameters],
            ).fetchall()
        return [
            {
                "at": datetime.fromtimestamp(origin + (row["step"] + 0.5) * step_seconds, UTC).isoformat(
                    timespec="seconds"
                ),
                "temperature_c": _round(row["temperature_c"], 2),
                "humidity_percent": _round(row["humidity_percent"], 1),
                "pressure_hpa": _round(row["pressure_hpa"], 1),
                "wet": _round(row["wet"], 2),
                "readings": row["readings"],
            }
            for row in rows
        ]


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
