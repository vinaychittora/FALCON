import { useMemo, useState } from "react";
import {
  displayLabel,
  displayScientificName,
  eventTime,
  formatTime,
} from "../api/timeline";
import { rankObservations } from "../api/search";
import type { ClassifierMode, Detection, Job, Video } from "../types";
import Icon from "./Icon";
import {
  classifierLabels,
  consensusLabel,
  speciesModelName,
} from "../api/models";
import "./review.css";
import { useTaxonNames } from "./TaxonNames";

const reviewLabels = {
  unreviewed: "Unreviewed",
  correct: "Confirmed",
  corrected: "Corrected",
  unknown: "Uncertain",
  false_positive: "Rejected",
};

export default function ObservationHistory({
  events,
  jobs,
  runId,
  video,
  onRun,
  onSeek,
  onInspect,
}: {
  events: Detection[];
  jobs: Job[];
  runId: string;
  video?: Video;
  onRun: (id: string) => void;
  onSeek: (ms: number) => void;
  onInspect: (event: Detection) => void;
}) {
  const taxonNames = useTaxonNames();
  const currentRun = runId || jobs[0]?.job_id || "";
  const [filter, setFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState("");
  const [pagination, setPagination] = useState({
    runId: currentRun,
    offset: 0,
  });
  const filtered = useMemo(
    () =>
      rankObservations(events, filter, taxonNames).filter(
        (event) => !reviewFilter || event.review.status === reviewFilter,
      ),
    [events, filter, reviewFilter, taxonNames],
  );
  const lastPageOffset = Math.floor(Math.max(0, filtered.length - 1) / 20) * 20;
  const offset =
    pagination.runId === currentRun
      ? Math.min(pagination.offset, lastPageOffset)
      : 0;
  const setOffset = (nextOffset: number) =>
    setPagination({ runId: currentRun, offset: nextOffset });
  return (
    <section className="history-section" aria-label="Observation history">
      <div className="section-heading">
        <div>
          <h3>
            Observations <span>{events.length}</span>
          </h3>
          <p className="history-review-count">
            {
              events.filter((event) => event.review.status === "unreviewed")
                .length
            }{" "}
            awaiting review
          </p>
        </div>
        {video && events.length > 0 && (
          <a
            className="download"
            href={`/api/videos/${video.source_id}/log/download`}
          >
            <Icon name="download" size={16} /> Export all source runs
          </a>
        )}
      </div>
      <div className="history-controls">
        <input
          aria-label="Filter detections"
          type="search"
          placeholder="Search species, notes, or review status"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setOffset(0);
          }}
        />
        <label className="run-selector">
          <span>Review</span>
          <select
            value={reviewFilter}
            onChange={(e) => {
              setReviewFilter(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All decisions</option>
            {Object.entries(reviewLabels).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {jobs.length > 0 && (
          <label className="run-selector">
            <span>Analysis</span>
            <select
              value={runId}
              onChange={(e) => {
                onRun(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Latest run</option>
              {jobs.map((job) => {
                const mode = job.metrics.classifier_mode;
                const modelLabel =
                  typeof mode === "string" &&
                  Object.hasOwn(classifierLabels, mode)
                    ? classifierLabels[mode as ClassifierMode]
                    : null;
                return (
                  <option key={job.job_id} value={job.job_id}>
                    {new Date(job.created_at).toLocaleString([], {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    · {modelLabel && `${modelLabel} · `}
                    {job.status}
                    {job.can_resume &&
                      ` · resume from ${formatTime(job.resume_from_ms ?? job.coverage_ms)}`}
                  </option>
                );
              })}
            </select>
          </label>
        )}
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Observation</th>
              <th>Evidence</th>
              <th>Model score</th>
              <th>Review</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(offset, offset + 20).map((event) => (
              <tr key={event.event_id}>
                <td>
                  <button
                    className="time-link"
                    onClick={() => onSeek(eventTime(event))}
                  >
                    {formatTime(eventTime(event))}
                  </button>
                </td>
                <td className="species-cell">
                  {displayLabel(event, taxonNames)}
                  {event.review.status === "unreviewed" &&
                    event.modality === "visual" &&
                    event.classification.status === "unknown" &&
                    event.classification.top_k[0] && (
                      <small>
                        {(event.classification.model_evidence?.length ?? 0) > 1
                          ? `${speciesModelName(event.classification.model_evidence![0].model)} suggests:`
                          : "Closest:"}{" "}
                        {event.classification.top_k[0].common_name ||
                          event.classification.top_k[0].scientific_name}{" "}
                        · uncertain
                      </small>
                    )}
                  {displayScientificName(event, taxonNames) && (
                    <small>
                      <em>{displayScientificName(event, taxonNames)}</em>
                    </small>
                  )}
                  {event.modality === "visual" &&
                    consensusLabel(event.classification) && (
                      <small className="history-consensus">
                        {consensusLabel(event.classification)}
                      </small>
                    )}
                </td>
                <td>
                  <span className={`evidence-label ${event.modality}`}>
                    <Icon
                      name={event.modality === "visual" ? "eye" : "sound"}
                      size={15}
                    />
                    {event.modality === "visual" ? "Visual" : "Acoustic"}
                  </span>
                </td>
                <td>
                  <span className="table-score">
                    {event.modality === "visual"
                      ? (event.classification.score?.toFixed(3) ?? "—")
                      : event.confidence.toFixed(3)}
                  </span>
                  <small className="score-caption">
                    {event.modality === "visual"
                      ? event.classification.model_evidence?.[0]
                        ? `${speciesModelName(event.classification.model_evidence[0].model)} similarity`
                        : "species similarity"
                      : "BirdNET confidence"}
                  </small>
                </td>
                <td>
                  <span className={`review-status ${event.review.status}`}>
                    {reviewLabels[event.review.status]}
                  </span>
                </td>
                <td>
                  <button
                    className="text-button review-button"
                    onClick={() => onInspect(event)}
                  >
                    Review <Icon name="arrow" size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="history-empty">
            <Icon name="leaf" size={25} />
            <p>
              {events.length
                ? "No observations match your search."
                : "No observations in this analysis."}
            </p>
            <span>
              {events.length
                ? "Try a different name or review status."
                : "Run an analysis to create observation records."}
            </span>
          </div>
        )}
      </div>
      <div className="history-footer">
        <span>
          {filtered.length > 0
            ? `${offset + 1}–${Math.min(offset + 20, filtered.length)} of ${filtered.length} observations`
            : "No observations yet"}
        </span>
        <div>
          <button
            className="text-button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 20))}
          >
            Previous
          </button>
          <button
            className="text-button"
            disabled={offset + 20 >= filtered.length}
            onClick={() => setOffset(offset + 20)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
