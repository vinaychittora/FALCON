import { useMemo, useState } from "react";
import {
  fetchSessions,
  fetchSummary,
  groupLabel,
  REVIEW_POLICIES,
  type ReviewPolicy,
  type SessionRow,
  type Summary,
} from "../api/summary";
import {
  formatDateTime,
  formatDuration,
  fromLocalInput,
  toLocalInput,
} from "../api/format";
import Icon from "../components/Icon";
import { HelpLink } from "./HelpPage";
import { usePoll } from "../hooks/usePoll";
import Pill from "../ui/Pill";

type Period = "24h" | "7d" | "30d" | "all" | "custom";
const PERIODS: [Period, string][] = [
  ["24h", "Last 24 hours"],
  ["7d", "Last 7 days"],
  ["30d", "Last 30 days"],
  ["all", "All time"],
  ["custom", "Custom…"],
];

export function periodBounds(
  period: Period,
  from: string,
  to: string,
  now = new Date(),
) {
  if (period === "custom")
    return {
      captured_from: fromLocalInput(from),
      captured_to: fromLocalInput(to),
    };
  if (period === "all") return { captured_from: null, captured_to: null };
  const hours = { "24h": 24, "7d": 168, "30d": 720 }[period];
  return {
    captured_from: new Date(now.getTime() - hours * 3600_000).toISOString(),
    captured_to: null,
  };
}

