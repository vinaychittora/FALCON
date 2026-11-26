// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { afterEach, describe, expect, it, vi } from "vitest";
import { setDetectionPaused } from "./PauseDetection";

afterEach(() => vi.unstubAllGlobals());

describe("pause detection for camera work", () => {
  it("sends the paused state to the live service", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "live",
          detection_paused_since: "2026-11-08T16:00:00Z",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const state = await setDetectionPaused(true);
    expect(state.detection_paused_since).toBe("2026-11-08T16:00:00Z");
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toContain("/api/live/pause");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ paused: true });
  });
});
