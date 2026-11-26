// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Job } from "../types";
import { api } from "./client";
import { testSessionHeaders } from "./testSessions";

export const isActiveAnalysis = (job: Job | null | undefined) =>
  !!job && ["queued", "running", "pausing"].includes(job.status);

export const supportsAnalysisControl = (job: Job | null | undefined) =>
  typeof job?.can_resume === "boolean";

export const canResumeAnalysis = (
  job: Job | null | undefined,
  sourceId: string,
) =>
  !!job &&
  job.source_id === sourceId &&
  job.can_resume === true &&
  ["paused", "interrupted", "cancelled", "failed"].includes(job.status);

export function selectAnalysisJob(
  jobs: Job[],
  runId: string,
  sourceId: string,
) {
  return (
    (runId
      ? jobs.find((job) => job.job_id === runId && job.source_id === sourceId)
      : jobs.find((job) => job.source_id === sourceId)) ?? null
  );
}

export async function controlAnalysis(
  action: "pause" | "resume",
  job: Job,
  sourceId: string,
  testSessionId?: string | null,
): Promise<Job> {
  if (job.source_id !== sourceId)
    throw new Error("Select this analysis source before continuing.");
  if (action === "resume" && !canResumeAnalysis(job, sourceId))
    throw new Error(job.resume_reason || "This analysis cannot be resumed.");
  if (action === "pause" && !["queued", "running"].includes(job.status))
    throw new Error("This analysis is not running.");
  const operation =
    action === "pause" && !supportsAnalysisControl(job) ? "cancel" : action;
  return api<Job>(`/jobs/${job.job_id}/${operation}`, {
    method: "POST",
    ...(testSessionId ? { headers: testSessionHeaders(testSessionId) } : {}),
  });
}
