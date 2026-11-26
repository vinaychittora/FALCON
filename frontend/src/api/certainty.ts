// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Candidate, Certainty, Detection, VisualEvent } from "../types";
import type { Tone } from "../ui/Pill";
import { correctedNames, type TaxonNameIndex } from "./names";

export interface CertaintyView {
  level: Certainty;
  /** Short word for a pill. */
  label: string;
  tone: Tone;
  /** One sentence for a tooltip. */
  title: string;
}

const VIEWS: Record<Certainty, Omit<CertaintyView, "level">> = {
  likely: {
    label: "Likely",
    tone: "good",
    title: "One species stands clearly ahead of the alternatives.",
  },
  probable: {
    label: "Probable",
    tone: "warn",
    title:
      "A few look-alike species score almost the same; the name shows which.",
  },
  possible: {
    label: "Possible",
    tone: "bad",
    title: "A faint best guess: the similarity is below the species threshold.",
  },
  unknown: {
    label: "Unknown",
    tone: "muted",
    title: "A living thing, but not enough detail to say more.",
  },
};

/** Certainty of a visual record from its classification (unreviewed records only). */
export function visualCertainty(event: VisualEvent): Certainty {
  const classification = event.classification;
  if (classification.certainty) return classification.certainty;
  // Records written before certainty existed: derive it from the status.
  if (classification.status === "candidate") return "likely";
  if (
    classification.status === "unknown" &&
    classification.unknown_reason === "Ambiguous top candidates"
  )
    return "probable";
  return "unknown";
}

/**
 * Certainty of a sound visit from BirdNET's confidence (its clearest call): Likely at
 * 0.60 or more (shown on Live, one bell per bout), otherwise Probable (Review only).
 * Records start at the BirdNET threshold (0.40). Fixed, not a setting (9 Nov 2026).
 * Since 18 Nov the cleaned sound must also agree; older records have no verdict and
 * keep the tier they had. The backend keeps the same bar (storage/jsonl.py SOUND_LIKELY,
 * SOUND_PROBABLE_SQL): Probable bouts wait behind Review's "Show hidden".
 * A bird not recorded in Rajasthan (outsideArea, 24 Nov 2026) is "unknown" whatever its
 * confidence: an unidentified sound, so it rings nothing and shows only under Review's
 * hidden places, like the backend's same rule.
 */
export const SOUND_LIKELY = 0.6;
export function audioCertainty(
  confidence: number,
  cleanedAgrees?: boolean | null,
  outsideArea?: boolean | null,
): Certainty {
  if (outsideArea) return "unknown";
  return confidence >= SOUND_LIKELY && cleanedAgrees !== false
    ? "likely"
    : "probable";
}

/** An unidentified sound: BirdNET named a bird not recorded in Rajasthan and nobody has
 * named it since. Once corrected (or confirmed) it is an ordinary record. */
export function unidentifiedSound(event: Detection): boolean {
  return (
    event.modality === "audio" &&
    event.outside_area === true &&
    event.review.status !== "corrected" &&
    event.review.status !== "correct"
  );
}

export const UNIDENTIFIED_SOUND = "Unidentified sound";

/** The card's front line for an unidentified sound, else null:
 * "BirdNET's guess: Great Bittern 0.71 · not recorded in Rajasthan". */
export function soundGuessLine(event: Detection): string | null {
  if (event.modality !== "audio" || !unidentifiedSound(event)) return null;
  const name = event.common_name?.trim() || event.scientific_name;
  const score = (event.bout_confidence ?? event.confidence).toFixed(2);
  return `BirdNET's guess: ${name} ${score} · not recorded in Rajasthan`;
}

const UNIDENTIFIED_SOUND_VIEW: Omit<CertaintyView, "level"> = {
  label: "Unidentified",
  tone: "muted",
  title: "BirdNET's guess is a bird not recorded in Rajasthan. Use Correct to name it.",
};

/** The plain line in a sound record's details. */
export function cleanedSoundNote(
  agrees: boolean,
  score?: number | null,
): string {
  return agrees
    ? `Cleaned sound agrees, ${(score ?? 0).toFixed(2)}`
    : "Cleaned sound does not agree";
}

