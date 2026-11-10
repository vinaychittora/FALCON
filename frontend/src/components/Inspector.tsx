import { useEffect, useId, useMemo, useRef, useState } from "react";
import { scientificSubtitle } from "../api/names";
import { certaintyDetail, certaintyOf, leadingName } from "../api/certainty";
import { api } from "../api/client";
import { reviewEncounters } from "../api/encounters";
import { speciesModelName } from "../api/models";
import { captureTime } from "../api/observations";
import { normalizeSearch, rankTaxa } from "../api/search";
import { groupName } from "../api/taxa";
import {
  displayLabel,
  eventTime,
  formatTime,
  predictionLabel,
} from "../api/timeline";
import type { Detection, Review, Video } from "../types";
import type { Taxon } from "../pages/Taxa";
import { SuggestionBars } from "./DetectionCards";
import Icon, { type IconName } from "./Icon";
import ImagePlayer from "./ImagePlayer";
import EvidencePlayer from "./EvidencePlayer";
import ModelEvidence from "./ModelEvidence";
import VideoPlayer from "./VideoPlayer";
import "./review.css";
import { useTaxonNames } from "./TaxonNames";

const reviewOptions: {
  value: Review["status"];
  label: string;
  detail: string;
  key: string;
  icon: IconName;
}[] = [
  {
    value: "correct",
    label: "Confirm",
    detail: "The model's species is correct.",
    key: "C",
    icon: "check",
  },
  {
    value: "corrected",
    label: "Correct",
    detail: "Choose a different species.",
    key: "E",
    icon: "edit",
  },
  {
    value: "unknown",
    label: "Unsure",
    detail: "An animal; the species is unclear.",
    key: "U",
    icon: "question",
  },
  {
    value: "false_positive",
    label: "Not an animal",
    detail: "Wrong detection: leaves, shadow, a person.",
    key: "X",
    icon: "close",
  },
  {
    value: "discarded",
    label: "Discard",
    detail: "Not useful: duplicate, blurred or empty. Never exported.",
    key: "D",
    icon: "trash",
  },
  {
    value: "unreviewed",
    label: "Unreviewed",
    detail: "Leave it for later.",
    key: "R",
    icon: "refresh",
  },
];

/** Key/value facts for the record, in the order a researcher reads them. */
function recordFacts(
  event: Detection,
  encounter?: { encounter_id: string; records: number },
): [string, string][] {
  const facts: [string, string][] = [];
  if (event.modality === "visual") {
    const c = event.classification;
    const [x1, y1, x2, y2] = event.bbox_norm ?? [0, 0, 0, 0];
    facts.push(["Group", groupName(c.broad_group)]);
    const detector = event.detector;
    facts.push([
      "Detector",
      !detector
        ? "—"
        : detector.score === null
          ? "motion proposal"
          : `${detector.score.toFixed(3)} · ${detector.model}`,
    ]);
    const model =
      c.model_evidence?.[0]?.model ?? event.models?.classifier_model;
    facts.push([
      "Similarity",
      `${c.score?.toFixed(3) ?? "—"}${model ? ` · ${speciesModelName(model)}` : ""}`,
    ]);
    if (c.margin !== null && c.margin !== undefined)
      facts.push(["Gap to runner-up", c.margin.toFixed(3)]);
    if (c.genus) facts.push(["Genus", c.genus]);
    facts.push([
      "Box",
      `${Math.round((x2 - x1) * 100)} × ${Math.round((y2 - y1) * 100)} % of frame`,
    ]);
    const track = event.track_id ?? "";
    facts.push([
      "Track",
      track.split("-track-")[1]
        ? `#${track.split("-track-")[1]}`
        : track || "—",
    ]);
    if (encounter) facts.push(["Frames in visit", String(encounter.records)]);
    if (c.unknown_reason) facts.push(["Model note", c.unknown_reason]);
    // Records from before 8 Nov 2026 (no visit id) keep the tiers they were given then.
    facts.push([
      "Rules",
      event.visit_id
        ? "Counted frames (8 Nov 2026 rules)"
        : "Graded by old rules",
    ]);
  } else {
    facts.push([
      "Confidence",
      `${event.confidence.toFixed(3)} · ${event.model}`,
    ]);
    facts.push([
      "Window",
      `${formatTime(event.start_ms)} – ${formatTime(event.end_ms)}`,
    ]);
  }
  if (event.models?.device)
    facts.push(["Device", String(event.models.device).toUpperCase()]);
  const clips = event.evidence_summaries ?? [];
  if (clips.length)
    facts.push([
      "Clips",
      clips.map((clip) => `${clip.media_kind} ${clip.status}`).join(", "),
    ]);
  if (
    event.environment?.status === "fresh" ||
    event.environment?.status === "stale"
  ) {
    const e = event.environment;
    facts.push([
      "Weather",
      [
        e.temperature_c !== null ? `${e.temperature_c.toFixed(1)} °C` : null,
        e.humidity_percent !== null
          ? `${Math.round(e.humidity_percent)} %`
          : null,
        e.pressure_hpa !== null ? `${e.pressure_hpa.toFixed(0)} hPa` : null,
      ]
        .filter(Boolean)
        .join(" · ") + (e.status === "stale" ? " (stale)" : ""),
    ]);
  }
  return facts;
}

