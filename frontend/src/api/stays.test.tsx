// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import EncounterCard from "../ui/EncounterCard";
import StayCard from "../ui/StayCard";
import { keepDecided } from "../pages/ReviewPage";
import type { Taxon } from "../pages/Taxa";
import type { Detection } from "../types";
import type { Encounter } from "./encounters";
import { groupStays, hiddenMoreLine, hiddenReasonText, recordingsLine, rowFrom, stayTimeLine } from "./stays";

const robin = { taxon_id: 1, common_name: "Oriental Magpie-Robin", scientific_name: "Copsychus saularis" };
const taxa = [robin] as unknown as Taxon[];

const visit = (id: string, at: string, extra: Partial<Encounter> = {}): Encounter =>
  ({
    encounter_id: id,
    modality: "visual",
    review_status: "unreviewed",
    first_captured_at: at,
    duration_ms: 88_000,
    records: 4,
    source_filename: "Camera",
    thumbnail_event_id: id,
    stay_id: "v1",
    attached: false,
    stay_recordings: 1,
    hidden_reason: null,
    event: {
      event_id: id,
      modality: "visual",
      review: { status: "unreviewed", notes: null, corrected_taxon_id: null, corrected_scientific_name: null },
      classification: {
        status: "candidate", certainty: "likely", common_name: robin.common_name,
        scientific_name: robin.scientific_name, display_label: robin.common_name, score: 0.56,
        top_k: [{ ...robin, group: "Aves", score: 0.56 }],
      },
    } as unknown as Detection,
    ...extra,
  }) as unknown as Encounter;

const stayCard = (items: Encounter[]) =>
  renderToStaticMarkup(
    <ul>
      <StayCard stay={groupStays(items)[0]} taxa={taxa} onDecision={async () => {}} onOpen={() => {}}
                selected={new Set()} onSelect={() => {}} />
    </ul>,
  );

describe("one card per stay", () => {
  const a = visit("a", "2026-11-22T04:07:57Z");
  const b = visit("b", "2026-11-22T04:08:30Z");
  const c = visit("c", "2026-11-22T04:09:00Z", { duration_ms: 31_000 });
  const hidden = visit("h", "2026-11-22T04:08:00Z", { attached: true, hidden_reason: "STILL" });

  it("groups a page by stay in the order its first item comes; no stay means its own", () => {
    const solo = visit("s", "2026-11-22T05:00:00Z", { stay_id: undefined });
    const groups = groupStays([a, solo, b, hidden, c]);
    expect(groups.map((g) => [g.stayId, g.front.map((e) => e.encounter_id), g.attached.length])).toEqual([
      ["v1", ["a", "b", "c"], 1],
      ["s", ["s"], 0],
    ]);
  });

  it("one row and nothing hidden is today's card, unchanged", () => {
    const today = renderToStaticMarkup(
      <ul>
        <EncounterCard encounter={a} taxa={taxa} onDecision={async () => {}} onOpen={() => {}} selected={false}
                       onSelect={() => {}} />
      </ul>,
    );
    expect(stayCard([a])).toBe(today);
  });

  it("two or more rows get the head; each row its own decisions, from its own time", () => {
    const html = stayCard([a, b, c, hidden]);
    expect(html).toContain("3 animals in one stay");
    expect(html).toContain(stayTimeLine([a, b, c]));
    expect(html).toContain("One recording, kept once");
    expect(html.match(/class="rl-card rl-row/g)?.length).toBe(4);
    expect(html).toContain(`Your decision for Oriental Magpie-Robin, from ${rowFrom(a.first_captured_at)}`);
    expect(html).toContain(`<summary>${hiddenMoreLine(1)}</summary>`);
    expect(html).toContain(">Hidden<");
    expect(html).toContain(hiddenReasonText("STILL"));
  });

  it("one row with hidden ones attached: today's card plus the closed line, no head", () => {
    const html = stayCard([a, hidden]);
    expect(html).not.toContain("in one stay");
    expect(html).toContain("1 more that FALCON hid in this stay");
    expect(html.match(/class="rl-card"/g)?.length).toBe(1);
  });

  it("a decided row takes its stay from the fresh answer; one that left keeps its place", () => {
    const decided = { ...a, review_status: "correct" } as Encounter;
    const moved = { ...a, stay_id: "v9" } as Encounter;
    const kept = new Map([["a", { index: 0, encounter: decided }], ["b", { index: 1, encounter: b }]]);
    const result = keepDecided([moved, c], kept);
    expect(result.map((e) => [e.encounter_id, e.stay_id, e.review_status])).toEqual([
      ["a", "v9", "correct"], ["b", "v1", "unreviewed"], ["c", "v1", "unreviewed"],
    ]);
  });

  it("the head's lines", () => {
    expect(stayTimeLine([a, c], new Date("2026-11-24T00:00:00Z"))).toMatch(/ to .* · 1 min 34 s$/);
    expect(recordingsLine(1)).toBe("One recording, kept once");
    expect(recordingsLine(3)).toBe("3 recordings in a row, each kept once");
    expect(hiddenReasonText("GLIMPSE")).toBe("recorded in one frame only");
    expect(hiddenReasonText("UNRESOLVED")).toBe("no species and no group yet");
    expect(hiddenReasonText("SOMETHING_NEW")).toBe("FALCON keeps it out of the default list");
  });

  it("a stay of several rows says how many columns it may take; one row takes one cell", () => {
    expect(stayCard([a, b, c])).toContain('data-rows="3"');
    expect(stayCard([a, hidden])).not.toContain("data-rows");
  });
});
