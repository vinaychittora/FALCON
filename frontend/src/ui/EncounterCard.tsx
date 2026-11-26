// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
// This program is free software: you can redistribute it and/or modify it under the terms of the
// GNU Affero General Public License as published by the Free Software Foundation, version 3 of
// the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import { useRef, useState } from "react";
import Icon from "../components/Icon";
import { useTaxonNames } from "../components/TaxonNames";
import { soundGuessLine } from "../api/certainty";
import { thumbnailUrl, type Encounter } from "../api/encounters";
import { formatDuration } from "../api/format";
import {
  decisionAnnouncement,
  decisionLine,
  pickAction,
  recordIdentity,
  takenDecision,
  type DecisionKind,
} from "../api/recordView";
import { cardAction, cardWhen, evidenceLine, kindWord } from "../api/reviewList";
import { hiddenReasonText, rowFrom } from "../api/stays";
import type { Taxon } from "../pages/Taxa";
import type { ReviewStatus } from "../types";
import Pill, { type Tone } from "./Pill";
import SpeciesChooser from "./SpeciesChooser";
import "./review-list.css";

export const CARD_DECISIONS: { kind: DecisionKind; label: string; key: string }[] = [
  { kind: "confirm", label: "Confirm", key: "C" },
  { kind: "correct", label: "Correct", key: "R" },
  { kind: "unsure", label: "Unsure", key: "U" },
  { kind: "discard", label: "Discard", key: "D" },
];

/** The button a stored status belongs to (old "not an animal" is Discard). */
export function actionFor(status: string): ReviewStatus | null {
  if (status === "false_positive") return "discarded";
  return ["correct", "corrected", "unknown", "discarded"].includes(status)
    ? (status as ReviewStatus)
    : null;
}

export type DecisionHandler = (
  encounter: Encounter,
  status: ReviewStatus,
  taxonId?: number,
  notes?: string,
) => Promise<void>;

type Before = { status: ReviewStatus; taxonId?: number; notes?: string };

