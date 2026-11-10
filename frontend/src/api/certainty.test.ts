import { describe, expect, it } from "vitest";
import type { VisualEvent } from "../types";
import {
  audioCertainty,
  certaintyDetail,
  certaintyOf,
  joinNames,
  leadingName,
  metricsLine,
  visualCertainty,
} from "./certainty";

function owlet(
  overrides: Partial<VisualEvent["classification"]> = {},
): VisualEvent {
  return {
    event_id: "e",
    source_id: "s",
    source_filename: "f",
    job_id: "j",
    models: {},
    environment: {
      status: "not_connected",
      sensor_id: null,
      observed_at: null,
      age_seconds: null,
      temperature_c: null,
      humidity_percent: null,
      pressure_hpa: null,
    },
    review: {
      status: "unreviewed",
      corrected_taxon_id: null,
      corrected_scientific_name: null,
      notes: null,
      updated_at: null,
    },
    modality: "visual",
    timestamp_ms: 0,
    duration_ms: 500,
    track_id: "t",
    bbox_norm: [0, 0, 1, 1],
    detector: { label: "animal", score: 0.59, model: "MD" },
    classification: {
      broad_group: "Aves",
      scientific_name: null,
      common_name: null,
      score: 0.492,
      margin: 0.002,
      status: "unknown",
      display_label: "Spotted Owlet",
      unknown_reason: "Ambiguous top candidates",
      top_k: [],
      certainty: "probable",
      genus: null,
      contenders: [
        {
          taxon_id: 1,
          scientific_name: "Athene brama",
          common_name: "Spotted Owlet",
          group: "Aves",
          score: 0.492,
        },
        {
          taxon_id: 2,
          scientific_name: "Glaucidium radiatum",
          common_name: "Jungle Owlet",
          group: "Aves",
          score: 0.49,
        },
      ],
      ...overrides,
    },
  };
}

describe("certainty", () => {
  it("leads with the most probable species and lists the look-alikes under it", () => {
    const event = owlet();
    expect(certaintyOf(event)).toMatchObject({
      level: "probable",
      label: "Probable",
      tone: "warn",
    });
    expect(certaintyDetail(event)).toBe("or Jungle Owlet");
    const pitta = owlet({
      display_label: "Indian Pitta",
      genus: "Pitta",
      contenders: [
        {
          taxon_id: 1,
          scientific_name: "Pitta brachyura",
          common_name: "Indian Pitta",
          group: "Aves",
          score: 0.59,
        },
        {
          taxon_id: 2,
          scientific_name: "Pitta megarhyncha",
          common_name: "Mangrove Pitta",
          group: "Aves",
          score: 0.567,
        },
      ],
    });
    expect(certaintyDetail(pitta)).toBe("or Mangrove Pitta · same genus Pitta");
  });

  it("maps the other tiers and legacy records", () => {
    expect(
      certaintyOf(
        owlet({ certainty: "possible", display_label: "Spotted Owlet?" }),
      )?.tone,
    ).toBe("bad");
    expect(certaintyDetail(owlet({ certainty: "possible" }))).toMatch(
      /Faint guess/,
    );
    expect(
      certaintyOf(owlet({ certainty: "likely", status: "candidate" }))?.tone,
    ).toBe("good");
    expect(
      certaintyOf(
        owlet({ certainty: "unknown", display_label: "Unknown bird" }),
      )?.tone,
    ).toBe("muted");
    const legacy = owlet({ certainty: undefined });
    expect(visualCertainty(legacy)).toBe("probable");
    expect(
      visualCertainty(owlet({ certainty: undefined, status: "candidate" })),
    ).toBe("likely");
    const reviewed = owlet();
    reviewed.review.status = "correct";
    expect(certaintyOf(reviewed)).toBeNull();
    // Sound: Likely from 0.60 (Live and one bell per bout), otherwise Probable.
    expect(audioCertainty(0.8)).toBe("likely");
    expect(audioCertainty(0.6)).toBe("likely");
    expect(audioCertainty(0.59)).toBe("probable");
    expect(audioCertainty(0.41)).toBe("probable");
    expect(joinNames(["A", "B", "C"])).toBe("A, B or C");
    expect(joinNames(["A"])).toBe("A");
  });
});

describe("leading name", () => {
  it("leads with the most probable candidate, even for records stored before certainty existed", () => {
    const current = owlet();
    expect(leadingName(current)).toBe("Spotted Owlet");
    const legacy = owlet({
      certainty: undefined,
      contenders: undefined,
      display_label: "Unknown bird",
      top_k: [
        {
          taxon_id: 1,
          scientific_name: "Athene brama",
          common_name: "Spotted Owlet",
          group: "Aves",
          score: 0.492,
        },
        {
          taxon_id: 2,
          scientific_name: "Glaucidium radiatum",
          common_name: "Jungle Owlet",
          group: "Aves",
          score: 0.49,
        },
        {
          taxon_id: 3,
          scientific_name: "Ninox scutulata",
          common_name: "Brown Boobook",
          group: "Aves",
          score: 0.456,
        },
      ],
    });
    expect(leadingName(legacy)).toBe("Spotted Owlet");
    expect(certaintyDetail(legacy)).toBe("or Jungle Owlet");
    expect(
      leadingName(
        owlet({ certainty: "possible", display_label: "Spotted Owlet?" }),
      ),
    ).toBe("Spotted Owlet?");
    expect(
      leadingName(
        owlet({
          certainty: "unknown",
          display_label: "Unknown bird",
          contenders: [],
        }),
      ),
    ).toBe("Unknown bird");
    const named = owlet({
      status: "candidate",
      certainty: "likely",
      common_name: "Spotted Owlet",
      scientific_name: "Athene brama",
    });
    expect(leadingName(named)).toBe("Spotted Owlet");
    expect(
      metricsLine(
        owlet({
          top_k: [
            {
              taxon_id: 1,
              scientific_name: "a",
              common_name: null,
              group: "Aves",
              score: 0.49,
            },
            {
              taxon_id: 2,
              scientific_name: "b",
              common_name: null,
              group: "Aves",
              score: 0.48,
            },
          ],
        }),
      ),
    ).toBe("Detector 0.59 · Similarity 0.49 · Gap 0.002");
  });
});
