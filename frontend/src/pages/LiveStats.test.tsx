// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import LivePage from "./LivePage";

describe("stream stats on Live", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("start off, even when an old Overlay switch was stored as on", () => {
    const stored: Record<string, string> = { "falcon.live.overlay": "true", "live.overlay": "true" };
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => stored[key] ?? null,
      setItem: () => undefined,
      removeItem: () => undefined,
    });
    const html = renderToStaticMarkup(<LivePage taxa={[]} onOpen={() => {}} onNavigate={() => {}} />);
    const input = html.match(/<input[^>]*aria-label="Show stream stats on the video"[^>]*>/)?.[0] ?? "";
    expect(input).not.toBe("");
    expect(input).not.toMatch(/checked=""/);
    expect(html).toContain(">Stats<");
    expect(html).not.toContain(">Overlay<");
    expect(html).not.toContain("stage-info");
  });
});
