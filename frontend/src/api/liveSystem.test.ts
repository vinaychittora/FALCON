import { afterEach, describe, expect, it, vi } from "vitest";
import type { LiveState } from "../types";
import { api } from "./client";
import {
  liveRates,
  startSystemPolling,
  type LiveSystemSnapshot,
} from "./liveSystem";

const state = (
  session = "camera-session",
  frames = 10,
  audio = 20,
): LiveState => ({
  status: "live",
  session_id: session,
  name: "Backyard camera",
  error: null,
  started_at: null,
  preview_timestamp_ms: null,
  visual: [],
  audio: [],
  messages: [],
  audio_status: "listening",
  metrics: { visual_frames: frames, decoded_audio_frames: audio },
});

afterEach(() => vi.useRealTimers());

describe("live rates", () => {
  it("uses the server session clock when response latency changes", () => {
    const before = {
      value: { ...state(), session_timestamp_ms: 1000 },
      receivedAt: 1000,
      failed: false,
    };
    const next = {
      ...state("camera-session", 16, 22),
      session_timestamp_ms: 6000,
    };
    expect(liveRates(before, next, 8000).processedFps).toBe(1.2);
  });
  it("measures completed frames and audio packets from recent samples of the same session", () => {
    const before = { value: state(), receivedAt: 1000, failed: false };
    expect(liveRates(before, state("camera-session", 16, 22), 6000)).toEqual({
      processedFps: 1.2,
      audioPacketsArriving: true,
    });
    expect(liveRates(before, state(), 6000)).toEqual({
      processedFps: 0,
      audioPacketsArriving: false,
    });
  });
  it("does not join counters across restarts, stale readings or stopped streams", () => {
    const before = { value: state(), receivedAt: 1000, failed: false };
    for (const result of [
      liveRates(before, state("replacement", 16), 6000),
      liveRates(before, state(), 50000),
      liveRates({ ...before, failed: true }, state(), 6000),
      liveRates(before, { ...state(), status: "stopped" }, 6000),
      liveRates(before, state("camera-session", 1, 1), 6000),
    ])
      expect(result).toEqual({
        processedFps: null,
        audioPacketsArriving: null,
      });
  });
});

describe("live system polling", () => {
  it("timestamps each response independently of a slower hardware probe", async () => {
    vi.useFakeTimers();
    const values: LiveSystemSnapshot[] = [];
    const start = Date.now();
    const request = vi.fn((path: string) =>
      path === "/system/metrics"
        ? new Promise((resolve) => setTimeout(() => resolve({}), 2000))
        : Promise.resolve(path === "/live/state" ? state() : {}),
    ) as unknown as typeof api;
    const stop = startSystemPolling((value) => values.push(value), request);
    await vi.advanceTimersByTimeAsync(2000);
    expect(values[0].live.receivedAt).toBe(start);
    expect(values[0].host.receivedAt).toBe(start + 2000);
    expect(values[0].checkedAt).toBe(start + 2000);
    stop();
  });
  it("keeps successful live readings when host metrics fail and marks failed values stale", async () => {
    vi.useFakeTimers();
    const values: LiveSystemSnapshot[] = [];
    let round = 0;
    const request = vi.fn((path: string) => {
      if (path === "/live/state")
        return round < 1
          ? Promise.resolve(state())
          : Promise.reject(new Error("private transport details"));
      if (path === "/sensors/current")
        return Promise.resolve({ status: "not_connected" });
      return Promise.reject(new Error("host unavailable"));
    }) as unknown as typeof api;
    const stop = startSystemPolling((value) => values.push(value), request);
    await vi.advanceTimersByTimeAsync(0);
    expect(values[0].live.value?.status).toBe("live");
    expect(values[0].host).toEqual({
      value: null,
      receivedAt: null,
      failed: true,
    });
    round = 1;
    await vi.advanceTimersByTimeAsync(5000);
    expect(values[1].live.value?.status).toBe("live");
    expect(values[1].live.failed).toBe(true);
    expect(values[1].sensors.failed).toBe(false);
    expect(JSON.stringify(values)).not.toContain("private transport");
    stop();
  });
  it("bounds requests, never overlaps rounds and aborts pending work on unmount", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const request = vi.fn(
      (_path: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          const signal = init?.signal as AbortSignal;
          signals.push(signal);
          signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    ) as unknown as typeof api;
    const updated = vi.fn();
    const stop = startSystemPolling(updated, request);
    expect(request).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(7000);
    expect(request).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1000);
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    expect(updated).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(request).toHaveBeenCalledTimes(6);
    stop();
    await vi.advanceTimersByTimeAsync(30000);
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    expect(updated).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledTimes(6);
  });
});
