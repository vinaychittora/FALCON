// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { crossLink, type Encounter } from "./encounters";
import { recordingNote } from "../components/EvidencePlayer";

const base = { modality: "visual", heard: [], seen: [] } as unknown as Encounter;

describe("seen and heard together", () => {
  it("names the calls heard during a visit, clearest first", () => {
    expect(
      crossLink({
        ...base,
        heard: [
          { name: "Bluethroat", confidence: 0.71 },
          { name: "House Sparrow", confidence: 0.55 },
        ],
      }),
    ).toBe("Heard at the same time: Bluethroat 71 %, House Sparrow 55 %");
    expect(crossLink(base)).toBe("");
  });

  it("names the animals seen during a calling stretch", () => {
    expect(crossLink({ ...base, modality: "audio", seen: ["Indian Robin"] })).toBe(
      "Seen at the same time: Indian Robin",
    );
  });

  it("says how long a stay has been recording", () => {
    const started = "2026-11-14T04:00:00Z";
    expect(
      recordingNote({ media_kind: "video", captured_at: started }, Date.parse(started) + 42_000),
    ).toMatch(/^Recording, 42 s so far/);
  });
});
