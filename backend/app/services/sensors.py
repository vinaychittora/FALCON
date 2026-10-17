"""Sensor boundary for a future live source. Never pair today's reading with an old file."""

from datetime import datetime
from typing import Protocol

from app.schemas import EnvironmentReading


class SensorProvider(Protocol):
    def snapshot(self, captured_at: datetime | None) -> EnvironmentReading: ...


class DisconnectedSensors:
    def snapshot(self, captured_at: datetime | None = None) -> EnvironmentReading:
        return EnvironmentReading()
