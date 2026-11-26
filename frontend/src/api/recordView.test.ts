// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it, vi } from "vitest";
import type { Encounter } from "./encounters";
import {
  actionForKind,
  changedReviews,
  confirmAction,
  decisionAnnouncement,
  decisionSnapshot,
  itemFromEncounter,
  pickAction,
  cardStatus,
  noteDraft,
  recordIdentity,
  tierText,
  recordKeyAction,
  reviewsSavedMessage,
  snapshotOf,
  storeReview,
  type RecordItem,
} from "./recordView";
import type { Detection } from "../types";

const robin = { taxon_id: 1, common_name: "Oriental Magpie-Robin", scientific_name: "Copsychus saularis" };
const sparrow = { taxon_id: 2, common_name: "House Sparrow", scientific_name: "Passer domesticus" };
const taxa = [robin, sparrow];

const visual = (classification = {}, review = {}) =>
  ({
    event_id: "e",
    modality: "visual",
    review: { status: "unreviewed", notes: "first", corrected_taxon_id: null, corrected_scientific_name: null, ...review },
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
  }) as unknown as Detection;
const record = (event = visual()): RecordItem =>
  itemFromEncounter({ encounter_id: "visit", review_status: event.review.status, event } as Encounter);

describe("one tap decisions", () => {
  it("stores first, then shows the decision, and Undo restores status, species and note", async () => {
    const store = vi.fn().mockResolvedValue(undefined);
    const item = record();
    const before = snapshotOf(item.event);
    const saved = await storeReview(item, decisionSnapshot({ kind: "confirm", status: "correct" }, "first"), taxa, store);
    expect(store).toHaveBeenCalledWith(item, "correct", { taxonId: undefined, notes: "first" });
    expect(saved.encounter?.review_status).toBe("correct");
    const corrected = await storeReview(saved, decisionSnapshot(pickAction(saved.event, sparrow, taxa), "first"), taxa, store);
    expect(corrected.event.review.corrected_common_name).toBe("House Sparrow");
    const undone = await storeReview(corrected, before, taxa, store);
    expect(snapshotOf(undone.event)).toEqual(before);
  });

  it("does not show a decision as taken when the store fails", async () => {
    const item = record();
    await expect(storeReview(item, { status: "correct", notes: null }, taxa, () => Promise.reject(new Error("offline")))).rejects.toThrow();
    expect(item.event.review.status).toBe("unreviewed");
  });

  it("treats picking the model's own species as Confirm", () => {
    expect(pickAction(visual(), robin, taxa)).toEqual({ kind: "confirm", status: "correct" });
    expect(pickAction(visual(), sparrow, taxa)).toEqual({ kind: "correct", status: "corrected", taxonId: 2 });
  });

  it("offers Confirm only with a candidate species", () => {
    expect(confirmAction(visual(), taxa)?.status).toBe("correct");
    const probable = visual({ status: "unknown", certainty: "probable", scientific_name: null, common_name: null, contenders: [{ ...robin, score: 0.4 }] });
    expect(confirmAction(probable, taxa)).toEqual({ kind: "confirm", status: "corrected", taxonId: 1 });
    expect(confirmAction(visual({ status: "unknown", certainty: "unknown", scientific_name: null, common_name: null, top_k: [] }), taxa)).toBeNull();
    expect(actionForKind("discard", visual(), taxa)?.status).toBe("discarded");
  });

  it("counts changed records for the closing message", () => {
    const first = visual();
    const changed = visual({}, { status: "correct" });
    expect(changedReviews(new Map([["a", snapshotOf(first)], ["b", snapshotOf(first)]]), new Map([["a", changed], ["b", first]]))).toBe(1);
    expect(reviewsSavedMessage(1)).toBe("1 review saved");
    expect(reviewsSavedMessage(3)).toBe("3 reviews saved");
  });
});

describe("what the record says", () => {
  it("names the model's guess before a decision and the final name after one", () => {
    expect(recordIdentity(visual())).toMatchObject({ label: "Model's guess", pill: { text: "Likely" }, name: robin.common_name, modelSaid: null });
    expect(recordIdentity(visual({}, { status: "correct" }))).toMatchObject({ label: "Final identification", pill: { text: "Confirmed" } });
    const corrected = visual({}, { status: "corrected", corrected_taxon_id: 2, corrected_scientific_name: sparrow.scientific_name, corrected_common_name: sparrow.common_name });
    expect(recordIdentity(corrected)).toMatchObject({ pill: { text: "Corrected" }, name: "House Sparrow", scientific: sparrow.scientific_name, modelSaid: { name: robin.common_name, score: 0.41 } });
    expect(decisionAnnouncement(corrected)).toBe("Corrected to House Sparrow. The model said Oriental Magpie-Robin. Saved. Undo is available.");
    // Under "Model's guess" the pill stays the model's own tier after Unsure or Discard.
    expect(recordIdentity(visual({}, { status: "unknown" }))).toMatchObject({ label: "Model's guess", pill: { text: "Likely" } });
    expect(recordIdentity(visual({}, { status: "false_positive" }))).toMatchObject({ label: "Model's guess", pill: { text: "Likely" } });
    expect(tierText(visual({}, { status: "correct" }))).toBe("Likely");
  });
});

describe("keyboard", () => {
  it("maps the review keys and ignores typing and modified keys", () => {
    expect(["c", "R", "u", "d", "j", "ArrowRight", "k", "ArrowLeft", "n"].map((key) => recordKeyAction({ key }))).toEqual(["confirm", "correct", "unsure", "discard", "next", "next", "previous", "previous", "note"]);
    expect(recordKeyAction({ key: "c", target: { tagName: "INPUT" } })).toBeNull();
    expect(recordKeyAction({ key: "c", ctrlKey: true })).toBeNull();
  });
});

describe("note field", () => {
  it("shows the note of the record on screen, never the one before", () => {
    const drafts = { a: "typed on a" };
    expect(noteDraft(drafts, "a", "stored a")).toBe("typed on a");
    expect(noteDraft(drafts, "b", "stored b")).toBe("stored b");
    expect(noteDraft(drafts, "c", null)).toBe("");
  });
});

describe("card status pill", () => {
  it("reads Confirmed when the stored correction is the model's own species", () => {
    const confirmed = visual({}, { status: "corrected", corrected_taxon_id: 1, corrected_scientific_name: robin.scientific_name, corrected_common_name: robin.common_name });
    expect(cardStatus("corrected", confirmed).label).toBe("Confirmed");
    const corrected = visual({}, { status: "corrected", corrected_taxon_id: 2, corrected_scientific_name: sparrow.scientific_name, corrected_common_name: sparrow.common_name });
    expect(cardStatus("corrected", corrected).label).toBe("Confirmed · corrected");
    expect(cardStatus("unknown", visual({}, { status: "unknown" })).label).toBe("Unsure");
  });
});
