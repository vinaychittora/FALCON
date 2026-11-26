// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import {
  certaintyOf,
  leadingName,
  soundGuessLine,
  unidentifiedSound,
} from "./certainty";
import { canConfirm, encounterNames, withBoutConfidence, type Encounter } from "./encounters";
import { feedMark, splitLiveFeed } from "./liveFeed";
import { confirmAction, pickAction, recordIdentity } from "./recordView";
import { BIRDNET_GUESS, speciesChoices } from "./speciesChoice";
import { displayLabel, displayScientificName } from "./timeline";
import { visitName } from "./detectionBell";
import type { AudioEvent, ReviewStatus } from "../types";

const BITTERN = { taxon_id: -11, scientific_name: "Botaurus stellaris", common_name: "Great Bittern" };
const HERON = { taxon_id: 4956, scientific_name: "Ardea cinerea", common_name: "Gray Heron" };
const TAXA = [HERON, BITTERN];

function bout(outside: boolean | undefined, status: ReviewStatus = "unreviewed", best = 0.92): Encounter {
  const corrected = status === "corrected";
  const event = {
    event_id: "e1", modality: "audio", job_id: "j", source_id: "s", source_filename: "node",
    start_ms: 0, end_ms: 3000, scientific_name: "Botaurus stellaris", common_name: "Great Bittern",
    confidence: 0.71, model: "BirdNET", cleaned_agrees: true, outside_area: outside,
    review: {
      status,
      corrected_taxon_id: corrected ? HERON.taxon_id : null,
      corrected_scientific_name: corrected ? HERON.scientific_name : null,
      corrected_common_name: corrected ? HERON.common_name : null,
    },
  } as unknown as AudioEvent;
  return withBoutConfidence({
    encounter_id: "j:b", modality: "audio", source_id: "s", source_filename: "node", job_id: "j",
    track_id: null, records: 2, first_captured_at: null, duration_ms: 6000, review_status: status,
    thumbnail_event_id: "e1", event, best_confidence: best,
  });
}

describe("an unidentified sound (a bird not recorded in Rajasthan)", () => {
  const out = bout(true);

  it("is Unidentified in the one certainty function, even at 0.92", () => {
    expect(certaintyOf(out.event)).toMatchObject({ level: "unknown", label: "Unidentified" });
    expect(feedMark(out)).toBe("unknown");
  });

  it("never shows on Live and never rings", () => {
    const { shown, toReview } = splitLiveFeed([out], true);
    expect(shown).toEqual([]);
    expect(toReview).toBe(1);
    expect(feedMark(out)).not.toBe("likely");
  });

  it("is titled Unidentified sound with BirdNET's guess as the front line", () => {
    expect(leadingName(out.event)).toBe("Unidentified sound");
    expect(encounterNames(out.event)).toEqual({ primary: "Unidentified sound", scientific: null });
    expect(recordIdentity(out.event)).toMatchObject({ name: "Unidentified sound", scientific: null });
    expect(recordIdentity(out.event).pill.text).toBe("Unidentified");
    expect(soundGuessLine(out.event)).toBe(
      "BirdNET's guess: Great Bittern 0.92 · not recorded in Rajasthan",
    );
    expect(displayLabel(out.event)).toBe("Unidentified sound");
    expect(displayScientificName(out.event)).toBeNull();
    expect(visitName(out)).toBe("Unidentified sound");
  });

  it("cannot be confirmed; Correct offers the guess first and stores a correction", () => {
    expect(canConfirm(out.event)).toBe(false);
    expect(confirmAction(out.event, TAXA)).toBeNull();
    const choices = speciesChoices(out.event, TAXA, [{ scientific_name: HERON.scientific_name, visits: 3 }], "");
    expect(choices.groups[0].title).toBe(BIRDNET_GUESS);
    expect(choices.groups[0].rows[0].taxon).toEqual(BITTERN);
    expect(choices.groups[1].rows[0].taxon).toEqual(HERON);
    expect(pickAction(out.event, BITTERN, TAXA)).toEqual({
      kind: "correct", status: "corrected", taxonId: BITTERN.taxon_id,
    });
  });

  it("once corrected it is an ordinary corrected record", () => {
    const fixed = bout(true, "corrected");
    expect(unidentifiedSound(fixed.event)).toBe(false);
    expect(leadingName(fixed.event)).toBe("Gray Heron");
    expect(soundGuessLine(fixed.event)).toBeNull();
    expect(feedMark(fixed)).toBe("confirmed");
  });

  it("in-list and older records are named as before", () => {
    for (const named of [bout(false), bout(undefined)]) {
      expect(leadingName(named.event)).toBe("Great Bittern");
      expect(certaintyOf(named.event)?.level).toBe("likely");
      expect(canConfirm(named.event)).toBe(true);
      expect(soundGuessLine(named.event)).toBeNull();
    }
  });
});
