// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { encounterQuery, liveSourceId, scoreSummary } from "./encounters";
import {
  exportParams,
  missingForCamtrap,
  presetWindow,
  type ExportForm,
} from "./exports";
import {
  formatAgo,
  formatBytes,
  formatDuration,
  formatElapsed,
} from "./format";
import {
  componentState,
  nodeWarnings,
  streamState,
  type NodeStatus,
  type SensorNode,
} from "./nodes";
import { focusDistance } from "../ui/CameraControls";
import { liveSources } from "../pages/LivePage";
import { periodBounds } from "../pages/ReviewPage";
import type { AudioEvent } from "../types";

const FORM: ExportForm = {
  captured_from: "2026-10-01T00:00:00.000Z",
  captured_to: null,
  source_id: "",
  visual: true,
  audio: false,
  review: "verified",
  min_score: " 0.3 ",
  include_media: false,
  include_environment: true,
  title: "Backyard",
  project_title: "",
  contact_name: "Field team",
  contact_email: "",
  license: "CC-BY-4.0",
  latitude: "26.9",
  longitude: "75.8",
  coordinate_uncertainty_m: "",
  location_name: "",
};

function status(overrides: Partial<NodeStatus> = {}): NodeStatus {
  const component = {
    present: true,
    enabled: true,
    description: "x",
    state: "ok",
  };
  return {
    software: "falcon-node",
    version: "1.0.0",
    node_id: "n1",
    name: "Node",
    time: "",
    clock: { synchronized: true, source: "ntp", adopted_at: null },
    agent_uptime_seconds: 10,
    system: {
      board: "Raspberry Pi 4",
      hostname: "n1",
      addresses: [],
      uptime_seconds: 100,
      cpu_temperature_c: 50,
      load_1m: 0.5,
      cpu_count: 4,
      memory_used_percent: 40,
      disk_free_bytes: 10 * 1024 ** 3,
      disk_total_bytes: 32 * 1024 ** 3,
      wifi_signal_dbm: -60,
      power: {
        under_voltage_now: false,
        throttled_now: false,
        under_voltage_since_boot: false,
        throttled_since_boot: false,
      },
    },
    stream: {
      state: "streaming",
      since: null,
      restarts: 0,
      error: null,
      rtsp_port: 8554,
      rtsp_path: "falcon",
      video: true,
      audio: true,
      tracks: [],
      readers: 1,
    },
    components: {
      camera: component,
      microphone: component,
      climate: component,
      rain: { ...component, state: "dry" },
    },
    camera_settings: {} as NodeStatus["camera_settings"],
    microphone_settings: { audio_channel: "average", audio_gain_percent: null },
    last_reading: null,
    readings_queued: 0,
    reading_interval_seconds: 30,
    ...overrides,
  };
}

function node(overrides: Partial<SensorNode> = {}): SensorNode {
  return {
    node_id: "n1",
    name: "Backyard node",
    address: "http://192.0.2.60:8780",
    audio_analysis: true,
    created_at: "",
    updated_at: "",
    online: true,
    checked_at: null,
    last_seen: null,
    error: null,
    readings_collected: 0,
    observing: false,
    status: status(),
    ...overrides,
  };
}

describe("encounter queries", () => {
  it("includes only set filters and the live session's source", () => {
    const query = new URLSearchParams(
      encounterQuery({
        scope: "live",
        q: "  peafowl ",
        review_status: "",
        min_score: 0.2,
        limit: 10,
      }),
    );
    expect(Object.fromEntries(query)).toEqual({
      scope: "live",
      q: "peafowl",
      min_score: "0.2",
      limit: "10",
      offset: "0",
    });
    expect(liveSourceId("11111111-2222-3333-4444-555555555555")).toBe(
      "111111112222333344445555",
    );
    expect(liveSourceId(null)).toBeUndefined();
  });

  it("labels sound confidence and visual similarity honestly", () => {
    expect(
      scoreSummary({ modality: "audio", confidence: 0.81 } as AudioEvent).label,
    ).toBe("BirdNET confidence 0.81");
  });
});

