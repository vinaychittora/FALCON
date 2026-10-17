import type { ClassifierMode, VisualEvent } from "../types";

export const classifierLabels: Record<ClassifierMode, string> = {
  bioclip_2: "BioCLIP 2 · lighter",
  bioclip_2_5: "BioCLIP 2.5 Huge · detailed",
  ensemble: "Both models · cross-check",
};

export function speciesModelName(model: string) {
  if (/bioclip[-_ ]?2[._-]5/i.test(model)) return "BioCLIP 2.5 Huge";
  if (/bioclip[-_ ]?2/i.test(model)) return "BioCLIP 2";
  return model;
}

export function consensusLabel(classification: VisualEvent["classification"]) {
  if ((classification.model_evidence?.length ?? 0) < 2) return null;
  switch (classification.consensus) {
    case "agree":
      return "Models agree · candidate";
    case "disagree":
      return "Models disagree · uncertain";
    case "insufficient_evidence":
      return "Cross-check uncertain";
    default:
      return null;
  }
}
