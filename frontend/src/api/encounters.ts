// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { api } from "./client";
import {
  correctedNames,
  scientificSubtitle,
  type TaxonNameIndex,
} from "./names";
import { leadingName, unidentifiedSound } from "./certainty";
import type { Detection, ReviewStatus } from "../types";

/**
 * One animal visit: the frame records of one visual track, or the calls of one bird
 * heard close together (a bout of sound detections).
 */
export interface Encounter {
  encounter_id: string;
  modality: "visual" | "audio";
  source_id: string;
  source_filename: string;
  job_id: string;
  track_id: string | null;
  records: number;
  first_captured_at: string | null;
  duration_ms: number;
  review_status: ReviewStatus | "mixed";
  thumbnail_event_id: string;
  event: Detection;
  /** Sound visits: BirdNET confidence of the clearest call. */
  best_confidence?: number | null;
  /** Picture visits: calls heard at the same time (clearest first). */
  heard?: { name: string; confidence: number }[];
  /** Sound visits: animals seen at the same time. */
  seen?: string[];
  /** Review's list by stay: the stay (shared footage) the visit belongs to. */
  stay_id?: string | null;
  /** A hidden visit of the stay that the filter left out, shown behind the closed line. */
  attached?: boolean;
  /** The stay's recordings (videos with a visit in front). */
  stay_recordings?: number | null;
  /** Why FALCON hid a picture visit (STILL, GLIMPSE, …), if it did. */
  hidden_reason?: string | null;
}

/** One line linking what was seen and heard at the same time, or "". */
export function crossLink(encounter: Encounter): string {
  if (encounter.modality === "visual" && encounter.heard?.length)
    return `Heard at the same time: ${encounter.heard
      .map((h) => `${h.name} ${Math.round(h.confidence * 100)} %`)
      .join(", ")}`;
  if (encounter.modality === "audio" && encounter.seen?.length)
    return `Seen at the same time: ${encounter.seen.join(", ")}`;
  return "";
}

export interface EncounterPage {
  encounters: Encounter[];
  total: number;
  /** Visits left out by resolved_only: nothing known yet (no species, no group). */
  hidden_unresolved?: number;
  /** Picture visits left out by hide_glimpses: seen in one analysed frame only. */
  hidden_glimpses?: number;
  /** With group=stay: the stays in the list, and the matching visits on earlier pages. */
  total_stays?: number;
  visits_before?: number;
}

export interface EncounterFilters {
  scope: "live" | "all";
  source_id?: string;
  q?: string;
  review_status?: string;
  modality?: string;
  captured_from?: string | null;
  captured_to?: string | null;
  min_score?: number | null;
  /** Hide visits with no species and no group yet, and unreviewed people or vehicles. */
  resolved_only?: boolean;
  /** "latest" activity first (default) or by when each visit began. */
  order?: "latest" | "first_seen";
  /** Leave out picture visits seen in one frame only. */
  hide_glimpses?: boolean;
  /** Only unreviewed pictures with no species yet, hidden ones included. */
  unidentified?: boolean;
  /** Review's "Hidden" status: only the unreviewed visits FALCON hid by itself. */
  hidden_only?: boolean;
  /** "All" in Review: discarded visits too. */
  include_discarded?: boolean;
  /** Review's list only: page by stay, so a stay's visits come together. */
  group?: "stay";
  limit?: number;
  offset?: number;
}

export function encounterQuery(filters: EncounterFilters): string {
  const params = new URLSearchParams({ scope: filters.scope });
  const optional: [string, string | number | null | undefined][] = [
    ["source_id", filters.source_id],
    ["q", filters.q?.trim()],
    ["review_status", filters.review_status],
    ["modality", filters.modality],
    ["captured_from", filters.captured_from],
    ["captured_to", filters.captured_to],
    ["min_score", filters.min_score],
    ["resolved_only", filters.resolved_only ? "true" : undefined],
    ["order", filters.order],
    ["hide_glimpses", filters.hide_glimpses ? "true" : undefined],
    ["unidentified", filters.unidentified ? "true" : undefined],
    ["hidden_only", filters.hidden_only ? "true" : undefined],
    ["include_discarded", filters.include_discarded ? "true" : undefined],
    ["group", filters.group],
    ["limit", filters.limit ?? 50],
    ["offset", filters.offset ?? 0],
  ];
  for (const [key, value] of optional)
    if (value !== undefined && value !== null && value !== "")
      params.set(key, String(value));
  return params.toString();
}

/** A sound bout's event carries the bout's clearest call, so every card, pill and number
 * judges the bout as Live, the bell and the backend list do (best call, merged verdict). */
export function withBoutConfidence(encounter: Encounter): Encounter {
  if (encounter.event.modality !== "audio" || encounter.best_confidence == null) return encounter;
  return { ...encounter, event: { ...encounter.event, bout_confidence: encounter.best_confidence } };
}

export async function fetchEncounters(filters: EncounterFilters, signal?: AbortSignal) {
  const page = await api<EncounterPage>(
    "/detections/encounters?" + encounterQuery(filters),
    signal ? { signal } : undefined,
  );
  return { ...page, encounters: page.encounters.map(withBoutConfidence) };
}

/** Review, simplified 16 Nov: four buttons. A corrected visit counts as confirmed; the
 * old "not an animal" shows and filters as Discarded (the stored reason is kept). */
export type Decision = "confirm" | "correct" | "unknown" | "discard";

