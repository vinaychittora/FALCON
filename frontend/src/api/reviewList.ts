// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { ReviewStatus } from "../types";
import type { Encounter, EncounterFilters } from "./encounters";
import type { TaxonNameIndex } from "./names";
import {
  confirmAction,
  formatScore,
  recordIdentity,
  type DecisionAction,
  type DecisionKind,
  type SpeciesLike,
} from "./recordView";

/** "Visit" or "Sound", the first part of a card's line. */
export const kindWord = (encounter: Pick<Encounter, "modality">) =>
  encounter.modality === "audio" ? "Sound" : "Visit";

/** The one clock form on Review's cards, in the device's own form like every other time in
 * the app: "09:37", with seconds "09:37:57". */
export function cardClock(date: Date, seconds = false): string {
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
  });
}

/** "22 Nov", the day part of a card's time. */
export const cardDay = (date: Date) =>
  date.toLocaleDateString(undefined, { day: "numeric", month: "short" });

/** Time on a card: today's records the time only, older ones the day and month too. */
export function cardWhen(value: string | null | undefined, now = new Date()): string {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "—";
  const time = cardClock(date);
  if (date.toDateString() === now.toDateString()) return time;
  return `${cardDay(date)}, ${time}`;
}

/** The card's evidence line: the figures the card has always shown, with the record
 * view's formatter (two decimals, no percent sign). After a correction it starts with
 * what the model said. */
export function evidenceLine(
  encounter: Encounter,
  names?: TaxonNameIndex,
): { said: { name: string; score: string } | null; text: string } {
  const event = encounter.event;
  const identity = recordIdentity(event, names);
  const said = identity.modelSaid
    ? {
        name: identity.modelSaid.name,
        score: identity.modelSaid.score === null ? "" : formatScore(identity.modelSaid.score),
      }
    : null;
  const parts: string[] = [];
  if (event.modality === "audio") {
    parts.push(`Microphone ${formatScore(event.bout_confidence ?? event.confidence)}`);
    if (event.cleaned_agrees === true) parts.push("second check agrees");
    else if (event.cleaned_agrees === false) parts.push("second check does not agree");
    if (encounter.seen?.length) parts.push(`seen ${encounter.seen.join(", ")}`);
  } else {
    const score = event.classification.score;
    parts.push(score === null ? "No species score" : `Camera ${formatScore(score)}`);
    for (const heard of encounter.heard ?? [])
      parts.push(`heard ${heard.name} ${formatScore(heard.confidence)}`);
  }
  return { said, text: parts.join(" · ") };
}

/** What a card's decision stores: exactly what the record view stores. Correct opens the
 * chooser, so it has no action here; Confirm is null when the models named nothing. */
export function cardAction(
  kind: DecisionKind,
  encounter: Encounter,
  taxa: readonly SpeciesLike[],
): DecisionAction | null {
  if (kind === "confirm") return confirmAction(encounter.event, taxa);
  if (kind === "unsure") return { kind, status: "unknown" };
  if (kind === "discard") return { kind, status: "discarded" };
  return null;
}

export const statusOptionLabel = (label: string, count: number | null | undefined) =>
  count === null || count === undefined ? label : `${label} (${count.toLocaleString()})`;

/** The filters that decide what "To review" holds: the button, the option count and the
 * queue all use this, so their numbers agree. */
export function toReviewFilters(filters: EncounterFilters): EncounterFilters {
  return { ...filters, review_status: "unreviewed", include_discarded: false, offset: 0 };
}

export const FILTER_DEFAULTS = {
  period: "7d",
  modality: "",
  query: "",
  scope: "live",
  source: "",
  showHidden: false,
  unidentified: false,
  minScore: "",
} as const;

export type FilterState = {
  period: string;
  periodLabel: string;
  modality: string;
  query: string;
  scope: string;
  source: string;
  sourceLabel: string;
  showHidden: boolean;
  /** Optional so older callers keep working; off when left out. */
  unidentified?: boolean;
  minScore: string;
};

