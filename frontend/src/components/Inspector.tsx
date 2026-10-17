import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { normalizeSearch, rankTaxa } from "../api/search";
import {
  displayLabel,
  eventTime,
  formatTime,
  predictionLabel,
} from "../api/timeline";
import type { Detection, Review, Video } from "../types";
import type { Taxon } from "../pages/Taxa";
import ImagePlayer from "./ImagePlayer";
import ModelEvidence from "./ModelEvidence";
import VideoPlayer from "./VideoPlayer";
import "./review.css";
import { useTaxonNames } from "./TaxonNames";

const reviewOptions: {
  value: Review["status"];
  label: string;
  detail: string;
}[] = [
  {
    value: "correct",
    label: "Confirm identification",
    detail: "The model's species is correct.",
  },
  {
    value: "corrected",
    label: "Correct species",
    detail: "Select a different species.",
  },
  {
    value: "unknown",
    label: "Uncertain",
    detail: "An organism is present; species is unresolved.",
  },
  {
    value: "false_positive",
    label: "Reject detection",
    detail: "No target organism in this detection.",
  },
  {
    value: "unreviewed",
    label: "Unreviewed",
    detail: "Leave this record for later.",
  },
];

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
}: {
  event: Detection;
  taxa: Taxon[];
  source?: Video;
  onClose: () => void;
  onSeek?: (ms: number) => void;
  onSaved: (e: Detection) => void;
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
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="panel-heading">
        <div>
          <p className="review-kicker">Observation review</p>
          <h3 id={headingId}>{displayLabel(event, taxonNames)}</h3>
        </div>
        <button onClick={onClose} aria-label="Close observation review">
          Close
        </button>
      </div>
      <div className="review-context">
        <span title={event.source_filename}>{event.source_filename}</span>
        <span>
          {event.modality === "audio" ? "Acoustic" : "Visual"} ·{" "}
          {formatTime(eventTime(event))}
        </span>
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
      </div>
      {sourceMatches && source ? (
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
        <p className="review-source-note">
          Source media is not available for this record.
        </p>
      )}
      <div className="review-form">
        <div className="review-original">
          <span>Model identification</span>
          <strong>{predictionLabel(event)}</strong>
          <small>
            {event.modality === "visual"
              ? `Species similarity ${event.classification.score?.toFixed(3) ?? "—"} · not a probability`
              : `BirdNET confidence ${event.confidence.toFixed(3)}`}
          </small>
        </div>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <fieldset className="review-decisions" disabled={saving}>
          <legend>Review decision</legend>
          {reviewOptions.map((option) => (
            <label
              key={option.value}
              className={status === option.value ? "selected" : ""}
            >
              <input
                type="radio"
                name={headingId + "-decision"}
                value={option.value}
                checked={status === option.value}
                disabled={option.value === "correct" && !canConfirm}
                onChange={() => {
                  setStatus(option.value);
                  setSaved(false);
                }}
              />
              <span>
                <strong>{option.label}</strong>
                <small>{option.detail}</small>
              </span>
            </label>
          ))}
        </fieldset>
        {status === "corrected" && (
          <div className="species-picker">
            <label htmlFor={listId + "-search"}>Search species</label>
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
                ? "Closest matches appear first. Choose a species to apply it."
                : speciesOptions.context === "model"
                  ? "Model alternatives · type to search all species."
                  : speciesOptions.context === "selected"
                    ? "Selected species · type to search all species."
                    : "Type a common or scientific name to search all species."}
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
                      <em>{taxon.scientific_name}</em>
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
              {selectedTaxon?.common_name && (
                <em>{selectedTaxon.scientific_name}</em>
              )}
            </div>
          </div>
        )}
        <label className="review-notes">
          <span>
            Notes <small>Optional</small>
          </span>
          <textarea
            disabled={saving}
            maxLength={2000}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              setSaved(false);
            }}
            rows={3}
            placeholder="Identification features, uncertainty, or context"
          />
        </label>
        <div className="review-save-row">
          <span role="status">
            {saved
              ? "Review saved"
              : "Review is stored separately from model output."}
          </span>
          <button
            className="primary"
            disabled={saving || (status === "corrected" && !taxonId)}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save review"}
          </button>
        </div>
        {event.modality === "visual" &&
          !!event.classification.model_evidence?.length && (
            <details className="review-suggestions">
              <summary>Model suggestions and scores</summary>
              <ModelEvidence classification={event.classification} />
            </details>
          )}
      </div>
      <details className="review-raw">
        <summary>Record data</summary>
        <pre className="json-view">{JSON.stringify(event, null, 2)}</pre>
      </details>
    </dialog>
  );
}
