// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { paddedBox } from "./overlays";

const rect = { x: 0, y: 0, width: 1000, height: 500 };

describe("drawn boxes leave room around the animal", () => {
  it("widens a small box by at least 16 px on every side", () => {
    const box = paddedBox([0.5, 0.5, 0.52, 0.54], rect); // 20 x 20 px
    expect(box).toEqual({ x: 484, y: 234, width: 52, height: 52 });
  });

  it("widens a large box by a quarter of its size, kept inside the picture", () => {
    const box = paddedBox([0.0, 0.2, 0.4, 0.6], rect); // 400 x 200 px
    expect(box.x).toBe(0);
    expect(box.width).toBe(500);
    expect(box.y).toBeCloseTo(50);
    expect(box.height).toBeCloseTo(300);
  });
});
