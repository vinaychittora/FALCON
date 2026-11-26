// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import type { Encounter } from "./encounters";
import { feedMark, feedName, feedScore, liveFeedFilters, splitLiveFeed } from "./liveFeed";
import { pcClockFault, soundTone } from "../pages/LivePage";

describe("the Sound light warns when this computer's clock is off", () => {
  it("names the computer's clock and the fix, and stays quiet under 1 %", () => {
    const fault = pcClockFault({ drift_percent: 8.4, warning: true });
    expect(fault).toContain("this computer's clock runs about 8 % fast");
    expect(fault).toContain("wsl --shutdown");
    expect(pcClockFault({ drift_percent: 0.1, warning: false })).toBe("");
    expect(soundTone(true, "listening", "", "", fault)).toBe("bad");
  });
});

describe("the Live list asks for what Review's default view shows", () => {
  it("leaves out one-frame glimpses, so 'N more to review' never opens an empty list", () => {
    for (const showUnresolved of [false, true]) {
      expect(liveFeedFilters("live-1", "all", showUnresolved).hide_glimpses).toBe(true);
    }
    expect(liveFeedFilters("live-1", "all", false).resolved_only).toBe(true);
  });
});

function sound(
  id: string,
  confidence: number,
  extra: Partial<Encounter> = {},
): Encounter {
  return {
    encounter_id: id,
    modality: "audio",
    source_id: "s",
    source_filename: "live",
    job_id: "j",
    track_id: null,
    records: 1,
    first_captured_at: null,
    duration_ms: 3000,
    review_status: "unreviewed",
    thumbnail_event_id: id,
    event: {
      modality: "audio",
      confidence,
      review: { status: "unreviewed" },
    } as unknown as Encounter["event"],
    ...extra,
  };
}

function picture(
  id: string,
  status: string,
  certainty?: string,
  review = "unreviewed",
): Encounter {
  return {
    ...sound(id, 0),
    modality: "visual",
    review_status: review as Encounter["review_status"],
    event: {
      modality: "visual",
      classification: { status, certainty, score: 0.31 },
      review: { status: review },
    } as unknown as Encounter["event"],
  };
}

describe("live feed", () => {
  it("shows likely and confirmed visits, counts the rest for review", () => {
    const items = [
      sound("likely", 0.8),
      sound("probable", 0.5),
      picture("unknown", "unknown", "unknown"),
      picture("confirmed", "candidate", "likely", "correct"),
      picture("rejected", "candidate", "likely", "false_positive"),
    ];
    const { shown, toReview } = splitLiveFeed(items, false);
    expect(shown.map((item) => item.encounter_id)).toEqual([
      "likely",
      "confirmed",
    ]);
    expect(toReview).toBe(2);
  });

  it("show unresolved adds unknown pictures but never probable sound", () => {
    const items = [
      sound("probable", 0.5),
      { ...picture("unknown", "unknown", "unknown"), records: 3 },
    ];
    const { shown, toReview } = splitLiveFeed(items, true);
    expect(shown.map((item) => item.encounter_id)).toEqual(["unknown"]);
    expect(toReview).toBe(1);
  });

  it("names a likely picture with a question mark until it is confirmed", () => {
    const likely = picture("cat", "candidate", "likely");
    expect(feedName("Rusty-spotted Cat", likely)).toBe("Rusty-spotted Cat?");
    expect(feedName("Cat (species uncertain)", likely)).toBe(
      "Cat (species uncertain)",
    );
    const confirmed = picture("ok", "candidate", "likely", "correct");
    expect(feedName("Rusty-spotted Cat", confirmed)).toBe("Rusty-spotted Cat");
    expect(feedName("Rose-ringed Parakeet", sound("call", 0.9))).toBe(
      "Rose-ringed Parakeet",
    );
  });

  it("a likely picture needs two frames unless confirmed", () => {
    const single = { ...picture("one", "candidate", "likely"), records: 1 };
    const steady = { ...picture("two", "candidate", "likely"), records: 2 };
    const confirmed = {
      ...picture("ok", "candidate", "likely", "correct"),
      records: 1,
    };
    const { shown, toReview } = splitLiveFeed(
      [single, steady, confirmed],
      false,
    );
    expect(shown.map((item) => item.encounter_id)).toEqual(["two", "ok"]);
    expect(toReview).toBe(1);
  });

  it("a sound bout is as certain as its clearest call", () => {
    const bout = sound("bout", 0.55, { best_confidence: 0.86, records: 7 });
    expect(feedMark(bout)).toBe("likely");
    expect(feedScore(bout)).toBe(0.86);
  });
});
