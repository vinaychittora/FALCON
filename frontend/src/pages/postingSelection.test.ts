// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import type { PostPreview } from "../api/inaturalist";
import { linkProblem, rowFromPreview, selectionOnLoad } from "./PostingPage";

describe("the posting page keeps the record that was opened", () => {
  const listed = ["robin-audio", "bulbul", "prinia"];

  it("keeps a record from the address that is older than the listed ones", () => {
    expect(selectionOnLoad("waterhen-19-nov", listed, "waterhen-19-nov")).toBe("waterhen-19-nov");
  });

  it("keeps a listed record that was chosen", () => {
    expect(selectionOnLoad("bulbul", listed, null)).toBe("bulbul");
  });

  it("never falls back to the newest when the address named a visit that cannot be posted", () => {
    expect(selectionOnLoad(null, listed, "discarded-visit")).toBeNull();
  });

  it("starts on the newest only when the address names no visit", () => {
    expect(selectionOnLoad(null, listed, null)).toBe("robin-audio");
    expect(selectionOnLoad(null, [], null)).toBeNull();
  });

  it("says in one sentence why a visit from the address cannot be posted", () => {
    expect(linkProblem({ problems: ["Only visits you confirmed or corrected can be posted."], posted: null }))
      .toBe("This visit cannot be posted: confirm or correct it on Review first.");
    expect(linkProblem({ problems: ["Already posted."], posted: null })).toBe("This visit is already on iNaturalist.");
    expect(linkProblem({ problems: ["No camera spot is set for falcon-node."], posted: null })).toBe("");
  });

  it("shows an older visit from the address as an ordinary row", () => {
    const row = rowFromPreview({
      encounter_id: "hen", node: "falcon-node", species: { scientific_name: "Amaurornis phoenicurus", common_name: "White-breasted Waterhen" },
      observed_at: "2026-11-19T02:43:20Z", duration_ms: 0, frames: [{ event_id: "e1", captured_at: null, score: 0.49 }],
    } as unknown as PostPreview);
    expect([row.encounter_id, row.name, row.thumbnail_event_id, row.first_captured_at]).toEqual([
      "hen", "White-breasted Waterhen", "e1", "2026-11-19T02:43:20Z",
    ]);
    // Its tile is the first suggested frame at the panel's address, never the detection thumbnail.
    expect(row.tile_url).toBe("/api/inaturalist/visits/hen/photos/e1.jpg");
    const none = rowFromPreview({
      encounter_id: "x", node: "n", species: { scientific_name: null, common_name: null },
      observed_at: null, duration_ms: 0, frames: [],
    } as unknown as PostPreview);
    expect(none.tile_url).toBe("");
  });
});
