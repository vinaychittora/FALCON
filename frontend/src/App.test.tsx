import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("field-first navigation", () => {
  it("opens Monitor by default and separates Media tests from Field observations", () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain(
      'id="workspace-tab-monitor" role="tab" aria-selected="true"',
    );
    expect(html).toContain('<h1 class="sr-only">Monitor</h1>');
    expect(html).toContain('aria-labelledby="workspace-tab-monitor"');
    expect(html).toContain("Media tests</button>");
    expect(html).toContain("Observations</button>");
    expect(html).not.toContain("Upload photo, video or audio");
    expect(html).not.toContain("Field observations</h1>");
    expect(html).not.toContain('class="page-heading"');
    expect(html).not.toContain(
      "Live camera, audio and environmental readings.",
    );
    expect(html).toContain("Display and accessibility options");
  });
});
