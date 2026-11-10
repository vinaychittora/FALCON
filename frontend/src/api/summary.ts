import { api } from "./client";

export type ReviewPolicy = "verified" | "candidates" | "everything";

export interface SpeciesCount {
  scientific_name: string;
  common_name: string | null;
  visits: number;
  reviewed: number;
  machine: number;
  visual: number;
  audio: number;
  first_seen: string | null;
  last_seen: string | null;
}

export interface Summary {
  totals: {
    visits: number;
    records: number;
    visual: number;
    audio: number;
    identified: number;
    unresolved: number;
    reviewed: number;
    machine: number;
    not_animal: number;
  };
  species_count: number;
  species: SpeciesCount[];
  groups: { group: string; visits: number }[];
  note: string;
}

export interface SessionRow {
  session_id: string;
  source_id: string;
  name: string;
  started_at: string;
  ended_at: string | null;
  status: string;
  duration_ms: number | null;
  visits: number;
  records: number;
  reviewed: number;
  unresolved: number;
  species_count: number;
  species: {
    scientific_name: string;
    common_name: string | null;
    visits: number;
  }[];
  clips: number;
  clock_synchronized: boolean | null;
  active: boolean;
}

export interface SummaryFilters {
  scope?: "live" | "all";
  source_id?: string;
  captured_from?: string | null;
  captured_to?: string | null;
  review?: ReviewPolicy;
}

export const REVIEW_POLICIES: {
  value: ReviewPolicy;
  label: string;
  detail: string;
}[] = [
  {
    value: "candidates",
    label: "Verified + unreviewed",
    detail: "Reviewed visits plus the model's unreviewed suggestions.",
  },
  {
    value: "verified",
    label: "Verified only",
    detail: "Only visits a reviewer confirmed or corrected.",
  },
  {
    value: "everything",
    label: "Everything except discarded",
    detail: "Also rejected detections and people, counted as “not an animal”.",
  },
];

function params(filters: SummaryFilters): string {
  const query = new URLSearchParams({ scope: filters.scope ?? "live" });
  const optional: [string, string | null | undefined][] = [
    ["source_id", filters.source_id],
    ["captured_from", filters.captured_from],
    ["captured_to", filters.captured_to],
    ["review", filters.review],
  ];
  for (const [key, value] of optional) if (value) query.set(key, value);
  return query.toString();
}

export const fetchSummary = (filters: SummaryFilters) =>
  api<Summary>("/summary?" + params(filters));

export const fetchSessions = (filters: SummaryFilters) =>
  api<{ sessions: SessionRow[]; active_session_id: string | null }>(
    "/sessions?" + params(filters),
  );

/** Plain group names for the counts (model groups are iNaturalist taxon names). */
export const GROUP_LABELS: Record<string, string> = {
  Aves: "birds",
  Mammalia: "mammals",
  Reptilia: "reptiles",
  Amphibia: "amphibians",
  Lepidoptera: "butterflies and moths",
  Odonata: "dragonflies",
  Hymenoptera: "bees, wasps and ants",
  Insecta: "insects",
  Arachnida: "spiders",
  organism: "unknown animals",
  "unknown (reviewed)": "marked unsure",
};

export const groupLabel = (group: string) =>
  GROUP_LABELS[group] ?? group.toLowerCase();

/** "#/export?source=abc" -> "abc" */
export function hashQuery(hash: string, key: string): string {
  const query = hash.split("?")[1] ?? "";
  return new URLSearchParams(query).get(key) ?? "";
}