/** The caption under the filter row: the active filters in words. */
export function filterCaption(state: FilterState): { text: string; changed: boolean } {
  const parts = [
    state.periodLabel,
    state.modality === "visual"
      ? "video only"
      : state.modality === "audio"
        ? "sound only"
        : "video and sound",
  ];
  if (state.query.trim()) parts.push(`species “${state.query.trim()}”`);
  if (state.scope === "all") parts.push("field and media tests");
  if (state.source) parts.push(`session ${state.sourceLabel || state.source}`);
  if (state.unidentified) parts.push("unidentified only");
  if (state.showHidden) parts.push("hidden shown");
  if (state.minScore !== "") parts.push(`score from ${state.minScore}`);
  const changed =
    state.period !== FILTER_DEFAULTS.period ||
    state.modality !== FILTER_DEFAULTS.modality ||
    !!state.query.trim() ||
    state.scope !== FILTER_DEFAULTS.scope ||
    !!state.source ||
    state.showHidden !== FILTER_DEFAULTS.showHidden ||
    !!state.unidentified ||
    state.minScore !== FILTER_DEFAULTS.minScore;
  return { text: parts.join(" · "), changed };
}

const records = (n: number) => `${n} record${n === 1 ? "" : "s"}`;

/** The bottom bar's line after a bulk action. */
export function bulkMessage(status: ReviewStatus, count: number, name?: string): string {
  switch (status) {
    case "correct":
      return `Confirmed ${records(count)}`;
    case "corrected":
      return name ? `Corrected ${records(count)} to ${name}` : `Corrected ${records(count)}`;
    case "unknown":
      return `Marked ${records(count)} unsure`;
    case "discarded":
      return `Discarded ${records(count)}`;
    case "unreviewed":
      return `Reset ${records(count)} to “to review”`;
    default:
      return `Changed ${records(count)}`;
  }
}

export type BeforeReview = { status: ReviewStatus; taxonId?: number; notes?: string };

/** What each ticked card held before a bulk action, so Undo can put each one back. */
export function beforeReviews(encounters: readonly Encounter[]): Map<string, BeforeReview> {
  return new Map(
    encounters.map((item) => [
      item.encounter_id,
      {
        status: item.event.review.status,
        taxonId: item.event.review.corrected_taxon_id ?? undefined,
        notes: item.event.review.notes ?? undefined,
      },
    ]),
  );
}

/** The footer's primary button while the Filters panel is open on a narrow screen: the
 * list's own total for the filters now set (25 Nov). */
export const showRecordsLabel = (total: number) =>
  `Show ${total.toLocaleString()} record${total === 1 ? "" : "s"}`;

/** The footer when nothing in the list waits for a decision: the count first, so it is
 * never read as an empty result (25 Nov). An empty list says what the list says. */
export function waitingLine(total: number): string {
  if (total === 0) return "No encounters match.";
  if (total === 1) return "1 record in this list, not waiting for a review.";
  return `${total.toLocaleString()} records in this list, none waiting for a review.`;
}

/** The line under the filters while Status is Hidden: a reminder. */
export const HIDDEN_CLEAR_NOTE = "Cleared 7 days after capture unless you review them.";

/** Undo of a bulk action: the visits grouped by what they held before, so each group
 * goes back in a few requests instead of one request per visit. */
export function undoGroups(before: ReadonlyMap<string, BeforeReview>): { review: BeforeReview; ids: string[] }[] {
  const groups = new Map<string, { review: BeforeReview; ids: string[] }>();
  for (const [id, review] of before) {
    const key = JSON.stringify([review.status, review.taxonId ?? null, review.notes ?? null]);
    const group = groups.get(key) ?? { review, ids: [] };
    group.ids.push(id);
    groups.set(key, group);
  }
  return [...groups.values()];
}

/** Review's own default view (7 days, live recordings, hidden ones left out): the
 * navigation badge and the station status count what Review's button opens. */
export function defaultToReviewFilters(now = new Date()): EncounterFilters {
  return {
    scope: "live",
    review_status: "unreviewed",
    include_discarded: false,
    resolved_only: true,
    hide_glimpses: true,
    q: "",
    min_score: null,
    captured_from: new Date(now.getTime() - 168 * 3600_000).toISOString(),
    captured_to: null,
    offset: 0,
  } as EncounterFilters;
}
