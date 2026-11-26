// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { certaintyDetail, cleanedSoundNote, soundGuessLine } from "../api/certainty";
import { api } from "../api/client";
import {
  fetchEncounters,
  reviewEncounters,
  type Encounter,
} from "../api/encounters";
import { formatClock, formatDuration } from "../api/format";
import { speciesModelName } from "../api/models";
import { captureTime } from "../api/observations";
import {
  actionForKind,
  changedReviews,
  noteDraft,
  tierText,
  confirmAction,
  decisionAnnouncement,
  decisionLine,
  decisionSnapshot,
  evidenceGroups,
  failedSentence,
  formatScore,
  isSameReview,
  itemFromEncounter,
  pickAction,
  recordIdentity,
  recordKeyAction,
  snapshotOf,
  storeReview,
  takenDecision,
  type DecisionAction,
  type DecisionKind,
  type EvidenceGroup,
  type RecordItem,
  type ReviewSnapshot,
  type ReviewStore,
} from "../api/recordView";
import { cardClock, cardDay } from "../api/reviewList";
import {
  decidingLine,
  decisionGroupLabel,
  isDiscarded,
  stayChips,
  stayRows,
  trackOf,
  visitName,
} from "../api/stayChips";
import { groupName } from "../api/taxa";
import { eventTime, formatTime } from "../api/timeline";
import { useBackToClose } from "../hooks/useBackToClose";
import type { Detection, Video } from "../types";
import type { Taxon } from "../pages/Taxa";
import Pill from "../ui/Pill";
import SpeciesChooser from "../ui/SpeciesChooser";
import { StatusText, useLayerStatus } from "../ui/LayerStatus";
import RecordMedia, {
  evidenceKind,
  evidenceUrl,
  useSavedEvidence,
} from "./EvidencePlayer";
import Icon, { type IconName } from "./Icon";
import ImagePlayer from "./ImagePlayer";
import VideoPlayer from "./VideoPlayer";
import "./record-view.css";
import { useTaxonNames } from "./TaxonNames";

const DECISIONS: {
  kind: DecisionKind;
  label: string;
  icon: IconName;
  key: string;
  title: string;
}[] = [
  { kind: "confirm", label: "Confirm", icon: "check", key: "C", title: "The model's species is correct." },
  { kind: "correct", label: "Correct", icon: "edit", key: "R", title: "Choose the right species. Counts as confirmed." },
  { kind: "unsure", label: "Unsure", icon: "question", key: "U", title: "An animal; the species is unclear." },
  {
    kind: "discard",
    label: "Discard",
    icon: "trash",
    key: "D",
    title: "Not usable as evidence: not an animal, a person, noise, blurred or duplicate. Say why in the note. Never exported.",
  },
];

type Fact = [string, string];

/** Key/value facts for the record, by the label the expands ask for. */
export function recordFacts(
  event: Detection,
  encounter?: { records: number },
): Map<string, string> {
  const facts: Fact[] = [["Tier", tierText(event)]];
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
    const model = c.model_evidence?.[0]?.model ?? event.models?.classifier_model;
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
      track.split("-track-")[1] ? `#${track.split("-track-")[1]}` : track || "—",
    ]);
    if (encounter) facts.push(["Frames in visit", String(encounter.records)]);
    if (c.unknown_reason) facts.push(["Model note", c.unknown_reason]);
    // Records from before 8 Nov 2026 (no visit id) keep the tiers they were given then.
    facts.push([
      "Rules",
      event.visit_id ? "Counted frames (8 Nov 2026 rules)" : "Graded by old rules",
    ]);
  } else {
    facts.push(["Confidence", `${event.confidence.toFixed(3)} · ${event.model}`]);
    facts.push(["Window", `${formatTime(event.start_ms)} – ${formatTime(event.end_ms)}`]);
    if (event.cleaned_agrees !== null && event.cleaned_agrees !== undefined)
      facts.push(["Second check", cleanedSoundNote(event.cleaned_agrees, event.cleaned_score)]);
  }
  if (event.models?.device)
    facts.push(["Device", String(event.models.device).toUpperCase()]);
  const clips = event.evidence_summaries ?? [];
  if (clips.length)
    facts.push(["Clips", clips.map((clip) => `${clip.media_kind} ${clip.status}`).join(", ")]);
  return new Map(facts);
}

function FactList({ facts, keys }: { facts: Map<string, string>; keys: string[] }) {
  return (
    <dl className="rv-facts">
      {keys.flatMap((label) => {
        const value = facts.get(label);
        return value === undefined
          ? []
          : [
              <dt key={`${label}-t`}>{label}</dt>,
              <dd key={`${label}-d`}>{value}</dd>,
            ];
      })}
    </dl>
  );
}