/** How to show a detection's certainty, or null once a reviewer has decided. */
export function certaintyOf(event: Detection): CertaintyView | null {
  if (event.review.status !== "unreviewed") return null;
  if (
    event.modality === "visual" &&
    event.classification.status === "non_wildlife"
  )
    return null;
  if (unidentifiedSound(event))
    return { level: "unknown", ...UNIDENTIFIED_SOUND_VIEW };
  const level =
    event.modality === "visual"
      ? visualCertainty(event)
      : audioCertainty(event.bout_confidence ?? event.confidence, event.cleaned_agrees);
  return { level, ...VIEWS[level] };
}

/** "A, B or C" */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}

/**
 * The second line under an uncertain name: the look-alikes it is between and their
 * shared genus for a probable visit, or a reminder that a possible one is a faint guess.
 */
export function certaintyDetail(event: Detection): string | null {
  if (event.modality !== "visual" || event.review.status !== "unreviewed")
    return null;
  const { genus } = event.classification;
  const certainty = visualCertainty(event);
  if (certainty === "probable") {
    const others = contendersOf(event)
      .slice(1)
      .map((candidate) => candidate.common_name || candidate.scientific_name);
    const parts = [];
    if (others.length) parts.push(`or ${joinNames(others)}`);
    if (genus) parts.push(`same genus ${genus}`);
    return parts.length
      ? parts.join(" · ")
      : "Look-alikes score almost the same";
  }
  if (certainty === "possible")
    return "Faint guess · below the species threshold";
  return null;
}

/** The candidates an uncertain visual record is between, best first. */
export function contendersOf(event: VisualEvent): Candidate[] {
  const c = event.classification;
  const topK = c.top_k ?? [];
  if (c.contenders?.length) return c.contenders;
  if (
    c.status === "unknown" &&
    c.unknown_reason === "Ambiguous top candidates" &&
    topK.length
  ) {
    const top = topK[0];
    return topK.filter((item) => top.score - item.score <= 0.03).slice(0, 3);
  }
  return topK.slice(0, 1);
}

/**
 * The name that leads a card, box or heading: the reviewer's choice, the species, or
 * for an uncertain record the most probable candidate ("Indian Pitta", "Spotted Owlet?").
 * Falls back to "Unknown bird" when not even a faint guess is available.
 */
export function leadingName(event: Detection, taxa?: TaxonNameIndex): string {
  if (event.review.status === "corrected") {
    const names = correctedNames(event, taxa);
    return names.common ?? names.scientific ?? "Corrected identification";
  }
  if (unidentifiedSound(event)) return UNIDENTIFIED_SOUND;
  if (event.modality === "audio")
    return event.common_name?.trim() || event.scientific_name;
  const c = event.classification;
  if (c.status === "non_wildlife") return c.display_label;
  if (c.status === "candidate")
    return (
      c.common_name ||
      c.scientific_name ||
      c.display_label.replace(/\s+[—–]\s*candidate$/i, "")
    );
  const level = visualCertainty(event);
  const best = contendersOf(event)[0];
  if (best && (level === "probable" || level === "possible")) {
    const name = best.common_name || best.scientific_name;
    return level === "possible" ? `${name}?` : name;
  }
  return c.display_label.split(" · ")[0] || "Unknown organism";
}

/** "Detector 0.86 · Similarity 0.59 · Gap 0.023", only the parts that exist. */
export function metricsLine(event: VisualEvent): string {
  const parts: string[] = [];
  if (event.detector.score !== null)
    parts.push(`Detector ${event.detector.score.toFixed(2)}`);
  const c = event.classification;
  if (c.score !== null && c.score !== undefined)
    parts.push(`Similarity ${c.score.toFixed(2)}`);
  if (c.margin !== null && c.margin !== undefined && (c.top_k?.length ?? 0) > 1)
    parts.push(`Gap ${c.margin.toFixed(3)}`);
  return parts.join(" · ");
}

/** A short reason worth a line of its own (image quality); scores explain the rest. */
export function qualityReason(event: VisualEvent): string | null {
  const reason = event.classification.unknown_reason ?? "";
  if (/too small/i.test(reason)) return "Too small in the frame for a species";
  if (/blurred|featureless/i.test(reason))
    return "Blurred frame; waiting for a sharper one";
  if (/no usable crop/i.test(reason)) return "No usable frame yet";
  return null;
}
