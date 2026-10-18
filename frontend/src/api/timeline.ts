import type { Detection, VisualEvent, AudioEvent } from "../types";
import {
  correctedNames,
  scientificSubtitle,
  type TaxonNameIndex,
} from "./names";
export function currentEvents(events: Detection[], time: number) {
  const visual = events.filter(
    (e): e is VisualEvent =>
      e.modality === "visual" &&
      e.timestamp_ms <= time &&
      time < e.timestamp_ms + e.duration_ms &&
      e.classification.status !== "non_wildlife",
  );
  const audio = events
    .filter(
      (e): e is AudioEvent =>
        e.modality === "audio" && e.start_ms <= time && time < e.end_ms,
    )
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 10);
  return { visual, audio };
}
export const eventTime = (e: Detection) =>
  e.modality === "visual" ? e.timestamp_ms : e.start_ms;
export const predictionLabel = (e: Detection) =>
  e.modality === "visual"
    ? e.classification.display_label
    : e.common_name?.trim() || e.scientific_name;
export const displayLabel = (e: Detection, taxa?: TaxonNameIndex) =>
  e.review.status === "corrected"
    ? (correctedNames(e, taxa).common ??
      correctedNames(e, taxa).scientific ??
      "Corrected identification")
    : e.review.status === "unknown"
      ? "Unknown · reviewed"
      : e.review.status === "false_positive"
        ? "False positive · reviewed"
        : e.review.status === "discarded"
          ? `${predictionLabel(e)} · discarded`
          : predictionLabel(e);

/** Scientific subtitle only when it adds information to the primary label. */
export const displayScientificName = (
  event: Detection,
  taxa?: TaxonNameIndex,
) => {
  if (["unknown", "false_positive"].includes(event.review.status)) return null;
  const scientific =
    event.review.status === "corrected"
      ? correctedNames(event, taxa).scientific
      : event.modality === "visual"
        ? event.classification.scientific_name
        : event.scientific_name;
  return scientificSubtitle(displayLabel(event, taxa), scientific);
};
export function matchesObservation(
  event: Detection,
  query: string,
  taxa?: TaxonNameIndex,
) {
  const names =
    event.modality === "visual"
      ? [
          event.classification.scientific_name,
          ...[
            ...event.classification.top_k,
            ...(event.classification.model_evidence ?? []).flatMap(
              (model) => model.top_k,
            ),
          ].flatMap((candidate) => [
            candidate.common_name,
            candidate.scientific_name,
          ]),
        ]
      : [event.scientific_name, event.common_name];
  return [
    displayLabel(event, taxa),
    event.review.corrected_scientific_name,
    event.modality,
    event.review.status,
    ...names,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(query.trim().toLowerCase());
}
export const formatTime = (ms: number) => {
  // Round the entire timestamp first so 59.96 seconds becomes 01:00.0.
  const tenths = Number.isFinite(ms) ? Math.max(0, Math.round(ms / 100)) : 0;
  return `${Math.floor(tenths / 600)
    .toString()
    .padStart(2, "0")}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
};
