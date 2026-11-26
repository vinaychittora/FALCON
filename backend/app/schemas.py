# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
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
# "ensemble" (both models cross-checking) was removed on 10 Nov 2026; old saved
# settings and jobs that name it are read as BioCLIP 2.5.
ClassifierMode = Literal["bioclip_2", "bioclip_2_5"]


# Tuning fixed at the values that work on this rig (10 Nov 2026 clean-up). They stay
# fields so file tests, replays and the CPU fallback can vary them, but saved settings
# and the Configuration page never change them: load_analysis_settings resets them.
FIXED_SETTINGS = (
    "sample_fps", "species_threshold", "group_threshold", "ambiguity_margin",
    "likely_similarity", "likely_margin", "mixed_groups", "scenery_forget_hours",
    "likely_frames", "detector_size", "max_proposals", "fixed_camera", "small_animal_mode",
    "birdnet_confidence", "sound_bout_gap_seconds", "sound_bout_max_minutes",
    "clip_pre_seconds", "clip_post_seconds", "flicker_step", "flicker_flips_per_minute",
    "flicker_hold_seconds", "still_object_minutes", "recording_date", "week", "device",
    "log_non_wildlife", "min_crop_side", "min_sharpness", "crops_per_track",
    "prompt_templates", "max_seconds",
)
# Chosen for this rig (10 Nov 2026): fixed too, but not the schema defaults that
# file tests rely on. The 3 % edges keep the pillar out of the picture.
RIG_SETTINGS: dict[str, object] = {
    "detector_threshold": 0.5,
    "roi": (0.03, 0.0, 0.97, 1.0),
    "crop_left_percent": 0,
    "crop_right_percent": 0,
    "classifier_mode": "bioclip_2_5",
}


class AnalysisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sample_fps: float = Field(default=3, ge=0.5, le=5)
    detector_threshold: float = Field(default=0.25, ge=0.01, le=0.99)
    species_threshold: float = Field(default=0.33, ge=-1, le=1)
    # Below the species threshold, a lower bar still allows "unknown bird / mammal"
    # when the strongest candidates agree on the group.
    group_threshold: float = Field(default=0.15, ge=-1, le=1)
    ambiguity_margin: float = Field(default=0.025, ge=0, le=1)
    # "Likely" needs more than a species name: on 8 Nov the bowl and a dead leaf were
    # named at similarity 0.38-0.41 with a gap under 0.02, real birds at 0.50-0.55.
    likely_similarity: float = Field(default=0.45, ge=-1, le=1)
    # Last night's cat (a real visit) held a gap of 0.02-0.03; the bowl and leaf <= 0.02.
    likely_margin: float = Field(default=0.02, ge=0, le=1)
    # Top-five candidates from this many groups (frog, otter, bee...) = not an animal
    # the model recognises: named "Unidentified animal", never a species.
    mixed_groups: int = Field(default=3, ge=2, le=5)
    # Scenery spots (the bowl) not hit for this long are forgotten (1 hour to 30 days).
    scenery_forget_hours: float = Field(default=48.0, ge=1, le=720)
    # A visit is "Likely" only when this many sampled frames agree on the species.
    likely_frames: int = Field(default=3, ge=1, le=20)
    detector_size: Literal[320, 640, 960] = 960
    max_proposals: int = Field(default=10, ge=1, le=50)
    fixed_camera: bool = False
    small_animal_mode: bool = False
    roi: BBox = (0, 0, 1, 1)
    audio_enabled: bool = True
    birdnet_confidence: float = Field(default=0.4, ge=0.01, le=0.99)
    # Repeated calls of one species form one visit until this much silence passes,
    # or the visit reaches the maximum length.
    sound_bout_gap_seconds: int = Field(default=120, ge=0, le=1800)
    sound_bout_max_minutes: int = Field(default=15, ge=1, le=120)
    # Saved clip per visit (video and sound): from this long before the first detected
    # frame or call to this long after it. An animal that stays gets back-to-back clips.
    # Cut this much off the left and right of the camera picture (percent of the width),
    # e.g. mounting posts at the edges of a wide 16:9 mode. Applies to Live, detection
    # and clips alike, so box positions stay consistent.
    crop_left_percent: int = Field(default=0, ge=0, le=30)
    crop_right_percent: int = Field(default=0, ge=0, le=30)
    clip_pre_seconds: int = Field(default=5, ge=1, le=12)
    clip_post_seconds: int = Field(default=5, ge=2, le=20)
    # Camera hunting between day and night: hold detections while the picture
    # brightness jumps by more than flicker_step this many times a minute.
    flicker_step: int = Field(default=20, ge=5, le=128)
    flicker_flips_per_minute: int = Field(default=6, ge=2, le=120)
    flicker_hold_seconds: int = Field(default=60, ge=10, le=600)
    # A box found in nearly the same place for most of this many minutes is part of the
    # scene (the water bowl, a stone) and is no longer recorded. 0 turns this off.
    still_object_minutes: int = Field(default=3, ge=0, le=60)
    site_lat: float | None = Field(default=None, ge=-90, le=90)
    site_lon: float | None = Field(default=None, ge=-180, le=180)
    recording_date: date | None = None
    week: int | None = Field(default=None, ge=1, le=48)
    device: Literal["auto", "cuda", "cpu"] = "auto"
    classifier_mode: ClassifierMode = "bioclip_2_5"
    log_non_wildlife: bool = False
    # Paint people gray in previews, review images and saved clips. Off shows them as
    # filmed; they are still never recorded as observations.
    mask_people: bool = True
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

    def saved(self) -> dict[str, object]:
        """What settings.json keeps: only the settings a person chooses."""
        return self.model_dump(mode="json", exclude={*FIXED_SETTINGS, *RIG_SETTINGS})

    @model_validator(mode="before")
    @classmethod
    def removed_ensemble(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("classifier_mode") == "ensemble":
            return {**data, "classifier_mode": "bioclip_2_5"}
        return data

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


Certainty = Literal["likely", "probable", "possible", "unknown"]


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
    # How far the evidence goes: likely (a species, green), probable (a few look-alikes,
    # often one genus, orange), possible (a faint best guess, red), unknown (gray).
    certainty: Certainty = "unknown"
    # Shared genus of the look-alikes, when they agree on one.
    genus: str | None = None
    # The candidates too close to separate (the top one first).
    contenders: list[Candidate] = Field(default_factory=list)


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
    status: Literal["pending", "ready", "partial", "failed", "removed"]
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
    # The visit this frame belongs to (live, from 8 Nov 2026, spec Phase 1): may span
    # several tracks or a restart. Records without it were graded by the old rules.
    visit_id: str | None = None


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
    # Shared by repeated calls of one species heard close together: one visit.
    bout_id: str | None = None
    # Second opinion from the cleaned sound (18 Nov 2026); None on older records.
    cleaned_score: float | None = None
    cleaned_agrees: bool | None = None
    # A bird not recorded in Rajasthan (24 Nov 2026): an "Unidentified sound" whose name is
    # BirdNET's guess, hidden until reviewed. None on older records or without the list.
    outside_area: bool | None = None
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
