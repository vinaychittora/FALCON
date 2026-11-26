// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Encounter } from "./encounters";
import { encounterNames } from "./encounters";
import type { TaxonNameIndex } from "./names";
import { cardClock } from "./reviewList";

/**
 * The recording view of a stay (since 24 Nov 2026): every box carries its name, and a row of
 * chips under the player picks the animal the four buttons act on.
 */

/** The last eight characters of a visit key: how the recording's boxes name their visit. */
export const trackOf = (encounterId: string) => encounterId.slice(-8);

const startOf = (item: Encounter) => {
  const time = item.first_captured_at ? Date.parse(item.first_captured_at) : NaN;
  return Number.isFinite(time) ? time : Number.POSITIVE_INFINITY;
};

const byStart = (a: Encounter, b: Encounter) =>
  startOf(a) - startOf(b) || a.encounter_id.localeCompare(b.encounter_id);

/** The rows of the stay `item` belongs to, as the list holds them: the rows in front in
 * start order, then the hidden ones attached to it. Fewer than two rows: no chips. */
export function stayRows(item: Encounter | undefined, pool: readonly Encounter[] | undefined): Encounter[] {
  if (!item || !pool?.length || item.modality !== "visual" || !item.stay_id) return [];
  const members = pool.filter((row) => row.stay_id === item.stay_id);
  if (!members.some((row) => row.encounter_id === item.encounter_id)) members.push(item);
  const rows = [
    ...members.filter((row) => !row.attached).sort(byStart),
    ...members.filter((row) => row.attached).sort(byStart),
  ];
  return rows.length >= 2 ? rows : [];
}

const DISCARDED = new Set(["discarded", "false_positive"]);

/** A visit's name on a box: the verdict's name once decided, the card's name while
 * undecided (species, group or unidentified), "Discarded" once discarded. */
export function visitName(item: Encounter, names?: TaxonNameIndex): string {
  if (DISCARDED.has(item.event.review.status)) return "Discarded";
  return encounterNames(item.event, names).primary;
}

export interface StayChip {
  id: string;
  name: string;
  /** "09:37", or "09:37:57" when two chips would otherwise read the same. */
  time: string;
  /** This row is decided: a tick before the name. */
  decided: boolean;
  /** A hidden row attached to the stay: muted. */
  hidden: boolean;
  /** Discarded while the view is open: the chip stays (Undo in reach), muted. */
  discarded: boolean;
}

/** Discarded visits: their boxes are not drawn, as the server leaves them out. */
export const isDiscarded = (item: Encounter) => DISCARDED.has(item.event.review.status);

/** One chip per row: "Name 09:37", in the device's own time form. */
export function stayChips(rows: readonly Encounter[], names?: TaxonNameIndex): StayChip[] {
  const base = rows.map((row) => {
    const start = row.first_captured_at ? new Date(row.first_captured_at) : null;
    const valid = !!start && !Number.isNaN(start.getTime());
    return {
      id: row.encounter_id,
      name: visitName(row, names),
      start: valid ? start : null,
      decided: row.event.review.status !== "unreviewed",
      hidden: !!row.attached,
      discarded: isDiscarded(row),
    };
  });
  const short = base.map((chip) => `${chip.name} ${chip.start ? cardClock(chip.start) : "—"}`);
  return base.map((chip, index) => {
    const twin = short.some((text, other) => other !== index && text === short[index]);
    return {
      id: chip.id,
      name: chip.name,
      time: chip.start ? cardClock(chip.start, twin) : "—",
      decided: chip.decided,
      hidden: chip.hidden,
      discarded: chip.discarded,
    };
  });
}

/** "Deciding: Name, from 09:37:57", the line above the four buttons. */
export function decidingLine(row: Encounter, names?: TaxonNameIndex): string {
  const start = row.first_captured_at ? new Date(row.first_captured_at) : null;
  const time = start && !Number.isNaN(start.getTime()) ? cardClock(start, true) : "—";
  return `Deciding: ${visitName(row, names)}, from ${time}`;
}

/** The four buttons' group label while chips are shown. */
export function decisionGroupLabel(row: Encounter, names?: TaxonNameIndex): string {
  const start = row.first_captured_at ? new Date(row.first_captured_at) : null;
  const time = start && !Number.isNaN(start.getTime()) ? cardClock(start, true) : "—";
  return `Your decision for ${visitName(row, names)}, from ${time}`;
}
