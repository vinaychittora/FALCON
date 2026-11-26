// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { placePanel } from "./Floating";

const view = { width: 1024, height: 768 };
const panel = { width: 220, height: 160 };

describe("floating menus and tooltips stay fully on screen", () => {
  it("opens above the button, right edges lined up", () => {
    const at = placePanel({ left: 900, top: 700, right: 920, bottom: 720 }, panel, view);
    expect(at).toEqual({ left: 700, top: 532 });
  });

  it("never runs off the left edge (a control at the start of a phone's second row)", () => {
    const phone = { width: 375, height: 812 };
    const at = placePanel({ left: 16, top: 600, right: 40, bottom: 620 }, panel, phone);
    expect(at.left).toBe(12);
    expect(at.left + panel.width).toBeLessThanOrEqual(phone.width - 12);
  });

  it("never runs off the right edge", () => {
    const at = placePanel({ left: 1100, top: 700, right: 1200, bottom: 720 }, panel, view);
    expect(at.left + panel.width).toBeLessThanOrEqual(view.width - 12);
  });

  it("opens below when there is no room above", () => {
    const at = placePanel({ left: 500, top: 40, right: 520, bottom: 60 }, panel, view);
    expect(at.top).toBe(68);
  });
});
