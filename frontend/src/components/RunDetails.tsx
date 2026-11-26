// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { ClassifierMode, Job } from "../types";
import { classifierLabels } from "../api/models";
import Icon, { type IconName } from "./Icon";
import "./run-details.css";

const decimal = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatRunNumber(value: unknown, whole = false): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return (whole ? integer : decimal).format(value);
}

export function formatRunDuration(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
    return "—";
  const seconds = Math.floor(value);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [hours, minutes, seconds % 60]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

type Metric = { key: string; label: string; unit?: string; whole?: boolean };
const groups: { title: string; icon: IconName; fields: Metric[] }[] = [
  {
    title: "Visual processing",
    icon: "eye",
    fields: [
      { key: "sampled_frames", label: "Sampled frames", whole: true },
      { key: "classified_crops", label: "Classified crops", whole: true },
      { key: "scene_cuts", label: "Scene changes", whole: true },
      { key: "sample_fps", label: "Sampling rate", unit: "fps" },
      {
        key: "detector_passes_max",
        label: "Max detector passes / frame",
        whole: true,
      },
    ],
  },
  {
    title: "Inference timing",
    icon: "clock",
    fields: [
      {
        key: "detector_ms_per_sample",
        label: "Detector / sampled frame",
        unit: "ms",
      },
      { key: "classifier_ms_per_crop", label: "Classifier / crop", unit: "ms" },
      {
        key: "visual_elapsed_seconds",
        label: "Visual processing time",
        unit: "s",
      },
      { key: "detector_elapsed_seconds", label: "Detector time", unit: "s" },
      {
        key: "classifier_elapsed_seconds",
        label: "Classifier time",
        unit: "s",
      },
    ],
  },
  {
    title: "Compute & source",
    icon: "chip",
    fields: [
      { key: "device", label: "Inference device" },
      { key: "peak_vram_mb", label: "Recorded peak GPU memory", unit: "MiB" },
      { key: "peak_ram_mb", label: "Peak system memory", unit: "MiB" },
      {
        key: "detector_size",
        label: "Detector input",
        unit: "px",
        whole: true,
      },
      { key: "media_kind", label: "Media type" },
    ],
  },
];

const presented = new Set([
  ...groups.flatMap((group) => group.fields.map((field) => field.key)),
  "classifier_mode",
  "total_elapsed_seconds",
  "effective_processed_fps",
  "visual_metrics_scope",
]);

const additionalFields: Record<string, Omit<Metric, "key">> = {
  visual_detections: {
    label: "Visual detections in measured segments",
    whole: true,
  },
  audio_elapsed_seconds: { label: "Audio processing time", unit: "s" },
  audio_analysis_ratio: {
    label: "Audio compute / recording duration",
    unit: "×",
  },
  audio_peak_ram_mb: { label: "Peak audio process memory", unit: "MiB" },
  matched_birdnet_species: { label: "BirdNET taxonomy matches", whole: true },
};

function MetricValue({
  value,
  unit,
  whole,
}: {
  value: unknown;
  unit?: string;
  whole?: boolean;
}) {
  const text =
    typeof value === "string"
      ? value === "cuda" || value === "cpu"
        ? value.toUpperCase()
        : value
      : formatRunNumber(value, whole);
  return (
    <>
      {text}
      {unit && text !== "—" && <small>{unit}</small>}
    </>
  );
}

function Summary({
  icon,
  label,
  value,
  unit,
  caption,
}: {
  icon: IconName;
  label: string;
  value: string;
  unit?: string;
  caption: string;
}) {
  return (
    <div className="run-summary-item">
      <dt>
        <Icon name={icon} size={17} />
        {label}
      </dt>
      <dd>
        {value}
        {unit && value !== "—" && <small>{unit}</small>}
      </dd>
      <span className="run-summary-caption">{caption}</span>
    </div>
  );
}

export default function RunDetails({
  job,
  sourceName,
}: {
  job: Job | null;
  sourceName?: string;
}) {
  if (!job)
    return (
      <div className="run-empty">
        <Icon name="activity" size={26} />
        <h3>No analysis selected</h3>
        <p>Select an analyzed source to see its run statistics.</p>
      </div>
    );
  const metrics = job.metrics;
  const mode = metrics.classifier_mode;
  const model =
    typeof mode === "string" && mode in classifierLabels
      ? classifierLabels[mode as ClassifierMode]
      : "Not reported";
  const progress = Number.isFinite(job.progress)
    ? Math.min(100, Math.max(0, job.progress * 100))
    : 0;
  const extraMetrics = Object.entries(metrics).filter(
    ([key]) => !presented.has(key),
  );
  return (
    <section className="run-detail" aria-label="Selected analysis run">
      <header className="run-heading">
        <div className="run-source">
          <span className="run-eyebrow">Analysis run</span>
          <h3 title={sourceName}>{sourceName ?? "Selected source"}</h3>
          <p>Species model · {model}</p>
        </div>
        <span className={`run-status run-status-${job.status}`}>
          <i />
          {job.status}
        </span>
      </header>
      <div className="run-progress-label">
        <span>{job.stage || "Preparing analysis"}</span>
        <strong>{formatRunNumber(progress)}%</strong>
      </div>
      <div
        className="run-progress-track"
        role="progressbar"
        aria-label="Analysis progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Number(progress.toFixed(2))}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      {job.error && <p className="error">{job.error}</p>}
      <dl className="run-summary">
        <Summary
          icon="clock"
          label="Recorded runtime"
          value={formatRunDuration(metrics.total_elapsed_seconds)}
          caption="HH:MM:SS · updated on pause or finish"
        />
        <Summary
          icon="activity"
          label="Processing speed"
          value={formatRunNumber(metrics.effective_processed_fps)}
          unit="fps"
          caption="Sampled frames per second"
        />
        <Summary
          icon="eye"
          label="Visual observations"
          value={formatRunNumber(job.visual_count, true)}
          caption="Saved detections, not unique animals"
        />
        <Summary
          icon="sound"
          label="Audio observations"
          value={formatRunNumber(job.audio_count, true)}
          caption={`Audio · ${job.audio_status || "pending"}`}
        />
      </dl>
      <div className="run-metric-groups">
        {groups.map((group) => (
          <section
            className="run-metric-group"
            key={group.title}
            aria-label={group.title}
          >
            <h4>
              <Icon name={group.icon} size={17} />
              {group.title}
            </h4>
            <dl>
              {group.fields.map((field) => (
                <div key={field.key}>
                  <dt>{field.label}</dt>
                  <dd>
                    <MetricValue
                      value={metrics[field.key]}
                      unit={field.unit}
                      whole={field.whole}
                    />
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
      <details className="run-disclosure">
        <summary>Measurement details</summary>
        <div className="run-measurement-notes">
          <p>
            Values are displayed to two decimal places; saved records retain
            their original precision. A dash means the measurement is not
            available.
          </p>
          <p>
            Recorded runtime and peak GPU memory update when the run pauses or
            ends. Processing speed measures analyzed frames per second, not the
            source frame rate. Memory is shown in MiB.
          </p>
          {typeof metrics.visual_metrics_scope === "string" && (
            <p>{metrics.visual_metrics_scope}</p>
          )}
          {extraMetrics.length > 0 && (
            <dl>
              {extraMetrics.map(([key, value]) => (
                <div key={key}>
                  <dt>
                    {additionalFields[key]?.label ?? key.replaceAll("_", " ")}
                  </dt>
                  <dd>
                    <MetricValue
                      value={value}
                      unit={additionalFields[key]?.unit}
                      whole={additionalFields[key]?.whole}
                    />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </details>
      <details className="run-disclosure run-log">
        <summary>
          Activity log{" "}
          <span className="run-log-count">
            {integer.format(job.messages.length)}
          </span>
        </summary>
        <div
          className="run-log-scroll"
          tabIndex={0}
          role="region"
          aria-label="Analysis activity log"
        >
          <ol>
            {job.messages.map((message, index) => (
              <li key={index}>{message}</li>
            ))}
          </ol>
          {job.messages.length === 0 && <p>No activity recorded yet.</p>}
        </div>
      </details>
    </section>
  );
}
