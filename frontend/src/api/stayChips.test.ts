// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { drawnBoxes, ownBoxes, type StoredBox } from "../components/EvidencePlayer";
import type { Detection, ReviewStatus } from "../types";
import type { Encounter } from "./encounters";
import { cardClock } from "./reviewList";
import { decidingLine, decisionGroupLabel, stayChips, stayRows, trackOf, visitName } from "./stayChips";

const robin = { common_name: "Oriental Magpie-Robin", scientific_name: "Copsychus saularis" };

const visit = (
  id: string,
  at: string,
  extra: Partial<Encounter> = {},
  review: { status: ReviewStatus; corrected_common_name?: string } = { status: "unreviewed" },
  classification: Record<string, unknown> = {},
): Encounter =>
  ({
    encounter_id: id,
    modality: "visual",
    review_status: review.status,
    first_captured_at: at,
    duration_ms: 20_000,
    records: 4,
    source_filename: "Camera",
    thumbnail_event_id: id,
    stay_id: "stay-1",
    attached: false,
    stay_recordings: 1,
    hidden_reason: null,
    event: {
      event_id: id,
      modality: "visual",
      review: {
        notes: null, corrected_taxon_id: null, corrected_scientific_name: null, corrected_common_name: null,
        ...review,
      },
      classification: {
        status: "candidate", certainty: "likely", common_name: robin.common_name,
        scientific_name: robin.scientific_name, display_label: robin.common_name, score: 0.56,
        broad_group: "Aves", top_k: [{ ...robin, group: "Aves", score: 0.56 }],
        ...classification,
      },
    } as unknown as Detection,
    ...extra,
  }) as unknown as Encounter;

const at = (iso: string) => cardClock(new Date(iso));
const atSeconds = (iso: string) => cardClock(new Date(iso), true);

describe("the stay's chips", () => {
  const b = visit("job-1:track-0002", "2026-11-22T04:08:30Z");
  const a = visit("job-1:track-0001", "2026-11-22T04:07:57Z");
  const hidden = visit("job-1:track-0009", "2026-11-22T04:06:00Z", { attached: true, hidden_reason: "STILL" });
  const elsewhere = visit("job-2:track-0001", "2026-11-22T05:00:00Z", { stay_id: "stay-2" });

  it("lists the rows in front in start order, then the hidden ones; other stays stay out", () => {
    const rows = stayRows(b, [b, elsewhere, hidden, a]);
    expect(rows.map((row) => row.encounter_id)).toEqual(["job-1:track-0001", "job-1:track-0002", "job-1:track-0009"]);
  });

  it("shows no chips for a stay of one row with nothing attached, nor for a sound", () => {
    expect(stayRows(elsewhere, [a, b, elsewhere])).toEqual([]);
    expect(stayRows({ ...a, modality: "audio" }, [a, b])).toEqual([]);
    expect(stayRows(a, undefined)).toEqual([]);
  });

  it("reads 'Name 09:37' in the device's own form, muted for hidden rows", () => {
    const chips = stayChips(stayRows(a, [a, b, hidden]));
    expect(chips.map((chip) => [chip.name, chip.time, chip.hidden])).toEqual([
      ["Oriental Magpie-Robin", at(a.first_captured_at!), false],
      ["Oriental Magpie-Robin", at(b.first_captured_at!), false],
      ["Oriental Magpie-Robin", at(hidden.first_captured_at!), true],
    ]);
  });

  it("gives both chips seconds when two would read the same, and only those two", () => {
    const first = visit("j:t1", "2026-11-22T04:07:05Z");
    const second = visit("j:t2", "2026-11-22T04:07:40Z");
    const later = visit("j:t3", "2026-11-22T04:09:10Z");
    const times = stayChips([first, second, later]).map((chip) => chip.time);
    expect(times).toEqual([
      atSeconds(first.first_captured_at!),
      atSeconds(second.first_captured_at!),
      at(later.first_captured_at!),
    ]);
    expect(times[0]).not.toEqual(times[1]);
  });

  it("puts a tick on a decided row and shows the corrected name", () => {
    const corrected = visit("j:t1", "2026-11-22T04:07:05Z", {}, { status: "corrected", corrected_common_name: "Bluethroat" });
    const open = visit("j:t2", "2026-11-22T04:09:40Z");
    const chips = stayChips([corrected, open]);
    expect(chips.map((chip) => [chip.name, chip.decided])).toEqual([["Bluethroat", true], ["Oriental Magpie-Robin", false]]);
  });

  it("keeps the chip of a discarded row, muted, so Undo stays in reach", () => {
    const thrown = visit("j:t1", "2026-11-22T04:07:05Z", {}, { status: "discarded" });
    const open = visit("j:t2", "2026-11-22T04:09:40Z");
    const chips = stayChips([thrown, open]);
    expect(chips.map((chip) => [chip.name, chip.decided, chip.discarded])).toEqual([
      ["Discarded", true, true],
      ["Oriental Magpie-Robin", false, false],
    ]);
  });

  it("says which animal the buttons act on", () => {
    expect(decidingLine(a)).toBe(`Deciding: Oriental Magpie-Robin, from ${atSeconds(a.first_captured_at!)}`);
    expect(decisionGroupLabel(a)).toBe(`Your decision for Oriental Magpie-Robin, from ${atSeconds(a.first_captured_at!)}`);
  });
});

