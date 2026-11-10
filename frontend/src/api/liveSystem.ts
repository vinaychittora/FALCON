import { api } from "./client";
import type { EnvironmentReading, LiveState } from "../types";

export interface SystemMetrics {
  sampled_at: string | null;
  sample_age_seconds: number | null;
  sampling: boolean;
  refresh_interval_seconds: number;
  scope: "linux" | "wsl" | "windows" | "other";
  scope_label: string;
  /** Linux clock source; "tsc" under WSL was measured running 10 % fast. */
  clocksource?: string | null;
  cpu: {
    percent: number | null;
    logical_count: number | null;
    temperature_c: number | null;
  };
  memory: {
    used_bytes: number | null;
    total_bytes: number | null;
    percent: number | null;
  };
  storage: {
    free_bytes: number | null;
    total_bytes: number | null;
    percent: number | null;
  };
  process: {
    uptime_seconds: number | null;
    rss_bytes: number | null;
    cpu_percent: number | null;
  };
  gpu: {
    available: boolean;
    devices: {
      index: number;
      name: string;
      utilization_percent: number | null;
      memory_used_mib: number | null;
      memory_total_mib: number | null;
      temperature_c: number | null;
      power_watts: number | null;
    }[];
  };
  unavailable: string[];
}

export interface Reading<T> {
  value: T | null;
  receivedAt: number | null;
  failed: boolean;
}
export interface LiveSystemSnapshot {
  live: Reading<LiveState>;
  sensors: Reading<EnvironmentReading>;
  host: Reading<SystemMetrics>;
  processedFps: number | null;
  audioPacketsArriving: boolean | null;
  checkedAt: number | null;
}

export const emptySystemSnapshot = (): LiveSystemSnapshot => ({
  live: { value: null, receivedAt: null, failed: false },
  sensors: { value: null, receivedAt: null, failed: false },
  host: { value: null, receivedAt: null, failed: false },
  processedFps: null,
  audioPacketsArriving: null,
  checkedAt: null,
});

export function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Rates only join successful, recent samples of the same live session. */
export function liveRates(
  previous: Reading<LiveState>,
  next: LiveState,
  now: number,
) {
  const receiveSeconds =
    previous.receivedAt === null ? 0 : (now - previous.receivedAt) / 1000;
  if (
    previous.failed ||
    receiveSeconds <= 0 ||
    receiveSeconds > 15 ||
    !next.session_id ||
    previous.value?.session_id !== next.session_id ||
    previous.value.status !== "live" ||
    next.status !== "live"
  )
    return { processedFps: null, audioPacketsArriving: null };
  const sessionTime = finiteNumber(next.session_timestamp_ms);
  const oldSessionTime = finiteNumber(previous.value.session_timestamp_ms);
  const seconds =
    sessionTime !== null && oldSessionTime !== null
      ? (sessionTime - oldSessionTime) / 1000
      : receiveSeconds;
  if (seconds <= 0 || seconds > 15)
    return { processedFps: null, audioPacketsArriving: null };
  const count = finiteNumber(next.metrics.visual_frames);
  const oldCount = finiteNumber(previous.value.metrics.visual_frames);
  const audio = finiteNumber(next.metrics.decoded_audio_frames);
  const oldAudio = finiteNumber(previous.value.metrics.decoded_audio_frames);
  return {
    processedFps:
      count !== null && oldCount !== null && count >= oldCount
        ? (count - oldCount) / seconds
        : null,
    audioPacketsArriving:
      audio !== null && oldAudio !== null && audio >= oldAudio
        ? audio > oldAudio
        : null,
  };
}

/** One bounded round at a time; unmount aborts the current requests and future rounds. */
export function startSystemPolling(
  onUpdate: (snapshot: LiveSystemSnapshot) => void,
  request: typeof api = api,
  now: () => number = Date.now,
): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let snapshot = emptySystemSnapshot();
  async function poll() {
    controller = new AbortController();
    const signal = controller.signal;
    deadline = setTimeout(() => controller?.abort(), 8000);
    const timed = <T>(promise: Promise<T>) =>
      promise.then((value) => ({ value, receivedAt: now() }));
    const [live, sensors, host] = await Promise.allSettled([
      timed(request<LiveState>("/live/state", { signal, cache: "no-store" })),
      timed(
        request<EnvironmentReading>("/sensors/current", {
          signal,
          cache: "no-store",
        }),
      ),
      timed(
        request<SystemMetrics>("/system/metrics", {
          signal,
          cache: "no-store",
        }),
      ),
    ]);
    clearTimeout(deadline);
    if (stopped) return;
    const checkedAt = now();
    const reading = <T>(
      result: PromiseSettledResult<{ value: T; receivedAt: number }>,
      before: Reading<T>,
    ): Reading<T> =>
      result.status === "fulfilled"
        ? { ...result.value, failed: false }
        : { ...before, failed: true };
    snapshot = {
      live: reading(live, snapshot.live),
      sensors: reading(sensors, snapshot.sensors),
      host: reading(host, snapshot.host),
      ...(live.status === "fulfilled"
        ? liveRates(snapshot.live, live.value.value, live.value.receivedAt)
        : { processedFps: null, audioPacketsArriving: null }),
      checkedAt,
    };
    onUpdate(snapshot);
    timer = setTimeout(() => void poll(), 5000);
  }
  void poll();
  return () => {
    stopped = true;
    clearTimeout(timer);
    clearTimeout(deadline);
    controller?.abort();
  };
}
