import { useEffect, useState } from "react";
import { api } from "../api/client";
import {
  displayLabel,
  displayScientificName,
  eventTime,
  formatTime,
} from "../api/timeline";
import type { Detection, Video } from "../types";
import Icon from "./Icon";
import { useTaxonNames } from "./TaxonNames";

interface ArchivedSource {
  source_id: string;
  source_filename: string;
  modalities: string[];
  count: number;
  latest_at: string;
  job_ids: string[];
}
interface ArchivePage {
  events: Detection[];
  total: number;
}
const PAGE_SIZE = 50;
const statuses = [
  ["", "All review states"],
  ["unreviewed", "Unreviewed"],
  ["correct", "Confirmed"],
  ["corrected", "Corrected"],
  ["unknown", "Unresolved"],
  ["false_positive", "Rejected"],
];

export default function ObservationArchive({
  videos,
  revision,
  onInspect,
  onSource,
}: {
  videos: Video[];
  revision: number;
  onInspect: (event: Detection) => void;
  onSource: (sourceId: string, event: Detection) => void;
}) {
  const taxonNames = useTaxonNames();
  const [sources, setSources] = useState<ArchivedSource[]>([]);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({
    source: "",
    review: "",
    modality: "",
    query: "",
    offset: 0,
  });
  const [reload, setReload] = useState(0);
  const [snapshot, setSnapshot] = useState<{
    key: string;
    data: ArchivePage;
    error: string;
  }>({ key: "", data: { events: [], total: 0 }, error: "" });
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(filters.offset),
  });
  if (filters.source) params.set("source_id", filters.source);
  if (filters.review) params.set("review_status", filters.review);
  if (filters.modality) params.set("modality", filters.modality);
  if (filters.query) params.set("q", filters.query);
  const requestKey = params.toString();
  useEffect(() => {
    const timer = setTimeout(
      () =>
        setFilters((previous) => ({
          ...previous,
          query: search.trim(),
          offset: 0,
        })),
      250,
    );
    return () => clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    let stopped = false;
    api<{ sources: ArchivedSource[] }>("/detections/sources")
      .then((data) => {
        if (!stopped) setSources(data.sources);
      })
      .catch(() => {});
    return () => {
      stopped = true;
    };
  }, [revision, reload]);
  useEffect(() => {
    let stopped = false;
    const load = () => {
      api<ArchivePage>("/detections?" + requestKey)
        .then((data) => {
          if (!stopped) setSnapshot({ key: requestKey, data, error: "" });
        })
        .catch((error) => {
          if (!stopped)
            setSnapshot({
              key: requestKey,
              data: { events: [], total: 0 },
              error: error instanceof Error ? error.message : String(error),
            });
        });
    };
    load();
    const timer = setInterval(load, 30000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [requestKey, revision, reload]);
  const loading = snapshot.key !== requestKey;
  const { events, total } = loading ? { events: [], total: 0 } : snapshot.data;
  const changeFilter = (key: "source" | "review" | "modality", value: string) =>
    setFilters((previous) => ({ ...previous, [key]: value, offset: 0 }));
  return (
    <section
      className="observation-archive"
      aria-label="Saved observation archive"
    >
      <div className="archive-filters">
        <label className="archive-search">
          Search all observations
          <input
            type="search"
            value={search}
            placeholder="Species, scientific name or source…"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          Source
          <select
            value={filters.source}
            onChange={(event) => changeFilter("source", event.target.value)}
          >
            <option value="">All sources</option>
            {sources.map((source) => (
              <option key={source.source_id} value={source.source_id}>
                {source.source_filename} · {source.count.toLocaleString()}
              </option>
            ))}
          </select>
        </label>
        <label>
          Review
          <select
            value={filters.review}
            onChange={(event) => changeFilter("review", event.target.value)}
          >
            {statuses.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Evidence
          <select
            value={filters.modality}
            onChange={(event) => changeFilter("modality", event.target.value)}
          >
            <option value="">All evidence</option>
            <option value="visual">Visual</option>
            <option value="audio">Acoustic</option>
          </select>
        </label>
        <button
          className="icon-button"
          onClick={() => setReload((value) => value + 1)}
          aria-label="Refresh observation archive"
        >
          <Icon name="refresh" size={18} />
        </button>
      </div>
      <div className="archive-summary" role="status">
        <span>
          {loading
            ? "Loading observations…"
            : total.toLocaleString() + " matching records"}
        </span>
        <span>
          {filters.query
            ? "Closest matches first · includes alternative candidates"
            : "Most recently saved first"}
        </span>
      </div>
      {snapshot.key === requestKey && snapshot.error && (
        <p className="error" role="alert">
          {snapshot.error}
        </p>
      )}
      <div className="table-scroll archive-table">
        <table>
          <thead>
            <tr>
              <th>Observation</th>
              <th>Source / position</th>
              <th>Evidence</th>
              <th>Score</th>
              <th>Review</th>
              <th aria-label="Record action" />
            </tr>
          </thead>
          <tbody>
            {events.map((event) => {
              const source = videos.find(
                (item) => item.source_id === event.source_id,
              );
              const scientific = displayScientificName(event, taxonNames);
              const score =
                event.modality === "visual"
                  ? event.classification.score
                  : event.confidence;
              return (
                <tr key={event.event_id}>
                  <td className="species-cell">
                    <button
                      className="source-name-button"
                      onClick={() => onInspect(event)}
                    >
                      {displayLabel(event, taxonNames)}
                    </button>
                    {scientific && (
                      <small>
                        <i>{scientific}</i>
                      </small>
                    )}
                  </td>
                  <td className="archive-source-cell">
                    {source ? (
                      <button
                        className="source-name-button"
                        onClick={() => onSource(event.source_id, event)}
                      >
                        {event.source_filename}
                      </button>
                    ) : (
                      <span>{event.source_filename}</span>
                    )}
                    <small>
                      {formatTime(eventTime(event))} ·{" "}
                      {source ? "media time" : "session elapsed"}
                    </small>
                  </td>
                  <td>
                    <span className={"evidence-label " + event.modality}>
                      <Icon
                        name={event.modality === "visual" ? "eye" : "sound"}
                        size={15}
                      />
                      {event.modality === "visual" ? "Visual" : "Acoustic"}
                    </span>
                  </td>
                  <td className="table-score">
                    {score === null ? "—" : score.toFixed(3)}
                    <small>
                      {event.modality === "visual"
                        ? "similarity"
                        : "confidence"}
                    </small>
                  </td>
                  <td>
                    <span className={"review-badge " + event.review.status}>
                      {statuses.find(
                        ([value]) => value === event.review.status,
                      )?.[1] ?? event.review.status}
                    </span>
                  </td>
                  <td>
                    <button className="subtle" onClick={() => onInspect(event)}>
                      Review <Icon name="arrow" size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!loading && !events.length && !snapshot.error && (
          <p className="empty-text">No observations match these filters.</p>
        )}
      </div>
      <div className="history-footer">
        <span>
          {total ? filters.offset + 1 : 0}–
          {Math.min(filters.offset + PAGE_SIZE, total)} of{" "}
          {total.toLocaleString()}
        </span>
        <div>
          <button
            disabled={loading || filters.offset === 0}
            onClick={() =>
              setFilters((previous) => ({
                ...previous,
                offset: Math.max(0, previous.offset - PAGE_SIZE),
              }))
            }
          >
            Previous
          </button>
          <button
            disabled={loading || filters.offset + PAGE_SIZE >= total}
            onClick={() =>
              setFilters((previous) => ({
                ...previous,
                offset: previous.offset + PAGE_SIZE,
              }))
            }
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
