import { describe, expect, it, vi } from "vitest";
import type { Box, VisualEvent } from "../types";
import {
  drawObservationOverlays,
  observationOverlays,
  selectOverlayEvents,
} from "./overlays";

function event(
  id: string,
  bbox: Box["bbox_norm"],
  score: number,
  name = "Montagu's Harrier",
): VisualEvent {
  return {
    modality: "visual",
    event_id: id,
    bbox_norm: bbox,
    detector: { score },
    classification: {
      status: "candidate",
      display_label: name + " — candidate",
      scientific_name: "Circus pygargus",
      common_name: name,
      top_k: [{ common_name: name, score: 0.7 }],
    },
    review: { status: "unreviewed" },
  } as VisualEvent;
}

const harrier = () =>
  event(
    "whole",
    [0.171875, 0.4736111111111111, 0.52265625, 0.8284722222222223],
    0.9326171875,
  );
const head = () =>
  event(
    "head",
    [0.4375, 0.46953125, 0.523248291015625, 0.743359375],
    0.67041015625,
  );

describe("observation overlay selection", () => {
  it("keeps one full Montagu's Harrier box despite a slightly protruding head fragment", () => {
    const full = harrier();
    const ground = event(
      "ground",
      [0.00078125, 0.8027777777777778, 1, 0.9986111111111111],
      0.54541015625,
    );
    ground.classification.status = "unknown";
    const inputs = [head(), ground, full];
    const before = structuredClone(inputs);
    expect(selectOverlayEvents(inputs).map((e) => e.event_id)).toEqual([
      "whole",
      "ground",
    ]);
    expect(inputs).toEqual(before);
  });

  it("hides the false gecko fragment nested in the full peregrine without editing its record", () => {
    const falcon = event(
      "falcon",
      [0.1593017578125, 0.1779296875, 0.503173828125, 1],
      0.91943359375,
      "Peregrine Falcon",
    );
    const gecko = event(
      "gecko",
      [0.43760986328125, 0.1736328125, 0.5025390625, 0.98671875],
      0.82080078125,
      "Common Leopard Gecko",
    );
    expect(selectOverlayEvents([gecko, falcon])).toEqual([falcon]);
    expect(gecko.classification.display_label).toBe(
      "Common Leopard Gecko — candidate",
    );
  });

  it("preserves all adjacent flamingos and the separate unknown strip", () => {
    const boxes: Box["bbox_norm"][] = [
      [0.26279296875, 0.4359375, 0.46669921875, 0.8734375],
      [0.452197265625, 0.3673828125, 0.5625, 0.8875],
      [0.0718505859375, 0.46171875, 0.3131103515625, 0.884375],
      [0.767626953125, 0.3900390625, 0.78125, 0.696875],
    ];
    const events = boxes.map((box, i) =>
      event(
        String(i),
        box,
        [0.85888671875, 0.436767578125, 0.31201171875, 0.352294921875][i],
        "Lesser Flamingo",
      ),
    );
    events[3].classification.status = "unknown";
    expect(selectOverlayEvents(events)).toHaveLength(4);
  });

  it("consolidates high-IoU duplicate predictions without removing a nearby bird", () => {
    const full = event("full", [0.1, 0.2, 0.5, 0.8], 0.9);
    const duplicate = event("duplicate", [0.11, 0.21, 0.49, 0.79], 0.8);
    const neighbor = event("neighbor", [0.42, 0.2, 0.7, 0.8], 0.8);
    expect(
      selectOverlayEvents([neighbor, duplicate, full]).map((e) => e.event_id),
    ).toEqual(["full", "neighbor"]);
  });

  it("does not hide an interior small organism or let an unknown background hide a bird", () => {
    const background = event("background", [0, 0, 1, 1], 0.99);
    background.classification.status = "unknown";
    const full = event("bird", [0.1, 0.1, 0.9, 0.9], 0.9);
    const small = event("interior", [0.4, 0.4, 0.55, 0.55], 0.7);
    expect(selectOverlayEvents([background, full, small])).toHaveLength(3);
  });

  it.each(["correct", "corrected"] as const)(
    "protects a %s identification even inside a larger box",
    (status) => {
      const fragment = head();
      fragment.review.status = status;
      fragment.review.corrected_scientific_name = "Circus pygargus";
      expect(selectOverlayEvents([harrier(), fragment])).toHaveLength(2);
    },
  );

  it("renders every unresolved or reviewed-unknown prediction with only the quiet unknown label", () => {
    const unknown = event("unknown", [0.1, 0.1, 0.2, 0.3], 0.5);
    unknown.classification.status = "unknown";
    unknown.classification.display_label =
      "Unknown bird · closest match: harrier";
    const reviewedUnknown = event("reviewed", [0.7, 0.1, 0.9, 0.3], 0.9);
    reviewedUnknown.review.status = "unknown";
    expect(observationOverlays([unknown, reviewedUnknown])).toEqual([
      {
        bbox_norm: reviewedUnknown.bbox_norm,
        tone: "unknown",
        label: "Unknown organism",
      },
      {
        bbox_norm: unknown.bbox_norm,
        tone: "unknown",
        label: "Unknown organism",
      },
    ]);
  });

  it("hides false positives and retains the corrected name and candidate score", () => {
    const falsePositive = harrier();
    falsePositive.review.status = "false_positive";
    const corrected = head();
    corrected.review.status = "corrected";
    corrected.review.corrected_scientific_name = "Circus macrourus";
    expect(observationOverlays([falsePositive, corrected])).toEqual([
      {
        bbox_norm: corrected.bbox_norm,
        tone: "candidate",
        label: "Circus macrourus · detector 0.67",
      },
    ]);
  });
});

it("draws unresolved overlays as thinner, smaller neutral annotations than identified ones", () => {
  const strokes: { color: string; width: number }[] = [];
  const labels: { text: string; font: string }[] = [];
  const context = {
    lineWidth: 0,
    strokeStyle: "",
    font: "",
    fillStyle: "",
    measureText: (text: string) => ({ width: text.length * 5 }),
    strokeRect() {
      strokes.push({ color: this.strokeStyle, width: this.lineWidth });
    },
    fillRect: vi.fn(),
    fillText(text: string) {
      labels.push({ text, font: this.font });
    },
  };
  const unknown = harrier();
  unknown.review.status = "unknown";
  const known = event("other", [0.7, 0.2, 0.9, 0.7], 0.9);
  drawObservationOverlays(
    context as unknown as CanvasRenderingContext2D,
    observationOverlays([unknown, known]),
    { x: 0, y: 0, width: 800, height: 450 },
    800,
  );
  expect(strokes).toEqual([
    { color: "rgba(190, 196, 198, 0.55)", width: 1 },
    { color: "#b9e77a", width: 2 },
  ]);
  expect(labels[0]).toEqual({
    text: "Unknown organism",
    font: "11px system-ui",
  });
  expect(labels[1].font).toBe("13px system-ui");
});
