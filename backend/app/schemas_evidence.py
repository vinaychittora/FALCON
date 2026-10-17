"""Durable, review-independent evidence records."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_timestamp(value: str | datetime) -> str:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("A timezone-aware capture timestamp is required")
    return moment.astimezone(UTC).isoformat()


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    source_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    session_id: str
    job_id: str
    media_kind: Literal["video", "audio"]
    status: Literal["pending", "ready", "partial", "failed"] = "pending"
    relative_path: str | None = None
    captured_at: str
    requested_start_ms: int = Field(ge=0)
    requested_end_ms: int = Field(gt=0)
    actual_start_ms: int | None = Field(default=None, ge=0)
    actual_end_ms: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    mime_type: Literal["video/mp4", "audio/wav"]
    audio_present: bool = False
    clock_basis: Literal["server_receive_time"] = "server_receive_time"
    message: str | None = Field(default=None, max_length=1000)
    event_ids: list[str] = Field(default_factory=list)

    _utc = field_validator("captured_at")(utc_timestamp)

    @model_validator(mode="after")
    def ordered(self) -> "EvidenceRecord":
        if self.requested_end_ms <= self.requested_start_ms:
            raise ValueError("Evidence end must follow its start")
        if (self.actual_start_ms is None) != (self.actual_end_ms is None):
            raise ValueError("Both actual interval endpoints are required")
        if self.actual_start_ms is not None and self.actual_end_ms is not None:
            if self.actual_end_ms <= self.actual_start_ms:
                raise ValueError("Actual evidence end must follow its start")
        if self.media_kind == "video" and self.mime_type != "video/mp4":
            raise ValueError("Video evidence must use the video/mp4 MIME type")
        if self.media_kind == "audio" and self.mime_type != "audio/wav":
            raise ValueError("Audio evidence must use the audio/wav MIME type")
        if self.status in {"ready", "partial"} and not (
            self.relative_path and self.sha256 and self.size_bytes and self.duration_ms
            and self.actual_start_ms is not None
        ):
            raise ValueError("Available evidence requires a file, checksum and actual interval")
        return self


class EvidencePage(BaseModel):
    evidence: list[EvidenceRecord]


class EvidenceSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    source_id: str
    name: str
    started_at: str
    clock_basis: Literal["server_receive_time"] = "server_receive_time"
    settings: dict[str, object] = Field(default_factory=dict)
    ended_at: str | None = None
    status: str = "running"
    metrics: dict[str, float | int | str] = Field(default_factory=dict)

    _utc = field_validator("started_at")(utc_timestamp)
