// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { beforeEach, describe, expect, it } from "vitest";
import {
  activityState,
  beginRequest,
  confirm,
  falconDown,
  foregroundBusy,
  forgetFailures,
  inBackground,
  resetActivity,
  startTask,
} from "./activity";

const T = 1_000_000;

describe("the activity sign (25 Nov)", () => {
  beforeEach(() => resetActivity());

  it("says Connected when nothing is going on", () => {
    expect(activityState(T, true).kind).toBe("connected");
  });

  it("shows Loading only after 250 ms, and only for requests the user started", () => {
    const end = beginRequest(T);
    expect(activityState(T + 200, true).kind).toBe("connected");
    expect(activityState(T + 300, true).text).toBe("Loading…");
    expect(foregroundBusy(T + 300)).toBe(true);
    end("ok", T + 400);
    inBackground(() => beginRequest(T));
    expect(activityState(T + 1000, true).kind).toBe("connected");
    expect(foregroundBusy(T + 1000)).toBe(false);
  });

  it("says Posting… while a post runs, also past 5 s, then Posted for 3 s", () => {
    const end = startTask("Posting…");
    const request = beginRequest(T);
    expect(activityState(T + 300, true).text).toBe("Posting…");
    expect(activityState(T + 9000, true).text).toBe("Posting…");
    request("ok", T + 9000);
    end();
    confirm("Posted to iNaturalist", T + 9000);
    expect(activityState(T + 9100, true).text).toBe("Posted to iNaturalist");
    expect(activityState(T + 12100, true).kind).toBe("connected");
  });

  it("still says it cannot reach FALCON during a post", () => {
    startTask("Posting…");
    beginRequest(T)("network", T + 10);
    beginRequest(T + 20)("network", T + 30);
    expect(activityState(T + 40, true).kind).toBe("down");
  });

  it("says FALCON is slow after 5 s, for any request", () => {
    inBackground(() => beginRequest(T));
    expect(activityState(T + 5100, true).text).toBe("FALCON is slow to answer…");
  });

  it("says it cannot reach FALCON after two network failures in a row, then Connected again", () => {
    beginRequest(T)("network", T + 10);
    expect(falconDown()).toBe(false);
    beginRequest(T + 3000)("network", T + 3010);
    expect(falconDown()).toBe(true);
    const down = activityState(T + 3020, true);
    expect(down.kind).toBe("down");
    expect(down.text).toMatch(/^Can't reach FALCON since .+\. Trying again…$/);
    beginRequest(T + 6000)("ok", T + 6010);
    expect(falconDown()).toBe(false);
    expect(activityState(T + 6020, true).text).toBe("Connected again");
  });

  it("counts any answer from FALCON, even an error, as reachable; aborts count as nothing", () => {
    beginRequest(T)("network", T);
    beginRequest(T)("answered", T);
    beginRequest(T)("network", T);
    beginRequest(T)("aborted", T);
    expect(falconDown()).toBe(false);
  });

  it("judges again after the tab comes back into view", () => {
    beginRequest(T)("network", T);
    beginRequest(T)("network", T);
    expect(falconDown()).toBe(true);
    forgetFailures();
    expect(falconDown()).toBe(false);
  });

  it("shows a confirmation for 3 s, and offline above everything", () => {
    confirm("2 reviews saved", T);
    expect(activityState(T + 2900, true).text).toBe("2 reviews saved");
    expect(activityState(T + 3100, true).kind).toBe("connected");
    expect(activityState(T, false).text).toBe("This device has no network.");
  });

  it("asks for a tap when the browser blocks the Ring sound", () => {
    expect(activityState(T, true, true).text).toBe("Tap the page once to allow sound.");
  });
});
