import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import WorkspaceTabs, { nextWorkspaceTab } from "./WorkspaceTabs";
import DisplayPreferences from "./DisplayPreferences";

describe("workspace navigation and display controls", () => {
  it("supports arrows, Home and End without swallowing unrelated keys", () => {
    expect(nextWorkspaceTab("monitor", "ArrowLeft")).toBe("system");
    expect(nextWorkspaceTab("system", "ArrowRight")).toBe("monitor");
    expect(nextWorkspaceTab("observations", "ArrowRight")).toBe("media");
    expect(nextWorkspaceTab("taxa", "Home")).toBe("monitor");
    expect(nextWorkspaceTab("media", "End")).toBe("system");
    expect(nextWorkspaceTab("system", "Tab")).toBeNull();
  });

  it("exposes one selected keyboard tab and its associated panel", () => {
    const html = renderToStaticMarkup(
      <WorkspaceTabs
        selected="system"
        onSelect={() => {}}
        liveBusy={true}
        taxaCount={1369}
      />,
    );
    expect(html.match(/role="tab"/g)).toHaveLength(5);
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(html.match(/tabindex="0"/g)).toHaveLength(1);
    expect(html).toContain(
      'id="workspace-tab-system" role="tab" aria-selected="true"',
    );
    expect(html.match(/aria-controls="workspace-panel"/g)).toHaveLength(5);
  });

  it("exposes labelled theme, text-size and contrast controls", () => {
    const html = renderToStaticMarkup(<DisplayPreferences />);
    expect(html).toContain("Theme<select");
    expect(html).toContain("Text size<select");
    expect(html).toContain('value="dark" selected=""');
    expect(html).toContain("Higher contrast");
  });
});
