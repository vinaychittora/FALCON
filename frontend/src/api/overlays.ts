import type { Box, VisualEvent } from "../types";
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

/**
 * Display-only consolidation for current and historical analyses. The
 * observation feed and stored model evidence remain complete and unchanged.
 */
export function selectOverlayEvents(events: VisualEvent[]): VisualEvent[] {
  const ranked = events
    .filter(
      (event) =>
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
): Box[] {
  return (
    selectOverlayEvents(events)
      .map((event): Box => {
        const unknown = unresolved(event);
        return {
          bbox_norm: event.bbox_norm,
          tone: unknown ? "unknown" : "candidate",
          label: unknown
            ? "Unknown organism"
            : displayLabel(event, taxa) +
              (event.detector.score === null
                ? ""
                : " · detector " + event.detector.score.toFixed(2)),
        };
      })
      // Quiet boxes go behind identified animals and their labels.
      .sort(
        (a, b) => Number(a.tone !== "unknown") - Number(b.tone !== "unknown"),
      )
  );
}

export function drawObservationOverlays(
  ctx: CanvasRenderingContext2D,
  boxes: Box[],
  rect: { x: number; y: number; width: number; height: number },
  canvasWidth: number,
) {
  for (const box of boxes) {
    const quiet = box.tone === "unknown";
    const [x1, y1, x2, y2] = box.bbox_norm;
    const x = rect.x + x1 * rect.width;
    const y = rect.y + y1 * rect.height;
    ctx.font = quiet ? "11px system-ui" : "13px system-ui";
    ctx.lineWidth = quiet ? 1 : 2;
    ctx.strokeStyle = quiet ? "rgba(190, 196, 198, 0.55)" : "#b9e77a";
    ctx.strokeRect(x, y, (x2 - x1) * rect.width, (y2 - y1) * rect.height);
    const padding = quiet ? 6 : 8;
    const labelHeight = quiet ? 19 : 24;
    const textWidth = Math.min(
      ctx.measureText(box.label).width + padding * 2,
      canvasWidth - 8,
    );
    const tx = Math.max(0, Math.min(x, canvasWidth - textWidth));
    const ty = Math.max(0, y - labelHeight - 2);
    ctx.fillStyle = quiet ? "rgba(38, 44, 46, 0.55)" : "#18251ee8";
    ctx.fillRect(tx, ty, textWidth, labelHeight);
    ctx.fillStyle = quiet ? "#d8dddf" : "#e3f4ce";
    ctx.fillText(
      box.label,
      tx + padding,
      ty + (quiet ? 13 : 17),
      textWidth - padding * 2,
    );
  }
}
