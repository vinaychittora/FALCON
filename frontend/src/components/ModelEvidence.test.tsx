// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ModelEvidence as Evidence, VisualEvent } from "../types";
import ModelEvidence from "./ModelEvidence";

const evidence = (model: string, name: string, score: number): Evidence => ({
  model,
  version: "pinned-revision",
  status: "candidate",
  score,
  margin: 0.04,
  unknown_reason: null,
  top_k: [
    {
      taxon_id: 1,
      scientific_name: name,
      common_name: null,
      group: "Aves",
      score,
    },
  ],
});

function classification(
  extra: Partial<VisualEvent["classification"]> = {},
): VisualEvent["classification"] {
  return {
    broad_group: "Aves",
    scientific_name: null,
    common_name: null,
    score: 0.81,
    margin: 0.04,
    status: "unknown",
    display_label: "Unknown bird",
    unknown_reason: "Models suggest different species",
    top_k: [],
    ...extra,
  };
}

describe("separate species model evidence", () => {
  it("does not invent evidence for historical records", () => {
    expect(
      renderToStaticMarkup(<ModelEvidence classification={classification()} />),
    ).toBe("");
  });

  it("shows each conflicting suggestion with its own score", () => {
    const html = renderToStaticMarkup(
      <ModelEvidence
        classification={classification({
          consensus: "disagree",
          model_evidence: [
            evidence(
              "imageomics/bioclip-2.5-vith14",
              "Copsychus saularis",
              0.81,
            ),
            evidence("imageomics/bioclip-2", "Saxicoloides fulicatus", 0.71),
          ],
        })}
      />,
    );
    expect(html).toContain("Models disagree · uncertain");
    expect(html).toContain("BioCLIP 2.5 Huge");
    expect(html).toContain("BioCLIP 2");
    expect(html).toContain("Copsychus saularis");
    expect(html).toContain("Saxicoloides fulicatus");
    expect(html).toContain("0.810");
    expect(html).toContain("0.710");
    expect(html).not.toContain("0.760");
    expect(html).not.toContain("81%");
    expect(html).toContain("Similarity is not a probability");
  });

  it("keeps a shared top suggestion uncertain when one model is ambiguous", () => {
    const first = evidence(
      "imageomics/bioclip-2.5-vith14",
      "Copsychus saularis",
      0.81,
    );
    const second = evidence("imageomics/bioclip-2", "Copsychus saularis", 0.71);
    second.status = "unknown";
    second.margin = 0.002;
    second.unknown_reason = "Ambiguous top candidates";
    const html = renderToStaticMarkup(
      <ModelEvidence
        classification={classification({
          consensus: "insufficient_evidence",
          model_evidence: [first, second],
        })}
      />,
    );
    expect(html).toContain("Cross-check uncertain");
    expect(html).not.toContain("Models agree");
    expect(html).toContain("Ambiguous top candidates");
    expect(html).toContain("0.002");
  });

  it("does not show agreement for a single model", () => {
    const html = renderToStaticMarkup(
      <ModelEvidence
        classification={classification({
          consensus: "single",
          model_evidence: [
            evidence("imageomics/bioclip-2", "Copsychus saularis", 0.71),
          ],
        })}
      />,
    );
    expect(html).toContain("BioCLIP 2");
    expect(html).not.toContain("Models agree");
    expect(html).not.toContain("Cross-check");
  });
});
