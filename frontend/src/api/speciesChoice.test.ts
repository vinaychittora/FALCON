// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import type { Detection } from "../types";
import { enterChoice, matchRank, speciesChoices } from "./speciesChoice";

const species = (taxon_id: number, common_name: string, scientific_name: string) => ({ taxon_id, common_name, scientific_name });
const robin = species(1, "Oriental Magpie-Robin", "Copsychus saularis");
const moth = species(2, "Oriental leafworm moth", "Spodoptera litura");
const bee = species(3, "Asian Green Bee-eater", "Merops orientalis");
const sparrow = species(4, "House Sparrow", "Passer domesticus");
const flower = species(5, "Thick-billed Flowerpecker", "Dicaeum agile");
const taxa = [moth, bee, sparrow, robin, flower];
const event = {
  modality: "visual",
  classification: {
    status: "candidate",
    scientific_name: flower.scientific_name,
    common_name: flower.common_name,
    score: 0.41,
    top_k: [{ ...flower, score: 0.41 }, { ...bee, score: 0.3 }],
  },
} as unknown as Detection;

describe("species chooser", () => {
  it("starts with the model's other suggestions, then species confirmed here", () => {
    const choices = speciesChoices(event, taxa, [{ scientific_name: sparrow.scientific_name, visits: 2 }, { scientific_name: robin.scientific_name, visits: 9 }], "");
    expect(choices.groups.map((group) => group.title)).toEqual(["The model's other suggestions", "Confirmed here before"]);
    expect(choices.groups[0].rows).toEqual([{ taxon: bee, right: "0.30" }]);
    expect(choices.groups[1].rows.map((row) => row.taxon)).toEqual([robin, sparrow]);
  });

  it("ranks Oriental Magpie-Robin above Oriental leafworm moth for Oriental m", () => {
    const rows = speciesChoices(event, taxa, [], "Oriental m").groups[0].rows.map((row) => row.taxon);
    expect(rows.indexOf(robin)).toBeLessThan(rows.indexOf(moth));
  });

  it("puts model suggestions and species seen here ahead of the rest", () => {
    const choices = speciesChoices(event, taxa, [{ scientific_name: robin.scientific_name, visits: 1 }], "orient");
    expect(choices.groups[0].title).toBe("3 matches · likely ones first");
    expect(choices.groups[0].rows.map((row) => row.taxon)).toEqual([bee, robin, moth]);
    expect(choices.groups[0].rows[1].right).toBe("seen here");
  });

  it("prefers word starts, still finds typos, and reports no match", () => {
    expect(matchRank(["Magpie Robin"], "rob")).toBe(0);
    expect(matchRank(["Magpie Robin"], "obin")).toBe(2);
    expect(matchRank(["Hoplobatrachus tigerinus", "Indian Bullfrog"], "bullforg")).toBe(3);
    expect(speciesChoices(event, taxa, [], "zzzz").total).toBe(0);
  });
});

describe("Enter in the search field", () => {
  it("picks only a row reached with the arrow keys", () => {
    const rows = ["Asian Green Bee-eater", "Green Sandpiper"];
    expect(enterChoice(rows, -1)).toBeNull();
    expect(enterChoice(rows, 0)).toBe("Asian Green Bee-eater");
    expect(enterChoice(rows, 1)).toBe("Green Sandpiper");
    expect(enterChoice([], 0)).toBeNull();
  });
});
