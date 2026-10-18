import { api } from "./client";

export type ReviewScope = "verified" | "candidates" | "everything";

export interface ExportForm {
  captured_from: string | null;
  captured_to: string | null;
  source_id: string;
  visual: boolean;
  audio: boolean;
  review: ReviewScope;
  min_score: string;
  include_media: boolean;
  include_environment: boolean;
  title: string;
  project_title: string;
  contact_name: string;
  contact_email: string;
  license: "" | "CC0-1.0" | "CC-BY-4.0" | "CC-BY-NC-4.0";
  latitude: string;
  longitude: string;
  coordinate_uncertainty_m: string;
  location_name: string;
}

export interface ExportPreview {
  deployments: number;
  observations: number;
  records: number;
  observation_types: Record<string, number>;
  classification: Record<string, number>;
  species: {
    scientific_name: string;
    common_name: string | null;
    count: number;
  }[];
  media: number;
  media_bytes: number;
  environment_readings: number;
  warnings: string[];
  latitude: number | null;
  longitude: number | null;
}

export const REVIEW_SCOPES: {
  value: ReviewScope;
  label: string;
  detail: string;
}[] = [
  {
    value: "verified",
    label: "Verified only",
    detail: "Confirmed or corrected by a reviewer. Best for publication.",
  },
  {
    value: "candidates",
    label: "Verified + unreviewed",
    detail:
      "Adds machine identifications not yet reviewed (marked as machine).",
  },
  {
    value: "everything",
    label: "Everything except discarded",
    detail:
      "Also unsure and rejected detections (rejected are exported as blank).",
  },
];

export const LICENSES: { value: ExportForm["license"]; label: string }[] = [
  { value: "", label: "No license stated" },
  { value: "CC0-1.0", label: "CC0 1.0 (public domain)" },
  { value: "CC-BY-4.0", label: "CC BY 4.0 (credit required)" },
  { value: "CC-BY-NC-4.0", label: "CC BY-NC 4.0 (non-commercial)" },
];

export function exportParams(
  form: ExportForm,
  forPreview = false,
): URLSearchParams {
  const params = new URLSearchParams();
  const modalities = [form.visual && "visual", form.audio && "audio"]
    .filter(Boolean)
    .join(",");
  params.set("modalities", modalities || "visual,audio");
  params.set("review", form.review);
  params.set("include_media", String(form.include_media));
  params.set("include_environment", String(form.include_environment));
  const optional: [string, string | null][] = [
    ["captured_from", form.captured_from],
    ["captured_to", form.captured_to],
    ["source_id", form.source_id],
    ["min_score", form.min_score.trim()],
    ["latitude", form.latitude.trim()],
    ["longitude", form.longitude.trim()],
  ];
  if (!forPreview)
    optional.push(
      ["title", form.title.trim()],
      ["project_title", form.project_title.trim()],
      ["contact_name", form.contact_name.trim()],
      ["contact_email", form.contact_email.trim()],
      ["license", form.license],
      ["coordinate_uncertainty_m", form.coordinate_uncertainty_m.trim()],
      ["location_name", form.location_name.trim()],
    );
  for (const [key, value] of optional) if (value) params.set(key, value);
  return params;
}

export const fetchExportPreview = (form: ExportForm) =>
  api<ExportPreview>("/exports/preview?" + exportParams(form, true).toString());

export const camtrapDownloadUrl = (form: ExportForm) =>
  "/api/exports/camtrap-dp?" + exportParams(form).toString();

export function missingForCamtrap(form: ExportForm): string[] {
  const missing: string[] = [];
  const latitude = Number(form.latitude),
    longitude = Number(form.longitude);
  if (
    form.latitude.trim() === "" ||
    !Number.isFinite(latitude) ||
    Math.abs(latitude) > 90
  )
    missing.push("site latitude");
  if (
    form.longitude.trim() === "" ||
    !Number.isFinite(longitude) ||
    Math.abs(longitude) > 180
  )
    missing.push("site longitude");
  if (!form.contact_name.trim()) missing.push("contact name");
  if (!form.visual && !form.audio) missing.push("video or sound detections");
  return missing;
}

/** Time-window presets ending now. */
export function presetWindow(
  preset: "24h" | "7d" | "30d" | "all",
  now = new Date(),
) {
  if (preset === "all") return { captured_from: null, captured_to: null };
  const hours = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 }[preset];
  return {
    captured_from: new Date(now.getTime() - hours * 3600 * 1000).toISOString(),
    captured_to: now.toISOString(),
  };
}
