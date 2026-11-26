// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AudioEvent, Review, VisualEvent } from "../types";
import { AudioCards, VisualCards } from "./DetectionCards";
import ObservationHistory from "./ObservationHistory";

const originalName = "Saxicoloides fulicatus";
const correctedName = "Copsychus saularis";
const review: Review = {
  status: "corrected",
  corrected_taxon_id: 42,
  corrected_scientific_name: correctedName,
  corrected_common_name: "Oriental Magpie-Robin",
  notes: null,
  updated_at: null,
};
const visual = {
  event_id: "visual",
  source_id: "source",
  source_filename: "sample.mp4",
  job_id: "job",
  modality: "visual",
  timestamp_ms: 0,
  duration_ms: 500,
  track_id: "job-track-1",
  review,
  detector: { score: 0.8, model: "detector" },
  classification: {
    status: "unknown",
    broad_group: "Aves",
    scientific_name: originalName,
    display_label: "Unknown bird",
    score: 0.3,
    top_k: [],
  },
} as unknown as VisualEvent;
const acoustic = {
  ...visual,
  modality: "audio",
  start_ms: 0,
  end_ms: 3000,
  confidence: 0.8,
  scientific_name: originalName,
  common_name: "Indian Robin",
} as unknown as AudioEvent;

describe("reviewed identifications in observation lists", () => {
  it("shows the corrected scientific name on visual and acoustic cards", () => {
    const html = renderToStaticMarkup(
      <>
        <VisualCards events={[visual]} onInspect={() => {}} />
        <AudioCards events={[acoustic]} onInspect={() => {}} />
      </>,
    );
    expect(
      html.match(new RegExp(`<em>${correctedName}</em>`, "g")),
    ).toHaveLength(2);
    expect(html).not.toContain(`<em>${originalName}</em>`);
    // Reviewing an identification must never rewrite the model evidence.
    expect(visual.classification.scientific_name).toBe(originalName);
    expect(acoustic.scientific_name).toBe(originalName);
  });

  it.each(["unknown", "false_positive"] as const)(
    "does not present the original taxon as an accepted name after a %s review",
    (status) => {
      const html = renderToStaticMarkup(
        <AudioCards
          events={[{ ...acoustic, review: { ...review, status } }]}
          onInspect={() => {}}
        />,
      );
      expect(html).not.toContain(`<em>${originalName}</em>`);
      expect(html).not.toContain(`<em>${correctedName}</em>`);
    },
  );

  it("uses the corrected name for acoustic history and labels the export scope", () => {
    const html = renderToStaticMarkup(
      <ObservationHistory
        events={[acoustic]}
        jobs={[]}
        runId="job"
        video={{ source_id: "source" } as never}
        onRun={() => {}}
        onSeek={() => {}}
        onInspect={() => {}}
      />,
    );
    expect(html).toContain(`<em>${correctedName}</em>`);
    expect(html).not.toContain(`<em>${originalName}</em>`);
    expect(html).toContain("Export all source runs");
  });
});
