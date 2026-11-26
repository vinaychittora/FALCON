// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import type { VisualEvent } from "../types";
import {
  normalizeSearch,
  rankObservations,
  rankTaxa,
  searchScore,
} from "./search";

const taxa = [
  {
    taxon_id: 1,
    common_name: "Sulphur-bellied Warbler",
    scientific_name: "Phylloscopus griseolus",
  },
  {
    taxon_id: 2,
    common_name: "Oriental Magpie-Robin",
    scientific_name: "Copsychus saularis",
  },
  {
    taxon_id: 3,
    common_name: "Common Tailorbird",
    scientific_name: "Orthotomus sutorius",
  },
  {
    taxon_id: 4,
    common_name: "Indian Robin",
    scientific_name: "Copsychus fulicatus",
  },
  {
    taxon_id: 5,
    common_name: "Garden Lizard",
    scientific_name: "Calotes versicolor",
  },
];

describe("ranked local species search", () => {
  it.each([
    ["sulpher balleid warbler", 1],
    ["magpie robin", 2],
    ["tailerbird", 3],
    ["tailor bird", 3],
    ["Phylloscopus griesolus", 1],
    ["copsychus saulrais", 2],
  ])(
    "finds %s despite punctuation, misspelling, or transposition",
    (query, id) => {
      expect(rankTaxa(taxa, query)[0]?.taxon_id).toBe(id);
    },
  );

  it("ranks exact names before exact words, prefixes, and fuzzy matches", () => {
    const records = ["Robim", "Robinbird", "Indian Robin", "Robin"].map(
      (name, i) => ({
        taxon_id: i,
        common_name: name,
        scientific_name: "",
      }),
    );
    expect(rankTaxa(records, "robin").map((t) => t.common_name)).toEqual([
      "Robin",
      "Indian Robin",
      "Robinbird",
      "Robim",
    ]);
  });

  it("requires every query token and avoids fuzzy matches for short inputs", () => {
    expect(rankTaxa(taxa, "zz")).toEqual([]);
    expect(rankTaxa(taxa, "rob")).toHaveLength(2);
    expect(rankTaxa(taxa, "robin elephant")).toEqual([]);
    expect(searchScore(["Robin"], "robin robin")).toBeNull();
    expect(searchScore(["Zebra"], "zbr")).toBeNull();
  });

  it("normalizes case, punctuation, accents and whitespace without changing stored names", () => {
    expect(normalizeSearch("  MÉNÉTRIÉS’S—Warbler  ")).toBe(
      "menetries s warbler",
    );
    expect(rankTaxa(taxa, " MAGPIE–ROBIN ")[0].common_name).toBe(
      "Oriental Magpie-Robin",
    );
    expect(rankTaxa(taxa, "")).toEqual(taxa);
    expect(searchScore(["warbler"], "x".repeat(200))).toBeNull();
  });

  it("finds saved corrections and either model's alternatives without promoting a suggestion", () => {
    const event = {
      source_filename: "example.mp4",
      modality: "visual",
      review: {
        status: "corrected",
        corrected_scientific_name: "Leiopicus mahrattensis",
        notes: "reviewed",
      },
      classification: {
        status: "unknown",
        display_label: "Unknown bird",
        top_k: [],
        model_evidence: [{ model: "second", top_k: [taxa[2]] }],
      },
    } as unknown as VisualEvent;
    expect(rankObservations([event], "tailerbird")).toEqual([event]);
    expect(rankObservations([event], "Leiopicus mahrattenssi")).toEqual([
      event,
    ]);
    expect(event.classification.status).toBe("unknown");
    expect(event.review.corrected_scientific_name).toBe(
      "Leiopicus mahrattensis",
    );
  });
});
