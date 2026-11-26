// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { eventTime, formatTime, predictionLabel } from "../api/timeline";
import type { Detection } from "../types";
export default function Timeline({
  events,
  duration,
  time,
  coverage,
  onSeek,
}: {
  events: Detection[];
  duration: number;
  time: number;
  coverage: number;
  onSeek: (ms: number) => void;
}) {
  return (
    <div className="timeline">
      <div className="timeline-label">
        <span>VISUAL</span>
        <span>AUDIO</span>
      </div>
      <div className="timeline-tracks">
        <div
          className="coverage"
          style={{
            width: `${Math.min(100, (coverage / Math.max(1, duration)) * 100)}%`,
          }}
        />
        {events.map((e) => (
          <button
            key={e.event_id}
            aria-label={`Seek ${predictionLabel(e)} at ${formatTime(eventTime(e))}`}
            title={`${predictionLabel(e)} · ${formatTime(eventTime(e))}`}
            className={"event-marker " + e.modality}
            style={{
              left: `${(eventTime(e) / Math.max(1, duration)) * 100}%`,
              width: `${Math.max(0.35, ((e.modality === "visual" ? e.duration_ms : e.end_ms - e.start_ms) / Math.max(1, duration)) * 100)}%`,
            }}
            onClick={() => onSeek(eventTime(e))}
          />
        ))}
        <div
          className="playhead"
          style={{ left: `${(time / Math.max(1, duration)) * 100}%` }}
        />
        <input
          className="seek-slider"
          aria-label="Seek recording"
          type="range"
          min="0"
          max={duration}
          step="100"
          value={time}
          onChange={(e) => onSeek(Number(e.target.value))}
        />
      </div>
      <span className="muted">{formatTime(duration)}</span>
    </div>
  );
}
