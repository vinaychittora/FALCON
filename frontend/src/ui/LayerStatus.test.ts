// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { layerState } from "./LayerStatus";
import { failedSentence } from "../api/recordView";
import { NetworkError } from "../api/activity";

describe("the status inside a layer (25 Nov)", () => {
  it("shows the connection states", () => {
    for (const kind of ["offline", "down", "slow", "loading"] as const)
      expect(layerState({ kind, text: "x", since: 0 } as never)?.kind).toBe(kind);
  });
  it("uses the short can't-reach text inside a layer", () => {
    expect(
      layerState({ kind: "down", text: "Can't reach FALCON since 10:44 pm. Trying again…", since: 0 })?.text,
    ).toBe("Can't reach FALCON since 10:44 pm.");
  });
  it("shows Connected again but not the save confirmations or the sound hint", () => {
    expect(layerState({ kind: "confirm", text: "Connected again" })?.text).toBe("Connected again");
    expect(layerState({ kind: "confirm", text: "2 reviews saved" })).toBeNull();
    expect(layerState({ kind: "sound", text: "Tap the page once to allow sound." })).toBeNull();
    expect(layerState({ kind: "connected", text: "Connected" })).toBeNull();
  });
  it("names the network in the popup's failed-save line, and only then", () => {
    const net = new NetworkError();
    expect(failedSentence("save", net)).toBe("Could not save: can't reach FALCON. Try again.");
    expect(failedSentence("undo", net)).toBe("Could not undo: can't reach FALCON. Try again.");
    expect(failedSentence("note", net)).toBe("Could not save the note: can't reach FALCON. Try again.");
    const other = new Error("500");
    expect(failedSentence("save", other)).toBe("Could not save. Try again.");
    expect(failedSentence("undo", other)).toBe("Could not undo. Try again.");
    expect(failedSentence("note", other)).toBe("Could not save the note. Try again.");
  });
  it("lets the posting panel add its own confirmation", () => {
    expect(layerState({ kind: "confirm", text: "Posted to iNaturalist" }, ["Posted to iNaturalist"])?.text).toBe(
      "Posted to iNaturalist",
    );
    expect(layerState({ kind: "loading", text: "Posting…" })?.text).toBe("Posting…");
  });
});
