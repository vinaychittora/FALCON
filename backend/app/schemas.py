from datetime import date
from string import Formatter
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Video(BaseModel):
    media_kind: Literal["video", "image", "audio"] = "video"
    source_id: str
    filename: str
    duration_ms: int
    width: int
    height: int
    fps: float
    codec: str
    audio: bool
    size_bytes: int
    start_time_s: float = 0
    audio_start_s: float = 0
    playback_warning: str | None = None
    bitrate_bps: int | None = None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    container: str | None = None


class VideoCatalog(BaseModel):
    videos: list[Video]
    errors: list[str]


Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
BBox = tuple[Unit, Unit, Unit, Unit]
ClassifierMode = Literal["bioclip_2", "bioclip_2_5", "ensemble"]


class AnalysisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sample_fps: float = Field(default=2, ge=0.5, le=5)
    detector_threshold: float = Field(default=0.25, ge=0.01, le=0.99)
    species_threshold: float = Field(default=0.22, ge=-1, le=1)
    ambiguity_margin: float = Field(default=0.025, ge=0, le=1)
    detector_size: Literal[320, 640, 960] = 640
    max_proposals: int = Field(default=12, ge=1, le=50)
    fixed_camera: bool = False
    small_animal_mode: bool = False
    roi: BBox = (0, 0, 1, 1)
    audio_enabled: bool = True
    birdnet_confidence: float = Field(default=0.5, ge=0.01, le=0.99)
    site_lat: float | None = Field(default=None, ge=-90, le=90)
    site_lon: float | None = Field(default=None, ge=-180, le=180)
    recording_date: date | None = None
    week: int | None = Field(default=None, ge=1, le=48)
    device: Literal["auto", "cuda", "cpu"] = "auto"
    classifier_mode: ClassifierMode = "bioclip_2"
    log_non_wildlife: bool = False
    min_crop_side: int = Field(default=32, ge=8, le=256)
    min_sharpness: float = Field(default=12, ge=0, le=500)
    crops_per_track: int = Field(default=3, ge=1, le=8)
    prompt_templates: list[str] = Field(
        default_factory=lambda: [
            "{scientific_name}",
            "a photograph of {scientific_name}",
            "{common_name}, {scientific_name}",
        ]
    )
    max_seconds: float | None = Field(default=None, gt=0, le=86400)

    @model_validator(mode="after")
    def valid_configuration(self) -> "AnalysisSettings":
        x1, y1, x2, y2 = self.roi
        if x1 >= x2 or y1 >= y2:
            raise ValueError("ROI must have positive width and height")
        if (self.site_lat is None) != (self.site_lon is None):
            raise ValueError("Set both latitude and longitude, or neither")
        if not 1 <= len(self.prompt_templates) <= 6:
            raise ValueError("Use 1–6 prompt templates")
        for template in self.prompt_templates:
            if len(template) > 200 or "{scientific_name}" not in template:
                raise ValueError(
                    "Each prompt must contain {scientific_name} and be at most 200 characters"
                )
            try:
                fields = list(Formatter().parse(template))
                if any(
                    field is not None
                    and (
                        field not in {"scientific_name", "common_name"}
                        or specification
                        or conversion
                    )
                    for _, field, specification, conversion in fields
                ):
                    raise ValueError("Unsupported prompt placeholder")
            except ValueError as exc:
                raise ValueError(
                    "Only scientific_name and common_name placeholders are supported"
                ) from exc
        return self


class Candidate(BaseModel):
    taxon_id: int
    scientific_name: str
    common_name: str | None
    group: str
    score: float


class ModelEvidence(BaseModel):
    model: str
    version: str
    status: Literal["candidate", "unknown"]
    score: float | None = None
    margin: float | None = None
    top_k: list[Candidate] = Field(default_factory=list)
    unknown_reason: str | None = None


