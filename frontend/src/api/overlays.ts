// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import type { Box, VisualEvent } from "../types";
import { leadingName, visualCertainty } from "./certainty";
import { displayLabel } from "./timeline";
import type { TaxonNameIndex } from "./names";

const reviewedIdentification = (event: VisualEvent) =>
  event.review.status === "correct" || event.review.status === "corrected";

function unresolved(event: VisualEvent) {
  if (event.review.status === "unknown") return true;
  if (
    event.review.status === "corrected" &&
    event.review.corrected_scientific_name
  )
    return false;
  return event.classification.status !== "candidate";
}

/** Green for a reviewed or likely species, orange/red for probable/possible, gray otherwise. */
function boxTone(event: VisualEvent): NonNullable<Box["tone"]> {
  if (reviewedIdentification(event)) return "candidate";
  if (event.review.status !== "unreviewed") return "unknown";
  const level = visualCertainty(event);
  return level === "likely"
    ? "candidate"
    : level === "probable" || level === "possible"
      ? level
      : "unknown";
}

/** "Unknown bird" when the group is known, otherwise "Unknown organism". */
function unknownLabel(event: VisualEvent) {
  if (event.review.status === "unknown") return "Unknown organism";
  const label = event.classification.display_label || "";
  return /^Unknown\s/i.test(label) ? label.split(" · ")[0] : "Unknown organism";
}

function geometry(box: Box["bbox_norm"]) {
  const [x1, y1, x2, y2] = box;
  return { width: x2 - x1, height: y2 - y1, area: (x2 - x1) * (y2 - y1) };
}

function overlap(a: Box["bbox_norm"], b: Box["bbox_norm"]) {
  return (
    Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) *
    Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]))
  );
}

function duplicates(a: VisualEvent, b: VisualEvent) {
  const ga = geometry(a.bbox_norm),
    gb = geometry(b.bbox_norm);
  const intersection = overlap(a.bbox_norm, b.bbox_norm);
  return intersection / (ga.area + gb.area - intersection) >= 0.75;
}

function edgeFragment(part: VisualEvent, whole: VisualEvent) {
  const small = geometry(part.bbox_norm),
    large = geometry(whole.bbox_norm);
  if (
    small.area >= large.area * 0.45 ||
    overlap(part.bbox_norm, whole.bbox_norm) / small.area < 0.95
  )
    return false;

  const widthRatio = small.width / large.width;
  const heightRatio = small.height / large.height;
  // Tile-edge fragments span much of one side of the full organism. An
  // interior small box alone is not enough evidence to hide another animal.
  const verticalStrip = widthRatio <= 0.45 && heightRatio >= 0.5;
  const horizontalStrip = heightRatio <= 0.45 && widthRatio >= 0.5;
  const [px1, py1, px2, py2] = part.bbox_norm;
  const [wx1, wy1, wx2, wy2] = whole.bbox_norm;
  const alignedX =
    Math.abs(px1 - wx1) <= large.width * 0.05 ||
    Math.abs(px2 - wx2) <= large.width * 0.05;
  const alignedY =
    Math.abs(py1 - wy1) <= large.height * 0.05 ||
    Math.abs(py2 - wy2) <= large.height * 0.05;
  return (verticalStrip && alignedX) || (horizontalStrip && alignedY);
}

function canSuppress(kept: VisualEvent, event: VisualEvent) {
  if (reviewedIdentification(event)) return false;
  if (unresolved(kept) && !unresolved(event)) return false;
  if (duplicates(kept, event)) return true;
  return (
    (kept.detector.score ?? 0) >= (event.detector.score ?? 0) &&
    edgeFragment(event, kept)
  );
}

/** Nothing useful is known yet: no species, no group, or an unreviewed person/vehicle. */
export function isUnresolved(event: VisualEvent): boolean {
  if (event.review.status !== "unreviewed") return false;
  const { status, broad_group } = event.classification;
  return (
    status === "non_wildlife" ||
    (status === "unknown" && (broad_group || "organism") === "organism")
  );
}

/**
 * Display-only consolidation for current and historical analyses. The
 * observation feed and stored model evidence remain complete and unchanged.
 * Unresolved boxes are left out unless asked for.
 */