function Expand({
  label,
  summary,
  children,
}: {
  label: string;
  summary: string;
  children: React.ReactNode;
}) {
  return (
    <details className="rv-expand">
      <summary>
        <span>
          <span className="rv-expand-label">{label}</span>
          <span className="rv-expand-summary">{summary}</span>
        </span>
        <Icon name="chevronDown" />
      </summary>
      <div className="rv-expand-body">{children}</div>
    </details>
  );
}

function EvidenceRows({ group, top = true }: { group: EvidenceGroup; top?: boolean }) {
  return (
    <ul className="rv-rows">
      {group.rows.map((row, index) => (
        <li key={row.id} className={top && index === 0 ? "top" : ""}>
          <span className="rv-row-name">
            {row.name}
            {row.yourChoice && <span className="rv-choice">your choice</span>}
          </span>
          <span className="rv-bar" aria-hidden="true">
            {row.score !== null && (
              <i style={{ width: `${Math.max(3, Math.min(100, row.score * 100))}%` }} />
            )}
          </span>
          <span className="rv-score">
            {row.score !== null && <span className="rv-sr">{row.scoreLabel} </span>}
            {row.score !== null ? formatScore(row.score) : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

function EvidenceBlock({ groups }: { groups: EvidenceGroup[] }) {
  return (
    <div className="rv-evidence rv-gut">
      {groups.map((group) => (
        <section key={group.title} aria-label={group.title}>
          <div className="rv-evidence-head">
            <span>{group.title}</span>
            <small>{group.hint}</small>
          </div>
          {group.rows.length ? (
            <EvidenceRows group={group} />
          ) : (
            <p className="rv-evidence-note">{group.empty}</p>
          )}
          {group.note && (
            <p className="rv-evidence-note">
              <Icon name="check" size={15} /> {group.note}
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

const storeOnServer: ReviewStore = async (item, status, options) => {
  if (item.encounter) {
    await reviewEncounters([item.encounter.encounter_id], status, options);
    return;
  }
  await api<Detection>(`/detections/${item.event.event_id}/review`, {
    method: "POST",
    body: JSON.stringify({
      status,
      notes: options.notes?.trim() || null,
      corrected_taxon_id: status === "corrected" ? options.taxonId : null,
    }),
  });
};

interface Layer {
  items: RecordItem[];
  index: number;
  list: boolean;
}

/** A row of the page with the decision taken here since it was opened. */
function updatedRowFrom(row: Encounter, rowItems: Record<string, RecordItem>, items: RecordItem[]): Encounter {
  const known = rowItems[row.encounter_id] ?? items.find((entry) => entry.id === row.encounter_id);
  return known ? { ...row, event: known.event } : row;
}

function useHeardRecords(encounter?: Encounter) {
  const [records, setRecords] = useState<Encounter[]>([]);
  const names = encounter?.heard?.map((item) => item.name).join("|") ?? "";
  const id = encounter?.encounter_id ?? "";
  const source = encounter?.source_id;
  const first = encounter?.first_captured_at;
  const duration = encounter?.duration_ms ?? 0;
  useEffect(() => {
    if (!names || !first) return;
    let alive = true;
    const start = Date.parse(first);
    if (!Number.isFinite(start)) return;
    fetchEncounters({
      scope: "all",
      source_id: source,
      modality: "audio",
      captured_from: new Date(start - 5000).toISOString(),
      captured_to: new Date(start + duration + 5000).toISOString(),
      limit: 50,
    })
      .then((page) => {
        if (alive)
          setRecords(
            page.encounters.filter((item) =>
              names
                .split("|")
                .includes(
                  item.event.modality === "audio"
                    ? item.event.common_name || item.event.scientific_name
                    : "",
                ),
            ),
          );
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [id, names, source, first, duration]);
  return records;
}

export default function Inspector({
  event,
  encounter,
  queue,
  pool,
  startIndex = 0,
  taxa,
  source,
  onClose,
  onSeek,
  onSaved,
  playEvidence = false,
}: {
  event?: Detection;
  /** When set, the decision applies to every record of this encounter. */
  encounter?: Encounter;
  /** The list this record was opened from; Previous and Next walk it. */
  queue?: Encounter[];
  /** Review's page with its attached hidden rows: the animals of each stay (chips). */
  pool?: Encounter[];
  startIndex?: number;
  taxa: Taxon[];
  source?: Video;
  onClose: (savedReviews: number) => void;
  onSeek?: (ms: number) => void;
  onSaved?: (event: Detection) => void;
  playEvidence?: boolean;
}) {
  const names = useTaxonNames();
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const noteInput = useRef<HTMLInputElement>(null);
  const correctButton = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const positionId = useId();
  const [layers, setLayers] = useState<Layer[]>(() => {
    if (queue?.length)
      return [{ items: queue.map(itemFromEncounter), index: startIndex, list: true }];
    const only: RecordItem = encounter
      ? itemFromEncounter(encounter)
      : { id: event?.event_id ?? "", event: event as Detection };
    return [{ items: [only], index: 0, list: false }];
  });
  const [busy, setBusy] = useState<DecisionKind | "undo" | null>(null);
  const [error, setError] = useState("");
  // The popup covers the app bar and its status line: its own top bar carries the status.
  const lineStatus = useLayerStatus();
  const [choosing, setChoosing] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [undoFor, setUndoFor] = useState<Record<string, ReviewSnapshot>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [noteSaved, setNoteSaved] = useState<Record<string, boolean>>({});
  const [chosenPiece, setChosenPiece] = useState<Record<string, string>>({});
  // The stay's chips: which animal each opened row's view describes, the rows decided
  // here that are not in the list in front, and the visits on the opened row's recording.
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [rowItems, setRowItems] = useState<Record<string, RecordItem>>({});
  const [frontTracks, setFrontTracks] = useState<Record<string, Set<string>>>({});
  const chipRow = useRef<HTMLDivElement>(null);
  const originals = useRef(new Map<string, ReviewSnapshot>());
  const latest = useRef(new Map<string, Detection>());
  const noteJobs = useRef(new Map<string, { text: string; job: Promise<void> }>());
  const closing = useRef(false);

  const layer = layers[layers.length - 1];
  const front = layer.items[layer.index];
  const { rows, item } = useMemo(() => {
    const all = stayRows(front.encounter, pool).map((row) => updatedRowFrom(row, rowItems, layer.items));
    const chosen = all.find((row) => row.encounter_id === picked[front.id]);
    const shown: RecordItem =
      !chosen || chosen.encounter_id === front.id
        ? front
        : (rowItems[chosen.encounter_id] ??
          layer.items.find((entry) => entry.id === chosen.encounter_id) ??
          itemFromEncounter(chosen));
    return { rows: all, item: shown };
  }, [front, pool, picked, rowItems, layer.items]);
  const chips = stayChips(rows, names);
  const pickedRowNow = rows.find((row) => row.encounter_id === item.id);
  // The recording stays when the chosen animal is on it; otherwise its own one loads.
  const offFront =
    item.id !== front.id && !!frontTracks[front.id] && !frontTracks[front.id].has(trackOf(item.id));
  const mediaItem = offFront ? item : front;
  const current = item.event;
  const related = item.encounter;
  const records = related?.records ?? 1;
  const identity = recordIdentity(current, names);
  const groups = evidenceGroups(current, related, names);
  const taken = takenDecision(current, names);
  const confirm = confirmAction(current, taxa);
  const facts = recordFacts(current, related);
  const evidence = useSavedEvidence(mediaItem.event.event_id, mediaItem.event.evidence_summaries);
  const piece =
    evidence.items.find((entry) => entry.evidence_id === chosenPiece[mediaItem.id]) ??
    evidence.items[0] ??
    null;
  const heard = useHeardRecords(current.modality === "visual" ? related : undefined);
  const draft = noteDraft(drafts, item.id, current.review.notes);
  const sourceMatches = source?.source_id === current.source_id;
  const isField = current.source_kind === "live" || !sourceMatches;
  const captured = captureTime(current.captured_at);
  const lengthMs = related?.duration_ms ?? (current.modality === "visual" ? current.duration_ms : current.end_ms - current.start_ms);
  const when = !isField
    ? `${formatTime(eventTime(current))} in the recording`
    : captured && current.captured_at
      ? // The list card's form (device's own clock), so header, chips and card agree.
        `${cardDay(new Date(current.captured_at))}, ${cardClock(new Date(current.captured_at))}`
      : "capture time unavailable";
  const kindLabel = current.modality === "audio" ? "Sound" : "Visit";
  const hasPrevious = layer.index > 0;
  const hasNext = layer.index < layer.items.length - 1;

  const remember = useCallback((entry: RecordItem) => {
    if (!originals.current.has(entry.id))
      originals.current.set(entry.id, snapshotOf(entry.event));
    if (!latest.current.has(entry.id)) latest.current.set(entry.id, entry.event);
  }, []);
  useEffect(() => {
    layers.forEach((entry) => entry.items.forEach(remember));
  }, [layers, remember]);

  const replaceItem = useCallback(
    (updated: RecordItem) => {
      latest.current.set(updated.id, updated.event);
      setRowItems((all) => ({ ...all, [updated.id]: updated }));
      setLayers((all) =>
        all.map((entry) => ({
          ...entry,
          items: entry.items.map((row) => (row.id === updated.id ? updated : row)),
        })),
      );
      onSaved?.(updated.event);
    },
    [onSaved],
  );

  const saveNote = useCallback(
    async (target: RecordItem, text: string) => {
      const notes = text.trim() || null;
      if ((target.event.review.notes ?? null) === notes) return;
      if (target.event.review.status === "unreviewed") return;
      const running = noteJobs.current.get(target.id);
      if (running?.text === (notes ?? "")) return running.job;
      const job = (async () => {
        try {
          const saved = await storeReview(
            target,
            { ...snapshotOf(target.event), notes },
            taxa,
            storeOnServer,
          );
          replaceItem(saved);
          setNoteSaved((all) => ({ ...all, [target.id]: true }));
          setError("");
        } catch (reason) {
          setError(failedSentence("note", reason));
          throw new Error("note not saved", { cause: reason });
        } finally {
          noteJobs.current.delete(target.id);
        }
      })();
      noteJobs.current.set(target.id, { text: notes ?? "", job });
      return job;
    },
    [replaceItem, taxa],
  );

  const finish = useCallback(async () => {
    if (closing.current) return;
    if (layers.length > 1) {
      setLayers((all) => all.slice(0, -1));
      return;
    }
    closing.current = true;
    try {
      await saveNote(item, draft);
    } catch {
      closing.current = false;
      return;
    }
    onClose(changedReviews(originals.current, latest.current));
  }, [draft, item, layers.length, onClose, saveNote]);

  useBackToClose(() => void finish());
  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    return () => element.close();
  }, []);
  // A new record in the list takes focus to its title; a chip keeps focus where it is.
  useEffect(() => {
    heading.current?.focus();
  }, [front.id]);
  // On the phone the chip row scrolls sideways inside itself: the chosen chip in view.
  useEffect(() => {
    const row = chipRow.current;
    const chip = row?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (!row || !chip) return;
    const left = chip.offsetLeft - row.offsetLeft;
    if (left < row.scrollLeft) row.scrollLeft = left - 8;
    else if (left + chip.offsetWidth > row.scrollLeft + row.clientWidth)
      row.scrollLeft = left + chip.offsetWidth - row.clientWidth + 8;
  }, [item.id, chips.length]);
  const frontId = front.id;
  const mediaIsFront = mediaItem.id === frontId;
  const onTracks = useCallback(
    (_evidenceId: string, tracks: Set<string>) => {
      if (mediaIsFront) setFrontTracks((all) => ({ ...all, [frontId]: tracks }));
    },
    [frontId, mediaIsFront],
  );
  const { knownNames, goneTracks } = useMemo(() => {
    const map = new Map<string, string>();
    const gone = new Set<string>();
    for (const row of pool ?? []) {
      if (row.modality !== "visual") continue;
      const now = updatedRowFrom(row, rowItems, layer.items);
      map.set(trackOf(row.encounter_id), visitName(now, names));
      if (isDiscarded(now)) gone.add(trackOf(row.encounter_id));
    }
    return { knownNames: map, goneTracks: gone };
  }, [pool, rowItems, layer.items, names]);
  const labelFor = useCallback((track: string) => knownNames.get(track), [knownNames]);

  function pick(id: string) {
    if (id === item.id) return;
    void saveNote(item, draft).catch(() => undefined);
    setError("");
    setChoosing(false);
    setPicked((all) => ({ ...all, [frontId]: id }));
  }

  function move(step: number) {
    void saveNote(item, draft).catch(() => undefined);
    setError("");
    setChoosing(false);
    setLayers((all) =>
      all.map((entry, index) =>
        index === all.length - 1
          ? {
              ...entry,
              index: Math.max(0, Math.min(entry.items.length - 1, entry.index + step)),
            }
          : entry,
      ),
    );
  }

  async function goOn() {
    try {
      await saveNote(item, draft);
    } catch {
      return;
    }
    if (hasNext) move(1);
    else void finish();
  }

  async function take(action: DecisionAction) {
    const snapshot = decisionSnapshot(action, draft);
    if (busy || isSameReview(item, snapshot)) return;
    // A chip's animal that is not in the list in front still counts in "N reviews saved".
    remember(item);
    setBusy(action.kind);
    setError("");
    const before = snapshotOf(current);
    try {
      const saved = await storeReview(item, snapshot, taxa, storeOnServer);
      replaceItem(saved);
      setUndoFor((all) => ({ ...all, [item.id]: before }));
      setNoteSaved((all) => ({ ...all, [item.id]: false }));
      setAnnouncement(decisionAnnouncement(saved.event, names));
    } catch (reason) {
      setError(failedSentence("save", reason));
    } finally {
      setBusy(null);
    }
  }

  function press(kind: DecisionKind) {
    if (busy) return;
    if (kind === "correct") {
      setChoosing(true);
      return;
    }
    const action = actionForKind(kind, current, taxa);
    if (action) void take(action);
  }

  async function undo() {
    const before = undoFor[item.id];
    if (!before || busy) return;
    setBusy("undo");
    setError("");
    try {
      const saved = await storeReview(item, before, taxa, storeOnServer);
      replaceItem(saved);
      setUndoFor((all) => {
        const next = { ...all };
        delete next[item.id];
        return next;
      });
      setDrafts((all) => ({ ...all, [item.id]: before.notes ?? "" }));
      setNoteSaved((all) => ({ ...all, [item.id]: false }));
      setAnnouncement("Decision undone.");
    } catch (reason) {
      setError(failedSentence("undo", reason));
    } finally {
      setBusy(null);
    }
  }

  function onKeyDown(keyEvent: React.KeyboardEvent<HTMLDialogElement>) {
    const action = recordKeyAction({
      key: keyEvent.key,
      ctrlKey: keyEvent.ctrlKey,
      metaKey: keyEvent.metaKey,
      altKey: keyEvent.altKey,
      target: keyEvent.target as HTMLElement,
    });
    if (!action) return;
    keyEvent.preventDefault();
    if (action === "next") {
      if (hasNext) move(1);
    } else if (action === "previous") {
      if (hasPrevious) move(-1);
    } else if (action === "note") {
      noteInput.current?.focus();
    } else if (action !== "confirm" || confirm) {
      press(action);
    }
  }

  function openRelated(list: Encounter[]) {
    setLayers((all) => [
      ...all,
      { items: list.map(itemFromEncounter), index: 0, list: list.length > 1 },
    ]);
  }

  const secondCheck = facts.get("Second check");
  const canPost =
    !!related &&
    (current.review.status === "correct" || current.review.status === "corrected");
  const postHidden =
    !related || ["discarded", "false_positive"].includes(current.review.status);
  const certainty = current.modality === "visual" ? certaintyDetail(current) : null;
  const note = facts.get("Model note");
  const gap = facts.get("Gap to runner-up");
  const cameraSummary = [
    certainty ?? note,
    gap ? `gap ${Number(gap).toFixed(2)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const heardRows = related?.heard ?? [];
  const environment = current.environment;
  const weather =
    environment?.status === "fresh" || environment?.status === "stale"
      ? [
          environment.temperature_c !== null ? `${environment.temperature_c.toFixed(1)} °C` : null,
          environment.humidity_percent !== null ? `${Math.round(environment.humidity_percent)} %` : null,
          environment.pressure_hpa !== null ? `${environment.pressure_hpa.toFixed(0)} hPa` : null,
        ]
          .filter(Boolean)
          .join(" · ") + (environment.status === "stale" ? " (stale)" : "")
      : "";
  const pieceCaptured = piece ? captureTime(piece.captured_at) : null;
  const playable = piece?.status === "ready" || piece?.status === "partial";
  const pieceSeconds = piece?.duration_ms ? Math.round(piece.duration_ms / 1000) : null;
  const previewBoxes = (ms: number) =>
    current.modality === "visual" &&
    ms >= current.timestamp_ms &&
    ms < current.timestamp_ms + current.duration_ms
      ? [{ bbox_norm: current.bbox_norm, label: "Selected detection" }]
      : [];
  const seek = useMemo(() => ({ ms: eventTime(current), nonce: 0 }), [current]);
  return (
    <>
      <dialog
        ref={dialog}
        className="rv"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={positionId}
        onCancel={(cancel) => {
          cancel.preventDefault();
          void finish();
        }}
        onKeyDown={onKeyDown}
        onClick={(click) => {
          if (click.target === click.currentTarget) void finish();
        }}
      >
        <header className={`rv-top rv-gut${lineStatus.shown ? " ls-active" : ""}`}>
          <button
            type="button"
            className="rv-icon"
            aria-label="Close and go back"
            title="Close (Esc)"
            onClick={() => void finish()}
          >
            <Icon name="close" />
          </button>
          <div className="rv-position" id={positionId}>
            {layer.list && (
              <span className="first">
                {layer.index + 1} of {layer.items.length}
              </span>
            )}
            <span className={`${layer.list ? "second" : "first"} rv-visit-line`}>
              {kindLabel} · {when} · {formatDuration(lengthMs)}
            </span>
            {/* Narrow: the status takes the visit line's place while it is not Connected. */}
            {lineStatus.shown && (
              <span className={`${layer.list ? "second" : "first"} rv-ls-inline`}>
                <StatusText state={lineStatus.shown} />
              </span>
            )}
          </div>
          {/* Wide: the status has its own place in the bar, always shown. */}
          <span className="rv-ls-wide">
            <StatusText state={lineStatus.always} />
          </span>
          <span className={`fs-progress${lineStatus.busy ? " on" : ""}`} aria-hidden="true" />
          {layer.list && (
            <>
              <button
                type="button"
                className="rv-icon"
                aria-label="Previous record"
                aria-keyshortcuts="K"
                title="Previous record (K)"
                disabled={!hasPrevious}
                onClick={() => move(-1)}
              >
                <Icon name="chevronLeft" />
              </button>
              <button
                type="button"
                className="rv-icon"
                aria-label="Next record"
                aria-keyshortcuts="J"
                title="Next record (J)"
                disabled={!hasNext}
                onClick={() => move(1)}
              >
                <Icon name="chevron" />
              </button>
            </>
          )}
        </header>

        <div className="rv-scroll">
          <section className="rv-media" aria-label="Evidence">
            {sourceMatches && source && !isField ? (
              <div className="rv-source" aria-label="Original source at observation time">
                {source.media_kind === "audio" ? (
                  <audio
                    controls
                    preload="metadata"
                    src={`/api/videos/${source.source_id}/file`}
                    onLoadedMetadata={(media) => {
                      media.currentTarget.currentTime = eventTime(current) / 1000;
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
              <RecordMedia
                key={mediaItem.event.event_id}
                eventId={mediaItem.event.event_id}
                evidence={evidence}
                current={piece}
                onChoose={(id) =>
                  setChosenPiece((all) => ({ ...all, [mediaItem.id]: id }))
                }
                ownKey={chips.length ? item.id : null}
                labelFor={labelFor}
                sourceId={current.source_id}
                names={names}
                onTracks={onTracks}
                dropTracks={goneTracks}
                autoPlay={playEvidence}
                legacy={isField && !captured}
                box={
                  current.modality === "visual"
                    ? {
                        bbox: current.bbox_norm,
                        label: identity.name,
                        capturedAt: current.captured_at ?? null,
                        final: taken === "confirm" || taken === "correct",
                      }
                    : undefined
                }
                sound={
                  current.modality === "audio"
                    ? {
                        capturedAt: current.captured_at ?? null,
                        lengthMs: current.end_ms - current.start_ms,
                      }
                    : undefined
                }
              />
            )}
            {chips.length > 0 && (
              <div
                ref={chipRow}
                className="rv-chips rv-gut"
                role="group"
                aria-label="Animals in this stay"
              >
                {chips.map((chip) => (
                  <button
                    key={chip.id}
                    type="button"
                    className={`rv-chip${chip.hidden || chip.discarded ? " hidden" : ""}`}
                    aria-pressed={chip.id === item.id}
                    title={chip.hidden ? "Hidden by FALCON in this stay" : undefined}
                    onClick={() => pick(chip.id)}
                  >
                    {chip.decided && <Icon name="check" size={14} />}
                    <span className="rv-chip-name">{chip.name}</span>
                    <span className="rv-chip-time">{chip.time}</span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <div className="rv-body">
            <div className="rv-identity rv-gut">
              <div className="rv-identity-top">
                <span className="rv-label">{identity.label}</span>
                <Pill tone={identity.pill.tone} title={identity.pill.title}>
                  {identity.pill.text}
                </Pill>
              </div>
              <h1 id={titleId} ref={heading} tabIndex={-1}>
                {identity.name}
              </h1>
              {identity.scientific && <div className="rv-sci">{identity.scientific}</div>}
              {soundGuessLine(current) && <div className="rv-said">{soundGuessLine(current)}</div>}
              {identity.modelSaid && (
                <div className="rv-said">
                  Model said: <b>{identity.modelSaid.name}</b>{" "}
                  {identity.modelSaid.score !== null && (
                    <span className="rv-mono">{formatScore(identity.modelSaid.score)}</span>
                  )}
                </div>
              )}
            </div>

            <EvidenceBlock groups={groups} />

            <div className="rv-expands rv-gut">
              {current.modality === "visual" ? (
                <Expand
                  label="Camera model in detail"
                  summary={cameraSummary || "Scores, box and rules"}
                >
                  <FactList
                    facts={facts}
                    keys={["Tier", "Model note", "Group", "Genus", "Detector", "Similarity", "Gap to runner-up", "Box", "Track", "Frames in visit", "Rules", "Device"]}
                  />
                  {(current.classification.model_evidence?.length ?? 0) > 1 ? (
                    current.classification.model_evidence?.map((model) => (
                      <div key={model.model}>
                        <div className="rv-subhead">{speciesModelName(model.model)}</div>
                        <p className="rv-expand-text">
                          {model.status === "candidate" ? "Candidate" : "Uncertain"} ·
                          similarity {formatScore(model.score)} · top-two margin{" "}
                          {formatScore(model.margin)}
                          {model.unknown_reason ? ` · ${model.unknown_reason}` : ""}
                        </p>
                        <EvidenceRows
                          group={{
                            title: "",
                            hint: "",
                            rows: model.top_k.slice(0, 5).map((row) => ({
                              id: String(row.taxon_id),
                              name: row.common_name || row.scientific_name,
                              score: row.score,
                              scoreLabel: "similarity",
                            })),
                          }}
                        />
                      </div>
                    ))
                  ) : (
                    <div>
                      <div className="rv-subhead">All model suggestions</div>
                      <EvidenceRows
                        group={{
                          title: "",
                          hint: "",
                          rows: (current.classification.top_k ?? []).slice(0, 5).map((row) => ({
                            id: String(row.taxon_id),
                            name: row.common_name || row.scientific_name,
                            score: row.score,
                            scoreLabel: "similarity",
                          })),
                        }}
                      />
                    </div>
                  )}
                </Expand>
              ) : (
                <Expand
                  label="Microphone model in detail"
                  summary={`Confidence ${formatScore(current.confidence)}${secondCheck ? " · second check available" : ""}`}
                >
                  <FactList facts={facts} keys={["Tier", "Confidence", "Second check", "Window", "Device"]} />
                </Expand>
              )}

              {current.modality === "visual" && (
                <Expand
                  label="Sound during this visit"
                  summary={
                    heardRows[0]
                      ? `${heardRows[0].name} ${formatScore(heardRows[0].confidence)}${
                          heard[0]?.event.modality === "audio" &&
                          heard[0].event.cleaned_agrees !== null &&
                          heard[0].event.cleaned_agrees !== undefined
                            ? heard[0].event.cleaned_agrees
                              ? " · second check agrees"
                              : " · second check does not agree"
                            : ""
                        }`
                      : "No bird heard during this visit"
                  }
                >
                  {heardRows.length ? (
                    heardRows.map((row) => {
                      const matches = heard.filter(
                        (record) =>
                          record.event.modality === "audio" &&
                          (record.event.common_name || record.event.scientific_name) === row.name,
                      );
                      const first = matches[0]?.event;
                      return (
                        <div key={row.name}>
                          <div className="rv-subhead">{row.name}</div>
                          <dl className="rv-facts">
                            <dt>Score</dt>
                            <dd>{formatScore(row.confidence)}</dd>
                            {first?.modality === "audio" && (
                              <>
                                <dt>Model</dt>
                                <dd>{first.model}</dd>
                                <dt>Second check</dt>
                                <dd>
                                  {first.cleaned_agrees === null || first.cleaned_agrees === undefined
                                    ? "Not available"
                                    : cleanedSoundNote(first.cleaned_agrees, first.cleaned_score)}
                                </dd>
                                <dt>When</dt>
                                <dd>{formatClock(matches[0].first_captured_at)}</dd>
                              </>
                            )}
                          </dl>
                          {matches.length > 0 && (
                            <button
                              type="button"
                              className="rv-button"
                              onClick={() => openRelated(matches)}
                            >
                              {matches.length === 1
                                ? "Open the sound record"
                                : `Open the ${matches.length} sound records`}
                            </button>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    <p className="rv-expand-text">No bird heard during this visit.</p>
                  )}
                </Expand>
              )}

              {weather && environment && (
                <Expand label="Weather at that moment" summary={weather}>
                  <dl className="rv-facts">
                    {environment.temperature_c !== null && (
                      <>
                        <dt>Temperature</dt>
                        <dd>{environment.temperature_c.toFixed(1)} °C</dd>
                      </>
                    )}
                    {environment.humidity_percent !== null && (
                      <>
                        <dt>Humidity</dt>
                        <dd>{Math.round(environment.humidity_percent)} %</dd>
                      </>
                    )}
                    {environment.pressure_hpa !== null && (
                      <>
                        <dt>Pressure</dt>
                        <dd>{environment.pressure_hpa.toFixed(0)} hPa</dd>
                      </>
                    )}
                    <dt>Reading</dt>
                    <dd>{environment.status === "stale" ? "Stale" : "Fresh"}</dd>
                  </dl>
                </Expand>
              )}

              <Expand
                label="Recording"
                summary={
                  piece
                    ? [
                        pieceSeconds !== null ? `${pieceSeconds} s` : null,
                        evidenceKind(piece).toLowerCase(),
                        pieceCaptured ? `starts ${formatClock(piece.captured_at)}` : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")
                    : "No saved media"
                }
              >
                <dl className="rv-facts">
                  {piece && (
                    <>
                      <dt>Length</dt>
                      <dd>{pieceSeconds !== null ? `${pieceSeconds} s` : "—"}</dd>
                      <dt>Kind</dt>
                      <dd>{evidenceKind(piece)}</dd>
                      <dt>Clip starts</dt>
                      <dd>
                        {pieceCaptured
                          ? `${pieceCaptured.date} · ${pieceCaptured.time} · server receive time`
                          : "Clip time unavailable"}
                      </dd>
                    </>
                  )}
                  <dt>Station</dt>
                  <dd>{current.source_filename}</dd>
                  {facts.get("Clips") && (
                    <>
                      <dt>Clips</dt>
                      <dd>{facts.get("Clips")}</dd>
                    </>
                  )}
                </dl>
                {piece && playable && (
                  <a className="rv-button" href={evidenceUrl(piece.evidence_id)} download>
                    <Icon name="download" size={16} /> Save clip
                  </a>
                )}
                {onSeek && (
                  <button
                    type="button"
                    className="rv-button"
                    onClick={() => {
                      onSeek(eventTime(current));
                      void finish();
                    }}
                  >
                    Open in source
                  </button>
                )}
              </Expand>

              <Expand label="Record data" summary="The complete stored record">
                <pre className="rv-raw" tabIndex={0} role="region" aria-label="Raw record data">
                  {JSON.stringify(current, null, 2)}
                </pre>
              </Expand>

              {!postHidden && (
                <button
                  type="button"
                  className="rv-action"
                  disabled={!canPost}
                  onClick={() => {
                    if (!related) return;
                    window.location.hash = `#/posting?visit=${encodeURIComponent(related.encounter_id)}`;
                    void finish();
                  }}
                >
                  <Icon name="upload" />
                  <span>
                    <span className="rv-expand-label">Post to iNaturalist</span>
                    <span className="rv-expand-summary">
                      {canPost
                        ? "Opens the preview. Nothing is sent until you press Post."
                        : "Available after Confirm or Correct"}
                    </span>
                  </span>
                  <Icon name="chevron" />
                </button>
              )}
              <p className="rv-meta">
                {records > 1
                  ? `A decision applies to all ${records} ${current.modality === "visual" ? "frames" : "records"} of this ${current.modality === "visual" ? "visit" : "sound visit"}.`
                  : "Your decision is stored next to the model output, never over it."}
              </p>
            </div>
          </div>
        </div>

        <footer className="rv-dock rv-gut">
          {error && (
            <p className="rv-error" role="alert">
              {error}
            </p>
          )}
          {taken && (
            <div className="rv-done">
              <div className="rv-status">
                <span className="rv-what">
                  <Icon name="check" size={18} />
                  <span>
                    {decisionLine(current, names)}
                    {noteSaved[item.id] ? " · note saved" : ""}
                  </span>
                </span>
                {undoFor[item.id] && (
                  <button
                    type="button"
                    className="rv-undo"
                    disabled={!!busy}
                    onClick={() => void undo()}
                  >
                    Undo
                  </button>
                )}
              </div>
              <div className="rv-note-row">
                <label className="rv-sr" htmlFor={`${titleId}-note`}>
                  Note for this record (optional)
                </label>
                <input
                  id={`${titleId}-note`}
                  ref={noteInput}
                  className="rv-note"
                  type="text"
                  maxLength={2000}
                  enterKeyHint="done"
                  placeholder="Add a note (optional)"
                  aria-keyshortcuts="N"
                  value={draft}
                  onChange={(change) => {
                    setDrafts((all) => ({ ...all, [item.id]: change.target.value }));
                    setNoteSaved((all) => ({ ...all, [item.id]: false }));
                  }}
                  onBlur={() => void saveNote(item, draft).catch(() => undefined)}
                  onKeyDown={(keyEvent) => {
                    if (keyEvent.key === "Enter") {
                      keyEvent.preventDefault();
                      void goOn();
                    }
                  }}
                />
                <button
                  type="button"
                  className="rv-next"
                  aria-keyshortcuts="J"
                  onClick={() => void goOn()}
                >
                  <kbd aria-hidden="true">J</kbd>
                  {layer.list ? (hasNext ? "Next" : "Finish") : "Done"}
                  {layer.list && hasNext && <Icon name="chevron" size={17} />}
                </button>
              </div>
            </div>
          )}
          {!confirm && !taken && (
            <p className="rv-hint" id={`${titleId}-confirm-hint`}>
              No species to confirm. Use Correct to name it.
            </p>
          )}
          {chips.length > 0 && pickedRowNow && (
            <p className="rv-deciding" aria-live="polite">
              {decidingLine(pickedRowNow, names)}
            </p>
          )}
          <div
            className="rv-decisions"
            role="group"
            aria-label={chips.length > 0 && pickedRowNow ? decisionGroupLabel(pickedRowNow, names) : "Your decision"}
          >
            {DECISIONS.map((decision) => {
              const pressed = taken === decision.kind;
              const unavailable = decision.kind === "confirm" && !confirm;
              const primary = decision.kind === "confirm" && !taken && !!confirm;
              return (
                <button
                  key={decision.kind}
                  type="button"
                  ref={decision.kind === "correct" ? correctButton : undefined}
                  className={`rv-decision${primary ? " primary" : ""}${busy === decision.kind ? " busy" : ""}`}
                  data-kind={decision.kind}
                  title={decision.title}
                  aria-pressed={pressed}
                  aria-keyshortcuts={decision.key}
                  aria-haspopup={decision.kind === "correct" ? "dialog" : undefined}
                  aria-busy={busy === decision.kind}
                  aria-describedby={unavailable ? `${titleId}-confirm-hint` : undefined}
                  disabled={!!busy || unavailable}
                  onClick={() => press(decision.kind)}
                >
                  <kbd aria-hidden="true">{decision.key}</kbd>
                  <Icon name={decision.icon} />
                  {busy === decision.kind ? "Saving…" : decision.label}
                </button>
              );
            })}
          </div>
          <div className="rv-sr" role="status" aria-live="polite">
            {announcement}
          </div>
        </footer>
      </dialog>
      {choosing && (
        <SpeciesChooser
          event={current}
          taxa={taxa}
          onCancel={() => {
            setChoosing(false);
            window.setTimeout(() => correctButton.current?.focus(), 0);
          }}
          onPick={(taxon) => {
            setChoosing(false);
            window.setTimeout(() => correctButton.current?.focus(), 0);
            void take(pickAction(current, taxon, taxa));
          }}
        />
      )}
    </>
  );
}
