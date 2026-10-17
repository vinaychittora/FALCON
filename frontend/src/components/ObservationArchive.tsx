import { useEffect, useState } from "react";
import { api } from "../api/client";
import {
  captureTime,
  fieldArchiveQuery,
  fieldExportUrl,
  fieldMedia,
} from "../api/observations";
import { displayLabel, displayScientificName } from "../api/timeline";
import type { Detection } from "../types";
import Icon from "./Icon";
import { useTaxonNames } from "./TaxonNames";
import "./evidence.css";

interface ArchivedSource {
  source_id: string;
  source_filename: string;
  count: number;
  started_at?: string | null;
  source_kind?: string;
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

export function FieldObservationRows({
  events,
  onInspect,
}: {
  events: Detection[];
  onInspect: (event: Detection, play?: boolean) => void;
}) {
  const taxonNames = useTaxonNames();
  return events
    .filter((event) => event.source_kind === "live")
    .map((event) => {
      const scientific = displayScientificName(event, taxonNames);
      const score =
        event.modality === "visual"
          ? event.classification.score
          : event.confidence;
      const captured = captureTime(event.captured_at);
      const media = fieldMedia(event);
      return (
        <tr key={event.event_id}>
          <td className="field-capture-time">
            {captured ? (
              <time
                dateTime={captured.utc}
                title={captured.utc + " · server receive time"}
              >
                <span>{captured.date}</span>
                <small>{captured.time}</small>
              </time>
            ) : (
              <span className="muted">Capture time unavailable</span>
            )}
          </td>
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
            <small className="field-device-name">{event.source_filename}</small>
          </td>
          <td>
            <span className={"field-media-kind " + event.modality}>
              <Icon
                name={event.modality === "visual" ? "camera" : "sound"}
                size={17}
              />
              {event.modality === "visual" ? "Video" : "Audio"}
            </span>
            <small
              className={
                "field-media-state " + (media.available ? "available" : "")
              }
            >
              {media.label}
            </small>
          </td>
          <td className="table-score">
            {score == null || !Number.isFinite(score) ? "—" : score.toFixed(2)}
            <small>
              {event.modality === "visual" ? "similarity" : "confidence"}
            </small>
          </td>
          <td>
            <span className={"review-badge " + event.review.status}>
              {statuses.find(([value]) => value === event.review.status)?.[1] ??
                event.review.status}
            </span>
          </td>
          <td className="field-record-action">
            <button
              className={media.available ? "field-play-button" : "subtle"}
              onClick={() => onInspect(event, !!media.available)}
            >
              <Icon name={media.available ? "play" : "arrow"} size={16} />
              {media.available
                ? media.kind === "video"
                  ? "Play video"
                  : "Play audio"
                : "Review"}
            </button>
          </td>
        </tr>
      );
    });
}

export default function ObservationArchive({
  revision,
  onInspect,
}: {
  revision: number;
  onInspect: (event: Detection, play?: boolean) => void;
}) {
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
  }>({
    key: "",
    data: { events: [], total: 0 },
    error: "",
  });
  const requestKey = fieldArchiveQuery(filters, PAGE_SIZE);
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
    api<{ sources: ArchivedSource[] }>("/detections/sources?scope=live")
      .then((data) => {
        if (!stopped)
          setSources(
            data.sources.filter((source) => source.source_kind === "live"),
          );
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
    const timer = setInterval(load, 10000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [requestKey, revision, reload]);
  const loading = snapshot.key !== requestKey;
  const { events, total } = loading ? { events: [], total: 0 } : snapshot.data;
  const fieldEvents = events.filter((event) => event.source_kind === "live");
  const changeFilter = (key: "source" | "review" | "modality", value: string) =>
    setFilters((previous) => ({ ...previous, [key]: value, offset: 0 }));
  return (
    <section
      className="observation-archive field-observations"
      aria-label="Field observations"
    >
      <div className="archive-filters">
        <label className="archive-search">
          Search identifications
          <input
            type="search"
            value={search}
            placeholder="Common or scientific name"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          Device session
          <select
            value={filters.source}
            onChange={(event) => changeFilter("source", event.target.value)}
          >
            <option value="">All device sessions</option>
            {sources.map((source) => {
              const started = captureTime(source.started_at);
              return (
                <option key={source.source_id} value={source.source_id}>
                  {source.source_filename}
                  {started
                    ? " · " + started.date + ", " + started.time
                    : " · time unavailable"}
                </option>
              );
            })}
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
          Media
          <select
            value={filters.modality}
            onChange={(event) => changeFilter("modality", event.target.value)}
          >
            <option value="">Video and audio</option>
            <option value="visual">Video detections</option>
            <option value="audio">Audio detections</option>
          </select>
        </label>
        <button
          className="icon-button"
          onClick={() => setReload((value) => value + 1)}
          aria-label="Refresh field observations"
        >
          <Icon name="refresh" size={18} />
        </button>
      </div>
      <div className="archive-summary">
        <span role="status">
          {loading
            ? "Loading field observations…"
            : total.toLocaleString() + " field records"}
        </span>
        <span className="field-clock-note">
          <Icon name="clock" size={14} /> Local time · server receive clock
        </span>
        <a
          className="evidence-export"
          href={fieldExportUrl(filters.source)}
          download
          title="Field observation data and retained media. Search and review filters do not limit this export."
        >
          <Icon name="download" size={16} /> Export{" "}
          {filters.source ? "device session" : "field records"}
        </a>
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
              <th>Date / time</th>
              <th>Identification</th>
              <th>Recorded media</th>
              <th>Model score</th>
              <th>Review</th>
              <th aria-label="Record action" />
            </tr>
          </thead>
          <tbody>
            <FieldObservationRows events={fieldEvents} onInspect={onInspect} />
          </tbody>
        </table>
        {!loading && !fieldEvents.length && !snapshot.error && (
          <div className="field-empty">
            <Icon name="camera" size={26} />
            <p>
              {filters.query ||
              filters.source ||
              filters.review ||
              filters.modality
                ? "No field observations match these filters."
                : "No field observations yet."}
            </p>
            <span>Live device records and their saved clips appear here.</span>
          </div>
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
