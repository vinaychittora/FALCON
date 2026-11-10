import { useCallback, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import {
  fetchEncounters,
  reviewEncounters,
  STATUS_LABELS,
  type Encounter,
  type EncounterFilters,
} from "../api/encounters";
import { formatDateTime, fromLocalInput, toLocalInput } from "../api/format";
import { hashQuery } from "../api/summary";
import Icon from "../components/Icon";
import { HelpLink } from "./HelpPage";
import { usePoll } from "../hooks/usePoll";
import { usePersistentState } from "../hooks/usePersistentState";
import type { ReviewStatus } from "../types";
import CertaintyLegend from "../ui/CertaintyLegend";
import EncounterCard, { type DecisionHandler } from "../ui/EncounterCard";
import SpeciesPicker from "../ui/SpeciesPicker";
import type { Taxon } from "./Taxa";

type Period = "24h" | "7d" | "30d" | "all" | "custom";
type SourceRow = {
  source_id: string;
  source_filename: string;
  count: number;
  latest_at: string | null;
  source_kind: string;
  started_at: string | null;
};

const PAGE = 48;
const PERIODS: [Period, string][] = [
  ["24h", "Last 24 hours"],
  ["7d", "Last 7 days"],
  ["30d", "Last 30 days"],
  ["all", "All time"],
  ["custom", "Custom…"],
];
const STATUSES: [string, string][] = [
  ["unreviewed", "To review"],
  ["", "All (not discarded)"],
  ["correct", "Confirmed"],
  ["corrected", "Corrected"],
  ["unknown", "Unsure"],
  ["false_positive", "Not an animal"],
  ["discarded", "Discarded"],
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

export default function ReviewPage({
  taxa,
  onOpen,
  revision,
}: {
  taxa: Taxon[];
  onOpen: (encounter: Encounter) => void;
  revision: number;
}) {
  const [period, setPeriod] = useState<Period>(() =>
    typeof window !== "undefined" && hashQuery(window.location.hash, "source")
      ? "all"
      : "7d",
  );
  const [from, setFrom] = useState(() =>
    toLocalInput(new Date(Date.now() - 86400_000)),
  );
  const [to, setTo] = useState(() => toLocalInput(new Date()));
  const [scope, setScope] = useState<"live" | "all">("live");
  // "#/review?source=…" opens one session (from the Summary page).
  const [source, setSource] = useState(() =>
    typeof window === "undefined"
      ? ""
      : hashQuery(window.location.hash, "source"),
  );
  const [showUnresolved, setShowUnresolved] = useState(false);
  const [showGlimpses, setShowGlimpses] = usePersistentState<boolean>(
    "review.glimpses",
    false,
  );
  const [modality, setModality] = useState("");
  const [status, setStatus] = useState("unreviewed");
  const [query, setQuery] = useState("");
  const [minScore, setMinScore] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkPicking, setBulkPicking] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const grid = useRef<HTMLDivElement>(null);
  const bounds = periodBounds(period, from, to);
  const filters: EncounterFilters = {
    scope,
    source_id: source || undefined,
    modality: modality || undefined,
    review_status: status || undefined,
    q: query,
    min_score: minScore === "" ? null : Number(minScore),
    resolved_only: !showUnresolved,
    hide_glimpses: !showGlimpses,
    ...bounds,
    limit: PAGE,
    offset,
  };
  const key = JSON.stringify({
    ...filters,
    captured_from: period === "custom" ? bounds.captured_from : period,
    revision,
  });
  const page = usePoll(() => fetchEncounters(filters), 30000, key);
  const sources = usePoll(
    () => api<{ sources: SourceRow[] }>(`/detections/sources?scope=${scope}`),
    60000,
    scope,
  );
  const encounters = useMemo(() => page.data?.encounters ?? [], [page.data]);
  const total = page.data?.total ?? 0;
  const selectedEncounters = encounters.filter((item) =>
    selected.has(item.encounter_id),
  );

  const changeFilter = useCallback(
    <T,>(setter: (value: T) => void) =>
      (value: T) => {
        setter(value);
        setOffset(0);
        setSelected(new Set());
      },
    [],
  );

  const decide: DecisionHandler = async (encounter, next, taxonId) => {
    await reviewEncounters([encounter.encounter_id], next, { taxonId });
    page.refresh();
  };

  async function bulk(next: ReviewStatus, taxonId?: number) {
    const ids = [...selected];
    if (!ids.length) return;
    setBulkBusy(true);
    setError("");
    try {
      const result = await reviewEncounters(ids, next, { taxonId });
      setNotice(
        `${ids.length} encounter${ids.length === 1 ? "" : "s"} marked ${STATUS_LABELS[next].label.toLowerCase()} (${result.updated} records).`,
      );
      setSelected(new Set());
      setBulkPicking(false);
      page.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBulkBusy(false);
    }
  }

  function select(encounter: Encounter, value: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (value) next.add(encounter.encounter_id);
      else next.delete(encounter.encounter_id);
      return next;
    });
  }

  function moveFocus(event: React.KeyboardEvent<HTMLDivElement>) {
    const key = event.key.toLowerCase();
    if (key !== "j" && key !== "k" && key !== "arrowdown" && key !== "arrowup")
      return;
    const cards = [
      ...(grid.current?.querySelectorAll<HTMLElement>(".encounter-card") ?? []),
    ];
    const index = cards.findIndex((card) => card === document.activeElement);
    const step = key === "j" || key === "arrowdown" ? 1 : -1;
    const next =
      cards[
        Math.max(0, Math.min(cards.length - 1, (index < 0 ? -1 : index) + step))
      ];
    if (next) {
      event.preventDefault();
      next.focus();
      next.scrollIntoView({ block: "nearest" });
    }
  }

  return (
    <div className="page review-page">
      <header className="page-header">
        <div>
          <h1>
            Review <HelpLink slug="user-guide" section="review" />
          </h1>
          <p>
            Check each animal visit once: confirm, correct, mark unsure, reject
            or discard. Discarded visits never reach an export.
          </p>
        </div>
        <div className="header-stat">
          <strong>{page.data ? total.toLocaleString() : "…"}</strong>
          <span>
            {status
              ? STATUSES.find(([value]) => value === status)?.[1].toLowerCase()
              : "encounters"}
            {page.data?.hidden_unresolved
              ? ` · ${page.data.hidden_unresolved.toLocaleString()} unresolved hidden`
              : ""}
            {page.data?.hidden_glimpses
              ? ` · ${page.data.hidden_glimpses.toLocaleString()} glimpses hidden`
              : ""}
          </span>
        </div>
      </header>
      <section className="card filter-bar" aria-label="Filters">
        <div className="filter">
          <label htmlFor="review-window">Time</label>
          <select
            id="review-window"
            value={period}
            onChange={(change) =>
              changeFilter(setPeriod)(change.target.value as Period)
            }
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
              <label htmlFor="review-from">From</label>
              <input
                id="review-from"
                type="datetime-local"
                value={from}
                onChange={(change) =>
                  changeFilter(setFrom)(change.target.value)
                }
              />
            </div>
            <div className="filter">
              <label htmlFor="review-to">To</label>
              <input
                id="review-to"
                type="datetime-local"
                value={to}
                onChange={(change) => changeFilter(setTo)(change.target.value)}
              />
            </div>
          </>
        )}
        <div className="filter">
          <label htmlFor="review-status">Status</label>
          <select
            id="review-status"
            value={status}
            onChange={(change) => changeFilter(setStatus)(change.target.value)}
          >
            {STATUSES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="filter">
          <label htmlFor="review-media">Detections</label>
          <select
            id="review-media"
            value={modality}
            onChange={(change) =>
              changeFilter(setModality)(change.target.value)
            }
          >
            <option value="">Video and sound</option>
            <option value="visual">Video only</option>
            <option value="audio">Sound only</option>
          </select>
        </div>
        <div className="filter grow">
          <label htmlFor="review-search">Species</label>
          <input
            id="review-search"
            type="search"
            placeholder="Common or scientific name"
            value={query}
            onChange={(change) => changeFilter(setQuery)(change.target.value)}
          />
        </div>
        <details className="filter-more">
          <summary>
            <Icon name="filter" size={15} /> More
          </summary>
          <div className="filter-more-body">
            <div className="filter">
              <label htmlFor="review-scope">Recordings</label>
              <select
                id="review-scope"
                value={scope}
                onChange={(change) => {
                  changeFilter(setScope)(change.target.value as "live" | "all");
                  setSource("");
                }}
              >
                <option value="live">Field (live sensors)</option>
                <option value="all">Field and media tests</option>
              </select>
            </div>
            <div className="filter">
              <label htmlFor="review-source">Session</label>
              <select
                id="review-source"
                value={source}
                onChange={(change) =>
                  changeFilter(setSource)(change.target.value)
                }
              >
                <option value="">All sessions</option>
                {(sources.data?.sources ?? []).map((row) => (
                  <option key={row.source_id} value={row.source_id}>
                    {row.source_filename} ·{" "}
                    {formatDateTime(row.started_at ?? row.latest_at, false)} ·{" "}
                    {row.count}
                  </option>
                ))}
              </select>
            </div>
            <label className="filter switch-row">
              <input
                type="checkbox"
                role="switch"
                checked={showUnresolved}
                onChange={(change) =>
                  changeFilter(setShowUnresolved)(change.target.checked)
                }
              />
              <span>Show unresolved (no species, no group)</span>
            </label>
            <label className="filter switch-row">
              <input
                type="checkbox"
                role="switch"
                checked={showGlimpses}
                onChange={(change) =>
                  changeFilter(setShowGlimpses)(change.target.checked)
                }
              />
              <span>Show glimpses (1 frame)</span>
            </label>
            <div className="filter">
              <label htmlFor="review-score">Minimum score</label>
              <input
                id="review-score"
                type="number"
                min={0}
                max={1}
                step={0.05}
                placeholder="any"
                value={minScore}
                onChange={(change) =>
                  changeFilter(setMinScore)(change.target.value)
                }
              />
            </div>
          </div>
        </details>
        <button
          className="icon-button"
          onClick={() => page.refresh()}
          aria-label="Refresh"
        >
          <Icon name="refresh" size={17} />
        </button>
      </section>
      {notice && (
        <p className="banner banner-good" role="status">
          {notice}
          <button
            className="icon-button"
            onClick={() => setNotice("")}
            aria-label="Dismiss"
          >
            <Icon name="close" size={14} />
          </button>
        </p>
      )}
      {(error || page.error) && (
        <p className="banner banner-bad" role="alert">
          {error || page.error}
        </p>
      )}
      <div
        className={`bulk-bar${selected.size ? " visible" : ""}`}
        aria-live="polite"
      >
        <label className="switch-row">
          <input
            type="checkbox"
            checked={
              !!encounters.length &&
              selectedEncounters.length === encounters.length
            }
            onChange={(change) =>
              setSelected(
                change.target.checked
                  ? new Set(encounters.map((item) => item.encounter_id))
                  : new Set(),
              )
            }
          />
          <span>
            {selected.size
              ? `${selected.size} selected`
              : "Select all on this page"}
          </span>
        </label>
        {!!selected.size && (
          <div className="bulk-actions">
            <button disabled={bulkBusy} onClick={() => void bulk("correct")}>
              <Icon name="check" size={15} /> Confirm
            </button>
            <button disabled={bulkBusy} onClick={() => setBulkPicking(true)}>
              <Icon name="edit" size={15} /> Set species…
            </button>
            <button disabled={bulkBusy} onClick={() => void bulk("unknown")}>
              <Icon name="question" size={15} /> Unsure
            </button>
            <button
              disabled={bulkBusy}
              onClick={() => void bulk("false_positive")}
            >
              <Icon name="close" size={15} /> Not an animal
            </button>
            <button
              disabled={bulkBusy}
              className="danger-outline"
              onClick={() => void bulk("discarded")}
            >
              <Icon name="trash" size={15} /> Discard
            </button>
            <button
              disabled={bulkBusy}
              className="text-button"
              onClick={() => void bulk("unreviewed")}
            >
              Reset to “to review”
            </button>
          </div>
        )}
        {bulkPicking && selectedEncounters[0] && (
          <SpeciesPicker
            event={selectedEncounters[0].event}
            taxa={taxa}
            onCancel={() => setBulkPicking(false)}
            onPick={(taxon) => void bulk("corrected", taxon.taxon_id)}
          />
        )}
      </div>
      <CertaintyLegend />
      <p className="feed-help">
        Keyboard: <kbd>J</kbd>/<kbd>K</kbd> move · <kbd>C</kbd> confirm ·{" "}
        <kbd>E</kbd> correct · <kbd>U</kbd> unsure · <kbd>X</kbd> not an animal
        · <kbd>D</kbd> discard · <kbd>Space</kbd> select · <kbd>Enter</kbd>{" "}
        details
      </p>
      <div className="encounter-grid" ref={grid} onKeyDown={moveFocus}>
        {encounters.map((encounter) => (
          <EncounterCard
            key={encounter.encounter_id}
            encounter={encounter}
            taxa={taxa}
            onDecision={decide}
            onOpen={onOpen}
            selected={selected.has(encounter.encounter_id)}
            onSelect={select}
            showDate
          />
        ))}
      </div>
      {page.data && !encounters.length && (
        <section className="card empty-state">
          <Icon name="check" size={32} />
          <h2>
            {status === "unreviewed"
              ? "Nothing left to review here"
              : "No encounters match"}
          </h2>
          <p>Change the time window or filters to see other encounters.</p>
        </section>
      )}
      {total > PAGE && (
        <nav className="pager" aria-label="Pages">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            Previous
          </button>
          <span>
            {offset + 1}–{Math.min(total, offset + PAGE)} of{" "}
            {total.toLocaleString()}
          </span>
          <button
            disabled={offset + PAGE >= total}
            onClick={() => setOffset(offset + PAGE)}
          >
            Next
          </button>
        </nav>
      )}
    </div>
  );
}
