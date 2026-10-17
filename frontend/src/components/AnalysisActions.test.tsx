import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Job, Video } from "../types";
import AnalysisActions from "./AnalysisActions";

const source = { source_id: "source", media_kind: "video" } as Video;
const job = {
  job_id: "run",
  source_id: "source",
  status: "paused",
  can_resume: true,
  resume_from_ms: 73500,
} as Job;
function render(
  overrides: Partial<Parameters<typeof AnalysisActions>[0]> = {},
) {
  return renderToStaticMarkup(
    <AnalysisActions
      source={source}
      job={job}
      blocked={false}
      canStart={true}
      pending={null}
      onStart={() => {}}
      onPause={() => {}}
      onResume={() => {}}
      {...overrides}
    />,
  );
}
function buttons(html: string) {
  return [...html.matchAll(/<button([^>]*)>(.*?)<\/button>/gs)].map(
    (match) => ({
      disabled: match[1].includes("disabled"),
      label: match[2].replace(/<[^>]+>/g, ""),
    }),
  );
}

describe("pause and resume controls", () => {
  it("offers saved-position Resume separately from a new analysis", () => {
    const html = render();
    expect(buttons(html).map((button) => button.label)).toEqual([
      "Resume from 01:13.5",
      "Analyze again",
    ]);
    expect(html).toContain("Create a new analysis from the beginning");
    expect(html).toContain("saved settings and observations");
  });
  it("resume remains available when current settings are not loaded", () => {
    expect(buttons(render({ canStart: false }))).toEqual([
      { disabled: false, label: "Resume from 01:13.5" },
      { disabled: true, label: "Analyze again" },
    ]);
  });
  it("disables starting and resuming while another analysis or camera owns the engine", () => {
    expect(
      buttons(render({ blocked: true })).every((button) => button.disabled),
    ).toBe(true);
  });
  it("keeps Pause usable for the active job despite the engine being busy", () => {
    expect(
      buttons(
        render({
          job: { ...job, status: "running", can_resume: false },
          blocked: true,
        }),
      ),
    ).toEqual([
      { disabled: true, label: "Analyzing…" },
      { disabled: false, label: "Pause analysis" },
    ]);
  });
  it("blocks duplicate pause requests and preserves legacy Stop before backend deployment", () => {
    expect(
      buttons(
        render({ job: { ...job, status: "pausing", can_resume: false } }),
      ),
    ).toEqual([
      { disabled: true, label: "Pausing…" },
      { disabled: true, label: "Saving progress…" },
    ]);
    expect(
      render({ job: { ...job, status: "running", can_resume: undefined } }),
    ).toContain(">Stop</button>");
  });
  it("labels audio-stage resume without claiming a precise audio offset", () => {
    const html = render({ job: { ...job, resume_stage: "audio" } });
    expect(html).toContain("Resume audio analysis");
    expect(html).not.toContain("Resume from");
  });
  it("does not expose another source's checkpoint or pause action", () => {
    const html = render({ job: { ...job, source_id: "other" } });
    expect(html).not.toContain("Resume");
    expect(html).not.toContain("Pause");
    expect(html).toContain("Analyze recording");
  });
});
