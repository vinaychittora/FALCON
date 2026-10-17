"""Independent sensor history; observations never act as the sampling clock."""

from datetime import UTC, datetime, timedelta

from app.schemas_sensors import SensorHistoryPage, SensorReading, SensorReadingWrite
from app.storage.database import Database


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Sensor times must include a timezone")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


class SensorReplayConflict(ValueError):
    pass


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
