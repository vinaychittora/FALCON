import { api } from "./client";
import {
  correctedNames,
  scientificSubtitle,
  type TaxonNameIndex,
} from "./names";
import { predictionLabel } from "./timeline";
import type { Detection, ReviewStatus } from "../types";

/** One animal visit: the frame records of one visual track, or one sound detection. */
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
}

export interface EncounterPage {
  encounters: Encounter[];
  total: number;
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
    ["limit", filters.limit ?? 50],
    ["offset", filters.offset ?? 0],
  ];
  for (const [key, value] of optional)
    if (value !== undefined && value !== null && value !== "")
      params.set(key, String(value));
  return params.toString();
}

export function fetchEncounters(filters: EncounterFilters) {
  return api<EncounterPage>(
    "/detections/encounters?" + encounterQuery(filters),
  );
}

export type Decision =
  "confirm" | "correct" | "unknown" | "reject" | "discard" | "unreviewed";

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
    hint: "Choose the right species",
    key: "e",
  },
  {
    decision: "unknown",
    status: "unknown",
    label: "Unsure",
    hint: "An animal, species unclear",
    key: "u",
  },
  {
    decision: "reject",
    status: "false_positive",
    label: "Not an animal",
    hint: "Wrong detection (leaves, shadow, person…)",
    key: "x",
  },
  {
    decision: "discard",
    status: "discarded",
    label: "Discard",
    hint: "Not useful: duplicate, blurred, empty",
    key: "d",
  },
];

export const STATUS_LABELS: Record<
  ReviewStatus | "mixed",
  { label: string; tone: string }
> = {
  unreviewed: { label: "To review", tone: "neutral" },
  correct: { label: "Confirmed", tone: "good" },
  corrected: { label: "Corrected", tone: "good" },
  unknown: { label: "Unsure", tone: "warn" },
  false_positive: { label: "Not an animal", tone: "bad" },
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

export function canConfirm(event: Detection): boolean {
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
  const primary = predictionLabel(event).replace(/\s+[—–]\s*candidate$/i, "");
  const scientific =
    event.modality === "visual"
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
