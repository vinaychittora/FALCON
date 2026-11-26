// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { afterEach, describe, expect, it, vi } from "vitest";
import { encounterQuery, fetchAllEncounters, REVIEW_BATCH, reviewInBatches, STATUS_FILTERS } from "./encounters";
import { undoGroups } from "./reviewList";

describe("Review's Hidden status and whole-list actions", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers Hidden right after To review and asks the server for hidden records only", () => {
    expect(STATUS_FILTERS.slice(0, 2)).toEqual([["unreviewed", "To review"], ["hidden", "Hidden"]]);
    const query = new URLSearchParams(encounterQuery({ scope: "live", review_status: "unreviewed", hidden_only: true }));
    expect(query.get("hidden_only")).toBe("true");
    expect(query.get("review_status")).toBe("unreviewed");
    expect(new URLSearchParams(encounterQuery({ scope: "live" })).get("hidden_only")).toBeNull();
  });

  it("sends a whole-list decision in requests of at most 200 and reports progress", async () => {
    const bodies: { encounter_ids: string[] }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ updated: 1, missing: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const ids = Array.from({ length: 450 }, (_, i) => `v${i}`);
    const progress: number[] = [];
    await reviewInBatches(ids, "discarded", {}, (done) => progress.push(done));
    expect(bodies.map((body) => body.encounter_ids.length)).toEqual([REVIEW_BATCH, REVIEW_BATCH, 50]);
    expect(progress).toEqual([200, 400, 450]);
  });

  it("reads a whole list once per visit even when it shifts while paging", async () => {
    const pages = [
      { encounters: Array.from({ length: 200 }, (_, i) => ({ encounter_id: `v${i}`, event: { modality: "visual" } })), total: 260 },
      { encounters: Array.from({ length: 60 }, (_, i) => ({ encounter_id: `v${i + 195}`, event: { modality: "visual" } })), total: 260 },
    ];
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify(pages[call++]), { status: 200, headers: { "Content-Type": "application/json" } })));
    const all = await fetchAllEncounters({ scope: "live" });
    expect(all.length).toBe(255);
    expect(new Set(all.map((item) => item.encounter_id)).size).toBe(255);
  });

  it("undoes by earlier state, so the whole action goes back in few requests", () => {
    const before = new Map([
      ["a", { status: "unreviewed" as const }],
      ["b", { status: "unreviewed" as const }],
      ["c", { status: "corrected" as const, taxonId: 7711 }],
      ["d", { status: "unreviewed" as const, notes: "dark" }],
    ]);
    const groups = undoGroups(before);
    expect(groups.map((g) => g.ids)).toEqual([["a", "b"], ["c"], ["d"]]);
    expect(groups[1].review.taxonId).toBe(7711);
  });
});
