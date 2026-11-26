// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { isActiveAnalysis, selectAnalysisJob } from "../api/analysis";
import type { Detection, Job } from "../types";

interface Snapshot {
  key: string;
  job: Job | null;
  jobs: Job[];
  events: Detection[];
  error: string;
}
const empty: Snapshot = { key: "", job: null, jobs: [], events: [], error: "" };

export function useAnalysis(sourceId: string, runId: string) {
  const key = sourceId + ":" + runId;
  const [snapshot, setSnapshot] = useState<Snapshot>(empty),
    [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    let stopped = false,
      busy = false,
      socket: WebSocket | null = null,
      socketId = "",
      socketRevision = 0,
      latestSocketJob: Job | null = null;
    if (!sourceId) return;
    async function load() {
      if (stopped || busy) return;
      busy = true;
      const revisionAtStart = socketRevision;
      try {
        const list = await api<Job[]>(`/videos/${sourceId}/jobs`);
        const current = selectAnalysisJob(list, runId, sourceId);
        const data = current
          ? await api<Detection[]>(
              `/videos/${sourceId}/detections?job_id=${current.job_id}`,
            )
          : [];
        if (stopped) return;
        // Fetching detections can outlast a progress update. Refresh the records
        // without rolling the same run back to the earlier polled snapshot.
        const resolvedJob =
          socketRevision > revisionAtStart &&
          latestSocketJob?.job_id === current?.job_id
            ? latestSocketJob
            : current;
        setSnapshot({
          key,
          job: resolvedJob ?? null,
          jobs: list.map((job) =>
            resolvedJob?.job_id === job.job_id ? resolvedJob : job,
          ),
          events: data,
          error: "",
        });
        if (
          resolvedJob &&
          isActiveAnalysis(resolvedJob) &&
          socketId !== resolvedJob.job_id
        ) {
          socket?.close();
          socketId = resolvedJob.job_id;
          socket = new WebSocket(
            `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/jobs/${resolvedJob.job_id}/events`,
          );
          const connectedSocket = socket;
          const connectedJobId = resolvedJob.job_id;
          socket.onclose = () => {
            if (socket === connectedSocket) {
              socket = null;
              socketId = "";
            }
          };
          socket.onmessage = (e) => {
            if (stopped || socket !== connectedSocket) return;
            try {
              const update = JSON.parse(String(e.data)) as { job: Job };
              if (
                update.job.job_id !== connectedJobId ||
                update.job.source_id !== sourceId
              )
                return;
              latestSocketJob = update.job;
              socketRevision += 1;
              setSnapshot((previous) =>
                previous.key === key && previous.job?.job_id === connectedJobId
                  ? {
                      ...previous,
                      job: update.job,
                      jobs: previous.jobs.map((job) =>
                        job.job_id === connectedJobId ? update.job : job,
                      ),
                    }
                  : previous,
              );
            } catch {
              setSnapshot((previous) => ({
                ...(previous.key === key ? previous : empty),
                key,
                error: "Invalid job progress message",
              }));
            }
          };
        } else if (!isActiveAnalysis(resolvedJob)) {
          socket?.close();
          socket = null;
          socketId = "";
        }
      } catch (e) {
        if (!stopped)
          setSnapshot((previous) => ({
            ...(previous.key === key ? previous : empty),
            key,
            error: String(e),
          }));
      } finally {
        busy = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 1500);
    return () => {
      stopped = true;
      clearInterval(timer);
      socket?.close();
    };
  }, [sourceId, runId, key, revision]);
  // Never show a previous source's boxes while the next source is loading.
  return { ...(snapshot.key === key ? snapshot : empty), refresh };
}
