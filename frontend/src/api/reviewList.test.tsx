// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import EncounterCard from "../ui/EncounterCard";
import { keepDecided } from "../pages/ReviewPage";
import type { Taxon } from "../pages/Taxa";
import type { Detection } from "../types";
import type { Encounter, EncounterFilters } from "./encounters";
import {
  beforeReviews,
  bulkMessage,
  cardAction,
  cardWhen,
  evidenceLine,
  filterCaption,
  statusOptionLabel,
  toReviewFilters,
} from "./reviewList";

const robin = { taxon_id: 1, common_name: "Oriental Magpie-Robin", scientific_name: "Copsychus saularis" };
const sparrow = { taxon_id: 2, common_name: "House Sparrow", scientific_name: "Passer domesticus" };
const taxa = [robin, sparrow];

const visit = (id: string, review = {}, classification = {}): Encounter =>
  ({
    encounter_id: id,
    modality: "visual",
    review_status: (review as { status?: string }).status ?? "unreviewed",
    first_captured_at: "2026-11-18T03:14:00Z",
    duration_ms: 9000,
    records: 4,
    source_filename: "Camera",
    thumbnail_event_id: id,
    heard: [{ name: "House Sparrow", confidence: 0.853 }],
    event: {
      event_id: id,
      modality: "visual",
      review: { status: "unreviewed", notes: null, corrected_taxon_id: null, corrected_scientific_name: null, ...review },
      classification: {
        status: "candidate",
        certainty: "likely",
        common_name: robin.common_name,
        scientific_name: robin.scientific_name,
        display_label: robin.common_name,
        score: 0.41,
        top_k: [{ ...robin, group: "Aves", score: 0.41 }],
        ...classification,
      },
    } as unknown as Detection,
  }) as unknown as Encounter;

const card = (encounter: Encounter) =>
  renderToStaticMarkup(
    <EncounterCard encounter={encounter} taxa={taxa as unknown as Taxon[]} onDecision={async () => {}} onOpen={() => {}} onSelect={() => {}} />,
  );

describe("the card", () => {
  it("keeps the model's tier pill after Unsure and Discard", () => {
    for (const status of ["unknown", "discarded"]) {
      const html = card(visit("a", { status }));
      expect(html).toContain(">Likely<");
      expect(html).not.toContain(">Unsure</span>");
      expect(html).not.toContain(">Discarded<");
    }
    expect(card(visit("a", { status: "correct" }))).toContain(">Confirmed<");
  });

  it("has four decision buttons in one group, text only, with the pressed one marked", () => {
    const html = card(visit("a", { status: "unknown" }));
    const group = html.slice(html.indexOf('class="decs"'));
    expect(group.match(/class="dec"/g)).toHaveLength(4);
    expect(html).toMatch(/aria-pressed="true"[^>]*>Unsure</);
    expect(html).toContain("Select Oriental Magpie-Robin");
  });

  it("disables Confirm with the reason in words when the models named nothing", () => {
    const html = card(visit("a", {}, { status: "unknown", certainty: "unknown", top_k: [], scientific_name: null, common_name: null }));
    expect(html).toContain("No species to confirm. Use Correct to name it.");
    expect(html).toMatch(/disabled=""[^>]*>Confirm</);
  });

  it("writes the evidence with two decimals and the model's name after a correction", () => {
    expect(evidenceLine(visit("a")).text).toBe("Camera 0.41 · heard House Sparrow 0.85");
    const corrected = visit("a", { status: "corrected", corrected_taxon_id: 2, corrected_scientific_name: sparrow.scientific_name, corrected_common_name: sparrow.common_name });
    expect(evidenceLine(corrected).said).toEqual({ name: robin.common_name, score: "0.41" });
  });

  it("shows the time only for today's records", () => {
    const now = new Date("2026-11-18T10:00:00Z");
    expect(cardWhen("2026-11-18T03:14:00Z", now)).not.toMatch(/Nov/);
    expect(cardWhen("2026-11-10T03:14:00Z", now)).toMatch(/Nov/);
  });
});

describe("decisions", () => {
  it("maps each tap to exactly one stored decision, the record view's", () => {
    const probable = visit("p", {}, { status: "unknown", certainty: "probable" });
    expect(cardAction("confirm", visit("a"), taxa)).toEqual({ kind: "confirm", status: "correct" });
    expect(cardAction("confirm", probable, taxa)).toEqual({ kind: "confirm", status: "corrected", taxonId: 1 });
    expect(cardAction("unsure", visit("a"), taxa)).toEqual({ kind: "unsure", status: "unknown" });
    expect(cardAction("discard", visit("a"), taxa)).toEqual({ kind: "discard", status: "discarded" });
    expect(cardAction("correct", visit("a"), taxa)).toBeNull(); // opens the chooser
  });

  it("keeps a decided card in its place until the list is refreshed", () => {
    const decided = visit("b", { status: "unknown" });
    const kept = new Map([["b", { index: 1, encounter: decided }]]);
    const fresh = [visit("a"), visit("c")]; // the server no longer lists b under To review
    expect(keepDecided(fresh, kept).map((item) => item.encounter_id)).toEqual(["a", "b", "c"]);
    expect(keepDecided(fresh, new Map()).map((item) => item.encounter_id)).toEqual(["a", "c"]);
  });
});

describe("bulk actions", () => {
  it("remember exactly the ticked cards, so Undo restores each one", () => {
    const ticked = [visit("a"), visit("b", { status: "corrected", corrected_taxon_id: 2, notes: "male" })];
    const before = beforeReviews(ticked);
    expect([...before.keys()]).toEqual(["a", "b"]);
    expect(before.get("b")).toEqual({ status: "corrected", taxonId: 2, notes: "male" });
    expect(before.get("a")).toEqual({ status: "unreviewed", taxonId: undefined, notes: undefined });
    expect(bulkMessage("unknown", 2)).toBe("Marked 2 records unsure");
    expect(bulkMessage("corrected", 1, "House Sparrow")).toBe("Corrected 1 record to House Sparrow");
  });
});

describe("filters and counts", () => {
  it("counts To review and opens the queue with the same filters", () => {
    const filters = { scope: "live", modality: "audio", review_status: "confirmed", include_discarded: false, limit: 48, offset: 96, q: "" } as EncounterFilters;
    const counted = toReviewFilters(filters);
    expect(counted).toMatchObject({ scope: "live", modality: "audio", review_status: "unreviewed", include_discarded: false, offset: 0 });
    expect(statusOptionLabel("To review", 6)).toBe("To review (6)");
    expect(statusOptionLabel("To review", null)).toBe("To review");
  });

  it("names the active filters and marks a change from the defaults", () => {
    const base = { period: "7d", periodLabel: "Last 7 days", modality: "", query: "", scope: "live", source: "", sourceLabel: "", showHidden: false, minScore: "" };
    expect(filterCaption(base)).toEqual({ text: "Last 7 days · video and sound", changed: false });
    expect(filterCaption({ ...base, period: "24h", periodLabel: "Last 24 hours", modality: "audio" })).toEqual({ text: "Last 24 hours · sound only", changed: true });
  });
});