export function selectOverlayEvents(
  events: VisualEvent[],
  showUnresolved = true,
): VisualEvent[] {
  const ranked = events
    .filter(
      (event) =>
        (showUnresolved || !isUnresolved(event)) &&
        event.review.status !== "false_positive" &&
        (event.classification.status !== "non_wildlife" ||
          reviewedIdentification(event)) &&
        event.bbox_norm.every(Number.isFinite) &&
        geometry(event.bbox_norm).width > 0 &&
        geometry(event.bbox_norm).height > 0,
    )
    .slice()
    .sort(
      (a, b) =>
        Number(reviewedIdentification(b)) - Number(reviewedIdentification(a)) ||
        Number(unresolved(a)) - Number(unresolved(b)) ||
        (b.detector.score ?? 0) - (a.detector.score ?? 0) ||
        geometry(b.bbox_norm).area - geometry(a.bbox_norm).area,
    );
  const kept: VisualEvent[] = [];
  for (const event of ranked) {
    if (!kept.some((other) => canSuppress(other, event))) kept.push(event);
  }
  return kept;
}

export function observationOverlays(
  events: VisualEvent[],
  taxa?: TaxonNameIndex,
  options: { showUnresolved?: boolean } = {},
): Box[] {
  return (
    selectOverlayEvents(events, options.showUnresolved ?? true)
      .map((event): Box => {
        const tone = boxTone(event);
        return {
          bbox_norm: event.bbox_norm,
          tone,
          // Names only on the picture; the scores live in the side panel.
          label:
            tone === "unknown"
              ? unknownLabel(event)
              : tone === "candidate"
                ? displayLabel(event, taxa)
                : leadingName(event, taxa),
        };
      })
      // Quiet boxes go behind identified animals and their labels.
      .sort(
        (a, b) => Number(a.tone !== "unknown") - Number(b.tone !== "unknown"),
      )
  );
}

/** Green: likely · orange: probable · red: possible · gray: unknown. */
export const BOX_COLORS: Record<NonNullable<Box["tone"]>, string> = {
  candidate: "#b9e77a",
  probable: "#f3b35b",
  possible: "#f08a7e",
  unknown: "rgba(190, 196, 198, 0.55)",
};
const LABEL_COLORS: Record<NonNullable<Box["tone"]>, string> = {
  candidate: "#e3f4ce",
  probable: "#fbe0b5",
  possible: "#f9d2cc",
  unknown: "#d8dddf",
};

/**
 * The drawn box: the detection widened by 25 % of its size (at least 16 px) on every
 * side, so a small bird stays visible inside it, kept in the picture.
 */
export function paddedBox(
  bbox: [number, number, number, number],
  rect: { x: number; y: number; width: number; height: number },
): { x: number; y: number; width: number; height: number } {
  const [x1, y1, x2, y2] = bbox;
  const w = (x2 - x1) * rect.width;
  const h = (y2 - y1) * rect.height;
  const padX = Math.max(0.25 * w, 16);
  const padY = Math.max(0.25 * h, 16);
  const left = Math.max(rect.x, rect.x + x1 * rect.width - padX);
  const top = Math.max(rect.y, rect.y + y1 * rect.height - padY);
  const right = Math.min(rect.x + rect.width, rect.x + x2 * rect.width + padX);
  const bottom = Math.min(rect.y + rect.height, rect.y + y2 * rect.height + padY);
  return { x: left, y: top, width: right - left, height: bottom - top };
}

export function drawObservationOverlays(
  ctx: CanvasRenderingContext2D,
  boxes: Box[],
  rect: { x: number; y: number; width: number; height: number },
  canvasWidth: number,
) {
  for (const box of boxes) {
    const quiet = box.tone === "unknown";
    const drawn = paddedBox(box.bbox_norm, rect);
    const { x, y } = drawn;
    ctx.font = quiet ? "11px system-ui" : "12px system-ui";
    ctx.lineWidth = quiet ? 1 : 2;
    ctx.strokeStyle = BOX_COLORS[box.tone ?? "candidate"];
    ctx.strokeRect(x, y, drawn.width, drawn.height);
    const padding = 5;
    const labelHeight = 17;
    const textWidth = Math.min(
      ctx.measureText(box.label).width + padding * 2,
      canvasWidth - 8,
    );
    const tx = Math.max(0, Math.min(x, canvasWidth - textWidth));
    // The name sits outside the box: above it, or below it at the top edge.
    const above = y - labelHeight - 2;
    const ty = above >= rect.y ? above : y + drawn.height + 2;
    ctx.fillStyle = quiet ? "rgba(38, 44, 46, 0.45)" : "rgba(24, 37, 30, 0.6)";
    ctx.fillRect(tx, ty, textWidth, labelHeight);
    ctx.fillStyle = LABEL_COLORS[box.tone ?? "candidate"];
    ctx.fillText(box.label, tx + padding, ty + 12, textWidth - padding * 2);
  }
}