export function reviewSpeciesOptions(
  event: Detection,
  taxa: Taxon[],
  selectedId: number,
  search: string,
): { options: Taxon[]; context: "search" | "model" | "selected" | "empty" } {
  if (normalizeSearch(search))
    return { options: rankTaxa(taxa, search).slice(0, 8), context: "search" };
  const byId = new Map(taxa.map((taxon) => [taxon.taxon_id, taxon]));
  const byName = new Map(taxa.map((taxon) => [taxon.scientific_name, taxon]));
  const candidates =
    event.modality === "visual"
      ? [
          ...event.classification.top_k,
          ...(event.classification.model_evidence ?? []).flatMap(
            (model) => model.top_k,
          ),
        ]
      : [{ taxon_id: 0, scientific_name: event.scientific_name }];
  const modelTaxa = candidates.flatMap((candidate) => {
    const local =
      byId.get(candidate.taxon_id) ?? byName.get(candidate.scientific_name);
    return local ? [local] : [];
  });
  const selected = byId.get(selectedId);
  const unique = new Map(
    [...(selected ? [selected] : []), ...modelTaxa].map((taxon) => [
      taxon.taxon_id,
      taxon,
    ]),
  );
  return {
    options: [...unique.values()].slice(0, 8),
    context: modelTaxa.length ? "model" : selected ? "selected" : "empty",
  };
}