export const DECISIONS: {
  decision: Decision;
  status: ReviewStatus;
  label: string;
  hint: string;
  key: string;
}[] = [
  {
    decision: "confirm",
    status: "correct",
    label: "Confirm",
    hint: "The species is right",
    key: "c",
  },
  {
    decision: "correct",
    status: "corrected",
    label: "Correct",
    hint: "Choose the right species; counts as confirmed",
    key: "r",
  },
  {
    decision: "unknown",
    status: "unknown",
    label: "Unsure",
    hint: "An animal, species unclear",
    key: "u",
  },
  {
    decision: "discard",
    status: "discarded",
    label: "Discard",
    hint: "Not usable as evidence: not an animal, a person, noise, blurred, duplicate",
    key: "d",
  },
];

/** The Review status filter. */
export const STATUS_FILTERS: [string, string][] = [
  ["unreviewed", "To review"],
  // Unreviewed records FALCON hid by itself: what "Show hidden" adds to To review.
  ["hidden", "Hidden"],
  ["confirmed", "Confirmed"],
  ["unknown", "Unsure"],
  ["discarded", "Discarded"],
  ["", "All"],
];

export const STATUS_LABELS: Record<
  ReviewStatus | "mixed",
  { label: string; tone: string }
> = {
  unreviewed: { label: "To review", tone: "neutral" },
  correct: { label: "Confirmed", tone: "good" },
  corrected: { label: "Confirmed · corrected", tone: "good" },
  unknown: { label: "Unsure", tone: "warn" },
  false_positive: { label: "Discarded", tone: "muted" },
  discarded: { label: "Discarded", tone: "muted" },
  mixed: { label: "Mixed", tone: "warn" },
};

export function reviewEncounters(
  encounterIds: string[],
  status: ReviewStatus,
  options: { taxonId?: number; notes?: string | null } = {},
) {
  return api<{ updated: number; missing: string[] }>(
    "/detections/encounters/review",
    {
      method: "POST",
      body: JSON.stringify({
        encounter_ids: encounterIds,
        review: {
          status,
          corrected_taxon_id:
            status === "corrected" ? (options.taxonId ?? null) : null,
          notes: options.notes?.trim() || null,
        },
      }),
    },
  );
}

/** The backend takes at most this many visits in one review request. */
export const REVIEW_BATCH = 200;

/** One decision for many visits, in requests of at most REVIEW_BATCH; `onProgress` gets
 * how many are done after each request. */
export async function reviewInBatches(
  encounterIds: string[],
  status: ReviewStatus,
  options: { taxonId?: number; notes?: string | null } = {},
  onProgress?: (done: number) => void,
) {
  for (let start = 0; start < encounterIds.length; start += REVIEW_BATCH) {
    await reviewEncounters(encounterIds.slice(start, start + REVIEW_BATCH), status, options);
    onProgress?.(Math.min(encounterIds.length, start + REVIEW_BATCH));
  }
}

/** Every visit of a list, over all its pages (for "Select all M in this list"). */
export async function fetchAllEncounters(filters: EncounterFilters): Promise<Encounter[]> {
  // The list can shift while it is paged by offset: each visit is kept once.
  const all = new Map<string, Encounter>();
  for (let offset = 0; ; offset += REVIEW_BATCH) {
    const page = await fetchEncounters({ ...filters, limit: REVIEW_BATCH, offset });
    for (const item of page.encounters) if (!all.has(item.encounter_id)) all.set(item.encounter_id, item);
    if (!page.encounters.length || offset + REVIEW_BATCH >= page.total) return [...all.values()];
  }
}

/** The card as it reads right after a decision, with the corrected name included. */
export function withDecision(
  encounter: Encounter,
  status: ReviewStatus,
  options: {
    taxonId?: number;
    notes?: string | null;
    taxa: readonly {
      taxon_id: number;
      scientific_name: string;
      common_name: string | null;
    }[];
  },
): Encounter {
  const taxon =
    status === "corrected"
      ? options.taxa.find((item) => item.taxon_id === options.taxonId)
      : undefined;
  return {
    ...encounter,
    review_status: status,
    event: {
      ...encounter.event,
      review: {
        ...encounter.event.review,
        status,
        notes: options.notes?.trim() || null,
        corrected_taxon_id:
          status === "corrected" ? (options.taxonId ?? null) : null,
        corrected_scientific_name: taxon?.scientific_name ?? null,
        corrected_common_name: taxon?.common_name ?? null,
      },
    },
  } as Encounter;
}

export function canConfirm(event: Detection): boolean {
  if (unidentifiedSound(event)) return false;
  return (
    event.modality === "audio" || event.classification.status === "candidate"
  );
}

export function encounterNames(
  event: Detection,
  taxa?: TaxonNameIndex,
): { primary: string; scientific: string | null } {
  if (event.review.status === "corrected") {
    const names = correctedNames(event, taxa);
    const primary =
      names.common ?? names.scientific ?? "Corrected identification";
    return {
      primary,
      scientific: scientificSubtitle(primary, names.scientific),
    };
  }
  const primary = leadingName(event, taxa);
  const scientific = unidentifiedSound(event)
    ? null
    : event.modality === "visual"
      ? event.classification.scientific_name
      : event.scientific_name;
  return { primary, scientific: scientificSubtitle(primary, scientific) };
}

export function scoreSummary(event: Detection): {
  value: number | null;
  label: string;
} {
  if (event.modality === "audio")
    return {
      value: event.confidence,
      label: `BirdNET confidence ${event.confidence.toFixed(2)}`,
    };
  const score = event.classification.score;
  return {
    value: score,
    label:
      score === null
        ? "No species score"
        : `Visual similarity ${score.toFixed(2)} (not a probability)`,
  };
}

export const thumbnailUrl = (eventId: string) =>
  `/api/detections/${encodeURIComponent(eventId)}/thumbnail`;

/** The live session's observations are stored under this source ID. */
export const liveSourceId = (sessionId: string | null | undefined) =>
  sessionId ? sessionId.replaceAll("-", "").slice(0, 24) : undefined;