class Classification(BaseModel):
    broad_group: str = "organism"
    scientific_name: str | None = None
    common_name: str | None = None
    score: float | None = None
    margin: float | None = None
    status: Literal["candidate", "unknown", "non_wildlife"] = "unknown"
    display_label: str = "Unknown organism"
    unknown_reason: str | None = None
    top_k: list[Candidate] = Field(default_factory=list)
    model_evidence: list[ModelEvidence] = Field(default_factory=list)
    consensus: Literal["single", "agree", "disagree", "insufficient_evidence"] = "single"


class Review(BaseModel):
    # discarded: not useful for the dataset (duplicate, blurred, empty frame). Kept in the
    # audit trail, hidden from the working archive and left out of clean exports.
    status: Literal["unreviewed", "correct", "false_positive", "corrected", "unknown", "discarded"] = (
        "unreviewed"
    )
    corrected_taxon_id: int | None = None
    corrected_scientific_name: str | None = None
    corrected_common_name: str | None = None
    notes: str | None = Field(default=None, max_length=2000)
    updated_at: str | None = None


class DetectorResult(BaseModel):
    label: str
    score: float | None
    model: str


class EnvironmentReading(BaseModel):
    """Absence is explicit; uploaded media has no trusted wall-clock capture time."""

    status: Literal["not_connected", "unavailable", "fresh", "stale"] = "not_connected"
    sensor_id: str | None = None
    observed_at: str | None = None
    age_seconds: float | None = None
    temperature_c: float | None = None
    humidity_percent: float | None = None
    pressure_hpa: float | None = None
    surface_wet: bool | None = None


class EvidenceSummary(BaseModel):
    evidence_id: str
    media_kind: Literal["video", "audio"]
    status: Literal["pending", "ready", "partial", "failed"]
    duration_ms: int = 0
    captured_at: str
    audio_present: bool = False
    mime_type: str
    message: str | None = None
    actual_start_ms: int | None = None
    actual_end_ms: int | None = None


class ObservationContext(BaseModel):
    captured_at: str | None = None
    time_basis: Literal["server_receive_time", "source_relative_time_only", "unknown"] = "unknown"
    source_kind: Literal["live", "file", "unknown"] = "unknown"
    evidence_summaries: list[EvidenceSummary] = Field(default_factory=list)


class VisualEvent(ObservationContext):
    schema_version: str = "0.1"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    source_id: str
    source_filename: str
    modality: Literal["visual"] = "visual"
    timestamp_ms: int
    duration_ms: int
    track_id: str
    bbox_norm: BBox
    detector: DetectorResult
    classification: Classification
    models: dict[str, str]
    environment: EnvironmentReading = Field(default_factory=EnvironmentReading)
    review: Review = Field(default_factory=Review)


class AudioEvent(ObservationContext):
    schema_version: str = "0.1"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    source_id: str
    source_filename: str
    modality: Literal["audio"] = "audio"
    start_ms: int
    end_ms: int
    scientific_name: str
    common_name: str
    confidence: float
    model: str = "BirdNET GLOBAL 6K V2.4"
    models: dict[str, str]
    environment: EnvironmentReading = Field(default_factory=EnvironmentReading)
    review: Review = Field(default_factory=Review)


Event = Annotated[VisualEvent | AudioEvent, Field(discriminator="modality")]


class Job(BaseModel):
    job_id: str
    source_id: str
    status: Literal[
        "queued", "running", "pausing", "paused", "completed", "cancelled", "failed", "interrupted"
    ] = "queued"
    stage: str = "queued"
    progress: float = 0
    coverage_ms: int = 0
    visual_count: int = 0
    audio_count: int = 0
    audio_status: str = "pending"
    created_at: str
    finished_at: str | None = None
    error: str | None = None
    messages: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    analysis_config: dict[str, object] = Field(default_factory=dict)
    can_resume: bool = False
    resume_from_ms: int = 0
    resume_stage: Literal["visual", "audio"] = "visual"
    resume_reason: str | None = None


class CurrentDetections(BaseModel):
    visual: list[VisualEvent]
    audio: list[AudioEvent]
