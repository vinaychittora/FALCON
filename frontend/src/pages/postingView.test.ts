// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import { postFooter, sendsText, splitByName, verdictPill } from "./postingView";
import type { PostableVisit } from "../api/inaturalist";

const base = {
  problems: [],
  account: true,
  kind: "picture" as const,
  soundOffered: false,
  pictures: 0,
  sound: false,
  failed: 0,
  waiting: 0,
  busy: false,
};

describe("the Post footer", () => {
  it("names the next step until a picture is chosen", () => {
    expect(postFooter(base)).toEqual({ text: "Choose 1 to 3 pictures first.", ready: false, reason: false });
    expect(postFooter({ ...base, soundOffered: true }).text).toBe(
      "Choose 1 to 3 pictures or include the sound first.",
    );
  });
  it("says what one press sends", () => {
    expect(postFooter({ ...base, pictures: 1 })).toEqual({ text: "1 picture", ready: true, reason: false });
    expect(postFooter({ ...base, pictures: 2, sound: true }).text).toBe("2 pictures and the sound");
    expect(postFooter({ ...base, kind: "sound", sound: true }).text).toBe("The sound");
  });
  it("puts the reason in place of the button for a visit that cannot be posted", () => {
    const out = postFooter({ ...base, pictures: 2, problems: ["This visit has no species name. Correct it to a species first."] });
    expect(out.reason).toBe(true);
    expect(out.ready).toBe(false);
    expect(out.text).toMatch(/no species name/);
  });
  it("is not ready without a key, while pictures load, after a failed picture or while posting", () => {
    expect(postFooter({ ...base, pictures: 1, account: false }).ready).toBe(false);
    expect(postFooter({ ...base, pictures: 1, waiting: 1 }).ready).toBe(false);
    expect(postFooter({ ...base, pictures: 1, failed: 1 }).ready).toBe(false);
    expect(postFooter({ ...base, pictures: 1, busy: true })).toEqual({ text: "Posting…", ready: false, reason: false });
    expect(postFooter({ ...base, kind: "sound" }).text).toBe("Include the sound first.");
  });
  it("words", () => {
    expect(sendsText(3, false)).toBe("3 pictures");
    expect(sendsText(0, true)).toBe("The sound");
  });
});

describe("the list", () => {
  const row = (name: string | null, scientific: string | null): PostableVisit => ({
    encounter_id: `${name}-${scientific}`, name, scientific_name: scientific, first_captured_at: null,
    duration_ms: 1000, records: 1, review_status: "correct", thumbnail_event_id: "", node: "n",
  });
  it("keeps visits without a species name apart, in order", () => {
    const { named, unnamed } = splitByName([row("A", "a"), row(null, null), row(null, "b"), row(null, null)]);
    expect(named.map((v) => v.encounter_id)).toEqual(["A-a", "null-b"]);
    expect(unnamed).toHaveLength(2);
  });
  it("pills the verdict, and nothing when it is not known", () => {
    expect(verdictPill("correct")).toBe("Confirmed");
    expect(verdictPill("corrected")).toBe("Corrected");
    expect(verdictPill("")).toBeNull();
  });
});
