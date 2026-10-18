"""Real, independently recorded environmental measurements in explicit SI units."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$"
SensorTimestamp = Annotated[datetime, AwareDatetime]


class SensorReadingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    # 1.1 adds surface_wet: a rain-plate wetness state (rain or dew), not rainfall.
    schema_version: Literal["1.0", "1.1"] = "1.0"
    reading_id: str = Field(pattern=IDENTIFIER)
    sensor_id: str = Field(pattern=IDENTIFIER)
    observed_at: SensorTimestamp
    temperature_c: float | None = Field(default=None, ge=-80, le=85, strict=True)
    humidity_percent: float | None = Field(default=None, ge=0, le=100, strict=True)
    pressure_hpa: float | None = Field(default=None, ge=300, le=1200, strict=True)
    surface_wet: bool | None = Field(default=None, strict=True)
    quality: Literal["valid", "suspect", "invalid"] = "valid"
    quality_note: str | None = Field(default=None, max_length=200)

    @field_validator("observed_at")
    @classmethod
    def utc_observed_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def has_measurement(self) -> "SensorReadingWrite":
        if all(value is None for value in (
            self.temperature_c, self.humidity_percent, self.pressure_hpa, self.surface_wet,
        )):
            raise ValueError("A sensor reading must contain at least one real measurement")
        if self.surface_wet is not None and self.schema_version == "1.0":
            raise ValueError("surface_wet requires schema version 1.1")
        return self


class SensorReading(SensorReadingWrite):
    received_at: SensorTimestamp

    @field_validator("received_at")
    @classmethod
    def utc_received_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class SensorIngestResult(BaseModel):
    reading: SensorReading
    created: bool


class SensorHistoryPage(BaseModel):
    readings: list[SensorReading] = Field(default_factory=list)
    total: int = 0
    limit: int = 100
    offset: int = 0
