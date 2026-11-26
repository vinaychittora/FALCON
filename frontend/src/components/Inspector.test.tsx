// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Encounter } from "../api/encounters";
import type { AudioEvent, VisualEvent } from "../types";
import Inspector from "./Inspector";

const robin = {
  taxon_id: 42,
  common_name: "Oriental Magpie-Robin",
  scientific_name: "Copsychus saularis",
  group: "Aves",
  observation_count: 100,
};
const flowerpecker = {
  ...robin,
  taxon_id: 7,
  common_name: "Thick-billed Flowerpecker",
  scientific_name: "Dicaeum agile",
};

function visit(review = {}, classification = {}) {
  return {
    event_id: "observation",
    source_id: "source",
    source_filename: "falcon-node",
    modality: "visual",
    timestamp_ms: 0,
    duration_ms: 1000,
    track_id: "run-track-1",
    bbox_norm: [0.1, 0.1, 0.4, 0.4],
    detector: { score: 0.8, model: "detector" },
    environment: { status: "not_connected" },
    models: {},
    evidence_summaries: [],
    review: { status: "unreviewed", notes: null, corrected_taxon_id: null, corrected_scientific_name: null, ...review },
    classification: {
      broad_group: "Aves",
      status: "candidate",
      certainty: "likely",
      display_label: "Thick-billed Flowerpecker — candidate",
      common_name: flowerpecker.common_name,
      scientific_name: flowerpecker.scientific_name,
      score: 0.41,
      margin: 0.02,
      unknown_reason: null,
      top_k: [{ ...flowerpecker, score: 0.41 }, { ...robin, score: 0.39 }],
      ...classification,
    },
  } as unknown as VisualEvent;
}

const render = (event: VisualEvent | AudioEvent, encounter?: Partial<Encounter>) =>
  renderToStaticMarkup(
    <Inspector
      event={event}
      encounter={encounter ? ({ encounter_id: "e", records: 3, event, ...encounter } as Encounter) : undefined}
      taxa={[robin, flowerpecker]}
      onClose={() => {}}
    />,
  );

describe("record view", () => {
  it("shows the decisions and the model evidence in front, with no Save button", () => {
    const html = render(visit(), { heard: [{ name: "House Sparrow", confidence: 0.851 }] });
    for (const word of ["Confirm", "Correct", "Unsure", "Discard", "Model&#x27;s guess", "Camera model", "Microphone model", "House Sparrow", "0.85", "similarity, not a probability"])
      expect(html).toContain(word);
    expect(html).not.toContain("Save review");
    expect(html).not.toContain("%<");
    expect(html).toContain('class="rv-decision primary"');
  });

  it("disables Confirm and leaves no primary decision without a candidate species", () => {
    const html = render(visit({}, { status: "unknown", certainty: "unknown", scientific_name: null, common_name: null, display_label: "Unknown bird", top_k: [] }));
    expect(html).not.toContain("rv-decision primary");
    expect(html.match(/<button[^>]*data-kind="confirm"[^>]*>/)?.[0]).toContain('disabled=""');
  });

  it("puts the corrected species first and keeps what the model said", () => {
    const html = render(visit({ status: "corrected", corrected_taxon_id: robin.taxon_id, corrected_scientific_name: robin.scientific_name, corrected_common_name: robin.common_name }), {});
    expect(html).toContain("Final identification");
    expect(html).toMatch(/<h1[^>]*>Oriental Magpie-Robin<\/h1>/);
    expect(html).toContain("Corrected to Oriental Magpie-Robin");
    expect(html).toContain("Model said");
    expect(html).toContain("your choice");
    expect(html.match(/<button[^>]*data-kind="correct"[^>]*>/)?.[0]).toContain('aria-pressed="true"');
  });

  it("keeps every other fact in labelled expands", () => {
    const html = render(visit(), {});
    for (const label of ["Camera model in detail", "Sound during this visit", "Recording", "Record data", "Post to iNaturalist", "Available after Confirm or Correct", "A decision applies to all 3 frames"])
      expect(html).toContain(label);
  });
});
