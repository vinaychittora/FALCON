// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import {
  encounterNames,
  encounterQuery,
  STATUS_FILTERS,
  STATUS_LABELS,
  withDecision,
  type Encounter,
} from "../api/encounters";
import { actionFor } from "../ui/EncounterCard";
import { keepDecided } from "./ReviewPage";

const card = (id: string, status = "unreviewed") =>
  ({ encounter_id: id, review_status: status }) as unknown as Encounter;

describe("simplified review", () => {
  it("offers four statuses, Hidden (24 Nov) and All, and All includes discarded", () => {
    expect(STATUS_FILTERS.map(([, label]) => label)).toEqual([
      "To review", "Hidden", "Confirmed", "Unsure", "Discarded", "All",
    ]);
    expect(encounterQuery({ scope: "live", include_discarded: true })).toContain(
      "include_discarded=true",
    );
  });

  it("shows old not-an-animal records as Discarded and corrected as confirmed", () => {
    expect(actionFor("false_positive")).toBe("discarded");
    expect(STATUS_LABELS.false_positive.label).toBe("Discarded");
    expect(STATUS_LABELS.corrected.label).toMatch(/^Confirmed/);
    expect(actionFor("unreviewed")).toBeNull();
  });

  it("keeps a decided card in place after the list refreshes", () => {
    const kept = new Map([["b", { index: 1, encounter: card("b", "correct") }]]);
    const shown = keepDecided([card("a"), card("c")], kept);
    expect(shown.map((item) => item.encounter_id)).toEqual(["a", "b", "c"]);
    expect(shown[1].review_status).toBe("correct");
  });

  it("shows the corrected species on the card straight away", () => {
    const heard = {
      ...card("a"),
      event: {
        modality: "audio",
        scientific_name: "Passer domesticus",
        common_name: "House Sparrow",
        review: { status: "unreviewed", notes: "kept" },
      },
    } as unknown as Encounter;
    const taxa = [
      { taxon_id: 7, scientific_name: "Copsychus saularis", common_name: "Oriental Magpie-Robin" },
    ];
    const corrected = withDecision(heard, "corrected", { taxonId: 7, notes: "kept", taxa });
    expect(encounterNames(corrected.event)).toEqual({
      primary: "Oriental Magpie-Robin",
      scientific: "Copsychus saularis",
    });
    expect(corrected.event.review.notes).toBe("kept");
    const undone = withDecision(corrected, "unreviewed", { notes: "kept", taxa });
    expect(undone.event.review.corrected_taxon_id).toBeNull();
    expect(encounterNames(undone.event).primary).toBe("House Sparrow");
  });
});
