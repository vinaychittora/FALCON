import { useState } from "react";
import Icon, { type IconName } from "../components/Icon";
import { useTaxonNames } from "../components/TaxonNames";
import {
  canConfirm,
  encounterNames,
  scoreSummary,
  STATUS_LABELS,
  thumbnailUrl,
  type Encounter,
} from "../api/encounters";
import { certaintyDetail, certaintyOf } from "../api/certainty";
import { formatClock, formatDateTime, formatDuration } from "../api/format";
import type { Taxon } from "../pages/Taxa";
import type { ReviewStatus } from "../types";
import Pill, { type Tone } from "./Pill";
import SpeciesPicker from "./SpeciesPicker";

const ACTIONS: {
  status: ReviewStatus;
  label: string;
  icon: IconName;
  key: string;
  title: string;
}[] = [
  {
    status: "correct",
    label: "Confirm",
    icon: "check",
    key: "C",
    title: "Confirm: the species is right",
  },
  {
    status: "corrected",
    label: "Correct",
    icon: "edit",
    key: "E",
    title: "Correct: choose the right species",
  },
  {
    status: "unknown",
    label: "Unsure",
    icon: "question",
    key: "U",
    title: "Unsure: an animal, species unclear",
  },
  {
    status: "false_positive",
    label: "Not an animal",
    icon: "close",
    key: "X",
    title: "Not an animal: wrong detection",
  },
  {
    status: "discarded",
    label: "Discard",
    icon: "trash",
    key: "D",
    title: "Discard: not useful (duplicate, blurred, empty)",
  },
];

export type DecisionHandler = (
  encounter: Encounter,
  status: ReviewStatus,
  taxonId?: number,
) => Promise<void>;

export default function EncounterCard({
  encounter,
  taxa,
  onDecision,
  onOpen,
  compact = false,
  selected,
  onSelect,
  showDate = false,
}: {
  encounter: Encounter;
  taxa: Taxon[];
  onDecision: DecisionHandler;
  onOpen: (encounter: Encounter) => void;
  compact?: boolean;
  selected?: boolean;
  onSelect?: (encounter: Encounter, selected: boolean) => void;
  showDate?: boolean;
}) {
  const names = useTaxonNames();
  const [picking, setPicking] = useState(false);
  const [pending, setPending] = useState<ReviewStatus | null>(null);
  const [error, setError] = useState("");
  const [imageFailed, setImageFailed] = useState(false);
  const event = encounter.event;
  const { primary, scientific } = encounterNames(event, names);
  const score = scoreSummary(event);
  const status = STATUS_LABELS[encounter.review_status];
  const certainty =
    encounter.review_status === "unreviewed" ? certaintyOf(event) : null;
  const detail = certaintyDetail(event);
  const confirmable = canConfirm(event) || event.review.status === "corrected";

  async function decide(next: ReviewStatus, taxonId?: number) {
    if (next === "corrected" && taxonId === undefined) {
      setPicking(true);
      return;
    }
    if (next === "correct" && !confirmable) {
      setPicking(true);
      return;
    }
    setPending(next);
    setError("");
    try {
      await onDecision(encounter, next, taxonId);
      setPicking(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPending(null);
    }
  }

  function onKeyDown(keyEvent: React.KeyboardEvent<HTMLElement>) {
    if (keyEvent.target !== keyEvent.currentTarget || picking || pending)
      return;
    const key = keyEvent.key.toLowerCase();
    const action = ACTIONS.find((item) => item.key.toLowerCase() === key);
    if (action) {
      keyEvent.preventDefault();
      void decide(action.status);
    } else if (key === "enter") {
      keyEvent.preventDefault();
      onOpen(encounter);
    } else if (key === " " && onSelect) {
      keyEvent.preventDefault();
      onSelect(encounter, !selected);
    }
  }

  const when = showDate
    ? formatDateTime(encounter.first_captured_at)
    : formatClock(encounter.first_captured_at);
  return (
    <article
      className={`encounter-card${compact ? " compact" : ""}${selected ? " selected" : ""}`}
      tabIndex={0}
      aria-label={`${primary}, ${status.label}, ${when}`}
      onKeyDown={onKeyDown}
      data-status={encounter.review_status}
      data-certainty={certainty?.level}
    >
      {onSelect && (
        <label className="encounter-select" title="Select for bulk review">
          <input
            type="checkbox"
            checked={!!selected}
            onChange={(change) => onSelect(encounter, change.target.checked)}
            aria-label={`Select ${primary}`}
          />
        </label>
      )}
      <button
        type="button"
        className={`encounter-thumb ${encounter.modality}`}
        onClick={() => onOpen(encounter)}
        aria-label={`Open ${primary} for detailed review`}
      >
        {!imageFailed ? (
          <img
            src={thumbnailUrl(encounter.thumbnail_event_id)}
            alt=""
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <Icon
            name={encounter.modality === "audio" ? "sound" : "eye"}
            size={compact ? 22 : 28}
          />
        )}
        <span className="encounter-kind">
          <Icon
            name={encounter.modality === "audio" ? "sound" : "camera"}
            size={12}
          />
        </span>
      </button>
      <div className="encounter-body">
        <div className="encounter-title">
          <div>
            <strong>{primary}</strong>
            {scientific && <em>{scientific}</em>}
            {!scientific && detail && <em>{detail}</em>}
          </div>
          {certainty ? (
            <Pill tone={certainty.tone} title={certainty.title}>
              {certainty.label}
            </Pill>
          ) : (
            <Pill tone={status.tone as Tone}>{status.label}</Pill>
          )}
        </div>
        <div className="encounter-meta">
          <span>
            <Icon name="clock" size={13} /> {when}
          </span>
          <span>{formatDuration(encounter.duration_ms)}</span>
          {encounter.modality === "visual" && (
            <span>
              {encounter.records} frame{encounter.records === 1 ? "" : "s"}
            </span>
          )}
          {!compact && (
            <span className="encounter-source">
              {encounter.source_filename}
            </span>
          )}
        </div>
        {score.value !== null && (
          <div className="score-bar" title={score.label}>
            <span
              style={{
                width: `${Math.max(4, Math.min(100, score.value * 100))}%`,
              }}
            />
            <small>{score.label}</small>
          </div>
        )}
        <div
          className="encounter-actions"
          role="group"
          aria-label="Review decision"
        >
          {ACTIONS.map((action) => (
            <button
              key={action.status}
              type="button"
              className={`decision decision-${action.status}${encounter.review_status === action.status ? " current" : ""}`}
              title={`${action.title} (${action.key})`}
              aria-label={action.label}
              aria-pressed={encounter.review_status === action.status}
              disabled={!!pending}
              onClick={() => void decide(action.status)}
            >
              <Icon name={action.icon} size={15} />
              {!compact && <span>{action.label}</span>}
            </button>
          ))}
          <button
            type="button"
            className="decision details"
            title="Details, clip and notes (Enter)"
            onClick={() => onOpen(encounter)}
          >
            <Icon name="external" size={15} />
            {!compact && <span>Details</span>}
          </button>
        </div>
        {pending && (
          <p className="encounter-note" role="status">
            Saving…
          </p>
        )}
        {error && (
          <p className="encounter-note error" role="alert">
            {error}
          </p>
        )}
        {picking && (
          <SpeciesPicker
            event={event}
            taxa={taxa}
            onCancel={() => setPicking(false)}
            onPick={(taxon) => void decide("corrected", taxon.taxon_id)}
          />
        )}
      </div>
    </article>
  );
}
