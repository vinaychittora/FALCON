// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { LiveState, Video } from "../types";
import "./source-technical.css";

export function formatBitrate(value?: number | null): string {
  if (
    value === null ||
    value === undefined ||
    !Number.isFinite(value) ||
    value < 0
  )
    return "Not reported";
  return value >= 1_000_000
    ? `${(value / 1_000_000).toFixed(2)} Mb/s`
    : `${(value / 1000).toFixed(1)} kb/s`;
}

function rate(value: unknown, unit: string): string {
  return typeof value === "number" && value > 0
    ? `${Number(value.toFixed(2)).toLocaleString()} ${unit}`
    : "Not reported";
}

function bytes(value: number): string {
  return value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(2)} GiB`
    : `${(value / 1024 ** 2).toFixed(2)} MiB`;
}

export default function SourceTechnical({
  source,
  live,
}: {
  source?: Video;
  live?: LiveState | null;
}) {
  const m = live?.metrics ?? {};
  const isLive = !source;
  const fields: [string, string][] = [];
  const text = (v: unknown) =>
    typeof v === "string" && v && v !== "unknown" ? v : "Not reported";
  const numeric = (v: unknown) => (typeof v === "number" ? v : undefined);
  if (source) {
    fields.push([
      "Format",
      source.container?.includes("mov,mp4")
        ? "QuickTime / MP4"
        : (source.container || source.codec).toUpperCase(),
    ]);
    if (source.media_kind !== "audio") {
      fields.push(["Dimensions", `${source.width} × ${source.height} px`]);
      fields.push([
        source.media_kind === "image" ? "Image codec" : "Video codec",
        source.codec,
      ]);
    }
    if (source.media_kind === "video")
      fields.push(["Frame rate", rate(source.fps, "fps")]);
    if (source.media_kind !== "image") {
      fields.push(["Bitrate · reported", formatBitrate(source.bitrate_bps)]);
      fields.push(["Duration", `${(source.duration_ms / 1000).toFixed(2)} s`]);
    }
    fields.push(["File size", bytes(source.size_bytes)]);
    if (source.audio) {
      fields.push(["Audio codec", text(source.audio_codec)]);
      fields.push(["Sample rate", rate(source.audio_sample_rate, "Hz")]);
      fields.push([
        "Channels",
        source.audio_channels ? String(source.audio_channels) : "Not reported",
      ]);
    } else if (source.media_kind === "video")
      fields.push(["Audio", "No audio stream"]);
  } else {
    const running = ["live", "connecting", "reconnecting", "stopping"].includes(
      live?.status ?? "",
    );
    fields.push(["Video codec", text(m.video_codec)]);
    fields.push([
      "Dimensions",
      m.width && m.height ? `${m.width} × ${m.height} px` : "Not reported",
    ]);
    fields.push(["Camera frame rate", rate(m.nominal_video_fps, "fps")]);
    fields.push([
      "Received frame rate",
      running && typeof m.received_video_fps === "number"
        ? `${m.received_video_fps.toFixed(1)} fps`
        : "Not reported",
    ]);
    fields.push([
      "Video bitrate · measured",
      running
        ? formatBitrate(numeric(m.measured_video_bitrate_bps))
        : "Not reported",
    ]);
    fields.push([
      "Video bitrate · reported",
      formatBitrate(numeric(m.reported_video_bitrate_bps)),
    ]);
    fields.push(["Audio codec", text(m.audio_codec)]);
    fields.push(["Sample rate", rate(m.audio_sample_rate, "Hz")]);
    fields.push([
      "Channels",
      m.audio_channels ? String(m.audio_channels) : "Not reported",
    ]);
    if (m.preview_max_fps)
      fields.push(["Preview limit", rate(m.preview_max_fps, "fps")]);
  }
  return (
    <section
      className="source-technical"
      aria-label="Source technical information"
    >
      <div className="source-technical-heading">
        <h3>Source information</h3>
        <span>{isLive ? "RTSP · TCP" : "Original file"}</span>
      </div>
      <dl>
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {isLive && (
        <p>
          Received rate and video payload bitrate use a rolling 5-second window.
        </p>
      )}
    </section>
  );
}
