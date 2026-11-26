// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
export interface Video {
  media_kind: "video" | "image" | "audio";
  source_id: string;
  filename: string;
  duration_ms: number;
  width: number;
  height: number;
  fps: number;
  codec: string;
  audio: boolean;
  size_bytes: number;
  playback_warning: string | null;
  bitrate_bps?: number | null;
  audio_codec?: string | null;
  audio_sample_rate?: number | null;
  audio_channels?: number | null;
  container?: string | null;
}
export interface Box {
  bbox_norm: [number, number, number, number];
  label: string;
  tone?: "candidate" | "probable" | "possible" | "unknown";
}
export interface Candidate {
  taxon_id: number;
  scientific_name: string;
  common_name: string | null;
  group: string;
  score: number;
}
export type ClassifierMode = "bioclip_2" | "bioclip_2_5" | "ensemble";
export interface ModelEvidence {
  model: string;
  version: string;
  status: "candidate" | "unknown";
  score: number | null;
  margin: number | null;
  top_k: Candidate[];
  unknown_reason: string | null;
}
export type ReviewStatus =
  | "unreviewed"
  | "correct"
  | "false_positive"
  | "corrected"
  | "unknown"
  | "discarded";
export interface Review {
  status: ReviewStatus;
  corrected_taxon_id: number | null;
  corrected_scientific_name: string | null;
  corrected_common_name?: string | null;
  notes: string | null;
  updated_at: string | null;
}
export interface EnvironmentReading {
  status: "not_connected" | "unavailable" | "fresh" | "stale";
  sensor_id: string | null;
  observed_at: string | null;
  age_seconds: number | null;
  temperature_c: number | null;
  humidity_percent: number | null;
  pressure_hpa: number | null;
  surface_wet?: boolean | null;
}
interface BaseEvent {
  captured_at?: string | null;
  time_basis?: "server_receive_time" | "source_relative_time_only" | "unknown";
  source_kind?: "live" | "file" | "unknown";
  evidence_summaries?: EvidenceSummary[];
  environment: EnvironmentReading;
  event_id: string;
  source_id: string;
  source_filename: string;
  job_id: string;
  models: Record<string, string>;
  review: Review;
}
export interface EvidenceSummary {
  evidence_id: string;
  media_kind: "video" | "audio";
  status: "pending" | "ready" | "partial" | "failed" | "removed";
  duration_ms: number;
  captured_at: string;
  audio_present: boolean;
  mime_type: string;
  message: string | null;
  actual_start_ms: number | null;
  actual_end_ms: number | null;
}
export interface VisualEvent extends BaseEvent {
  modality: "visual";
  timestamp_ms: number;
  duration_ms: number;
  track_id: string;
  /** The Phase 1 visit (from 8 Nov 2026); absent on records graded by the old rules. */
  visit_id?: string | null;
  bbox_norm: Box["bbox_norm"];
  detector: { label: string; score: number | null; model: string };
  classification: {
    broad_group: string;
    scientific_name: string | null;
    common_name: string | null;
    score: number | null;
    margin: number | null;
    status: "unknown" | "candidate" | "non_wildlife";
    display_label: string;
    unknown_reason: string | null;
    top_k: Candidate[];
    model_evidence?: ModelEvidence[];
    consensus?: "single" | "agree" | "disagree" | "insufficient_evidence";
    /** likely (green), probable (orange), possible (red), unknown (gray). */
    certainty?: Certainty;
    genus?: string | null;
    contenders?: Candidate[];
  };
}
export type Certainty = "likely" | "probable" | "possible" | "unknown";
export interface AudioEvent extends BaseEvent {
  modality: "audio";
  start_ms: number;
  end_ms: number;
  scientific_name: string;
  common_name: string;
  confidence: number;
  model: string;
  /** Second opinion from the cleaned sound; absent on records before 18 Nov 2026. */
  cleaned_score?: number | null;
  cleaned_agrees?: boolean | null;
  /** A bout's clearest call (set from Encounter.best_confidence when the list is fetched);
   * the tier and the card's number use it, like Live, the bell and the backend list. */
  bout_confidence?: number | null;
  /** A bird not recorded in Rajasthan (24 Nov 2026): an unidentified sound whose name is
   * BirdNET's guess. Absent on older records. */
  outside_area?: boolean | null;
}
export type Detection = VisualEvent | AudioEvent;
export interface Job {
  job_id: string;
  source_id: string;
  status:
    | "queued"
    | "running"
    | "pausing"
    | "paused"
    | "completed"
    | "cancelled"
    | "failed"
    | "interrupted";
  stage: string;
  progress: number;
  coverage_ms: number;
  can_resume?: boolean;
  resume_from_ms?: number;
  resume_reason?: string | null;
  resume_stage?: "visual" | "audio" | null;
  visual_count: number;
  audio_count: number;
  audio_status: string;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  messages: string[];
  metrics: Record<string, string | number>;
}
export interface Config {
  classifier_mode: ClassifierMode;
  sample_fps: number;
  detector_threshold: number;
  species_threshold: number;
  group_threshold: number;
  ambiguity_margin: number;
  detector_size: 320 | 640 | 960;
  max_proposals: number;
  fixed_camera: boolean;
  small_animal_mode: boolean;
  roi: [number, number, number, number];
  audio_enabled: boolean;
  birdnet_confidence: number;
  sound_bout_gap_seconds?: number;
  sound_bout_max_minutes?: number;
  still_object_minutes?: number;
  scenery_forget_hours?: number;
  crop_left_percent?: number;
  crop_right_percent?: number;
  clip_pre_seconds?: number;
  clip_post_seconds?: number;
  flicker_step?: number;
  flicker_flips_per_minute?: number;
  flicker_hold_seconds?: number;
  site_lat: number | null;
  site_lon: number | null;
  recording_date: string | null;
  week: number | null;
  device: "auto" | "cuda" | "cpu";
  log_non_wildlife: boolean;
  mask_people?: boolean;
  min_crop_side: number;
  min_sharpness: number;
  crops_per_track: number;
  prompt_templates: string[];
  max_seconds: number | null;
}
export interface Models {
  device: string;
  memory_mb: Record<string, number>;
  error: string | null;
  models: { name: string; version: string; loaded: boolean; device: string }[];
}

export interface LiveState {
  status:
    | "idle"
    | "connecting"
    | "live"
    | "reconnecting"
    | "stopping"
    | "stopped"
    | "failed";
  session_id: string | null;
  name: string | null;
  error: string | null;
  started_at: string | null;
  preview_timestamp_ms: number | null;
  session_timestamp_ms?: number;
  visual: VisualEvent[];
  audio: AudioEvent[];
  metrics: Record<string, string | number>;
  messages: string[];
  audio_status: string;
  /** Detection paused for camera work since (ISO), else null. */
  detection_paused_since?: string | null;
}