describe("research export form", () => {
  it("builds download parameters and leaves metadata out of the preview", () => {
    const download = exportParams(FORM);
    expect(download.get("modalities")).toBe("visual");
    expect(download.get("min_score")).toBe("0.3");
    expect(download.get("include_media")).toBe("false");
    expect(download.get("license")).toBe("CC-BY-4.0");
    expect(download.has("captured_to")).toBe(false);
    const preview = exportParams(FORM, true);
    expect(preview.has("contact_name")).toBe(false);
    expect(preview.get("latitude")).toBe("26.9");
  });

  it("names what Camtrap DP still needs", () => {
    expect(missingForCamtrap(FORM)).toEqual([]);
    expect(
      missingForCamtrap({
        ...FORM,
        latitude: "",
        longitude: "200",
        contact_name: " ",
        visual: false,
      }),
    ).toEqual([
      "site latitude",
      "site longitude",
      "contact name",
      "video or sound detections",
    ]);
  });

  it("computes time windows that end now", () => {
    const now = new Date("2026-10-18T12:00:00Z");
    expect(presetWindow("24h", now)).toEqual({
      captured_from: "2026-10-17T12:00:00.000Z",
      captured_to: "2026-10-18T12:00:00.000Z",
    });
    expect(presetWindow("all", now)).toEqual({
      captured_from: null,
      captured_to: null,
    });
    expect(periodBounds("7d", "", "", now).captured_from).toBe(
      "2026-10-11T12:00:00.000Z",
    );
  });
});

describe("sensor node status", () => {
  it("summarizes stream and component states", () => {
    expect(streamState(node()).label).toBe("Streaming");
    expect(
      streamState(node({ online: false, error: "Not reachable" })),
    ).toMatchObject({ label: "Offline", tone: "bad" });
    expect(
      streamState(
        node({
          status: status({
            stream: { ...status().stream, state: "no sources" },
          }),
        }),
      ).tone,
    ).toBe("warn");
    expect(componentState(undefined).label).toBe("Not detected");
    expect(
      componentState({ present: true, enabled: false, description: null })
        .label,
    ).toBe("Switched off");
    expect(
      componentState({
        present: true,
        enabled: true,
        description: null,
        state: "dry",
      }).label,
    ).toBe("Dry");
    expect(
      componentState({
        present: true,
        enabled: true,
        description: null,
        state: "ok",
      }),
    ).toEqual({ label: "Working", tone: "good" });
  });

  it("warns about power, heat, clock and storage", () => {
    expect(nodeWarnings(status())).toEqual([]);
    const warnings = nodeWarnings(
      status({
        clock: { synchronized: false, source: "none", adopted_at: null },
        system: {
          ...status().system,
          cpu_temperature_c: 80,
          disk_free_bytes: 100,
          power: {
            under_voltage_now: true,
            throttled_now: true,
            under_voltage_since_boot: true,
            throttled_since_boot: true,
          },
        },
      }),
    );
    expect(warnings).toHaveLength(5);
    expect(warnings[0]).toContain("voltage is too low");
  });

  it("offers nodes with a camera or microphone switched on, then the IP camera", () => {
    const off = status({
      components: {
        ...status().components,
        camera: { present: true, enabled: false, description: null },
        microphone: { present: false, enabled: true, description: null },
      },
    });
    const sources = liveSources(
      [node(), node({ node_id: "n2", name: "Pond", status: off })],
      {
        saved: true,
        name: "Tapo",
        url: "rtsp://camera/stream1",
        username: "",
        has_password: true,
        audio_enabled: true,
        updated_at: null,
      },
    );
    expect(sources.map((source) => [source.key, source.available])).toEqual([
      ["node:n1", true],
      ["node:n2", false],
      ["camera", true],
    ]);
    expect(sources[0].detail).toContain("camera + microphone");
  });
});

describe("formatting", () => {
  it("formats durations, sizes, clocks and focus distances", () => {
    expect(formatDuration(65_000)).toBe("1 min 05 s");
    expect(formatDuration(3_725_000)).toBe("1 h 02 min");
    expect(formatElapsed(3_725_000)).toBe("01:02:05");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
    expect(
      formatAgo("2026-10-18T11:59:30Z", Date.parse("2026-10-18T12:00:00Z")),
    ).toBe("30 s ago");
    expect(formatAgo(null)).toBe("never");
    expect(focusDistance(0)).toBe("infinity");
    expect(focusDistance(0.5)).toBe("2.0 m");
    expect(focusDistance(0.05)).toBe("infinity");
  });
});
