import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "../types";
import { api } from "./client";
import {
  canResumeAnalysis,
  controlAnalysis,
  isActiveAnalysis,
  selectAnalysisJob,
} from "./analysis";

vi.mock("./client", () => ({ api: vi.fn() }));
const paused = {
  job_id: "selected-run",
  source_id: "selected-source",
  status: "paused",
  can_resume: true,
  resume_from_ms: 73500,
  coverage_ms: 73500,
} as Job;

beforeEach(() => {
  vi.mocked(api).mockReset();
});

describe("saved analysis selection and engine ownership", () => {
  it("resumes only a server-approved checkpoint on the selected source", () => {
    for (const status of [
      "paused",
      "interrupted",
      "cancelled",
      "failed",
    ] as const)
      expect(canResumeAnalysis({ ...paused, status }, paused.source_id)).toBe(
        true,
      );
    expect(canResumeAnalysis(paused, "other-source")).toBe(false);
    expect(
      canResumeAnalysis({ ...paused, can_resume: false }, paused.source_id),
    ).toBe(false);
    expect(
      canResumeAnalysis({ ...paused, can_resume: undefined }, paused.source_id),
    ).toBe(false);
    expect(
      canResumeAnalysis({ ...paused, status: "completed" }, paused.source_id),
    ).toBe(false);
  });
  it("keeps pausing busy until the backend reports paused", () => {
    for (const status of ["queued", "running", "pausing"] as const)
      expect(isActiveAnalysis({ ...paused, status })).toBe(true);
    for (const status of [
      "paused",
      "interrupted",
      "cancelled",
      "completed",
    ] as const)
      expect(isActiveAnalysis({ ...paused, status })).toBe(false);
  });
  it("never falls back to another run or source when a historical run is selected", () => {
    const newer = { ...paused, job_id: "newer-run" };
    const foreign = {
      ...paused,
      job_id: "foreign-run",
      source_id: "other-source",
    };
    expect(
      selectAnalysisJob(
        [foreign, newer, paused],
        paused.job_id,
        paused.source_id,
      ),
    ).toBe(paused);
    expect(
      selectAnalysisJob([foreign, newer], paused.job_id, paused.source_id),
    ).toBeNull();
    expect(
      selectAnalysisJob([foreign, newer, paused], "", paused.source_id),
    ).toBe(newer);
  });
});

describe("analysis controls", () => {
  it("passes ownership when resuming a temporary test without changing its settings", async () => {
    vi.mocked(api).mockResolvedValue({ ...paused, status: "queued" });
    await controlAnalysis(
      "resume",
      paused,
      paused.source_id,
      "temporary-session",
    );
    expect(api).toHaveBeenCalledExactlyOnceWith("/jobs/selected-run/resume", {
      method: "POST",
      headers: { "X-Falcon-Test-Session": "temporary-session" },
    });
  });
  it("resumes the same historical job without sending current system settings", async () => {
    vi.mocked(api).mockResolvedValue({ ...paused, status: "queued" });
    await controlAnalysis("resume", paused, paused.source_id);
    expect(api).toHaveBeenCalledExactlyOnceWith("/jobs/selected-run/resume", {
      method: "POST",
    });
  });
  it("refuses to send commands for a stale source selection or ineligible checkpoint", async () => {
    await expect(
      controlAnalysis("resume", paused, "other-source"),
    ).rejects.toThrow("Select this analysis source");
    await expect(
      controlAnalysis(
        "resume",
        { ...paused, can_resume: false, resume_reason: "Source changed" },
        paused.source_id,
      ),
    ).rejects.toThrow("Source changed");
    expect(api).not.toHaveBeenCalled();
  });
  it("uses pause for a capable backend and preserves legacy Stop via cancel", async () => {
    const running = {
      ...paused,
      status: "running" as const,
      can_resume: false,
    };
    await controlAnalysis("pause", running, paused.source_id);
    expect(api).toHaveBeenLastCalledWith("/jobs/selected-run/pause", {
      method: "POST",
    });
    await controlAnalysis(
      "pause",
      { ...running, can_resume: undefined },
      paused.source_id,
    );
    expect(api).toHaveBeenLastCalledWith("/jobs/selected-run/cancel", {
      method: "POST",
    });
  });
  it("does not send another pause while progress is being saved", async () => {
    await expect(
      controlAnalysis(
        "pause",
        { ...paused, status: "pausing" },
        paused.source_id,
      ),
    ).rejects.toThrow("not running");
    expect(api).not.toHaveBeenCalled();
  });
});
