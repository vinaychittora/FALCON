"""Real periodic sensor history and event-time lookup, independent of inference."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from app.schemas import EnvironmentReading
from app.schemas_sensors import SensorHistoryPage, SensorReading, SensorReadingWrite
from app.storage.database import Database
from app.storage.sensors import SensorStore


class SensorProvider(Protocol):
    def snapshot(self, captured_at: datetime | None) -> EnvironmentReading: ...


class DisconnectedSensors:
    def snapshot(self, captured_at: datetime | None = None) -> EnvironmentReading:
        return EnvironmentReading()

    def current(self) -> EnvironmentReading:
        return EnvironmentReading()


class SensorHistoryProvider:
    def __init__(
        self, database: Database, *, sensor_id: str | None = None,
        stale_after_seconds: float = 120,
    ):
        if not 0 < stale_after_seconds <= 86400:
            raise ValueError("Use a positive sensor freshness interval of at most one day")
        self.store = SensorStore(database)
        self.sensor_id, self.stale_after_seconds = sensor_id, stale_after_seconds
        # Set by the sensor-node manager: the node whose readings belong to current detections.
        self.preferred: Callable[[], str | None] | None = None

    def session_sensor_id(self) -> str | None:
        """The sensor recorded with a live session, used to associate readings in exports."""
        if self.sensor_id:
            return self.sensor_id
        preferred = self.preferred() if self.preferred else None
        if preferred:
            return preferred
        nodes = self.store.node_ids()
        return nodes[0] if len(nodes) == 1 else None

    def ingest(self, reading: SensorReadingWrite) -> tuple[SensorReading, bool]:
        return self.store.ingest(reading)

    def history(
        self, *, limit: int = 100, offset: int = 0, sensor_id: str | None = None,
        observed_from: datetime | None = None, observed_to: datetime | None = None,
    ) -> SensorHistoryPage:
        return self.store.history(
            limit=limit, offset=offset, sensor_id=sensor_id,
            observed_from=observed_from, observed_to=observed_to,
        )

    def current(self) -> EnvironmentReading:
        return self.snapshot(datetime.now(UTC))

    def snapshot(self, captured_at: datetime | None) -> EnvironmentReading:
        # Uploaded files have no trusted wall-clock capture time. Never attach
        # current weather, even after physical sensors have been connected.
        if captured_at is None:
            return EnvironmentReading()
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            return EnvironmentReading(status="unavailable")
        sensor_id = self.sensor_id or (self.preferred() if self.preferred else None)
        if sensor_id is None:
            nodes = self.store.node_ids()
            if not nodes:
                return EnvironmentReading()
            if len(nodes) != 1:
                return EnvironmentReading(status="unavailable")
            sensor_id = nodes[0]
        reading = self.store.latest(sensor_id, captured_at)
        if reading is None:
            return EnvironmentReading(status="unavailable", sensor_id=sensor_id)
        age = max(0, (captured_at - reading.observed_at).total_seconds())
        if reading.quality != "valid":
            return EnvironmentReading(
                status="unavailable", sensor_id=sensor_id,
                observed_at=reading.observed_at.isoformat(), age_seconds=round(age, 2),
            )
        return EnvironmentReading(
            status="fresh" if age <= self.stale_after_seconds else "stale",
            sensor_id=sensor_id, observed_at=reading.observed_at.isoformat(),
            age_seconds=round(age, 2), temperature_c=reading.temperature_c,
            humidity_percent=reading.humidity_percent, pressure_hpa=reading.pressure_hpa,
            surface_wet=reading.surface_wet,
        )
