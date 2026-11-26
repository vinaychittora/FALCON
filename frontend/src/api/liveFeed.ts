// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { audioCertainty, visualCertainty } from "./certainty";
import type { Encounter, EncounterFilters } from "./encounters";
import type { Certainty } from "../types";

export const MIN_VISUAL_FRAMES = 2;

/** What the Live sidebar shows for one visit: confirmed by a reviewer, or a likely machine call. */
export type FeedMark = "confirmed" | Certainty;

/** Reviewer decision first; otherwise the machine's certainty (a bout uses its clearest call). */
export function feedMark(encounter: Encounter): FeedMark | null {
  const status = encounter.review_status;
  if (status === "correct" || status === "corrected") return "confirmed";
  if (status !== "unreviewed") return null;
  const event = encounter.event;
  if (event.modality === "audio")
    return audioCertainty(
      encounter.best_confidence ?? event.confidence,
      event.cleaned_agrees,
      event.outside_area,
    );
  if (event.classification.status === "non_wildlife") return null;
  return visualCertainty(event);
}

/**
 * The name on a Live line: a Likely picture visit not yet confirmed carries a question
 * mark ("Rusty-spotted Cat?"); a group-level one names its group ("Cat (species
 * uncertain)") and needs none; confirmed visits and sound keep the plain name.
 */
export function feedName(primary: string, encounter: Encounter): string {
  if (
    encounter.modality !== "visual" ||
    feedMark(encounter) !== "likely" ||
    primary.includes("(species uncertain)") ||
    primary.endsWith("?")
  )
    return primary;
  return `${primary}?`;
}

/** BirdNET confidence for sound, visual similarity for pictures. */
export function feedScore(encounter: Encounter): number | null {
  const event = encounter.event;
  if (event.modality === "audio")
    return encounter.best_confidence ?? event.confidence;
  return event.classification.score ?? null;
}

/**
 * The Live list's query. Newest visit on top and no reordering while an animal
 * lingers; visits that say nothing yet stay hidden unless asked for. One-frame
 * glimpses are left out exactly as on Review's default view, so "N more to review"
 * counts only what the click shows there (14 Nov: "2 more to review" opened an empty
 * list, both were glimpses Review hides).
 */
export function liveFeedFilters(
  sessionSource: string | undefined,
  feedFilter: string,
  showUnresolved: boolean,
): EncounterFilters {
  return {
    scope: "live",
    source_id: sessionSource,
    review_status: feedFilter === "unreviewed" ? "unreviewed" : undefined,
    resolved_only: !showUnresolved,
    hide_glimpses: true,
    order: "first_seen",
    limit: 80,
  };
}

/**
 * Split the Live feed into the rows shown and the number left for the Review page.
 * Shown: confirmed visits and likely ones. "Show unresolved" adds pictures that say
 * nothing yet (unknown), never probable or possible guesses: those wait in Review.
 */
export function splitLiveFeed(
  encounters: Encounter[],
  showUnresolved: boolean,
): { shown: Encounter[]; toReview: number } {
  const shown: Encounter[] = [];
  let toReview = 0;
  for (const encounter of encounters) {
    const mark = feedMark(encounter);
    // A picture seen in a single frame is usually a flicker or an edge artefact: it
    // waits in Review until a reviewer confirms it or a second frame arrives.
    const steady =
      encounter.modality !== "visual" ||
      encounter.records >= MIN_VISUAL_FRAMES ||
      mark === "confirmed";
    const visible =
      steady &&
      (mark === "confirmed" ||
        mark === "likely" ||
        (showUnresolved &&
          mark === "unknown" &&
          encounter.modality === "visual"));
    if (visible) shown.push(encounter);
    else if (
      encounter.review_status === "unreviewed" ||
      encounter.review_status === "mixed"
    )
      toReview += 1;
  }
  return { shown, toReview };
}

export const FEED_MARK_TITLES: Record<FeedMark, string> = {
  confirmed: "Confirmed by a reviewer",
  likely: "Likely: one species stands clearly ahead",
  probable: "Probable: look-alikes score almost the same",
  possible: "Possible: a faint guess",
  unknown: "Unknown: not enough detail yet",
};
