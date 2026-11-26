// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import SceneryView, { cropStyle, spotFacts, type ScenerySpot } from "./SceneryView";

const spot = (over: Partial<ScenerySpot> = {}): ScenerySpot => ({
  id: 3,
  box: [0.25, 0.5, 0.75, 1],
  kind: "scenery",
  first_seen: "2026-11-19T06:14:00Z",
  last_hit: "2026-11-19T07:58:00Z",
  hits: 1234,
  stale: false,
  drops_at: "2026-11-21T07:58:00Z",
  ...over,
});

describe("ignored scenery", () => {
  it("says what each spot is, when it was saved, and when it is dropped", () => {
    const now = Date.parse("2026-11-19T08:00:00Z");
    const facts = spotFacts(spot(), 48, now);
    expect(facts[0]).toBe("Scenery");
    expect(facts[1]).toMatch(/^Saved .*(19 Nov|Nov 19)/);
    expect(facts.slice(2)).toEqual(["Last matched 2 min ago", "Matched 1,234 times", "Dropped by itself 48 hours after its last match"]);
    expect(spotFacts(spot({ kind: "maybe animal", stale: true, hits: 1 }), 48, now)).toEqual(
      expect.arrayContaining(["Maybe an animal", "Matched 1 time", "Dropped by itself 6 hours after its last match", "Stale"]),
    );
  });

  it("crops exactly the spot's part of the still", () => {
    expect(cropStyle([0.25, 0.5, 0.75, 1])).toEqual({ size: "200.00% 200.00%", position: "50.00% 100.00%" });
    expect(cropStyle([0, 0, 1, 1])).toEqual({ size: "100.00% 100.00%", position: "0.00% 0.00%" });
  });

  it("is a labelled expand whose summary carries the counts", () => {
    const html = renderToStaticMarkup(<SceneryView boxes={7} heldBack={3} />);
    expect(html).toContain("Scenery ignored");
    expect(html).toContain("7 boxes · 3 detections held back this session");
    expect(html).toMatch(/<details[^>]*id="scenery-ignored"/);
  });
});
