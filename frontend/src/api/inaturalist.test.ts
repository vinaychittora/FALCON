// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { describe, expect, it } from "vitest";
import {
  clampTrim,
  keyExpiry,
  parseSpot,
  pickable,
  pickedId,
  savedPhotos,
  visitFromHash,
  withArticle,
  type VisitClip,
} from "./inaturalist";
import { pageFromHash } from "../App";
import { cameraDamage } from "../pages/LivePage";

describe("iNaturalist posting helpers", () => {
  it("reads a camera spot pasted from a map", () => {
    expect(parseSpot("12.5, 77.25")).toEqual([12.5, 77.25]);
    expect(parseSpot(" -12.5 77.25 ")).toEqual([-12.5, 77.25]);
    expect(parseSpot("12.5")).toBeNull();
    expect(parseSpot("95, 10")).toBeNull();
    expect(parseSpot("north")).toBeNull();
  });

  it("says how long the key is valid", () => {
    const now = new Date("2026-11-16T04:00:00Z");
    expect(keyExpiry("2026-11-16T09:12:00Z", now)).toMatch(/\(5 h 12 min left\)$/);
    expect(keyExpiry("2026-11-16T03:00:00Z", now)).toMatch(/\(0 min left\)$/);
  });

  it("keeps the sound trim inside the visit and at most a minute", () => {
    expect(clampTrim([5, 90], [0, 120], "end")).toEqual([30, 90]);
    expect(clampTrim([5, 90], [0, 120], "start")).toEqual([5, 65]);
    expect(clampTrim([-3, 4], [0, 10], "start")).toEqual([0, 4]);
    expect(clampTrim([6, 6], [0, 10], "end")).toEqual([5.5, 6]);
  });

  it("names a frame picked from the recording by its time", () => {
    expect(pickedId(12.3456)).toBe("t:12.346");
  });

  it("works without browser storage", () => {
    expect(savedPhotos("visit-1")).toBeNull();
  });

  it("opens the posting page for one visit from the Review popup", () => {
    expect(pageFromHash("#/posting?visit=job%3Atrack-1")).toBe("posting");
    expect(visitFromHash("#/posting?visit=job%3Atrack-1")).toBe("job:track-1");
    expect(visitFromHash("#/posting")).toBeNull();
  });
});

describe("picking frames outside the visit", () => {
  const clip = (pick_range?: [number, number]): VisitClip => ({
    evidence_id: "e1", start_s: 106.6, end_s: 153.3, detections: [], filmstrip: [], pick_range,
  });

  it("without the backend's range: only inside the visit (today's behaviour)", () => {
    expect(pickable(clip(), 120)).toEqual({ inside: true, allowed: true });
    expect(pickable(clip(), 90.17)).toEqual({ inside: false, allowed: false });
  });

  it("with the backend's range: anywhere in the recording, marked as outside", () => {
    expect(pickable(clip([0, 159]), 90.17)).toEqual({ inside: false, allowed: true });
    expect(pickable(clip([0, 159]), 120)).toEqual({ inside: true, allowed: true });
    expect(pickable(clip([0, 159]), 170)).toEqual({ inside: false, allowed: false });
  });
});

describe("species in sentences", () => {
  it("uses a or an", () => {
    expect(withArticle("Red-vented Bulbul")).toBe("a Red-vented Bulbul");
    expect(withArticle("Oriental Magpie-Robin")).toBe("an Oriental Magpie-Robin");
  });
});

describe("camera picture damage", () => {
  it("is shown only while the self-heal could not fix it", () => {
    expect(cameraDamage("")).toBe("");
    expect(cameraDamage(undefined)).toBe("");
    expect(cameraDamage("2026-11-16T04:43:00+00:00")).toMatch(
      /^camera picture damaged since .*restart the node/,
    );
  });
});
