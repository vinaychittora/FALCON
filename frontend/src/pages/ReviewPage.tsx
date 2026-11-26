// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { unidentifiedSound } from "../api/certainty";
import {
  fetchAllEncounters,
  fetchEncounters,
  reviewEncounters,
  reviewInBatches,
  STATUS_FILTERS,
  type Encounter,
  type EncounterFilters,
  withDecision,
} from "../api/encounters";
import {
  beforeReviews,
  bulkMessage,
  filterCaption,
  HIDDEN_CLEAR_NOTE,
  showRecordsLabel,
  statusOptionLabel,
  waitingLine,
  toReviewFilters,
  undoGroups,
  type BeforeReview,
} from "../api/reviewList";
import { formatDateTime, fromLocalInput, toLocalInput } from "../api/format";
import { hashQuery } from "../api/summary";
import Icon from "../components/Icon";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { usePoll } from "../hooks/usePoll";
import { usePersistentState } from "../hooks/usePersistentState";
import type { ReviewStatus } from "../types";
import CertaintyLegend from "../ui/CertaintyLegend";
import { type DecisionHandler } from "../ui/EncounterCard";
import StayCard from "../ui/StayCard";
import { groupStays } from "../api/stays";
import SpeciesChooser from "../ui/SpeciesChooser";
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
const STATUSES = STATUS_FILTERS;

/** Cards decided in this view stay where they were (with their note row) until the
 * filters change, even when the refreshed list no longer contains them. */
