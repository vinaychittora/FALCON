// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Candidate, Detection, ReviewStatus } from "../types";
import type { Tone } from "../ui/Pill";
import {
  certaintyOf,
  cleanedSoundNote,
  contendersOf,
  leadingName,
  unidentifiedSound,
  visualCertainty,
} from "./certainty";
import { STATUS_LABELS, withDecision, type Encounter } from "./encounters";
import { speciesModelName } from "./models";
import {
  correctedNames,
  scientificSubtitle,
  type TaxonNameIndex,
} from "./names";
import { predictionLabel } from "./timeline";
import { NetworkError } from "./activity";

export interface SpeciesLike {
  taxon_id: number;
  scientific_name: string;
  common_name: string | null;
}

export type DecisionKind = "confirm" | "correct" | "unsure" | "discard";

export interface DecisionAction {
  kind: DecisionKind;
  status: ReviewStatus;
  taxonId?: number;
}

export interface RecordItem {
  id: string;
  event: Detection;
  encounter?: Encounter;
}

export interface ReviewSnapshot {
  status: ReviewStatus;
  taxonId?: number;
  notes: string | null;
}

export type ReviewStore = (
  item: RecordItem,
  status: ReviewStatus,
  options: { taxonId?: number; notes?: string | null },
) => Promise<unknown>;

const key = (name: string) => name.trim().toLocaleLowerCase("en");

export const itemFromEncounter = (encounter: Encounter): RecordItem => ({
  id: encounter.encounter_id,
  event: encounter.event,
  encounter,
});

export const formatScore = (score: number | null | undefined) =>
  score === null || score === undefined ? "—" : score.toFixed(2);

/** The species the model itself put first for this record, if it has one. */
export function modelLeader(
  event: Detection,
): (Pick<Candidate, "scientific_name" | "common_name"> & {
  taxon_id: number;
  score: number | null;
}) | null {
  if (event.modality === "audio")
    return {
      taxon_id: 0,
      scientific_name: event.scientific_name,
      common_name: event.common_name,
      score: event.confidence,
    };
  const c = event.classification;
  if (c.status === "non_wildlife") return null;
  const topK = c.top_k ?? [];
  if (c.scientific_name) {
    const hit = topK.find(
      (item) => key(item.scientific_name) === key(c.scientific_name ?? ""),
    );
    return {
      taxon_id: hit?.taxon_id ?? 0,
      scientific_name: c.scientific_name,
      common_name: c.common_name ?? hit?.common_name ?? null,
      score: c.score ?? hit?.score ?? null,
    };
  }
  if (visualCertainty(event) === "unknown") return null;
  const best = contendersOf(event)[0] ?? topK[0];
  return best ? { ...best, score: best.score ?? c.score ?? null } : null;
}

function taxonFor(
  leader: NonNullable<ReturnType<typeof modelLeader>>,
  taxa: readonly SpeciesLike[],
) {
  return (
    taxa.find((taxon) => leader.taxon_id && taxon.taxon_id === leader.taxon_id) ??
    taxa.find((taxon) => key(taxon.scientific_name) === key(leader.scientific_name))
  );
}

/**
 * What Confirm stores, or null when there is no species to confirm. A record the model
 * only named as a leading candidate is stored with that species, so the name is kept.
 */
export function confirmAction(
  event: Detection,
  taxa: readonly SpeciesLike[],
): DecisionAction | null {
  // An unidentified sound has no species to confirm: Correct names it (the guess first).
  if (unidentifiedSound(event)) return null;
  if (event.modality === "audio" || event.classification.status === "candidate")
    return { kind: "confirm", status: "correct" };
  const leader = modelLeader(event);
  const taxon = leader && taxonFor(leader, taxa);
  return taxon
    ? { kind: "confirm", status: "corrected", taxonId: taxon.taxon_id }
    : null;
}

