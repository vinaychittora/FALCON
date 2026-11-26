// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import {
  canResumeAnalysis,
  isActiveAnalysis,
  supportsAnalysisControl,
} from "../api/analysis";
import { formatTime } from "../api/timeline";
import type { Job, Video } from "../types";
import Icon from "./Icon";

export default function AnalysisActions({
  source,
  job,
  blocked,
  canStart,
  pending,
  onStart,
  onPause,
  onResume,
}: {
  source?: Video;
  job: Job | null;
  blocked: boolean;
  canStart: boolean;
  pending: "start" | "pause" | "resume" | null;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
}) {
  const matchingJob = job?.source_id === source?.source_id ? job : null;
  const active = isActiveAnalysis(matchingJob);
  const pauseSupported = supportsAnalysisControl(matchingJob);
  const pausing = matchingJob?.status === "pausing" || pending === "pause";
  const resumable = canResumeAnalysis(matchingJob, source?.source_id ?? "");
  const starting = pending === "start" || pending === "resume";
  const freshLabel = matchingJob
    ? "Analyze again"
    : source?.media_kind === "image"
      ? "Analyze photo"
      : "Analyze recording";

  return (
    <>
      {resumable && (
        <button
          className="primary"
          disabled={blocked || !!pending}
          onClick={onResume}
          title="Continue this run with its saved settings and observations"
        >
          <Icon name="play" size={17} />
          {pending === "resume"
            ? "Resuming…"
            : matchingJob?.resume_stage === "audio"
              ? "Resume audio analysis"
              : `Resume from ${formatTime(matchingJob?.resume_from_ms ?? matchingJob?.coverage_ms ?? 0)}`}
        </button>
      )}
      <button
        className={resumable ? "text-button" : "primary"}
        disabled={!source || !canStart || blocked || active || !!pending}
        onClick={onStart}
        title={
          matchingJob ? "Create a new analysis from the beginning" : undefined
        }
      >
        {!resumable && <Icon name="eye" size={17} />}
        {resumable
          ? freshLabel
          : pausing
            ? pauseSupported
              ? "Pausing…"
              : "Stopping…"
            : starting
              ? pending === "resume"
                ? "Resuming…"
                : "Starting…"
              : active
                ? "Analyzing…"
                : freshLabel}
      </button>
      {active && (
        <button
          className="text-button"
          disabled={pausing || !!pending}
          onClick={onPause}
        >
          {pausing
            ? pauseSupported
              ? "Saving progress…"
              : "Stopping…"
            : pauseSupported
              ? "Pause analysis"
              : "Stop"}
        </button>
      )}
    </>
  );
}
