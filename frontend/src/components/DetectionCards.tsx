import {
  displayLabel,
  displayScientificName,
  formatTime,
} from "../api/timeline";
import type { VisualEvent, AudioEvent, Detection } from "../types";
import Icon from "./Icon";
import {
  certaintyDetail,
  certaintyOf,
  leadingName,
  metricsLine,
  qualityReason,
} from "../api/certainty";
import { groupName } from "../api/taxa";
import ModelEvidence from "./ModelEvidence";
import { useTaxonNames } from "./TaxonNames";
import { scientificSubtitle } from "../api/names";

/** Top candidates as compact bars; the leader is bold. */
export function SuggestionBars({
  event,
  limit = 3,
}: {
  event: VisualEvent;
  limit?: number;
}) {
  const rows = (event.classification.top_k ?? [])
    .filter((candidate) => typeof candidate.score === "number")
    .slice(0, limit);
  if (!rows.length) return null;
  const top = rows[0].score || 1;
  return (
    <ol className="suggestions" aria-label="Model suggestions">
      {rows.map((candidate, index) => (
        <li key={candidate.taxon_id} className={index === 0 ? "leader" : ""}>
          <span>
            {candidate.common_name || candidate.scientific_name}
            {scientificSubtitle(
              candidate.common_name || candidate.scientific_name,
              candidate.scientific_name,
            ) && <small>{candidate.scientific_name}</small>}
          </span>
          <i
            aria-hidden="true"
            style={{
              width: `${Math.max(4, Math.min(100, (candidate.score / top) * 100))}%`,
            }}
          />
          <code>{candidate.score.toFixed(3)}</code>
        </li>
      ))}
    </ol>
  );
}

export function VisualCards({
  events,
  onInspect,
}: {
  events: VisualEvent[];
  onInspect: (e: Detection) => void;
}) {
  const taxonNames = useTaxonNames();
  return (
    <>
      {events.length === 0 ? (
        <div className="empty-observation">
          <Icon name="eye" size={28} />
          <p>No visual observations at this timestamp.</p>
        </div>
      ) : (
        events.map((e) => {
          const certainty = certaintyOf(e);
          const detail = certaintyDetail(e);
          const quality = qualityReason(e);
          const name =
            e.review.status === "unreviewed"
              ? leadingName(e, taxonNames)
              : displayLabel(e, taxonNames);
          const scientific = displayScientificName(e, taxonNames);
          return (
            <article
              className="detection-card compact"
              key={e.event_id}
              data-certainty={certainty?.level}
            >
              <div className="card-top">
                <span className="tag">
                  {groupName(e.classification.broad_group)}
                </span>
                <span className="muted">
                  {e.track_id.split("-track-")[1]
                    ? `Track ${e.track_id.split("-track-")[1]} · `
                    : ""}
                  {formatTime(e.timestamp_ms)}
                </span>
              </div>
              <div className="card-name">
                <h4
                  className={
                    certainty ? `certainty-${certainty.level}` : undefined
                  }
                >
                  {name}
                </h4>
                {certainty && (
                  <span
                    className={`certainty certainty-${certainty.level}`}
                    title={certainty.title}
                  >
                    <i aria-hidden="true" />
                    {certainty.label}
                  </span>
                )}
              </div>
              {(scientific || detail) && <em>{scientific ?? detail}</em>}
              {scientific && detail && <em>{detail}</em>}
              <p className="metrics">{metricsLine(e) || "No model scores"}</p>
              {quality && <p className="reason">{quality}</p>}
              {e.review.status === "unreviewed" && <SuggestionBars event={e} />}
              {(e.classification.model_evidence?.length ?? 0) > 1 && (
                <details>
                  <summary>Compare models</summary>
                  <ModelEvidence classification={e.classification} />
                </details>
              )}
              <button className="subtle" onClick={() => onInspect(e)}>
                Review <Icon name="arrow" size={13} />
              </button>
            </article>
          );
        })
      )}
    </>
  );
}
export function AudioCards({
  events,
  onInspect,
}: {
  events: AudioEvent[];
  onInspect: (e: Detection) => void;
}) {
  const taxonNames = useTaxonNames();
  return (
    <>
      {events.length === 0 ? (
        <div className="empty-observation">
          <Icon name="sound" size={28} />
          <p>No acoustic detections at this timestamp.</p>
        </div>
      ) : (
        events.map((e) => {
          const certainty = certaintyOf(e);
          return (
            <article className="detection-card audio compact" key={e.event_id}>
              <div className="card-top">
                <span className="tag">Acoustic detection</span>
                <span className="muted">
                  {formatTime(e.start_ms)} – {formatTime(e.end_ms)}
                </span>
              </div>
              <div className="card-name">
                <h4
                  className={
                    certainty ? `certainty-${certainty.level}` : undefined
                  }
                >
                  {displayLabel(e, taxonNames)}
                </h4>
                {certainty && (
                  <span
                    className={`certainty certainty-${certainty.level}`}
                    title={certainty.title}
                  >
                    <i aria-hidden="true" />
                    {certainty.label}
                  </span>
                )}
              </div>
              {displayScientificName(e, taxonNames) && (
                <em>{displayScientificName(e, taxonNames)}</em>
              )}
              <p className="metrics">
                BirdNET confidence {e.confidence.toFixed(2)}
              </p>
              <button className="subtle" onClick={() => onInspect(e)}>
                Review <Icon name="arrow" size={13} />
              </button>
            </article>
          );
        })
      )}
    </>
  );
}
