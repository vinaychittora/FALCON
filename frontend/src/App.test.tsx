import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App, { helpRoute, pageFromHash, PAGES } from "./App";

describe("application shell", () => {
  it("opens Live by default with every section in the main navigation", () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain('href="#/live" class="active" aria-current="page"');
    for (const item of PAGES) expect(html).toContain(`href="#/${item.page}"`);
    expect(html).toContain("<h1>Live <a");
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
