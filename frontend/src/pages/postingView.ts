// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { PostableVisit } from "../api/inaturalist";

/** What the Post footer says (25 Nov, build 4): the next step while something is
 * missing, else what one press sends. `reason` means the visit cannot be posted at all:
 * the sentence stands in place of the button. */
export function postFooter(o: {
  problems: string[];
  account: boolean;
  kind: "picture" | "sound";
  soundOffered: boolean;
  pictures: number;
  sound: boolean;
  failed: number;
  waiting: number;
  busy: boolean;
}): { text: string; ready: boolean; reason: boolean } {
  if (o.problems.length) return { text: o.problems.join(" "), ready: false, reason: true };
  if (o.busy) return { text: "Posting…", ready: false, reason: false };
  if (!o.account)
    return { text: "Sign in to iNaturalist on the list first.", ready: false, reason: false };
  if (o.kind === "sound" && !o.sound)
    return { text: "Include the sound first.", ready: false, reason: false };
  if (o.kind === "picture" && o.pictures === 0 && !o.sound)
    return {
      text: o.soundOffered
        ? "Choose 1 to 3 pictures or include the sound first."
        : "Choose 1 to 3 pictures first.",
      ready: false,
      reason: false,
    };
  if (o.failed)
    return { text: "A chosen picture could not be loaded: retry it or remove it.", ready: false, reason: false };
  if (o.waiting)
    return { text: "Waiting for the chosen pictures to load.", ready: false, reason: false };
  return { text: sendsText(o.pictures, o.sound), ready: true, reason: false };
}

/** "1 picture", "2 pictures and the sound", "The sound". */
export function sendsText(pictures: number, sound: boolean): string {
  const parts = [];
  if (pictures) parts.push(`${pictures} picture${pictures === 1 ? "" : "s"}`);
  if (sound) parts.push(parts.length ? "the sound" : "The sound");
  return parts.join(" and ");
}

/** The list splits in two: visits with a species name, and those without one (they
 * cannot be posted until corrected to a species on Review). */
export function splitByName(visits: PostableVisit[]): {
  named: PostableVisit[];
  unnamed: PostableVisit[];
} {
  const named: PostableVisit[] = [];
  const unnamed: PostableVisit[] = [];
  for (const visit of visits) (visit.name || visit.scientific_name ? named : unnamed).push(visit);
  return { named, unnamed };
}

/** The row's pill: the verdict given, when the list says it. */
export function verdictPill(status: string): string | null {
  if (status === "corrected") return "Corrected";
  if (status === "correct") return "Confirmed";
  return null;
}

/** The end line of the list (the list endpoint reads the newest 200 confirmed visits). */
export const LIST_COVERS =
  "This list covers your newest 200 confirmed visits. Open an older one from Review with Post to iNaturalist.";