/** A species picked in the chooser. The model's own species counts as Confirm. */
export function pickAction(
  event: Detection,
  taxon: SpeciesLike,
  taxa: readonly SpeciesLike[],
): DecisionAction {
  const leader = modelLeader(event);
  if (leader && key(leader.scientific_name) === key(taxon.scientific_name)) {
    const confirm = confirmAction(event, taxa);
    if (confirm) return confirm;
  }
  return { kind: "correct", status: "corrected", taxonId: taxon.taxon_id };
}

export function actionForKind(
  kind: DecisionKind,
  event: Detection,
  taxa: readonly SpeciesLike[],
): DecisionAction | null {
  if (kind === "confirm") return confirmAction(event, taxa);
  if (kind === "unsure") return { kind, status: "unknown" };
  if (kind === "discard") return { kind, status: "discarded" };
  return null;
}

function correctionIsModelChoice(event: Detection, names?: TaxonNameIndex) {
  if (event.review.status !== "corrected") return false;
  const leader = modelLeader(event);
  const chosen = correctedNames(event, names).scientific;
  return !!leader && !!chosen && key(leader.scientific_name) === key(chosen);
}

/** The decision this record currently shows as taken. */
export function takenDecision(
  event: Detection,
  names?: TaxonNameIndex,
): DecisionKind | null {
  switch (event.review.status) {
    case "correct":
      return "confirm";
    case "corrected":
      return correctionIsModelChoice(event, names) ? "confirm" : "correct";
    case "unknown":
      return "unsure";
    case "discarded":
    case "false_positive":
      return "discard";
    default:
      return null;
  }
}

const stripCandidate = (name: string) =>
  name.replace(/\s+[—–]\s*candidate$/i, "");

export interface RecordIdentity {
  label: "Model's guess" | "Final identification";
  pill: { text: string; tone: Tone; title?: string };
  name: string;
  scientific: string | null;
  modelSaid: { name: string; score: number | null } | null;
}

/** Whose name is shown, the name itself, and what the model said after a correction. */
export function recordIdentity(
  event: Detection,
  names?: TaxonNameIndex,
): RecordIdentity {
  const taken = takenDecision(event, names);
  const leader = modelLeader(event);
  const name = stripCandidate(leadingName(event, names));
  const corrected =
    event.review.status === "corrected" ? correctedNames(event, names) : null;
  const scientific = scientificSubtitle(
    name,
    corrected
      ? corrected.scientific
      : unidentifiedSound(event)
        ? null
        : (leader?.scientific_name ?? null),
  );
  if (taken === "confirm" || taken === "correct")
    return {
      label: "Final identification",
      pill:
        taken === "confirm"
          ? { text: "Confirmed", tone: "good" }
          : { text: "Corrected", tone: "good" },
      name,
      scientific,
      modelSaid:
        taken === "correct"
          ? {
              name: leader
                ? leader.common_name || leader.scientific_name
                : stripCandidate(predictionLabel(event)),
              score: leader?.score ?? null,
            }
          : null,
    };
  const certainty = modelTier(event);
  return {
    label: "Model's guess",
    pill: certainty
      ? { text: certainty.label, tone: certainty.tone, title: certainty.title }
      : { text: "Unknown", tone: "muted" },
    name,
    scientific,
    modelSaid: null,
  };
}

/** The model's own tier as words, for the first row of the model detail. */
export function tierText(event: Detection): string {
  return modelTier(event)?.label ?? "Unknown";
}

/** The model's own tier, whatever the person decided since (certaintyOf hides it once
 * a record is reviewed). */
function modelTier(event: Detection) {
  return certaintyOf({ ...event, review: { ...event.review, status: "unreviewed" } } as Detection);
}

/** The note field's text: the typed draft of this record, else its stored note. Drafts are
 * kept per record, so a note never follows the screen to another record. */
export function noteDraft(
  drafts: Readonly<Record<string, string>>,
  id: string,
  stored: string | null | undefined,
): string {
  return drafts[id] ?? stored ?? "";
}