function Tile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail?: string;
}) {
  return (
    <div className="summary-tile">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

export function sessionState(row: SessionRow): {
  label: string;
  tone: "live" | "neutral" | "good" | "bad" | "muted";
} {
  if (row.active) return { label: "Observing now", tone: "live" };
  if (row.status === "failed")
    return { label: "Stopped with an error", tone: "bad" };
  if (!row.ended_at) return { label: "No end recorded", tone: "muted" };
  return { label: "Finished", tone: "neutral" };
}

export function SummaryView({
  summary,
  sessions,
  onNavigate,
}: {
  summary: Summary | null;
  sessions: SessionRow[] | null;
  onNavigate: (page: string) => void;
}) {
  const totals = summary?.totals;
  return (
    <>
      {summary && totals ? (
        <>
          <section className="summary-tiles" aria-label="Totals">
            <Tile
              label="Animal visits"
              value={totals.visits.toLocaleString()}
              detail={`${totals.records.toLocaleString()} analyzed frames and sound windows`}
            />
            <Tile
              label="Species"
              value={summary.species_count}
              detail={`${totals.identified.toLocaleString()} visits with a species name`}
            />
            <Tile
              label="Video / sound"
              value={`${totals.visual.toLocaleString()} / ${totals.audio.toLocaleString()}`}
              detail="visits seen by the camera / heard by the microphone"
            />
            <Tile
              label="Reviewed"
              value={totals.reviewed.toLocaleString()}
              detail={`${totals.machine.toLocaleString()} still unreviewed model suggestions`}
            />
            <Tile
              label="Species unclear"
              value={totals.unresolved.toLocaleString()}
              detail={
                summary.groups.length
                  ? summary.groups
                      .map((item) => `${item.visits} ${groupLabel(item.group)}`)
                      .join(" · ")
                  : "none"
              }
            />
          </section>
          <section className="card summary-species" aria-label="Species">
            <div className="card-header">
              <div>
                <h2>Visits per species</h2>
                <p className="muted">{summary.note}</p>
              </div>
            </div>
            {summary.species.length ? (
              <div className="table-wrap">
                <table className="summary-table">
                  <thead>
                    <tr>
                      <th>Species</th>
                      <th className="num">Visits</th>
                      <th className="num">Reviewed</th>
                      <th className="num">Video</th>
                      <th className="num">Sound</th>
                      <th>First seen</th>
                      <th>Last seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.species.map((item) => (
                      <tr key={item.scientific_name}>
                        <td>
                          <strong>
                            {item.common_name ?? item.scientific_name}
                          </strong>
                          {item.common_name && <em>{item.scientific_name}</em>}
                        </td>
                        <td className="num">{item.visits.toLocaleString()}</td>
                        <td className="num">
                          {item.reviewed.toLocaleString()}
                          {item.machine ? (
                            <small>
                              {" "}
                              + {item.machine.toLocaleString()} model
                            </small>
                          ) : null}
                        </td>
                        <td className="num">{item.visual.toLocaleString()}</td>
                        <td className="num">{item.audio.toLocaleString()}</td>
                        <td>{formatDateTime(item.first_seen, false)}</td>
                        <td>{formatDateTime(item.last_seen, false)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No species in this period yet.</p>
            )}
          </section>
        </>
      ) : (
        <p className="muted">Counting…</p>
      )}
      <section
        className="card summary-sessions"
        aria-label="Observation sessions"
      >
        <div className="card-header">
          <div>
            <h2>Observation sessions</h2>
            <p className="muted">
              One row each time a sensor or camera was started and stopped.
              Export a session on its own, or everything from the Export page.
            </p>
          </div>
          <a
            className="button"
            href="/api/evidence/export?scope=live"
            download
            title="Every field record with its review history, for backup"
          >
            <Icon name="download" size={15} /> Complete archive
          </a>
        </div>
        {sessions ? (
          sessions.length ? (
            <div className="table-wrap">
              <table className="summary-table sessions-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Started</th>
                    <th>Stopped</th>
                    <th className="num">Duration</th>
                    <th className="num">Visits</th>
                    <th>Species</th>
                    <th className="num">Clips</th>
                    <th>Export</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((row) => {
                    const state = sessionState(row);
                    return (
                      <tr
                        key={row.session_id}
                        className={row.active ? "active" : ""}
                      >
                        <td>
                          <strong>{row.name}</strong>
                          <Pill tone={state.tone}>{state.label}</Pill>
                          {row.clock_synchronized === false && (
                            <small className="warn">
                              Clock was not synchronized
                            </small>
                          )}
                        </td>
                        <td>{formatDateTime(row.started_at, false)}</td>
                        <td>
                          {row.ended_at
                            ? formatDateTime(row.ended_at, false)
                            : "—"}
                        </td>
                        <td className="num">
                          {row.duration_ms === null
                            ? "—"
                            : formatDuration(row.duration_ms)}
                        </td>
                        <td className="num">
                          {row.visits.toLocaleString()}
                          {row.unresolved ? (
                            <small>{row.unresolved} unclear</small>
                          ) : null}
                        </td>
                        <td>
                          {row.species_count ? (
                            <>
                              <strong>{row.species_count}</strong>
                              <small>
                                {row.species
                                  .slice(0, 3)
                                  .map(
                                    (item) =>
                                      item.common_name ?? item.scientific_name,
                                  )
                                  .join(", ")}
                                {row.species_count > 3 ? ", …" : ""}
                              </small>
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="num">{row.clips.toLocaleString()}</td>
                        <td className="actions">
                          <button
                            className="text-button"
                            onClick={() =>
                              onNavigate(`review?source=${row.source_id}`)
                            }
                          >
                            Review
                          </button>
                          <button
                            className="text-button"
                            onClick={() =>
                              onNavigate(`export?source=${row.source_id}`)
                            }
                          >
                            Camtrap DP
                          </button>
                          <a
                            className="text-button"
                            href={`/api/evidence/export?scope=live&source_id=${row.source_id}`}
                            download
                          >
                            Archive
                          </a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No sessions recorded in this period.</p>
          )
        ) : (
          <p className="muted">Loading sessions…</p>
        )}
      </section>
    </>
  );
}

export default function SummaryPage({
  onNavigate,
}: {
  onNavigate: (page: string) => void;
}) {
  const [period, setPeriod] = useState<Period>("7d");
  const [from, setFrom] = useState(() =>
    toLocalInput(new Date(Date.now() - 7 * 86400_000)),
  );
  const [to, setTo] = useState(() => toLocalInput(new Date()));
  const [review, setReview] = useState<ReviewPolicy>("candidates");
  const [source, setSource] = useState("");
  const bounds = periodBounds(period, from, to);
  const key = JSON.stringify({ period, bounds, review, source });
  const summary = usePoll(
    () => fetchSummary({ ...bounds, review, source_id: source || undefined }),
    30000,
    key,
  );
  const sessions = usePoll(() => fetchSessions(bounds), 30000, key);
  const sessionRows = useMemo(
    () => sessions.data?.sessions ?? null,
    [sessions.data],
  );
  const rows = useMemo(
    () =>
      sessionRows?.filter((row) => !source || row.source_id === source) ?? null,
    [sessionRows, source],
  );
  return (
    <div className="page summary-page">
      <header className="page-header">
        <div>
          <h1>
            Summary <HelpLink slug="user-guide" section="summary" />
          </h1>
          <p>
            How many visits and species were recorded, in a period or per
            observation session. Export any session or the whole archive.
          </p>
        </div>
      </header>
      <section className="card filter-bar" aria-label="Filters">
        <div className="filter">
          <label htmlFor="summary-window">Time</label>
          <select
            id="summary-window"
            value={period}
            onChange={(change) => setPeriod(change.target.value as Period)}
          >
            {PERIODS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        {period === "custom" && (
          <>
            <div className="filter">
              <label htmlFor="summary-from">From</label>
              <input
                id="summary-from"
                type="datetime-local"
                value={from}
                onChange={(change) => setFrom(change.target.value)}
              />
            </div>
            <div className="filter">
              <label htmlFor="summary-to">To</label>
              <input
                id="summary-to"
                type="datetime-local"
                value={to}
                onChange={(change) => setTo(change.target.value)}
              />
            </div>
          </>
        )}
        <div className="filter">
          <label htmlFor="summary-review">Count</label>
          <select
            id="summary-review"
            value={review}
            onChange={(change) =>
              setReview(change.target.value as ReviewPolicy)
            }
            title={
              REVIEW_POLICIES.find((item) => item.value === review)?.detail
            }
          >
            {REVIEW_POLICIES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <div className="filter grow">
          <label htmlFor="summary-source">Session</label>
          <select
            id="summary-source"
            value={source}
            onChange={(change) => setSource(change.target.value)}
          >
            <option value="">All sessions</option>
            {(sessionRows ?? []).map((row) => (
              <option key={row.session_id} value={row.source_id}>
                {row.name} · {formatDateTime(row.started_at, false)}
                {row.active ? " · observing now" : ""}
              </option>
            ))}
          </select>
        </div>
        <button
          className="icon-button"
          onClick={() => {
            summary.refresh();
            sessions.refresh();
          }}
          aria-label="Refresh"
        >
          <Icon name="refresh" size={17} />
        </button>
      </section>
      {(summary.error || sessions.error) && (
        <p className="banner banner-bad" role="alert">
          {summary.error || sessions.error}
        </p>
      )}
      <SummaryView
        summary={summary.data}
        sessions={rows}
        onNavigate={onNavigate}
      />
    </div>
  );
}
