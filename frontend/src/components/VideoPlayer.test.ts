// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, it, expect } from "vitest";
import { contentRect } from "./VideoPlayer";
describe("overlay geometry", () => {
  it("matches a letterboxed portrait video", () => {
    expect(contentRect(800, 450, 300, 600)).toEqual({
      x: 287.5,
      y: 0,
      width: 225,
      height: 450,
    });
  });
  it("matches a landscape video", () => {
    expect(contentRect(800, 450, 1920, 1080)).toEqual({
      x: 0,
      y: 0,
      width: 800,
      height: 450,
    });
  });
});