/** The card's status pill. A stored correction to the model's own leading species was a
 * Confirm (Probable and Possible records are stored that way), so it reads Confirmed. */
export function cardStatus(
  status: ReviewStatus | "mixed",
  event: Detection,
  names?: TaxonNameIndex,
): { label: string; tone: string } {
  if (status === "corrected" && takenDecision(event, names) === "confirm")
    return { label: "Confirmed", tone: "good" };
  return STATUS_LABELS[status];
}

export function decisionLine(event: Detection, names?: TaxonNameIndex): string {
  const name = stripCandidate(leadingName(event, names));
  switch (takenDecision(event, names)) {
    case "confirm":
      return `Confirmed · ${name}`;
    case "correct":
      return `Corrected to ${name}`;
    case "unsure":
      return "Marked unsure";
    case "discard":
      return "Discarded";
    default:
      return "";
  }
}

export function decisionAnnouncement(
  event: Detection,
  names?: TaxonNameIndex,
): string {
  const identity = recordIdentity(event, names);
  const said = identity.modelSaid
    ? ` The model said ${identity.modelSaid.name}.`
    : "";
  return `${decisionLine(event, names).replace(" · ", " ")}.${said} Saved. Undo is available.`;
}

export const snapshotOf = (event: Detection): ReviewSnapshot => ({
  status: event.review.status,
  taxonId: event.review.corrected_taxon_id ?? undefined,
  notes: event.review.notes ?? null,
});

const sameSnapshot = (a: ReviewSnapshot, b: ReviewSnapshot) =>
  a.status === b.status &&
  (a.taxonId ?? null) === (b.taxonId ?? null) &&
  (a.notes ?? "") === (b.notes ?? "");

/** The record as it reads after a stored decision. */
export function withReview(
  item: RecordItem,
  snapshot: ReviewSnapshot,
  taxa: readonly SpeciesLike[],
): RecordItem {
  const current = (item.encounter ??
    ({ event: item.event } as unknown as Encounter)) as Encounter;
  const next = withDecision(current, snapshot.status, {
    taxonId: snapshot.taxonId,
    notes: snapshot.notes,
    taxa,
  });
  return {
    ...item,
    event: next.event,
    encounter: item.encounter ? next : undefined,
  };
}

/** Store first; the record changes only when the store succeeded. */
export async function storeReview(
  item: RecordItem,
  snapshot: ReviewSnapshot,
  taxa: readonly SpeciesLike[],
  store: ReviewStore,
): Promise<RecordItem> {
  await store(item, snapshot.status, {
    taxonId: snapshot.taxonId,
    notes: snapshot.notes,
  });
  return withReview(item, snapshot, taxa);
}

/** The record view's red line after a failed save, undo or note (25 Nov, build 2b): when the
 * cause is the network it says so; every other failure keeps the plain sentence. */
export function failedSentence(what: "save" | "undo" | "note", reason: unknown): string {
  const network = reason instanceof NetworkError;
  if (what === "undo")
    return network ? "Could not undo: can't reach FALCON. Try again." : "Could not undo. Try again.";
  if (what === "note")
    return network
      ? "Could not save the note: can't reach FALCON. Try again."
      : "Could not save the note. Try again.";
  return network ? "Could not save: can't reach FALCON. Try again." : "Could not save. Try again.";
}

export function decisionSnapshot(
  action: DecisionAction,
  notes: string | null,
): ReviewSnapshot {
  return {
    status: action.status,
    taxonId: action.taxonId,
    notes: notes?.trim() || null,
  };
}

export const isSameReview = (item: RecordItem, snapshot: ReviewSnapshot) =>
  sameSnapshot(snapshotOf(item.event), snapshot);

export function changedReviews(
  originals: ReadonlyMap<string, ReviewSnapshot>,
  latest: ReadonlyMap<string, Detection>,
): number {
  let count = 0;
  for (const [id, before] of originals) {
    const event = latest.get(id);
    if (event && !sameSnapshot(before, snapshotOf(event))) count += 1;
  }
  return count;
}