export default function EncounterCard({
  encounter,
  taxa,
  onDecision,
  onOpen,
  selected,
  onSelect,
  row = false,
}: {
  encounter: Encounter;
  taxa: Taxon[];
  onDecision: DecisionHandler;
  onOpen: (encounter: Encounter) => void;
  selected?: boolean;
  onSelect?: (encounter: Encounter, selected: boolean) => void;
  /** One animal's row inside a stay card: its time "from 09:37:57", and a hidden row's
   * pill "Hidden" with the reason in plain words. Everything else is today's card. */
  row?: boolean;
}) {
  const names = useTaxonNames();
  const [picking, setPicking] = useState(false);
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const [error, setError] = useState("");
  const [imageFailed, setImageFailed] = useState(false);
  // What the card held before this view's decision, for Undo; null until a decision.
  const [before, setBefore] = useState<Before | null>(null);
  const [note, setNote] = useState("");
  const [noteSaved, setNoteSaved] = useState(false);
  const correctButton = useRef<HTMLButtonElement>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const event = encounter.event;
  const identity = recordIdentity(event, names);
  const guess = soundGuessLine(event);
  const taken = takenDecision(event, names);
  const evidence = evidenceLine(encounter, names);
  const confirm = cardAction("confirm", encounter, taxa);
  const when = cardWhen(encounter.first_captured_at);
  const from = row ? rowFrom(encounter.first_captured_at) : "";
  const label = row ? `${identity.name}, from ${from}` : `${identity.name}, ${when}`;
  const hiddenWhy = row && encounter.attached ? hiddenReasonText(encounter.hidden_reason) : "";
  const pill = hiddenWhy
    ? { text: "Hidden", tone: "muted", title: hiddenWhy }
    : identity.pill;
  const hintId = `hint-${encounter.encounter_id}`;

  /** One request per tap: a second tap while one is on its way does nothing. */
  async function store(status: ReviewStatus, taxonId?: number, notes?: string) {
    if (busy.current) return false;
    busy.current = true;
    setPending(true);
    setError("");
    try {
      await onDecision(encounter, status, taxonId, notes);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save. Try again.");
      return false;
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  async function take(status: ReviewStatus, taxonId?: number) {
    const earlier: Before = before ?? {
      status: event.review.status,
      taxonId: event.review.corrected_taxon_id ?? undefined,
      notes: event.review.notes ?? undefined,
    };
    if (await store(status, taxonId, event.review.notes ?? undefined)) {
      setBefore(earlier);
      setNote(event.review.notes ?? "");
      setNoteSaved(false);
    }
  }

  function decide(kind: DecisionKind) {
    if (kind === "correct") {
      setPicking(true);
      return;
    }
    const action = cardAction(kind, encounter, taxa);
    if (action) void take(action.status, action.taxonId);
  }

  async function saveNote() {
    if (!before) return;
    const status = event.review.status;
    if (await store(status, event.review.corrected_taxon_id ?? undefined, note))
      setNoteSaved(true);
  }

  async function undo() {
    if (!before) return;
    if (await store(before.status, before.taxonId, before.notes)) {
      setBefore(null);
      window.setTimeout(() => confirmButton.current?.focus(), 0);
    }
  }

  function onKeyDown(keyEvent: React.KeyboardEvent<HTMLElement>) {
    if (keyEvent.target !== keyEvent.currentTarget || picking) return;
    if (keyEvent.ctrlKey || keyEvent.metaKey || keyEvent.altKey) return;
    const key = keyEvent.key.toLowerCase();
    const decision = CARD_DECISIONS.find((item) => item.key.toLowerCase() === key);
    if (decision) {
      keyEvent.preventDefault();
      decide(decision.kind);
    } else if (key === "enter") {
      keyEvent.preventDefault();
      onOpen(encounter);
    } else if (key === " " && onSelect) {
      keyEvent.preventDefault();
      onSelect(encounter, !selected);
    }
  }

  const done = !!before && taken !== null;
  return (
    <li
      className={`rl-card${row ? " rl-row" : ""}${done ? " done" : ""}${selected ? " picked" : ""}`}
      tabIndex={0}
      aria-label={`${identity.name}, ${pill.text}, ${row ? `from ${from}` : when}`}
      onKeyDown={onKeyDown}
      data-status={encounter.review_status}
    >
      {onSelect && (
        <label className="ck">
          <input
            type="checkbox"
            checked={!!selected}
            onChange={(change) => onSelect(encounter, change.target.checked)}
          />
          <span className="bx" aria-hidden="true">
            <Icon name="check" size={14} />
          </span>
          <span className="rv-sr">Select {label}</span>
        </label>
      )}
      <button type="button" className="c-open" onClick={() => onOpen(encounter)}>
        {!imageFailed ? (
          <img
            src={thumbnailUrl(encounter.thumbnail_event_id)}
            alt=""
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <span className="c-noimg" aria-hidden="true">
            <Icon name={encounter.modality === "audio" ? "sound" : "eye"} size={26} />
          </span>
        )}
        <span className="c-t">
          <span className="rv-sr">Open the record: </span>
          <span className="c-nm">{identity.name}</span>
          {identity.scientific && <span className="c-sci">{identity.scientific}</span>}
          {guess && <span className="c-guess">{guess}</span>}
          <span className="c-l">
            <Pill tone={pill.tone as Tone} title={pill.title}>
              {pill.text}
            </Pill>
            <span className="wh">
              {row ? (
                <span className="nw">from {from} ·</span>
              ) : (
                <>
                  <span className="nw">{kindWord(encounter)} ·</span>{" "}
                  <span className="nw">{when} ·</span>
                </>
              )}{" "}
              <span className="nw">{formatDuration(encounter.duration_ms)}</span>
            </span>
          </span>
        </span>
        <Icon name="chevron" size={18} />
      </button>
      <div className="c-m">
        {evidence.said && (
          <>
            Model said: <b>{evidence.said.name}</b>
            {evidence.said.score ? ` ${evidence.said.score}` : ""} ·{" "}
          </>
        )}
        {evidence.text}
      </div>
      {hiddenWhy && <div className="c-m">FALCON hid it: {hiddenWhy}</div>}
      {event.review.notes && !done && (
        <div className="c-m">Note: {event.review.notes}</div>
      )}
      <div className="decs" role="group" aria-label={`Your decision for ${label}`}>
        {CARD_DECISIONS.map((decision) => {
          const unavailable = decision.kind === "confirm" && !confirm;
          return (
            <button
              key={decision.kind}
              ref={
                decision.kind === "correct"
                  ? correctButton
                  : decision.kind === "confirm"
                    ? confirmButton
                    : undefined
              }
              type="button"
              className="dec"
              data-kind={decision.kind}
              aria-pressed={taken === decision.kind}
              aria-keyshortcuts={decision.key}
              aria-describedby={unavailable ? hintId : undefined}
              aria-busy={pending || undefined}
              disabled={unavailable}
              onClick={() => decide(decision.kind)}
            >
              {decision.label}
            </button>
          );
        })}
      </div>
      {!confirm && !done && (
        <p className="c-hint" id={hintId}>
          No species to confirm. Use Correct to name it.
        </p>
      )}
      {done && (
        <div className="c-done">
          <div className="row-st">
            <span className="what">
              <Icon name="check" size={16} />
              <span>
                {decisionLine(event, names)}
                {noteSaved ? " · note saved" : ""}
              </span>
            </span>
            <button
              type="button"
              className="tlink"
              aria-disabled={pending || undefined}
              onClick={() => void undo()}
            >
              Undo
            </button>
          </div>
          <label className="rv-sr" htmlFor={`note-${encounter.encounter_id}`}>
            Note for {identity.name} (optional)
          </label>
          <input
            id={`note-${encounter.encounter_id}`}
            className="note"
            value={note}
            maxLength={2000}
            enterKeyHint="done"
            placeholder="Add a note (optional)"
            onChange={(change) => {
              setNote(change.target.value);
              setNoteSaved(false);
            }}
            onKeyDown={(keyEvent) => {
              keyEvent.stopPropagation();
              if (keyEvent.key === "Enter") {
                keyEvent.preventDefault();
                keyEvent.currentTarget.blur();
              }
            }}
            onBlur={() => {
              if (note !== (event.review.notes ?? "")) void saveNote();
            }}
          />
        </div>
      )}
      <p className="rv-sr" role="status">
        {done ? decisionAnnouncement(event, names) : ""}
      </p>
      {pending && <p className="c-hint">Saving…</p>}
      {error && (
        <p className="c-error" role="alert">
          {error}
        </p>
      )}
      {picking && (
        <SpeciesChooser
          event={event}
          taxa={taxa}
          onCancel={() => {
            setPicking(false);
            window.setTimeout(() => correctButton.current?.focus(), 0);
          }}
          onPick={(taxon) => {
            setPicking(false);
            window.setTimeout(() => correctButton.current?.focus(), 0);
            const action = pickAction(event, taxon, taxa);
            void take(action.status, action.taxonId);
          }}
        />
      )}
    </li>
  );
}
