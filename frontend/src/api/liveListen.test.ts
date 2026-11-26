// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { level, meterFraction, pcmToFloat } from "./liveListen";

describe("listening live", () => {
  it("turns 16-bit sound into samples, keeping a split byte for the next block", () => {
    const first = pcmToFloat(new Uint8Array([0x00, 0x40, 0x00]), null);
    expect(Array.from(first.samples)).toEqual([0.5]);
    expect(Array.from(first.rest ?? [])).toEqual([0x00]);
    const second = pcmToFloat(new Uint8Array([0xc0, 0xff, 0x7f]), first.rest);
    expect(Array.from(second.samples)).toEqual([-0.5, expect.closeTo(1, 3)]);
    expect(second.rest).toBeNull();
  });

  it("measures the level in dBFS for the meter", () => {
    const loud = level(new Float32Array([0.5, -0.5, 0.5, -0.5]));
    expect(loud.rms).toBeCloseTo(-6.02, 1);
    expect(loud.peak).toBeCloseTo(-6.02, 1);
    expect(level(new Float32Array(4)).rms).toBe(-Infinity);
    expect(meterFraction(-60)).toBe(0);
    expect(meterFraction(-30)).toBe(0.5);
    expect(meterFraction(3)).toBe(1);
    expect(meterFraction(-Infinity)).toBe(0);
  });
});
