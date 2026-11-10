import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AudioEvent, VisualEvent } from "../types";
import { AudioCards } from "../components/DetectionCards";
import ObservationHistory from "../components/ObservationHistory";
import Inspector from "../components/Inspector";
import { TaxonNamesContext } from "../components/TaxonNames";
import { indexTaxonNames, scientificSubtitle } from "./names";
import {
  displayLabel,
  displayScientificName,
  matchesObservation,
} from "./timeline";
import { rankObservations } from "./search";
import { observationOverlays } from "./overlays";

const pitta = {
  taxon_id: 100,
  common_name: "Indian Pitta",
  scientific_name: "Pitta brachyura",
  group: "Aves",
  observation_count: 1,
};
const names = indexTaxonNames([pitta]);
const oldCorrection = {
  event_id: "event",
  job_id: "run",
  source_id: "source",
  source_filename: "sample.wav",
  modality: "audio",
  start_ms: 0,
  end_ms: 3000,
  common_name: "Indian Robin",
  scientific_name: "Saxicoloides fulicatus",
  confidence: 0.8,
  review: {
    status: "corrected",
    corrected_taxon_id: pitta.taxon_id,
    corrected_scientific_name: pitta.scientific_name,
    notes: null,
  },
} as AudioEvent;

describe("reviewed common and scientific names", () => {
  it("suppresses a scientific fallback despite its candidate suffix without inventing a common name", () => {
    const scientific = "Anabasis obliquifasciella";
    for (const suffix of [
      " — candidate",
      " – candidate",
      " · candidate",
      " - Candidate",
      "",
    ]) {
      expect(scientificSubtitle(scientific + suffix, scientific)).toBeNull();
    }
    expect(
      scientificSubtitle("Indian Pitta — candidate", "Pitta brachyura"),
    ).toBe("Pitta brachyura");
    expect(
      scientificSubtitle(
        "Anabasis obliquifasciella complex — candidate",
        scientific,
      ),
    ).toBe(scientific);
  });
  it("resolves an older corrected Indian Pitta record by its saved taxon", () => {
    expect(displayLabel(oldCorrection, names)).toBe("Indian Pitta");
    expect(displayScientificName(oldCorrection, names)).toBe("Pitta brachyura");
    expect(oldCorrection.common_name).toBe("Indian Robin");
    expect(oldCorrection.review).not.toHaveProperty("corrected_common_name");
  });

  it("uses scientific-name lookup when a legacy taxon ID is unavailable", () => {
    expect(
      displayLabel(
        {
          ...oldCorrection,
          review: { ...oldCorrection.review, corrected_taxon_id: null },
        },
        names,
      ),
    ).toBe("Indian Pitta");
  });

  it("prefers the saved common-name snapshot when present", () => {
    const event = {
      ...oldCorrection,
      review: {
        ...oldCorrection.review,
        corrected_common_name: "Indian Pitta",
      },
    };
    expect(displayLabel(event)).toBe("Indian Pitta");
    expect(displayScientificName(event)).toBe("Pitta brachyura");
  });

  it("renders common name first and scientific name once in acoustic cards and history", () => {
    const card = renderToStaticMarkup(
      <TaxonNamesContext.Provider value={names}>
        <AudioCards events={[oldCorrection]} onInspect={() => {}} />
      </TaxonNamesContext.Provider>,
    );
    expect(card).toMatch(/<h4[^>]*>Indian Pitta<\/h4>/);
    expect(card).toContain("<em>Pitta brachyura</em>");
    expect(card.match(/Pitta brachyura/g)).toHaveLength(1);
    const history = renderToStaticMarkup(
      <TaxonNamesContext.Provider value={names}>
        <ObservationHistory
          events={[oldCorrection]}
          jobs={[]}
          runId="run"
          onRun={() => {}}
          onSeek={() => {}}
          onInspect={() => {}}
        />
      </TaxonNamesContext.Provider>,
    );
    expect(history).toContain("Indian Pitta");
    expect(history).toContain("<em>Pitta brachyura</em>");
    expect(history.match(/Pitta brachyura/g)).toHaveLength(1);
  });

  it("shows a scientific fallback only once when no common name is available", () => {
    const card = renderToStaticMarkup(
      <AudioCards events={[oldCorrection]} onInspect={() => {}} />,
    );
    expect(card).toMatch(/<h4[^>]*>Pitta brachyura<\/h4>/);
    expect(card.match(/Pitta brachyura/g)).toHaveLength(1);
  });

  it("keeps corrected common and scientific names searchable, including spelling errors", () => {
    expect(rankObservations([oldCorrection], "indain pitta", names)).toEqual([
      oldCorrection,
    ]);
    expect(rankObservations([oldCorrection], "Pitta brachyura", names)).toEqual(
      [oldCorrection],
    );
    expect(matchesObservation(oldCorrection, "Indian Pitta", names)).toBe(true);
    expect(matchesObservation(oldCorrection, "Pitta brachyura", names)).toBe(
      true,
    );
  });

  it("uses the same corrected name in visual overlays and the review heading", () => {
    const event = {
      ...oldCorrection,
      modality: "visual",
      bbox_norm: [0.1, 0.1, 0.8, 0.8],
      detector: { score: 0.8 },
      classification: { status: "unknown", top_k: [] },
    } as unknown as VisualEvent;
    expect(observationOverlays([event], names)[0].label).toBe("Indian Pitta");
    const html = renderToStaticMarkup(
      <TaxonNamesContext.Provider value={names}>
        <Inspector
          event={oldCorrection}
          taxa={[pitta]}
          onClose={() => {}}
          onSaved={() => {}}
        />
      </TaxonNamesContext.Provider>,
    );
    expect(html).toMatch(/<h3[^>]*>Indian Pitta<\/h3>/);
    expect(html).toContain("model said");
    expect(html).toContain("Indian Robin");
  });
});
