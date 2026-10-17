import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Job } from "../types";
import ObservationHistory from "./ObservationHistory";

function renderRun(mode?: string) {
  const job = {
    job_id: "test-run",
    created_at: "2026-10-17T08:30:00Z",
    status: "completed",
    metrics: mode ? { classifier_mode: mode } : {},
  } as Job;
  const html = renderToStaticMarkup(
    <ObservationHistory
      events={[]}
      jobs={[job]}
      runId="test-run"
      onRun={() => {}}
      onSeek={() => {}}
      onInspect={() => {}}
    />,
  );
  return html.match(/<option value="test-run"[^>]*>(.*?)<\/option>/)?.[1] ?? "";
}

describe("analysis history model labels", () => {
  it.each([
    ["bioclip_2", "BioCLIP 2 · lighter"],
    ["bioclip_2_5", "BioCLIP 2.5 Huge · detailed"],
    ["ensemble", "Both models · cross-check"],
  ])("identifies the recorded model mode %s", (mode, label) => {
    const option = renderRun(mode);
    expect(option).toContain(label);
    expect(option).toContain("completed");
  });

  it("does not infer a model for old or unrecognized runs", () => {
    for (const mode of [undefined, "future_model"]) {
      const option = renderRun(mode);
      expect(option).toContain("completed");
      expect(option).not.toContain("BioCLIP");
      expect(option).not.toContain("Both models");
      expect(option).not.toContain("future_model");
    }
  });
});
