// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Encounter } from "./encounters";
import { formatDuration } from "./format";
import { cardClock, cardDay } from "./reviewList";

/**
 * Review's one card per stay (since 24 Nov 2026). The list
 * comes by stay (group=stay): the picture visits that share footage. A card shows the
 * stay's rows in front, and behind a closed line the hidden ones the filter left out.
 */
export interface StayGroup {
  stayId: string;
  /** The rows in front, in time order. */
  front: Encounter[];
  /** Hidden visits of the stay that the filter left out (behind the closed line). */
  attached: Encounter[];
}

/** The page's items as stays, in the order their first item comes. An item without a
 * stay (any call but Review's) is a stay of its own. */
export function groupStays(encounters: Encounter[]): StayGroup[] {
  const groups = new Map<string, StayGroup>();
  for (const item of encounters) {
    const stayId = item.stay_id ?? item.encounter_id;
    let group = groups.get(stayId);
    if (!group) {
      group = { stayId, front: [], attached: [] };
      groups.set(stayId, group);
    }
    (item.attached ? group.attached : group.front).push(item);
  }
  return [...groups.values()].filter((group) => group.front.length || group.attached.length);
}

const start = (item: Encounter) => {
  const time = item.first_captured_at ? new Date(item.first_captured_at).getTime() : NaN;
  return Number.isFinite(time) ? time : null;
};

const clock = (time: number, seconds = false) => cardClock(new Date(time), seconds);

/** A row's start time with seconds: "09:37:57". */
export function rowFrom(value: string | null | undefined): string {
  const time = value ? new Date(value).getTime() : NaN;
  return Number.isFinite(time) ? clock(time, true) : "—";
}

/** The head's time line, the span of the rows in front, first start to last end:
 * "22 Nov, 09:37 to 09:40 · 2 min 13 s". */
export function stayTimeLine(front: Encounter[], now = new Date()): string {
  const starts = front.map(start).filter((time): time is number => time !== null);
  if (!starts.length) return "—";
  const first = Math.min(...starts);
  const last = Math.max(...front.map((item) => (start(item) ?? first) + Math.max(0, item.duration_ms)));
  const day = new Date(first);
  const date = day.toDateString() === now.toDateString() ? "" : `${cardDay(day)}, `;
  return `${date}${clock(first)} to ${clock(last)} · ${formatDuration(last - first)}`;
}

/** "One recording, kept once" or "3 recordings in a row, each kept once". */
export function recordingsLine(count: number | null | undefined): string {
  return !count || count <= 1 ? "One recording, kept once" : `${count} recordings in a row, each kept once`;
}

export const hiddenMoreLine = (count: number) =>
  `${count} more that FALCON hid in this stay`;

/** Why FALCON hid a visit, in plain words: the one map for these kinds (backend
 * inference/visits.py decides them; UNRESOLVED and GLIMPSE also come from the list's own
 * rules for an old group without a visit row). */
const HIDDEN_REASONS: Record<string, string> = {
  GLIMPSE: "recorded in one frame only",
  STILL: "it never moved enough to count as a visit",
  UNIDENTIFIED: "its frames named three or more kinds of animal",
  SMALL: "it was very small in the picture",
  CANDIDATE: "it has not met the visit rule yet (two frames and movement, or one species named steadily)",
  INSECT_NIGHT: "an insect at night",
  RODENT_NIGHT: "a rat or mouse at night",
  UNRESOLVED: "no species and no group yet",
};

export function hiddenReasonText(reason: string | null | undefined): string {
  return (reason && HIDDEN_REASONS[reason]) || "FALCON keeps it out of the default list";
}
