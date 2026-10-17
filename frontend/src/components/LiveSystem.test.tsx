import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  emptySystemSnapshot,
  type SystemMetrics,
  type LiveSystemSnapshot,
} from "../api/liveSystem";
import type { LiveState } from "../types";
import { LiveSystemView } from "./LiveSystem";

const live = {
  status: "live",
  name: "Backyard camera",
  session_id: "test-session",
  started_at: "2026-10-17T10:00:00Z",
  audio_status: "analyzing recent audio (CPU)",
  error: "rtsp://private:password@camera.test/stream1",
  metrics: {
    visual_frames: 10,
    audio_chunks_analyzed: 4,
    received_video_fps: 23.789123,
    frame_age_ms: 100,
    audio_result_lag_ms: 4321,
    inference_status: "processing",
    video_codec: "h264",
    audio_codec: "pcm_alaw",
    audio_error: "rtsp://private:password@camera.test/stream1",
  },
} as unknown as LiveState;
const host: SystemMetrics = {
  sampled_at: "2026-10-17T10:10:00Z",
  sample_age_seconds: 0.3,
  sampling: false,
  refresh_interval_seconds: 5,
  scope: "wsl",
  scope_label: "WSL",
  cpu: { percent: 6.5581, logical_count: 8, temperature_c: null },
  memory: {
    used_bytes: 2 * 1024 ** 3,
    total_bytes: 8 * 1024 ** 3,
    percent: 25,
  },
  storage: {
    free_bytes: 100 * 1024 ** 3,
    total_bytes: 200 * 1024 ** 3,
    percent: 50,
  },
  process: { uptime_seconds: 3661, rss_bytes: 1024 ** 3, cpu_percent: 150 },
  gpu: { available: false, devices: [] },
  unavailable: ["gpu", "cpu_temperature"],
};
function loaded(): LiveSystemSnapshot {
  return {
    ...emptySystemSnapshot(),
    checkedAt: 1000,
    live: { value: live, receivedAt: 1000, failed: false },
    host: { value: host, receivedAt: 1000, failed: false },
    sensors: {
      value: {
        status: "not_connected",
        sensor_id: null,
        observed_at: null,
        age_seconds: null,
        temperature_c: null,
        humidity_percent: null,
        pressure_hpa: null,
      },
      receivedAt: 1000,
      failed: false,
    },
  };
}
const render = (snapshot: LiveSystemSnapshot) =>
  renderToStaticMarkup(<LiveSystemView snapshot={snapshot} />);

describe("live system presentation", () => {
  it("shows live metrics and honest sensor/hardware absence without rendering transport secrets", () => {
    const html = render(loaded());
    expect(html).toContain("23.79 fps");
    expect(html).toContain("Backyard camera");
    expect(html).toContain("6.56 %");
    expect(html).toContain("01:01:01");
    expect(html).toContain("4.32 s");
    expect(html).toContain("Input error");
    expect(html).toContain("Not connected");
    expect(html).toContain("GPU telemetry unavailable");
    expect(html).toContain("CPU and RAM are not Windows host totals");
    expect(html).not.toContain("password");
    expect(html).not.toContain("camera.test");
    expect(html).not.toContain("23.789");
  });
  it("uses the same metric rows before values arrive and does not turn unavailable measurements into zero", () => {
    const initial = render(emptySystemSnapshot());
    const populated = render(loaded());
    expect(initial.match(/<dt>/g)?.length).toBe(
      populated.match(/<dt>/g)?.length,
    );
    expect(initial).toContain("Checking…");
    expect(initial).not.toContain("0.00 %");
    expect(initial).not.toContain("Not observing");
  });
  it("does not present stale telemetry or stopped camera rates as current", () => {
    const snapshot = loaded();
    snapshot.live = { ...snapshot.live, value: { ...live, status: "stopped" } };
    snapshot.host.failed = true;
    const html = render(snapshot);
    expect(html).toContain("Stopped");
    expect(html).toContain("Telemetry stale");
    expect(html).not.toContain("23.79 fps");
    expect(html).not.toContain("6.56 %");
    expect(html).not.toContain(">Processing</span>");
  });
  it("flags an evidence capture fault without showing its raw private message", () => {
    const snapshot = loaded();
    snapshot.live.value = {
      ...live,
      metrics: {
        ...live.metrics,
        evidence_recorder_status: "buffering",
        evidence_capture_fault: "secret recorder address",
      },
    };
    const html = render(snapshot);
    expect(html).toContain("Recorder needs attention");
    expect(html).not.toContain("secret recorder address");
    expect(html).not.toContain("Rolling buffer active");
  });
});
