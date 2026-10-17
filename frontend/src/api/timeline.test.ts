import { expect, it } from "vitest";
import { currentEvents, formatTime, matchesObservation } from "./timeline";
import type { Detection, VisualEvent } from "../types";

it("rounds timestamps across minute boundaries without displaying 60 seconds", () => {
  expect(formatTime(59949)).toBe("00:59.9");
  expect(formatTime(59950)).toBe("01:00.0");
  expect(formatTime(3599999)).toBe("60:00.0");
  expect(formatTime(-100)).toBe("00:00.0");
  expect(formatTime(NaN)).toBe("00:00.0");
});
it("uses half-open intervals and keeps audio independent through seeks", () => {
  const events = [
    {
      modality: "visual",
      timestamp_ms: 1000,
      duration_ms: 500,
      classification: { status: "unknown" },
    },
    { modality: "audio", start_ms: 1300, end_ms: 4300, confidence: 0.8 },
  ] as Detection[];
  expect(currentEvents(events, 999).visual).toHaveLength(0);
  expect(currentEvents(events, 1400).visual).toHaveLength(1);
  expect(currentEvents(events, 1500).visual).toHaveLength(0);
  expect(currentEvents(events, 1500).audio).toHaveLength(1);
  expect(currentEvents(events, 0).audio).toHaveLength(0);
});

it("finds an ensemble event by either model's suggestions without changing its uncertain label", () => {
  const robin = {
    taxon_id: 1,
    scientific_name: "Saxicoloides fulicatus",
    common_name: "Indian Robin",
    group: "Aves",
    score: 0.8,
  };
  const magpie = {
    ...robin,
    taxon_id: 2,
    scientific_name: "Copsychus saularis",
    common_name: "Oriental Magpie-Robin",
    score: 0.7,
  };
  const event = {
    modality: "visual",
    review: { status: "unreviewed" },
    classification: {
      scientific_name: null,
      display_label: "Unknown bird",
      status: "unknown",
      consensus: "disagree",
      top_k: [robin],
      model_evidence: [
        { model: "imageomics/bioclip-2.5-vith14", top_k: [robin] },
        { model: "imageomics/bioclip-2", top_k: [magpie] },
      ],
    },
  } as VisualEvent;
  expect(matchesObservation(event, " MAGPIE ")).toBe(true);
  expect(matchesObservation(event, "Copsychus saularis")).toBe(true);
  expect(matchesObservation(event, "Indian Robin")).toBe(true);
  expect(matchesObservation(event, "Unknown bird")).toBe(true);
  expect(matchesObservation(event, "warbler")).toBe(false);
  expect(event.classification.status).toBe("unknown");
});

it("continues to find older observations without model evidence", () => {
  const event = {
    modality: "visual",
    review: { status: "unreviewed" },
    classification: {
      scientific_name: null,
      display_label: "Unknown bird",
      top_k: [
        {
          scientific_name: "Copsychus saularis",
          common_name: "Oriental Magpie-Robin",
        },
      ],
    },
  } as VisualEvent;
  expect(matchesObservation(event, "magpie")).toBe(true);
  expect(matchesObservation(event, "unreviewed")).toBe(true);
  expect(matchesObservation(event, "")).toBe(true);
});
