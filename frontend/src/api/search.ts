import type { Detection } from "../types";
import { correctedNames, type TaxonNameIndex } from "./names";

export interface SearchableTaxon {
  taxon_id: number;
  scientific_name: string;
  common_name: string | null;
}

export function normalizeSearch(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLocaleLowerCase("en")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

// Optimal string alignment counts adjacent transpositions as a single edit.
function editDistance(a: string, b: string): number {
  const rows = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = 0; i <= a.length; i++) rows[i][0] = i;
  for (let j = 0; j <= b.length; j++) rows[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      rows[i][j] = Math.min(
        rows[i - 1][j] + 1,
        rows[i][j - 1] + 1,
        rows[i - 1][j - 1] + Number(a[i - 1] !== b[j - 1]),
      );
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        rows[i][j] = Math.min(rows[i][j], rows[i - 2][j - 2] + 1);
      }
    }
  }
  return rows[a.length][b.length];
}

function fieldScore(field: string, query: string): number | null {
  if (
    field === query ||
    field.replaceAll(" ", "") === query.replaceAll(" ", "")
  )
    return 0;
  const words = field.split(" ");
  const terms = query.split(" ");
  if (terms.length > 1 && words.includes(query.replaceAll(" ", "")))
    return 20 + (words.length - 1) / 100;
  if (terms.length > words.length) {
    // A common compound name may be typed with a space (e.g. "tailor bird").
    if (field.replaceAll(" ", "").includes(query.replaceAll(" ", "")))
      return 120;
    return null;
  }
  const used = new Set<number>();
  let cost = 0;
  let fuzzy = false;
  for (const term of terms) {
    let best: { index: number; cost: number; fuzzy: boolean } | null = null;
    for (let index = 0; index < words.length; index++) {
      if (used.has(index)) continue;
      const word = words[index];
      let candidate: { index: number; cost: number; fuzzy: boolean } | null =
        null;
      if (word === term) candidate = { index, cost: 0, fuzzy: false };
      else if (word.startsWith(term))
        candidate = {
          index,
          cost: 10 + (word.length - term.length) / 100,
          fuzzy: false,
        };
      else if (term.length >= 4) {
        const allowance = term.length >= 6 ? 2 : 1;
        if (Math.abs(word.length - term.length) <= allowance) {
          const distance = editDistance(term, word);
          if (distance <= allowance)
            candidate = { index, cost: 30 + distance, fuzzy: true };
        }
      }
      if (candidate && (!best || candidate.cost < best.cost)) best = candidate;
    }
    if (!best) return null;
    used.add(best.index);
    cost += best.cost;
    fuzzy ||= best.fuzzy;
  }
  return (
    (fuzzy ? 300 : cost ? 100 : 20) + cost + (words.length - terms.length) / 100
  );
}

/** Exact names and exact words precede prefixes; fuzzy matches require all terms. */
export function searchScore(
  fields: (string | null | undefined)[],
  rawQuery: string,
): number | null {
  const query = normalizeSearch(rawQuery);
  if (!query) return 0;
  if (query.length > 160 || query.split(" ").length > 16) return null;
  let best: number | null = null;
  for (const field of fields) {
    if (!field) continue;
    const score = fieldScore(normalizeSearch(field), query);
    if (score !== null && (best === null || score < best)) best = score;
  }
  return best;
}

export function rankSearch<T>(
  items: readonly T[],
  query: string,
  fields: (item: T) => (string | null | undefined)[],
): T[] {
  if (!normalizeSearch(query)) return [...items];
  return items
    .map((item, index) => ({
      item,
      index,
      score: searchScore(fields(item), query),
    }))
    .filter(
      (entry): entry is typeof entry & { score: number } =>
        entry.score !== null,
    )
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map(({ item }) => item);
}

export function rankTaxa<T extends SearchableTaxon>(
  taxa: readonly T[],
  query: string,
): T[] {
  return rankSearch(taxa, query, (taxon) => [
    taxon.common_name,
    taxon.scientific_name,
  ]);
}

export function rankObservations(
  events: readonly Detection[],
  query: string,
  taxa?: TaxonNameIndex,
): Detection[] {
  return rankSearch(events, query, (event) => {
    const common = [
      event.source_filename,
      event.modality,
      event.review.status.replaceAll("_", " "),
      event.review.status === "unknown" ? "uncertain" : null,
      event.review.status === "false_positive" ? "rejected" : null,
      event.review.status === "correct" ? "confirmed" : null,
      event.review.corrected_scientific_name,
      event.review.status === "corrected"
        ? correctedNames(event, taxa).common
        : null,
      event.review.notes,
    ];
    if (event.modality === "audio")
      return [...common, event.common_name, event.scientific_name, "acoustic"];
    const candidates = [
      ...event.classification.top_k,
      ...(event.classification.model_evidence ?? []).flatMap(
        (model) => model.top_k,
      ),
    ];
    return [
      ...common,
      event.classification.display_label,
      event.classification.common_name,
      event.classification.scientific_name,
      ...candidates.flatMap((candidate) => [
        candidate.common_name,
        candidate.scientific_name,
      ]),
    ];
  });
}
