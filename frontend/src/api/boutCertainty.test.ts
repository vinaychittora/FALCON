// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { certaintyOf } from "./certainty";
import { withBoutConfidence, type Encounter } from "./encounters";
import type { AudioEvent } from "../types";

function bout(latest: number, best: number, cleaned: boolean | null = null): Encounter {
  const event = {
    event_id: "e1", modality: "audio", job_id: "j", source_id: "s", source_filename: "node",
    start_ms: 0, end_ms: 3000, scientific_name: "Copsychus fulicatus", common_name: "Indian Robin",
    confidence: latest, model: "BirdNET", cleaned_agrees: cleaned,
    review: { status: "unreviewed" },
  } as unknown as AudioEvent;
  return {
    encounter_id: "j:b", modality: "audio", source_id: "s", source_filename: "node", job_id: "j",
    track_id: null, records: 2, first_captured_at: null, duration_ms: 6000, review_status: "unreviewed",
    thumbnail_event_id: "e1", event, best_confidence: best,
  };
}

describe("a sound bout's tier on Review follows its clearest call", () => {
  it("best 0.70, latest 0.45: Likely", () => {
    expect(certaintyOf(withBoutConfidence(bout(0.45, 0.7)).event)?.level).toBe("likely");
  });
  it("best 0.52: Probable", () => {
    expect(certaintyOf(withBoutConfidence(bout(0.52, 0.52)).event)?.level).toBe("probable");
  });
  it("best 0.70 but the merged cleaned verdict disagrees: Probable", () => {
    expect(certaintyOf(withBoutConfidence(bout(0.7, 0.7, false)).event)?.level).toBe("probable");
  });
});
