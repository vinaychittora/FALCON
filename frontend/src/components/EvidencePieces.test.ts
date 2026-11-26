// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { boxesAt, pieceLabel, type StoredBox } from "./EvidencePlayer";

const box = (t: number, track: string, own = false): StoredBox => ({
  t,
  bbox: [0.1, 0.1, 0.2, 0.2],
  track,
  own,
  tone: "probable",
  label: "Bird",
});

describe("one player for a visit's recordings", () => {
  it("draws each animal's nearest detection to the moment shown", () => {
    const boxes = [box(1000, "a", true), box(1333, "a", true), box(1100, "b"), box(5000, "c")];
    const shown = boxesAt(boxes, 1300);
    expect(shown.map((b) => [b.track, b.t])).toEqual([
      ["a", 1333],
      ["b", 1100],
    ]);
    expect(boxesAt(boxes, 3000)).toEqual([]);
  });

  it("labels the pieces: the whole stay, older clips and sound", () => {
    const base = { captured_at: "2026-11-14T01:55:03Z", audio_present: true, status: "ready" as const };
    expect(
      pieceLabel({ ...base, evidence_id: "s", media_kind: "video", duration_ms: 255_000, message: "Whole stay recording with sound." }),
    ).toMatch(/^Whole stay · 4:15 · /);
    expect(pieceLabel({ ...base, evidence_id: "c", media_kind: "video", duration_ms: 10_000, message: null })).toMatch(
      /^Clip · 10 s · /,
    );
    expect(pieceLabel({ ...base, evidence_id: "a", media_kind: "audio", duration_ms: 44_000, message: null })).toMatch(
      /^Sound · 44 s/,
    );
  });
});