export const reviewsSavedMessage = (count: number) =>
  `${count} review${count === 1 ? "" : "s"} saved`;

export type RecordKeyAction = DecisionKind | "next" | "previous" | "note";

export function recordKeyAction(event: {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  target?: { tagName?: string; isContentEditable?: boolean } | null;
}): RecordKeyAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  const tag = event.target?.tagName ?? "";
  if (
    ["INPUT", "TEXTAREA", "SELECT"].includes(tag) ||
    event.target?.isContentEditable
  )
    return null;
  const map: Record<string, RecordKeyAction> = {
    c: "confirm",
    r: "correct",
    u: "unsure",
    d: "discard",
    j: "next",
    arrowright: "next",
    k: "previous",
    arrowleft: "previous",
    n: "note",
  };
  return map[event.key.toLowerCase()] ?? null;
}

export interface EvidenceRow {
  id: string;
  name: string;
  score: number | null;
  scoreLabel: "similarity" | "confidence";
  yourChoice?: boolean;
}

export interface EvidenceGroup {
  title: string;
  hint: string;
  rows: EvidenceRow[];
  empty?: string;
  note?: string;
}

const candidateRow = (
  candidate: Candidate,
  chosen: string | null,
): EvidenceRow => ({
  id: String(candidate.taxon_id || candidate.scientific_name),
  name: candidate.common_name || candidate.scientific_name,
  score: candidate.score,
  scoreLabel: "similarity",
  yourChoice: !!chosen && key(candidate.scientific_name) === key(chosen),
});

/** What each model says, in the order it is shown in front of the reviewer. */
export function evidenceGroups(
  event: Detection,
  encounter: Encounter | undefined,
  names?: TaxonNameIndex,
): EvidenceGroup[] {
  const chosen =
    event.review.status === "corrected"
      ? correctedNames(event, names).scientific
      : null;
  if (event.modality === "visual") {
    const models = event.classification.model_evidence ?? [];
    const camera: EvidenceGroup[] =
      models.length > 1
        ? models.map((model) => ({
            title: `Camera model · ${speciesModelName(model.model)}`,
            hint: "similarity, not a probability",
            rows: model.top_k.slice(0, 3).map((row) => candidateRow(row, chosen)),
          }))
        : [
            {
              title: "Camera model",
              hint: "similarity, not a probability",
              rows: (event.classification.top_k ?? [])
                .slice(0, 3)
                .map((row) => candidateRow(row, chosen)),
              empty: "No species suggestion for this visit.",
            },
          ];
    return [
      ...camera,
      {
        title: "Microphone model",
        hint: "heard at the same time",
        rows: (encounter?.heard ?? []).map((row) => ({
          id: row.name,
          name: row.name,
          score: row.confidence,
          scoreLabel: "confidence" as const,
        })),
        empty: "No bird heard during this visit.",
      },
    ];
  }
  const secondCheck =
    event.cleaned_agrees === null || event.cleaned_agrees === undefined
      ? undefined
      : `Second check: ${cleanedSoundNote(event.cleaned_agrees, event.cleaned_score)
          .replace(/^C/, "c")}`;
  return [
    {
      title: "Microphone model",
      hint: "confidence, not a probability",
      rows: [
        {
          id: event.scientific_name,
          name: event.common_name?.trim() || event.scientific_name,
          score: encounter?.best_confidence ?? event.confidence,
          scoreLabel: "confidence",
        },
      ],
      note: secondCheck,
    },
    {
      title: "Camera model",
      hint: "seen at the same time",
      rows: (encounter?.seen ?? []).map((name) => ({
        id: name,
        name,
        score: null,
        scoreLabel: "similarity" as const,
      })),
      empty: "No animal seen at the same time.",
    },
  ];
}