export default function Inspector({
  event,
  taxa,
  source,
  onClose,
  onSeek,
  onSaved,
  playEvidence = false,
  encounter,
}: {
  event: Detection;
  taxa: Taxon[];
  source?: Video;
  onClose: () => void;
  onSeek?: (ms: number) => void;
  onSaved: (e: Detection) => void;
  playEvidence?: boolean;
  /** When set, the decision applies to every record of this encounter. */
  encounter?: { encounter_id: string; records: number };
}) {
  const taxonNames = useTaxonNames();
  const dialog = useRef<HTMLDialogElement>(null);
  const matchList = useRef<HTMLUListElement>(null);
  const headingId = useId(),
    listId = useId();
  const [status, setStatus] = useState<Review["status"]>(event.review.status),
    [notes, setNotes] = useState(event.review.notes ?? ""),
    [taxonId, setTaxonId] = useState(event.review.corrected_taxon_id ?? 0),
    [search, setSearch] = useState(""),
    [activeIndex, setActiveIndex] = useState(0),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false),
    [saving, setSaving] = useState(false);
  useEffect(() => {
    const d = dialog.current!;
    d.showModal();
    return () => d.close();
  }, []);
  const speciesOptions = useMemo(
    () => reviewSpeciesOptions(event, taxa, taxonId, search),
    [event, taxa, taxonId, search],
  );
  const available = speciesOptions.options;
  useEffect(() => {
    matchList.current?.children
      .item(activeIndex)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);
  const selectedTaxon = taxa.find((t) => t.taxon_id === taxonId);
  const canConfirm =
    event.modality === "audio" || event.classification.status === "candidate";
  const selectedName =
    selectedTaxon?.common_name ||
    selectedTaxon?.scientific_name ||
    (taxonId === event.review.corrected_taxon_id
      ? event.review.corrected_common_name ||
        event.review.corrected_scientific_name
      : null);
  const sourceMatches = source?.source_id === event.source_id;
  const captured = captureTime(event.captured_at);
  const certainty = certaintyOf(event);
  const detail = certaintyDetail(event);
  const facts = recordFacts(event, encounter);
  function onKey(e: React.KeyboardEvent<HTMLDialogElement>) {
    const target = e.target as HTMLElement;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || saving)
      return;
    const option = reviewOptions.find(
      (item) => item.key.toLowerCase() === e.key.toLowerCase(),
    );
    if (option && !(option.value === "correct" && !canConfirm)) {
      e.preventDefault();
      setStatus(option.value);
      setSaved(false);
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void save();
    }
  }
  const isField = event.source_kind === "live" || !sourceMatches;
  const seek = useMemo(() => ({ ms: eventTime(event), nonce: 0 }), [event]);
  const previewBoxes = (ms: number) =>
    event.modality === "visual" &&
    ms >= event.timestamp_ms &&
    ms < event.timestamp_ms + event.duration_ms
      ? [{ bbox_norm: event.bbox_norm, label: "Selected detection" }]
      : [];
  function chooseTaxon(taxon: Taxon) {
    setTaxonId(taxon.taxon_id);
    setActiveIndex(0);
    setSaved(false);
  }
  async function save() {
    if (status === "corrected" && !taxonId) return;
    setSaving(true);
    setError("");
    try {
      if (encounter) {
        await reviewEncounters([encounter.encounter_id], status, {
          taxonId,
          notes,
        });
        const taxon = taxa.find((item) => item.taxon_id === taxonId);
        onSaved({
          ...event,
          review: {
            status,
            notes: notes.trim() || null,
            corrected_taxon_id: status === "corrected" ? taxonId : null,
            corrected_scientific_name:
              status === "corrected" ? (taxon?.scientific_name ?? null) : null,
            corrected_common_name:
              status === "corrected" ? (taxon?.common_name ?? null) : null,
            updated_at: new Date().toISOString(),
          },
        });
        setSaved(true);
        return;
      }
      const updated = await api<Detection>(
        "/detections/" + event.event_id + "/review",
        {
          method: "POST",
          body: JSON.stringify({
            status,
            notes: notes.trim() || null,
            corrected_taxon_id: status === "corrected" ? taxonId : null,
          }),
        },
      );
      onSaved(updated);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="modal panel observation-review"
      aria-labelledby={headingId}
      onCancel={onClose}
      onKeyDown={onKey}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="panel-heading review-head">
        <div className="review-head-text">
          <p className="review-kicker">
            {event.modality === "audio" ? "Acoustic" : "Visual"} observation ·{" "}
            <span title={event.source_filename}>{event.source_filename}</span> ·{" "}
            {isField ? (
              captured ? (
                <time
                  dateTime={captured.utc}
                  title={captured.utc + " · server receive time"}
                >
                  {captured.date} {captured.time}
                </time>
              ) : (
                "capture time unavailable"
              )
            ) : (
              formatTime(eventTime(event)) + " in the recording"
            )}
          </p>
          <h3
            id={headingId}
            className={certainty ? `certainty-${certainty.level}` : undefined}
          >
            {event.review.status === "unreviewed"
              ? leadingName(event, taxonNames)
              : displayLabel(event, taxonNames)}
            {certainty && (
              <span
                className={`certainty certainty-${certainty.level}`}
                title={certainty.title}
              >
                <i aria-hidden="true" />
                {certainty.label}
              </span>
            )}
          </h3>
          {(detail || event.review.status !== "unreviewed") && (
            <p className="review-subline">
              {event.review.status !== "unreviewed"
                ? `Reviewed: ${event.review.status.replace("_", " ")}${event.review.status === "corrected" ? ` → ${leadingName(event, taxonNames)}` : ""} · model said ${predictionLabel(event).replace(/\s+[—–]\s*candidate$/i, "")}`
                : detail}
            </p>
          )}
        </div>
        <div className="review-head-actions">
          {onSeek && (
            <button
              className="text-button"
              onClick={() => {
                onSeek(eventTime(event));
                onClose();
              }}
            >
              Open in source
            </button>
          )}
          <button onClick={onClose} aria-label="Close observation review">
            <Icon name="close" size={16} />
          </button>
        </div>
      </div>
      <div className="review-grid">
        <section className="review-media" aria-label="Evidence">
          {sourceMatches && source && !isField ? (
            <div
              className="review-preview"
              aria-label="Original source at observation time"
            >
              {source.media_kind === "audio" ? (
                <audio
                  controls
                  preload="metadata"
                  src={`/api/videos/${source.source_id}/file`}
                  onLoadedMetadata={(e) => {
                    e.currentTarget.currentTime = eventTime(event) / 1000;
                  }}
                />
              ) : source.media_kind === "image" ? (
                <ImagePlayer video={source} boxesAt={previewBoxes} show />
              ) : (
                <VideoPlayer
                  video={source}
                  boxesAt={previewBoxes}
                  show
                  onTime={() => {}}
                  seek={seek}
                />
              )}
            </div>
          ) : (
            <EvidencePlayer
              eventId={event.event_id}
              initialEvidence={event.evidence_summaries}
              autoPlay={playEvidence}
              legacy={isField && !captured}
              box={
                event.modality === "visual"
                  ? {
                      bbox: event.bbox_norm,
                      label: leadingName(event, taxonNames),
                      capturedAt: event.captured_at ?? null,
                    }
                  : undefined
              }
            />
          )}
          <dl className="review-facts">
            {facts.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {event.modality === "visual" && (
            <section
              className="review-suggestions-open"
              aria-label="Model suggestions"
            >
              <h4>
                Model suggestions
                <small>similarity, not probability</small>
              </h4>
              {(event.classification.model_evidence?.length ?? 0) > 1 ? (
                <ModelEvidence classification={event.classification} />
              ) : (
                <SuggestionBars event={event} limit={5} />
              )}
            </section>
          )}
        </section>
        <section className="review-side" aria-label="Decision">
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <fieldset className="review-decision-row" disabled={saving}>
            <legend>Decision</legend>
            {reviewOptions.map((option) => (
              <button
                type="button"
                key={option.value}
                className={`decision decision-${option.value}${status === option.value ? " current" : ""}`}
                aria-pressed={status === option.value}
                title={`${option.detail} (${option.key})`}
                disabled={option.value === "correct" && !canConfirm}
                onClick={() => {
                  setStatus(option.value);
                  setSaved(false);
                }}
              >
                <Icon name={option.icon} size={15} />
                <span>{option.label}</span>
                <kbd>{option.key}</kbd>
              </button>
            ))}
          </fieldset>
          <p className="review-decision-hint">
            {reviewOptions.find((option) => option.value === status)?.detail}
            {status === "correct" && !canConfirm
              ? " Confirm needs a named species; use Correct to pick one."
              : ""}
          </p>
          {status === "corrected" && (
            <div className="species-picker">
              <label htmlFor={listId + "-search"}>Species</label>
              <input
                id={listId + "-search"}
                role="combobox"
                aria-label="Search corrected species"
                aria-autocomplete="list"
                aria-expanded={available.length > 0}
                aria-controls={listId}
                aria-activedescendant={
                  available[activeIndex]
                    ? listId + "-" + available[activeIndex].taxon_id
                    : undefined
                }
                aria-describedby={listId + "-help"}
                placeholder="Common or scientific name"
                value={search}
                disabled={saving}
                autoComplete="off"
                autoFocus
                onChange={(e) => {
                  setSearch(e.target.value);
                  setActiveIndex(0);
                }}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    e.preventDefault();
                    setActiveIndex((index) =>
                      Math.max(
                        0,
                        Math.min(
                          available.length - 1,
                          index + (e.key === "ArrowDown" ? 1 : -1),
                        ),
                      ),
                    );
                  } else if (e.key === "Enter" && available[activeIndex]) {
                    e.preventDefault();
                    chooseTaxon(available[activeIndex]);
                  }
                }}
              />
              <small id={listId + "-help"}>
                {speciesOptions.context === "search"
                  ? "Closest matches first. Enter chooses."
                  : speciesOptions.context === "model"
                    ? "The model's alternatives · type to search all species."
                    : speciesOptions.context === "selected"
                      ? "Selected species · type to search all species."
                      : "Type a common or scientific name."}
              </small>
              <ul
                ref={matchList}
                id={listId}
                role="listbox"
                aria-label="Species matches"
                className="species-matches"
              >
                {available.map((taxon, index) => (
                  <li
                    key={taxon.taxon_id}
                    id={listId + "-" + taxon.taxon_id}
                    role="option"
                    aria-selected={taxonId === taxon.taxon_id}
                    className={index === activeIndex ? "keyboard-active" : ""}
                  >
                    <button
                      type="button"
                      disabled={saving}
                      tabIndex={-1}
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => chooseTaxon(taxon)}
                    >
                      <span>
                        <strong>
                          {taxon.common_name || taxon.scientific_name}
                        </strong>
                        {scientificSubtitle(
                          taxon.common_name || taxon.scientific_name,
                          taxon.scientific_name,
                        ) && <em>{taxon.scientific_name}</em>}
                      </span>
                      {taxonId === taxon.taxon_id && (
                        <span className="species-selected-mark">Selected</span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
              {!available.length && speciesOptions.context === "search" && (
                <p className="muted" role="status">
                  No matching species in the local taxonomy.
                </p>
              )}
              <div className="chosen-species" aria-live="polite">
                <span>Selected species</span>
                <strong>{selectedName || "No species selected"}</strong>
                {selectedTaxon &&
                  scientificSubtitle(
                    selectedName || "",
                    selectedTaxon.scientific_name,
                  ) && <em>{selectedTaxon.scientific_name}</em>}
              </div>
            </div>
          )}
          <label className="review-notes">
            <span>
              Notes <small>optional</small>
            </span>
            <textarea
              disabled={saving}
              maxLength={2000}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
                setSaved(false);
              }}
              rows={2}
              placeholder="Field marks, behaviour, doubts"
            />
          </label>
          <div className="review-save-row">
            <span role="status">
              {saved
                ? "Review saved"
                : encounter && encounter.records > 1
                  ? `Applies to all ${encounter.records} frames of this visit · Ctrl+Enter saves`
                  : "Stored next to the model output, never over it · Ctrl+Enter saves"}
            </span>
            <button
              className="primary"
              disabled={saving || (status === "corrected" && !taxonId)}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : "Save review"}
            </button>
          </div>
          <details className="review-raw">
            <summary>Record data</summary>
            <pre className="json-view">{JSON.stringify(event, null, 2)}</pre>
          </details>
        </section>
      </div>
    </dialog>
  );
}
