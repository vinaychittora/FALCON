import type { Detection } from "../types";

export function captureDate(value: string | null | undefined) {
  if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function captureTime(value: string | null | undefined) {
  const date = captureDate(value);
  if (!date) return null;
  return {
    date: date.toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }),
    time: date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
      hour12: false,
    }),
    utc: date.toISOString(),
  };
}

export function fieldMedia(event: Detection) {
  const kind = event.modality === "visual" ? "video" : "audio";
  const evidence = (event.evidence_summaries ?? []).filter(
    (item) => item.media_kind === kind,
  );
  const available = evidence.find(
    (item) => item.status === "ready" || item.status === "partial",
  );
  const pending = evidence.some((item) => item.status === "pending");
  return {
    kind,
    available,
    label: available
      ? available.status === "partial"
        ? "Partial clip"
        : "Clip available"
      : pending
        ? "Saving clip…"
        : "No saved media",
  };
}

export function fieldArchiveQuery(
  filters: {
    source: string;
    review: string;
    modality: string;
    query: string;
    offset: number;
  },
  limit = 50,
) {
  const params = new URLSearchParams({
    scope: "live",
    limit: String(limit),
    offset: String(filters.offset),
  });
  for (const [key, value] of [
    ["source_id", filters.source],
    ["review_status", filters.review],
    ["modality", filters.modality],
    ["q", filters.query],
  ])
    if (value) params.set(key, value);
  return params.toString();
}

export function fieldExportUrl(source = "") {
  const params = new URLSearchParams({ scope: "live" });
  if (source) params.set("source_id", source);
  return `/api/evidence/export?${params}`;
}
