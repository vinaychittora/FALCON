// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App, { helpRoute, pageFromHash, PAGES } from "./App";

describe("application shell", () => {
  it("opens Live by default with every section in the main navigation", () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toMatch(/href="#\/live" class="fs-row" data-page="live" aria-current="page"/);
    // The top bar: menu, one-line page title, Listen, Help and the station status button.
    expect(html).toContain('aria-label="Open the menu" aria-haspopup="dialog"');
    expect(html).toContain('<h1 class="fs-title">Live</h1>');
    expect(html).toMatch(/role="switch" aria-checked="false"[^>]*>.*Listen<\/button>/);
    expect(html).toContain('aria-label="Help for this page"');
    expect(html).toMatch(/aria-label="Station status: [^"]+ to review"/);
    for (const item of PAGES) expect(html).toContain(`href="#/${item.page}"`);
    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).toContain('href="#/help/user-guide/live"');
    expect(html).toContain("Start observing");
    expect(html).toContain(
      "Field Acoustic, Lens &amp; Climate Observation Node",
    );
    expect(html).toContain("Display and accessibility options");
    expect(html).toContain('href="#/summary"');
    expect(html).not.toContain("Install app");
    expect(html).not.toContain("Upload photo, video or audio");
  });

  it("reads the page from the address hash and falls back to Live", () => {
    expect(pageFromHash("#/review")).toBe("review");
    expect(pageFromHash("#export")).toBe("export");
    expect(pageFromHash("#/sensors?node=1")).toBe("sensors");
    expect(pageFromHash("#/summary")).toBe("summary");
    expect(pageFromHash("#/export?source=abc")).toBe("export");
    expect(pageFromHash("#/unknown")).toBe("live");
    expect(pageFromHash("")).toBe("live");
    expect(pageFromHash("#/help/sensor-node/checks")).toBe("help");
    expect(helpRoute("#/help/sensor-node/checks")).toBe("sensor-node/checks");
    expect(helpRoute("#/live")).toBe("");
  });
});
