import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  captureTime,
  fieldArchiveQuery,
  fieldExportUrl,
} from "../api/observations";
import type {
  AudioEvent,
  Detection,
  EvidenceSummary,
  VisualEvent,
} from "../types";
import EvidencePlayer from "./EvidencePlayer";
import Inspector from "./Inspector";
import ObservationArchive, { FieldObservationRows } from "./ObservationArchive";

const clip: EvidenceSummary = {
  evidence_id: "saved-video",
  media_kind: "video",
  status: "ready",
  duration_ms: 5000,
  captured_at: "2026-10-17T08:30:13Z",
  audio_present: false,
  mime_type: "video/mp4",
  message: null,
  actual_start_ms: 0,
  actual_end_ms: 5000,
};
const visual = {
  event_id: "visual-observation",
  source_id: "field-source",
  source_filename: "Field device",
  source_kind: "live",
  captured_at: "2026-10-17T08:30:15Z",
  time_basis: "server_receive_time",
  modality: "visual",
  timestamp_ms: 999999,
  duration_ms: 500,
  review: { status: "unreviewed" },
  classification: {
    status: "candidate",
    common_name: "Indian Pitta",
    scientific_name: "Pitta brachyura",
    display_label: "Indian Pitta",
    score: 0.782314,
    top_k: [],
  },
  evidence_summaries: [clip],
} as unknown as VisualEvent;
const acoustic = {
  ...visual,
  event_id: "audio-observation",
  modality: "audio",
  start_ms: 999999,
  end_ms: 1002999,
  confidence: 0.867189,
  common_name: "Common Tailorbird",
  scientific_name: "Orthotomus sutorius",
  evidence_summaries: [
    {
      ...clip,
      evidence_id: "saved-audio",
      media_kind: "audio",
      mime_type: "audio/wav",
      audio_present: true,
    },
  ],
} as unknown as AudioEvent;

function rows(events: Detection[]) {
  return renderToStaticMarkup(
    <table>
      <tbody>
        <FieldObservationRows events={events} onInspect={() => {}} />
      </tbody>
    </table>,
  );
}

describe("field observation archive", () => {
  it("shows a scientific-only candidate once while preserving its candidate marker", () => {
    const scientific = "Anabasis obliquifasciella";
    const html = rows([
      {
        ...visual,
        classification: {
          ...visual.classification,
          common_name: null,
          scientific_name: scientific,
          display_label: scientific + " — candidate",
        },
      },
    ]);
    expect(html).toContain(scientific + " — candidate");
    expect(html.match(/Anabasis obliquifasciella/g)).toHaveLength(1);
    expect(html).not.toContain("<i>" + scientific);
    expect(rows([visual])).toContain("<i>Pitta brachyura</i>");
  });
  it("restricts list and export requests to live records, retaining source filters", () => {
    const query = new URLSearchParams(
      fieldArchiveQuery({
        source: "field&source",
        review: "corrected",
        modality: "audio",
        query: "tailerbird",
        offset: 50,
      }),
    );
    expect(query.get("scope")).toBe("live");
    expect(query.get("source_id")).toBe("field&source");
    expect(query.get("q")).toBe("tailerbird");
    expect(query.get("offset")).toBe("50");
    expect(fieldExportUrl()).toBe("/api/evidence/export?scope=live");
    expect(fieldExportUrl("a&b")).toBe(
      "/api/evidence/export?scope=live&source_id=a%26b",
    );
  });

  it("excludes uploaded media even if a malformed mixed response includes it", () => {
    const html = rows([
      visual,
      {
        ...visual,
        event_id: "test",
        source_kind: "file",
        source_filename: "private-test.mp4",
        classification: {
          ...visual.classification,
          display_label: "Test animal",
          common_name: "Test animal",
        },
      },
    ]);
    expect(html).toContain("Indian Pitta");
    expect(html).not.toContain("Test animal");
    expect(html).not.toContain("private-test.mp4");
  });

  it("shows actual local date/time with seconds and accessible UTC, never session elapsed", () => {
    const html = rows([visual]);
    const captured = captureTime(visual.captured_at)!;
    expect(html).toContain(captured.utc);
    expect(html).toContain(captured.date);
    expect(html).toContain(captured.time);
    expect(html).not.toContain("session elapsed");
    expect(html).not.toContain("16:39");
    expect(html).toContain("0.78");
    expect(html).not.toContain("0.782");
  });

  it("keeps unknown capture times explicit instead of interpreting a relative offset as a date", () => {
    expect(
      rows([
        {
          ...visual,
          captured_at: null,
          time_basis: "unknown",
          evidence_summaries: [],
        },
      ]),
    ).toContain("Capture time unavailable");
    expect(captureTime("2026-10-17T08:30:15")).toBeNull();
    expect(captureTime("not-a-date")).toBeNull();
  });

  it("offers modality-specific playback only for ready or partial recordings", () => {
    const html = rows([visual, acoustic]);
    expect(html).toContain("Play video");
    expect(html).toContain("Play audio");
    expect(html).toContain("0.87");
    const pending = rows([
      { ...visual, evidence_summaries: [{ ...clip, status: "pending" }] },
    ]);
    expect(pending).toContain("Saving clip…");
    expect(pending).not.toContain("Play video");
    const missing = rows([
      { ...visual, evidence_summaries: [{ ...clip, status: "failed" }] },
    ]);
    expect(missing).toContain("No saved media");
    expect(missing).not.toContain("Play video");
    const partial = rows([
      { ...visual, evidence_summaries: [{ ...clip, status: "partial" }] },
    ]);
    expect(partial).toContain("Partial clip");
    expect(partial).toContain("Play video");
  });

  it("labels the archive and export as field records", () => {
    const html = renderToStaticMarkup(
      <ObservationArchive revision={0} onInspect={() => {}} />,
    );
    expect(html).toContain('aria-label="Field observations"');
    expect(html).toContain("Date / time");
    expect(html).toContain("Recorded media");
    expect(html).toContain("Export field records");
  });
});

describe("evidence review", () => {
  it("renders the saved clip above the review form and exposes its absolute time", () => {
    const html = renderToStaticMarkup(
      <Inspector
        event={visual}
        taxa={[]}
        onClose={() => {}}
        onSaved={() => {}}
        playEvidence
      />,
    );
    expect(html).toContain('src="/api/evidence/saved-video/media"');
    expect(html).toContain('aria-label="Saved encounter video"');
    expect(html.indexOf("<video")).toBeLessThan(
      html.indexOf('class="review-form"'),
    );
    expect(html).toContain('dateTime="2026-10-17T08:30:15.000Z"');
    expect(html).toContain("Species similarity 0.78");
  });

  it("uses an audio player for acoustic evidence without claiming a camera soundtrack", () => {
    const html = renderToStaticMarkup(
      <EvidencePlayer
        eventId={acoustic.event_id}
        initialEvidence={acoustic.evidence_summaries}
        autoPlay
      />,
    );
    expect(html).toContain("<audio");
    expect(html).not.toContain("<video");
    expect(html).toContain("5.00 s");
    expect(html).toContain("Acoustic clip");
  });

  it("states the legacy media limitation without inventing a playback control", () => {
    const html = renderToStaticMarkup(
      <EvidencePlayer eventId="legacy" initialEvidence={[]} legacy />,
    );
    expect(html).toContain("No media was retained for this older session.");
    expect(html).not.toContain("<video");
    expect(html).not.toContain("<audio");
  });
});