describe("names on the boxes", () => {
  it("names a box by the verdict, the card's name, or Discarded", () => {
    const confirmed = visit("j:t1", "2026-11-22T04:07:05Z", {}, { status: "correct" });
    const corrected = visit("j:t2", "2026-11-22T04:07:05Z", {}, { status: "corrected", corrected_common_name: "Bluethroat" });
    const open = visit("j:t3", "2026-11-22T04:07:05Z");
    const unknown = visit("j:t4", "2026-11-22T04:07:05Z", {}, { status: "unreviewed" }, {
      status: "unknown", certainty: "unknown", common_name: null, scientific_name: null,
      display_label: "Unknown bird · Aves", broad_group: "Aves", top_k: [],
    });
    const discarded = visit("j:t5", "2026-11-22T04:07:05Z", {}, { status: "discarded" });
    const notAnimal = visit("j:t6", "2026-11-22T04:07:05Z", {}, { status: "false_positive" });
    expect([confirmed, corrected, open, unknown, discarded, notAnimal].map((item) => visitName(item))).toEqual([
      "Oriental Magpie-Robin", "Bluethroat", "Oriental Magpie-Robin", "Unknown bird", "Discarded", "Discarded",
    ]);
  });

  it("matches a box to its visit by the last eight characters of the visit key", () => {
    expect(trackOf("f141899b-e168-443d-bae5-adb134aa04bf:f141899b-track-86")).toBe("track-86");
    expect(trackOf("1a2b3c4d-0000-0000-0000-00000000abcd")).toBe("0000abcd");
  });
});

describe("switching the animal by chip", () => {
  const boxes: StoredBox[] = [
    { t: 1000, bbox: [0.1, 0.1, 0.2, 0.2], track: "track-01", own: true, tone: "likely", label: "A" },
    { t: 4000, bbox: [0.1, 0.1, 0.2, 0.2], track: "track-01", own: true, tone: "likely", label: "A" },
    { t: 6000, bbox: [0.5, 0.5, 0.6, 0.6], track: "track-02", own: false, tone: "faint", label: "B" },
    { t: 9000, bbox: [0.5, 0.5, 0.6, 0.6], track: "track-02", own: false, tone: "faint", label: "B" },
  ];

  it("keeps the server's own box and stretch when no chip is chosen", () => {
    expect(ownBoxes(boxes, null, [1000, 4000])).toEqual({ boxes, span: [1000, 4000] });
  });

  it("makes the chosen animal's box the bold one and its stretch the marked one", () => {
    const own = ownBoxes(boxes, "track-02", [1000, 4000]);
    expect(own.span).toEqual([6000, 9000]);
    expect(own.boxes.map((b) => b.own)).toEqual([false, false, true, true]);
  });

  it("draws no box and so no name with the Boxes switch off", () => {
    expect(drawnBoxes(boxes, 1000, true).map((b) => b.track)).toEqual(["track-01"]);
    expect(drawnBoxes(boxes, 1000, false)).toEqual([]);
  });

  it("leaves out a discarded visit's box and draws it again after Undo", () => {
    const gone = new Set(["track-02"]);
    expect(drawnBoxes(boxes, 6000, true, gone)).toEqual([]);
    gone.delete("track-02"); // Undo: the visit is no longer discarded
    expect(drawnBoxes(boxes, 6000, true, gone).map((b) => b.track)).toEqual(["track-02"]);
  });

  it("has no stretch for an animal that is not on this recording", () => {
    expect(ownBoxes(boxes, "track-77", [1000, 4000]).span).toBeNull();
  });
});
