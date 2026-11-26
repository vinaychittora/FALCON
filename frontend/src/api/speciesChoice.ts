// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Candidate, Detection } from "../types";
import { unidentifiedSound } from "./certainty";
import { modelLeader, formatScore, type SpeciesLike } from "./recordView";
import { normalizeSearch, searchScore } from "./search";

export interface ConfirmedSpecies {
  scientific_name: string;
  visits: number;
}

export interface ChoiceRow<T extends SpeciesLike> {
  taxon: T;
  right: string;
}

export interface ChoiceGroup<T extends SpeciesLike> {
  id: string;
  title: string;
  rows: ChoiceRow<T>[];
}

export interface SpeciesChoices<T extends SpeciesLike> {
  searching: boolean;
  total: number;
  groups: ChoiceGroup<T>[];
}

const key = (name: string) => name.trim().toLocaleLowerCase("en");
const label = (taxon: SpeciesLike) => taxon.common_name || taxon.scientific_name;

function modelCandidates(event: Detection): Candidate[] {
  if (event.modality === "audio")
    return [
      {
        taxon_id: 0,
        scientific_name: event.scientific_name,
        common_name: event.common_name,
        group: "Aves",
        score: event.confidence,
      },
    ];
  return [
    ...(event.classification.top_k ?? []),
    ...(event.classification.model_evidence ?? []).flatMap((item) => item.top_k),
  ];
}

/** 0 whole phrase at a word start, 1 every word starts a word, 2 inside a word, 3 typo. */
/** The row Enter in the search field picks: only one the person moved to (active >= 0).
 * With nothing chosen, Enter picks nothing, so a phone keyboard's action key cannot store
 * the first match by accident. */
export const MODEL_SUGGESTIONS = "The model's other suggestions";
export const BIRDNET_GUESS = "BirdNET's guess · not recorded in Rajasthan";

export function enterChoice<T>(rows: readonly T[], active: number): T | null {
  return active >= 0 && active < rows.length ? rows[active] : null;
}

export function matchRank(
  fields: (string | null | undefined)[],
  rawQuery: string,
): number | null {
  const query = normalizeSearch(rawQuery);
  if (!query) return 0;
  const terms = query.split(" ");
  let best: number | null = null;
  for (const raw of fields) {
    if (!raw) continue;
    const field = normalizeSearch(raw);
    const words = field.split(" ");
    let rank: number | null = null;
    if (field.startsWith(query) || field.includes(` ${query}`)) rank = 0;
    else if (terms.every((term) => words.some((word) => word.startsWith(term))))
      rank = 1;
    else if (terms.every((term) => field.includes(term))) rank = 2;
    if (rank !== null && (best === null || rank < best)) best = rank;
  }
  if (best !== null) return best;
  return searchScore(fields, rawQuery) === null ? null : 3;
}

export function speciesChoices<T extends SpeciesLike>(
  event: Detection,
  taxa: readonly T[],
  confirmedHere: readonly ConfirmedSpecies[],
  query: string,
): SpeciesChoices<T> {
  const byId = new Map(taxa.map((taxon) => [taxon.taxon_id, taxon]));
  const byName = new Map(taxa.map((taxon) => [key(taxon.scientific_name), taxon]));
  const scores = new Map<number, number>();
  const model: T[] = [];
  for (const candidate of modelCandidates(event)) {
    const taxon =
      byId.get(candidate.taxon_id) ?? byName.get(key(candidate.scientific_name));
    if (!taxon) continue;
    if (!scores.has(taxon.taxon_id)) model.push(taxon);
    scores.set(
      taxon.taxon_id,
      Math.max(scores.get(taxon.taxon_id) ?? -Infinity, candidate.score),
    );
  }
  const here = new Map<number, number>();
  for (const row of confirmedHere) {
    const taxon = byName.get(key(row.scientific_name));
    if (taxon) here.set(taxon.taxon_id, row.visits);
  }
  const rowOf = (taxon: T): ChoiceRow<T> => ({
    taxon,
    right: scores.has(taxon.taxon_id)
      ? formatScore(scores.get(taxon.taxon_id))
      : here.has(taxon.taxon_id)
        ? "seen here"
        : "",
  });
  if (normalizeSearch(query)) {
    const ranked = taxa
      .flatMap((taxon) => {
        const rank = matchRank([taxon.common_name, taxon.scientific_name], query);
        if (rank === null) return [];
        const tier = scores.has(taxon.taxon_id)
          ? 0
          : here.has(taxon.taxon_id)
            ? 1
            : 2;
        return [{ taxon, rank, tier }];
      })
      .sort(
        (a, b) =>
          a.tier - b.tier ||
          a.rank - b.rank ||
          label(a.taxon).localeCompare(label(b.taxon)),
      );
    return {
      searching: true,
      total: ranked.length,
      groups: ranked.length
        ? [
            {
              id: "matches",
              title: `${ranked.length} match${ranked.length === 1 ? "" : "es"} · likely ones first`,
              rows: ranked.slice(0, 100).map((item) => rowOf(item.taxon)),
            },
          ]
        : [],
    };
  }
  const leader = modelLeader(event);
  // An unidentified sound cannot be confirmed, so BirdNET's own guess is offered first
  // here; elsewhere the model's choice is Confirm and is not repeated.
  const guessFirst = unidentifiedSound(event);
  const others = model.filter(
    (taxon) =>
      guessFirst ||
      !leader ||
      key(taxon.scientific_name) !== key(leader.scientific_name),
  );
  const shown = new Set(others.map((taxon) => taxon.taxon_id));
  const confirmed = confirmedHere
    .flatMap((row) => {
      const taxon = byName.get(key(row.scientific_name));
      return taxon && !shown.has(taxon.taxon_id)
        ? [{ taxon, visits: row.visits }]
        : [];
    })
    .sort(
      (a, b) => b.visits - a.visits || label(a.taxon).localeCompare(label(b.taxon)),
    )
    .slice(0, 12);
  const groups: ChoiceGroup<T>[] = [];
  if (others.length)
    groups.push({
      id: "model",
      title: guessFirst ? BIRDNET_GUESS : MODEL_SUGGESTIONS,
      rows: others.map(rowOf),
    });
  if (confirmed.length)
    groups.push({
      id: "here",
      title: "Confirmed here before",
      rows: confirmed.map((item) => ({ taxon: item.taxon, right: "" })),
    });
  return {
    searching: false,
    total: groups.reduce((sum, group) => sum + group.rows.length, 0),
    groups,
  };
}