export function keepDecided(
  fresh: Encounter[],
  kept: Map<string, { index: number; encounter: Encounter }>,
): Encounter[] {
  const result = [...fresh];
  const present = new Set(fresh.map((item) => item.encounter_id));
  [...kept.values()]
    .filter((item) => !present.has(item.encounter.encounter_id))
    .sort((a, b) => a.index - b.index)
    .forEach((item) =>
      result.splice(Math.min(item.index, result.length), 0, item.encounter),
    );
  // The fresh answer decides the stay of a row that is still listed (new visits and kinds
  // can change it); a row that left the list keeps its place until the next load.
  return result.map((item) => {
    const decided = kept.get(item.encounter_id)?.encounter;
    if (!decided || decided === item) return decided ?? item;
    return { ...decided, stay_id: item.stay_id, attached: item.attached, stay_recordings: item.stay_recordings };
  });
}

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
  onCounts,
}: {
  taxa: Taxon[];
  onOpen: (encounter: Encounter, queue?: Encounter[], pool?: Encounter[]) => void;
  revision: number;
  /** Review's counts changed: the navigation badge counts again. */
  onCounts?: () => void;
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
  // One switch for everything FALCON hides: unresolved pictures and 1-frame glimpses.
  const [showHidden, setShowHidden] = usePersistentState<boolean>(
    "review.hidden",
    false,
  );
  // Only unreviewed pictures the model gave no species, hidden ones included. Not
  // remembered across reloads, like Status: a forgotten narrowing would hide records.
  const [unidentified, setUnidentified] = useState(false);
  const [modality, setModality] = useState("");
  const [status, setStatus] = useState("unreviewed");
  const [query, setQuery] = useState("");
  const [minScore, setMinScore] = useState("");
  // What is being typed; the list follows 400 ms after the last change (Enter at once), so
  // one list call and one set of counts go out per settled value, not one per letter.
  const [queryText, setQueryText] = useState("");
  const [scoreText, setScoreText] = useState("");
  const settle = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkPicking, setBulkPicking] = useState(false);
  // "Select all M in this list": the bulk buttons act on every page of the list.
  const [wholeList, setWholeList] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const grid = useRef<HTMLUListElement>(null);
  const bounds = periodBounds(period, from, to);
  // Status "Hidden": only what FALCON hid; the two switches mean nothing then.
  const hiddenStatus = status === "hidden";
  const baseFilters: EncounterFilters = {
    scope,
    source_id: source || undefined,
    modality: modality || undefined,
    review_status: hiddenStatus ? "unreviewed" : status || undefined,
    q: query,
    min_score: minScore === "" ? null : Number(minScore),
    resolved_only: !showHidden,
    hide_glimpses: !showHidden,
    unidentified: unidentified || undefined,
    include_discarded: status === "",
    ...bounds,
    limit: PAGE,
    offset,
  };
  const filters: EncounterFilters = hiddenStatus
    ? {
        ...baseFilters,
        hidden_only: true,
        resolved_only: false,
        hide_glimpses: false,
        unidentified: undefined,
      }
    : baseFilters;
  const key = JSON.stringify({
    ...filters,
    captured_from: period === "custom" ? bounds.captured_from : period,
    revision,
  });
  // The list itself comes by stay (shared footage); every count and Select all stay in visits.
  // A changed filter cancels the requests of the old one (usePoll); while the list for
  // the new filters is on its way the old cards are dimmed and marked as loading.
  const page = usePoll(
    (signal) => fetchEncounters({ ...filters, group: "stay" }, signal),
    30000,
    key,
  );
  const listLoading = !page.fresh;
  // How many the switch would add: the same filters with nothing hidden, count only.
  const everything = usePoll(
    (signal) =>
      fetchEncounters(
        {
          ...baseFilters,
          resolved_only: false,
          hide_glimpses: false,
          limit: 1,
          offset: 0,
        },
        signal,
      ),
    60000,
    `${key}-all`,
  );
  // The default list (nothing hidden shown), so Show hidden (N) keeps its number when on.
  const shown = usePoll(
    (signal) =>
      fetchEncounters(
        {
          ...baseFilters,
          resolved_only: true,
          hide_glimpses: true,
          limit: 1,
          offset: 0,
        },
        signal,
      ),
    60000,
    `${key}-shown`,
  );
  // Counts are shown only when they belong to the filters now set, like the list.
  const hiddenCount =
    shown.data && everything.data && shown.fresh && everything.fresh && !hiddenStatus
      ? Math.max(0, everything.data.total - shown.data.total)
      : null;
  const reviewFilters = toReviewFilters({ ...baseFilters, limit: 1 });
  const toReview = usePoll(
    (signal) => fetchEncounters({ ...reviewFilters, limit: 1, offset: 0 }, signal),
    30000,
    `${key}-to-review`,
  );
  // Each status option shows its count under the other filters now set, over all pages.
  const statusCounts = usePoll(
    (signal) =>
      Promise.all(
        STATUSES.map(([value]) =>
          value === "unreviewed"
            ? Promise.resolve(null)
            : fetchEncounters(
                {
                  ...baseFilters,
                  review_status: value === "hidden" ? "unreviewed" : value || undefined,
                  hidden_only: value === "hidden" || undefined,
                  include_discarded: value === "",
                  limit: 1,
                  offset: 0,
                },
                signal,
              ).then((result) => result.total),
        ),
      ),
    30000,
    `${key}-counts`,
  );
  const toReviewCount = toReview.fresh ? (toReview.data?.total ?? null) : null;
  const countFor = (value: string, index: number) =>
    value === "unreviewed"
      ? toReviewCount
      : statusCounts.fresh
        ? (statusCounts.data?.[index] ?? null)
        : null;
  const [openingQueue, setOpeningQueue] = useState(false);
  async function openReviewQueue() {
    setOpeningQueue(true);
    setError("");
    try {
      const queue: Encounter[] = [];
      let expected = Infinity;
      while (queue.length < expected) {
        const next = await fetchEncounters({
          ...reviewFilters,
          limit: 200,
          offset: queue.length,
        });
        expected = next.total;
        queue.push(...next.encounters);
        if (!next.encounters.length) break;
      }
      if (queue[0]) onOpen(queue[0], queue);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setOpeningQueue(false);
    }
  }
  const sources = usePoll(
    () => api<{ sources: SourceRow[] }>(`/detections/sources?scope=${scope}`),
    60000,
    scope,
  );
  const [kept, setKept] = useState<
    Map<string, { index: number; encounter: Encounter }>
  >(new Map());
  const encounters = useMemo(
    () => keepDecided(page.data?.encounters ?? [], kept),
    [page.data, kept],
  );
  const total = page.data?.total ?? 0;
  const selectedEncounters = encounters.filter((item) =>
    selected.has(item.encounter_id),
  );
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [bulkDone, setBulkDone] = useState<{
    message: string;
    before: Map<string, BeforeReview>;
    whole: boolean;
  } | null>(null);
  const bulkUndo = useRef<HTMLButtonElement>(null);
  const foot = useRef<HTMLElement>(null);
  useEffect(() => {
    if (bulkDone) bulkUndo.current?.focus();
  }, [bulkDone]);
  useEffect(() => {
    const element = foot.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new ResizeObserver(() =>
      root.style.setProperty("--foot", `${element.offsetHeight}px`),
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--foot");
    };
  }, []);

  const changeFilter = useCallback(
    <T,>(setter: (value: T) => void) =>
      (value: T) => {
        setter(value);
        setOffset(0);
        setSelected(new Set());
        setWholeList(false);
        setKept(new Map());
        setBulkDone(null);
      },
    [],
  );

  /** Apply the typed species and score now, or 400 ms after the last change. */
  function applyTyped(nextQuery: string, nextScore: string, now = false) {
    clearTimeout(settle.current);
    const apply = () => {
      if (nextQuery !== query) changeFilter(setQuery)(nextQuery);
      if (nextScore !== minScore) changeFilter(setMinScore)(nextScore);
    };
    if (now) apply();
    else settle.current = setTimeout(apply, 400);
  }
  useEffect(() => () => clearTimeout(settle.current), []);
  // Narrow layout: Filters is a panel that pushes the list down (from 1200 px the fields
  // sit in a row above the list and nothing changes).
  const narrow = useMediaQuery("(max-width: 1199.98px)");
  const listTop = useRef<HTMLDivElement>(null);
  /** "Show N records": close the panel and bring the top of the list into view. */
  function showList() {
    setFiltersOpen(false);
    window.requestAnimationFrame(() =>
      listTop.current?.scrollIntoView({ block: "start", behavior: "smooth" }),
    );
  }

  function refreshAll() {
    page.refresh();
    toReview.refresh();
    statusCounts.refresh();
    onCounts?.();
  }

  function keep(updates: { encounter: Encounter; next: Encounter }[]) {
    setKept((current) => {
      const map = new Map(current);
      for (const { encounter, next } of updates) {
        const index = encounters.findIndex(
          (item) => item.encounter_id === encounter.encounter_id,
        );
        map.set(encounter.encounter_id, {
          index: index < 0 ? (current.get(encounter.encounter_id)?.index ?? 0) : index,
          encounter: next,
        });
      }
      return map;
    });
  }

  const decide: DecisionHandler = async (encounter, next, taxonId, notes) => {
    await reviewEncounters([encounter.encounter_id], next, { taxonId, notes });
    keep([{ encounter, next: withDecision(encounter, next, { taxonId, notes, taxa }) }]);
    toReview.refresh();
    statusCounts.refresh();
    onCounts?.();
  };

  async function bulk(next: ReviewStatus, taxonId?: number, name?: string) {
    const whole = wholeList;
    if (!whole && !selectedEncounters.length) return;
    setBulkBusy(true);
    setError("");
    let chosen: Encounter[] = [];
    let saved = 0;
    try {
      // The whole list is read first, then decided, so pages shifting under the
      // decision change nothing.
      setProgress(whole ? `Reading ${total.toLocaleString()} records…` : "");
      const picked = whole
        ? await fetchAllEncounters({ ...filters, offset: 0 })
        : selectedEncounters;
      // Confirm skips unidentified sounds, as on each card: they have no species to
      // confirm and are named with Correct.
      chosen = next === "correct" ? picked.filter((item) => !unidentifiedSound(item.event)) : picked;
      const skipped = picked.length - chosen.length;
      const skippedNote = skipped
        ? ` · ${skipped.toLocaleString()} unidentified sound${skipped === 1 ? "" : "s"} left for Correct`
        : "";
      const before = beforeReviews(chosen);
      await reviewInBatches(
        chosen.map((item) => item.encounter_id),
        next,
        { taxonId },
        (done) => {
          saved = done;
          if (whole)
            setProgress(`Saved ${done.toLocaleString()} of ${chosen.length.toLocaleString()}…`);
        },
      );
      if (whole) {
        setKept(new Map());
        page.refresh();
      } else {
        keep(
          chosen.map((encounter) => ({
            encounter,
            next: withDecision(encounter, next, {
              taxonId,
              notes: encounter.event.review.notes ?? undefined,
              taxa,
            }),
          })),
        );
      }
      setBulkDone({ message: bulkMessage(next, chosen.length, name) + skippedNote, before, whole });
      setSelected(new Set());
      setWholeList(false);
      setBulkPicking(false);
      toReview.refresh();
      statusCounts.refresh();
      everything.refresh();
      shown.refresh();
      onCounts?.();
    } catch (reason) {
      const text = reason instanceof Error ? reason.message : String(reason);
      if (saved > 0) {
        // Part of the list was saved before a request failed: that part stays undoable.
        const done = chosen.slice(0, saved);
        setBulkDone({
          message: `${bulkMessage(next, saved, name)} of ${chosen.length.toLocaleString()}; the rest were not saved`,
          before: beforeReviews(done),
          whole: true,
        });
        setSelected(new Set());
        setWholeList(false);
        setKept(new Map());
        page.refresh();
        toReview.refresh();
        statusCounts.refresh();
        everything.refresh();
        shown.refresh();
        onCounts?.();
      }
      setError(saved > 0 ? `Stopped after ${saved.toLocaleString()} of ${chosen.length.toLocaleString()}: ${text}` : text);
    } finally {
      setProgress("");
      setBulkBusy(false);
    }
  }

  /** Undo takes back the whole action, a few requests per earlier state. */
  async function undoBulk() {
    if (!bulkDone) return;
    setBulkBusy(true);
    setError("");
    try {
      const groups = undoGroups(bulkDone.before);
      const count = bulkDone.before.size;
      let done = 0;
      for (const { review, ids } of groups) {
        await reviewInBatches(
          ids,
          review.status,
          { taxonId: review.taxonId, notes: review.notes },
          bulkDone.whole
            ? (n) => setProgress(`Undoing ${(done + n).toLocaleString()} of ${count.toLocaleString()}…`)
            : undefined,
        );
        done += ids.length;
      }
      if (bulkDone.whole) {
        setKept(new Map());
        page.refresh();
      } else {
        const restored: { encounter: Encounter; next: Encounter }[] = [];
        for (const [id, before] of bulkDone.before) {
          const encounter = encounters.find((item) => item.encounter_id === id);
          if (encounter)
            restored.push({
              encounter,
              next: withDecision(encounter, before.status, {
                taxonId: before.taxonId,
                notes: before.notes,
                taxa,
              }),
            });
        }
        keep(restored);
      }
      setBulkDone(null);
      toReview.refresh();
      statusCounts.refresh();
      everything.refresh();
      shown.refresh();
      onCounts?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setProgress("");
      setBulkBusy(false);
    }
  }

  function select(encounter: Encounter, value: boolean) {
    setBulkDone(null);
    setWholeList(false);
    setSelected((current) => {
      const next = new Set(current);
      if (value) next.add(encounter.encounter_id);
      else next.delete(encounter.encounter_id);
      return next;
    });
  }

  function moveFocus(event: React.KeyboardEvent<HTMLUListElement>) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    if (key !== "j" && key !== "k") return;
    const target = event.target as HTMLElement;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
    // Rows behind a closed "N more that FALCON hid" line are skipped until it is opened.
    const cards = [
      ...(grid.current?.querySelectorAll<HTMLElement>(".rl-card") ?? []),
    ].filter((card) => !card.closest("details:not([open])"));
    const index = cards.findIndex((card) => card.contains(document.activeElement));
    const step = key === "j" ? 1 : -1;
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

  const periodLabel = PERIODS.find(([value]) => value === period)?.[1] ?? period;
  const sourceRow = (sources.data?.sources ?? []).find((row) => row.source_id === source);
  const caption = filterCaption({
    period,
    periodLabel:
      period === "custom"
        ? `${formatDateTime(fromLocalInput(from), false)} to ${formatDateTime(fromLocalInput(to), false)}`
        : periodLabel,
    modality,
    query,
    scope,
    source,
    sourceLabel: sourceRow ? sourceRow.source_filename : "",
    showHidden,
    unidentified,
    minScore,
  });
  const stays = groupStays(encounters);
  // Rows in front: the visits of this list; attached hidden ones are extra.
  const front = encounters.filter((item) => !item.attached);
  // Pages count stays (a stay is never split); the range shown stays in visits.
  const totalStays = page.data?.total_stays ?? total;
  const pages = Math.max(1, Math.ceil(totalStays / PAGE));
  const pageNumber = Math.floor(offset / PAGE) + 1;
  const visitsBefore = page.data?.visits_before ?? offset;
  const frontOnPage = (page.data?.encounters ?? []).filter((item) => !item.attached).length;
  const allTicked =
    !!front.length && front.every((item) => selected.has(item.encounter_id));
  const bulkCount = wholeList ? total : selectedEncounters.length;
  const bulkCorrectTitle = `Correct ${bulkCount.toLocaleString()} record${bulkCount === 1 ? "" : "s"}`;

  return (
    <div className="page review-page rl-page">
      <div className="rl-main">
        <section className="rl-filters" aria-label="Filters">
          <div className="rl-fl">
            <span className="rl-sel">
              <span className="rl-status-cap" aria-hidden="true">
                Status
              </span>
              <label className="rv-sr" htmlFor="review-status">
                Show records by status
              </label>
              <select
                id="review-status"
                value={status}
                onChange={(change) => changeFilter(setStatus)(change.target.value)}
              >
                {STATUSES.map(([value, label], index) => (
                  <option key={value} value={value}>
                    {statusOptionLabel(label, countFor(value, index))}
                  </option>
                ))}
              </select>
              <span className="rl-arr" aria-hidden="true">
                <Icon name="chevronDown" size={20} />
              </span>
            </span>
            <button
              type="button"
              className={`rl-fbtn${caption.changed ? " on" : ""}`}
              aria-expanded={filtersOpen}
              aria-controls="review-filters"
              aria-describedby="review-caption"
              onClick={() => setFiltersOpen((open) => !open)}
            >
              <span className="rl-fb-t">Filters</span>
              <Icon name="chevronDown" size={18} />
            </button>
            <button
              type="button"
              className="rl-refresh"
              onClick={() => {
                setKept(new Map());
                setBulkDone(null);
                refreshAll();
              }}
              aria-label="Refresh the list"
            >
              <Icon name="refresh" size={18} />
            </button>
          </div>
          <div
            className={`rl-fpanel${filtersOpen ? " open" : ""}`}
            id="review-filters"
            role="group"
            aria-label="Filters"
          >
            <label>
              Time
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
            </label>
            {period === "custom" && (
              <>
                <label>
                  From
                  <input
                    id="review-from"
                    type="datetime-local"
                    value={from}
                    onChange={(change) => changeFilter(setFrom)(change.target.value)}
                  />
                </label>
                <label>
                  To
                  <input
                    id="review-to"
                    type="datetime-local"
                    value={to}
                    onChange={(change) => changeFilter(setTo)(change.target.value)}
                  />
                </label>
              </>
            )}
            <label>
              Detections
              <select
                id="review-media"
                value={modality}
                onChange={(change) => changeFilter(setModality)(change.target.value)}
              >
                <option value="">Video and sound</option>
                <option value="visual">Video only</option>
                <option value="audio">Sound only</option>
              </select>
            </label>
            <label className="rl-species">
              Species
              <input
                id="review-search"
                type="search"
                placeholder="Common or scientific name"
                enterKeyHint="search"
                value={queryText}
                onChange={(change) => {
                  setQueryText(change.target.value);
                  applyTyped(change.target.value, scoreText);
                }}
                onKeyDown={(keyEvent) => {
                  if (keyEvent.key !== "Enter") return;
                  keyEvent.preventDefault();
                  applyTyped(keyEvent.currentTarget.value, scoreText, true);
                  // On the phone the search key does what "Show N records" does.
                  if (narrow && filtersOpen) {
                    keyEvent.currentTarget.blur();
                    showList();
                  }
                }}
              />
            </label>
            <label>
              Recordings
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
            </label>
            <label>
              Session
              <select
                id="review-source"
                value={source}
                onChange={(change) => changeFilter(setSource)(change.target.value)}
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
            </label>
            <label
              className={`rl-check rl-hidden-switch${hiddenStatus ? " off" : ""}`}
              title={hiddenStatus ? "Not used while Status is Hidden: the list shows only hidden records" : undefined}
            >
              <input
                type="checkbox"
                role="switch"
                checked={showHidden}
                disabled={hiddenStatus}
                onChange={(change) =>
                  changeFilter(setShowHidden)(change.target.checked)
                }
              />
              <span title="Pictures with no species and no group, 1-frame glimpses, Probable sound records and sounds of birds not recorded in Rajasthan. Cleared 7 days after capture unless you review them.">
                Show hidden{hiddenCount !== null ? ` (${hiddenCount})` : ""}
              </span>
            </label>
            <label
              className={`rl-check rl-hidden-switch${hiddenStatus ? " off" : ""}`}
              title={hiddenStatus ? "Not used while Status is Hidden: the list shows only hidden records" : undefined}
            >
              <input
                type="checkbox"
                role="switch"
                checked={unidentified}
                disabled={hiddenStatus}
                onChange={(change) =>
                  changeFilter(setUnidentified)(change.target.checked)
                }
              />
              <span title="Unreviewed pictures the model gave no species, including hidden ones. Night insects and rats stay out.">
                Unidentified only
              </span>
            </label>
            <label className="rl-score">
              Minimum score
              <input
                id="review-score"
                type="number"
                min={0}
                max={1}
                step={0.05}
                placeholder="any"
                value={scoreText}
                onChange={(change) => {
                  setScoreText(change.target.value);
                  applyTyped(queryText, change.target.value);
                }}
                onKeyDown={(keyEvent) => {
                  if (keyEvent.key !== "Enter") return;
                  keyEvent.preventDefault();
                  applyTyped(queryText, keyEvent.currentTarget.value, true);
                }}
              />
            </label>
            <CertaintyLegend />
          </div>
          <p id="review-caption" className={`rl-fsum${caption.changed ? " on" : ""}`}>
            {caption.text}
          </p>
          {hiddenStatus && (
            <p className="rl-clear-note">{HIDDEN_CLEAR_NOTE}</p>
          )}
        </section>
        {status === "confirmed" && (
          <a className="rl-act" href="#/posting">
            Post confirmed visits to iNaturalist
            <Icon name="chevron" size={18} />
          </a>
        )}
        {(error || page.error) && (
          <p className="banner banner-bad" role="alert">
            {error || page.error}
          </p>
        )}
        <p className="rl-keys">
          Keyboard: <kbd>J</kbd>/<kbd>K</kbd> move · <kbd>C</kbd> confirm ·{" "}
          <kbd>R</kbd> correct · <kbd>U</kbd> unsure · <kbd>D</kbd> discard ·{" "}
          <kbd>Space</kbd> select · <kbd>Enter</kbd> details · after a decision,
          type a note under the card and press <kbd>Enter</kbd>
        </p>
        <div ref={listTop} className={`rl-list-top${encounters.length ? "" : " bare"}`}>
          <p className="rl-loading" role="status" aria-live="polite">
            {listLoading ? "Loading…" : ""}
          </p>
        </div>
        <div className="rl-cards-box">
        <ul
          className={`rl-cards${listLoading && encounters.length ? " stale" : ""}`}
          ref={grid}
          onKeyDown={moveFocus}
          aria-label="Records"
          aria-busy={listLoading}
        >
          {stays.map((stay) => (
            <StayCard
              key={stay.stayId}
              stay={stay}
              taxa={taxa}
              onDecision={decide}
              onOpen={(item) =>
                // Next and previous step through the rows in front, plus a hidden row that was opened.
                onOpen(
                  item,
                  encounters.filter((e) => !e.attached || e.encounter_id === item.encounter_id),
                  encounters,
                )
              }
              selected={selected}
              onSelect={select}
            />
          ))}
        </ul>
        </div>
        {page.data && !listLoading && !encounters.length && (
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
        {totalStays > PAGE && (
          <nav className="rl-pager" aria-label="Pages">
            <button
              disabled={offset === 0}
              onClick={() => {
                setKept(new Map());
                setSelected(new Set());
                setWholeList(false);
                setBulkDone(null);
                setOffset(Math.max(0, offset - PAGE));
              }}
            >
              Previous
            </button>
            <span>
              Page {pageNumber} of {pages}
              <br />
              {(visitsBefore + 1).toLocaleString()}–{Math.min(total, visitsBefore + frontOnPage).toLocaleString()} of{" "}
              {total.toLocaleString()}
            </span>
            <button
              disabled={offset + PAGE >= totalStays}
              onClick={() => {
                setKept(new Map());
                setSelected(new Set());
                setWholeList(false);
                setBulkDone(null);
                setOffset(offset + PAGE);
              }}
            >
              Next
            </button>
          </nav>
        )}
        <details className="rl-about">
          <summary>
            <span>
              About this list ·{" "}
              <b>{page.data ? total.toLocaleString() : "…"}</b>{" "}
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
          </summary>
          <p>
            Check each animal visit once: confirm (or correct the species),
            mark unsure, or discard what is not usable as evidence. Add a note
            any time. Discarded visits never reach an export.{" "}
            <a href="#/posting">Post confirmed visits to iNaturalist</a>
          </p>
        </details>
      </div>
      <footer className="rl-foot" ref={foot} aria-label="Review actions">
        <div className="rl-foot-in">
          {selected.size ? (
            <>
              <div className="rl-bulk-h">
                <b>
                  {wholeList
                    ? `All ${total.toLocaleString()} in this list selected`
                    : `${selected.size} selected`}
                </b>
                <span>
                  {!allTicked && (
                    <button
                      type="button"
                      className="tlink"
                      onClick={() =>
                        setSelected(new Set(front.map((item) => item.encounter_id)))
                      }
                    >
                      Select all {front.length}
                    </button>
                  )}
                  {allTicked && !wholeList && total > front.length && (
                    <button
                      type="button"
                      className="tlink"
                      onClick={() => setWholeList(true)}
                    >
                      Select all {total.toLocaleString()} in this list
                    </button>
                  )}
                  <button
                    type="button"
                    className="tlink"
                    onClick={() => {
                      setSelected(new Set());
                      setWholeList(false);
                    }}
                  >
                    Clear
                  </button>
                </span>
              </div>
              {progress && (
                <p className="rl-progress" role="status">
                  {progress}
                </p>
              )}
              <div
                className="rl-decs"
                role="group"
                aria-label={`Your decision for ${wholeList ? total : selected.size} selected`}
              >
                <button type="button" className="dec" disabled={bulkBusy} onClick={() => void bulk("correct")}>
                  <Icon name="check" /> Confirm
                </button>
                <button type="button" className="dec" disabled={bulkBusy} onClick={() => setBulkPicking(true)}>
                  <Icon name="edit" /> Correct
                </button>
                <button type="button" className="dec" disabled={bulkBusy} onClick={() => void bulk("unknown")}>
                  <Icon name="question" /> Unsure
                </button>
                <button type="button" className="dec" disabled={bulkBusy} onClick={() => void bulk("discarded")}>
                  <Icon name="trash" /> Discard
                </button>
              </div>
              <button
                type="button"
                className="tlink rl-reset"
                disabled={bulkBusy}
                onClick={() => void bulk("unreviewed")}
              >
                Reset to “to review”
              </button>
            </>
          ) : (
            <>
              {progress && (
                <p className="rl-progress" role="status">
                  {progress}
                </p>
              )}
              {bulkDone && (
                <div className="rl-row-st" role="status">
                  <span className="what">
                    <Icon name="check" size={16} />
                    <span>{bulkDone.message}</span>
                  </span>
                  <button
                    ref={bulkUndo}
                    type="button"
                    className="tlink"
                    disabled={bulkBusy}
                    onClick={() => void undoBulk()}
                  >
                    Undo
                  </button>
                </div>
              )}
              {narrow && filtersOpen ? (
                // Phone and tablet: the open panel pushes the list down, so the footer
                // says what the filters found and goes there.
                listLoading ? (
                  <button type="button" className="rl-go" disabled>
                    Loading…
                  </button>
                ) : total === 0 ? (
                  <p className="rl-caught">No record matches these filters.</p>
                ) : (
                  <button type="button" className="rl-go" onClick={showList}>
                    {showRecordsLabel(total)}
                    <Icon name="chevron" size={18} />
                  </button>
                )
              ) : toReviewCount ? (
                <button
                  type="button"
                  className="rl-go"
                  disabled={openingQueue}
                  onClick={() => void openReviewQueue()}
                >
                  Review {toReviewCount.toLocaleString()} record
                  {toReviewCount === 1 ? "" : "s"}
                  <Icon name="chevron" size={18} />
                </button>
              ) : toReview.fresh && page.fresh ? (
                <p className="rl-caught">
                  {status === "unreviewed"
                    ? "All caught up. Nothing left to review here."
                    : waitingLine(total)}
                </p>
              ) : null}
            </>
          )}
        </div>
      </footer>
      {bulkPicking && selectedEncounters[0] && (
        <SpeciesChooser
          event={selectedEncounters[0].event}
          taxa={taxa}
          title={bulkCorrectTitle}
          withModelSuggestions={false}
          onCancel={() => setBulkPicking(false)}
          onPick={(taxon) => {
            setBulkPicking(false);
            void bulk("corrected", taxon.taxon_id, taxon.common_name || taxon.scientific_name);
          }}
        />
      )}
    </div>
  );
}
