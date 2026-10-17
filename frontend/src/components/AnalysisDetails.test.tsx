import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AnalysisDetails from "./AnalysisDetails";

describe("System navigation", () => {
  it("shows live device status without depending on an uploaded analysis", () => {
    const html = renderToStaticMarkup(
      <AnalysisDetails
        tab="live"
        onTab={() => {}}
        config={null}
        models={null}
        busy={false}
        onConfig={() => {}}
        onSave={() => {}}
      />,
    );
    expect(html).toContain('aria-selected="true" class="active">Live status');
    expect(html).toContain("Configuration");
    expect(html).toContain("Device access");
    expect(html).not.toContain("Selected run");
    expect(html).not.toContain("Raw records");
    expect(html).not.toContain("Select an analyzed source");
  });
});
