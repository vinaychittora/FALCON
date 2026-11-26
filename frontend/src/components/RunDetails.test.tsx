// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Job } from "../types";
import RunDetails, { formatRunDuration, formatRunNumber } from "./RunDetails";

describe("scientific run metric presentation", () => {
  it("rounds float noise to two decimals without changing stored precision", () => {
    const value = 114.30682999999999;
    expect(formatRunNumber(value)).toBe("114.31");
    expect(formatRunNumber(0.757)).toBe("0.76");
    expect(formatRunNumber(2855, true)).toBe("2,855");
    expect(formatRunNumber(0)).toBe("0.00");
    expect(value).toBe(114.30682999999999);
  });
  it("distinguishes unavailable measurements from zero", () => {
    for (const value of [undefined, null, NaN, Infinity, "n/a"])
      expect(formatRunNumber(value)).toBe("—");
    expect(formatRunNumber(0, true)).toBe("0");
    expect(formatRunDuration(undefined)).toBe("—");
    expect(formatRunDuration(0)).toBe("00:00:00");
    expect(formatRunDuration(3661.999)).toBe("01:01:01");
  });
  it("reserves the same metric rows as data arrives and keeps prose outside statistics", () => {
    const job = {
      status: "running",
      stage: "visual analysis",
      progress: 0.25,
      visual_count: 130,
      audio_count: 0,
      audio_status: "pending",
      messages: [],
      metrics: {},
    } as unknown as Job;
    const render = (value: Job) =>
      renderToStaticMarkup(<RunDetails job={value} sourceName="example.mp4" />);
    const initial = render(job);
    const updated = render({
      ...job,
      metrics: {
        detector_elapsed_seconds: 114.30682999999999,
        visual_metrics_scope: "Completed frames in checkpointed segments",
        audio_analysis_ratio: 0.123456,
      },
    });
    expect(initial.match(/<dt>/g)?.length).toBe(19);
    expect(
      updated.split('class="run-disclosure"')[0].match(/<dt>/g)?.length,
    ).toBe(19);
    expect(updated).toContain("114.31");
    expect(updated).not.toContain("114.3068");
    expect(updated).toContain('aria-valuenow="25"');
    expect(updated.split('class="run-disclosure"')[0]).not.toContain(
      "Completed frames in checkpointed segments",
    );
    expect(updated).toContain("0.12");
    expect(job.metrics).toEqual({});
  });
});
