import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { VisualEvent } from "../types";
import Inspector, { reviewSpeciesOptions } from "./Inspector";

const taxon = {
  taxon_id: 42,
  common_name: "Common Tailorbird",
  scientific_name: "Orthotomus sutorius",
  group: "Aves",
  observation_count: 100,
};
function renderReview(corrected = false) {
  const event = {
    event_id: "observation",
    source_filename: "sample.mp4",
    modality: "visual",
    timestamp_ms: 0,
    review: {
      status: "corrected",
      notes: null,
      corrected_taxon_id: corrected ? taxon.taxon_id : null,
      corrected_scientific_name: corrected ? taxon.scientific_name : null,
    },
    classification: {
      status: "unknown",
      display_label: "Unknown bird",
      score: 0.31,
      top_k: [taxon],
    },
  } as unknown as VisualEvent;
  return renderToStaticMarkup(
    <Inspector
      event={event}
      taxa={[taxon]}
      onClose={() => {}}
      onSaved={() => {}}
    />,
  );
}

describe("species review selection", () => {
  const frog = {
    ...taxon,
    taxon_id: 1,
    common_name: "Indian Bullfrog",
    scientific_name: "Hoplobatrachus tigerinus",
  };
  const warbler = {
    ...taxon,
    taxon_id: 2,
    common_name: "Sulphur-bellied Warbler",
    scientific_name: "Phylloscopus griseolus",
  };
  const source = {
    modality: "visual",
    classification: {
      top_k: [warbler],
      model_evidence: [{ top_k: [taxon, warbler] }],
    },
  } as unknown as VisualEvent;

  it("starts with actual model alternatives and the saved selection rather than taxonomy cache order", () => {
    const choices = reviewSpeciesOptions(
      source,
      [frog, taxon, warbler],
      taxon.taxon_id,
      "",
    );
    expect(choices.context).toBe("model");
    expect(choices.options.map((choice) => choice.taxon_id)).toEqual([42, 2]);
    expect(
      reviewSpeciesOptions(source, [frog, taxon, warbler], 0, "").options.map(
        (choice) => choice.taxon_id,
      ),
    ).toEqual([2, 42]);
  });

  it("asks for a search if no local model alternatives exist", () => {
    expect(reviewSpeciesOptions(source, [frog], 0, "")).toEqual({
      options: [],
      context: "empty",
    });
    expect(reviewSpeciesOptions(source, [frog], frog.taxon_id, "")).toEqual({
      options: [frog],
      context: "selected",
    });
  });

  it("searches the complete taxonomy with typos when the user types", () => {
    const result = reviewSpeciesOptions(
      source,
      [frog, taxon, warbler],
      0,
      "bullforg",
    );
    expect(result.context).toBe("search");
    expect(result.options).toEqual([frog]);
  });

  it("does not choose the closest species automatically or enable saving an empty correction", () => {
    const html = renderReview();
    expect(html).toContain("No species selected");
    expect(html).toMatch(
      /<button class="primary" disabled="">Save review<\/button>/,
    );
    expect(html).toMatch(/role="option" aria-selected="false"/);
    expect(html.match(/<button[^>]*decision-correct[^>]*>/)?.[0]).toContain(
      'disabled=""',
    );
  });

  it("keeps an explicitly saved correction selected independently of model output", () => {
    const html = renderReview(true);
    expect(html).toMatch(/role="option" aria-selected="true"/);
    expect(html).toContain("Selected species");
    expect(html).toContain("Common Tailorbird");
    expect(html).toContain("Unknown bird");
    expect(html).not.toContain('<button class="primary" disabled="">');
    expect(html).toContain("model said");
  });
});
