import {
  displayLabel,
  displayScientificName,
  formatTime,
} from "../api/timeline";
import type { VisualEvent, AudioEvent, Detection } from "../types";
import Icon from "./Icon";
import { groupName } from "../api/taxa";
import { consensusLabel, speciesModelName } from "../api/models";
import ModelEvidence from "./ModelEvidence";
import { useTaxonNames } from "./TaxonNames";

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
        events.map((e) => (
          <article className="detection-card" key={e.event_id}>
            <div className="card-top">
              <span className="tag">
                {groupName(e.classification.broad_group)}
              </span>
              <span className="muted">
                {e.track_id.split("-track-")[1]
                  ? "Track " + e.track_id.split("-track-")[1]
                  : ""}
              </span>
            </div>
            <h4>{displayLabel(e, taxonNames)}</h4>
            {displayScientificName(e, taxonNames) && (
              <em>{displayScientificName(e, taxonNames)}</em>
            )}
            {e.review.status === "unreviewed" &&
              e.classification.status === "unknown" &&
              e.classification.top_k[0] && (
                <p className="closest-match">
                  <span>
                    {(e.classification.model_evidence?.length ?? 0) > 1
                      ? `${speciesModelName(e.classification.model_evidence![0].model)} suggests · uncertain`
                      : "Closest match · uncertain"}
                  </span>
                  <strong>
                    {e.classification.top_k[0].common_name ||
                      e.classification.top_k[0].scientific_name}
                  </strong>
                </p>
              )}
            <p className="score-line">
              Detector confidence{" "}
              <strong>
                {e.detector.score?.toFixed(3) ?? "Motion proposal"}
              </strong>
            </p>
            <p className="score-line">
              {e.classification.model_evidence?.[0]
                ? `${speciesModelName(e.classification.model_evidence[0].model)} similarity`
                : "Species similarity"}{" "}
              <strong>{e.classification.score?.toFixed(3) ?? "—"}</strong>
            </p>
            {consensusLabel(e.classification) && (
              <p className={`model-consensus ${e.classification.consensus}`}>
                {consensusLabel(e.classification)}
              </p>
            )}
            {e.classification.unknown_reason && (
              <p className="reason">
                {e.classification.unknown_reason === "Ambiguous top candidates"
                  ? "Several species look similar. More detail is needed."
                  : e.classification.unknown_reason}
              </p>
            )}
            <details>
              <summary>Compare alternatives</summary>
              <p className="muted">
                {e.detector.model} ·{" "}
                {e.detector.score?.toFixed(3) ??
                  "motion proposal (no detector score)"}
              </p>
              {e.classification.model_evidence?.length ? (
                <ModelEvidence classification={e.classification} />
              ) : (
                <>
                  <p className="muted">
                    Top-two margin {e.classification.margin?.toFixed(3) ?? "—"}.
                    Similarity is not a probability.
                  </p>
                  {e.classification.top_k.map((t) => (
                    <div className="alternative" key={t.taxon_id}>
                      <span>
                        {t.common_name || t.scientific_name}
                        <small>{t.scientific_name}</small>
                      </span>
                      <code>{t.score.toFixed(3)}</code>
                    </div>
                  ))}
                </>
              )}
            </details>
            <button className="subtle" onClick={() => onInspect(e)}>
              Review observation <Icon name="arrow" size={13} />
            </button>
          </article>
        ))
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
        events.map((e) => (
          <article className="detection-card audio" key={e.event_id}>
            <span className="tag">Acoustic detection</span>
            <h4>{displayLabel(e, taxonNames)}</h4>
            {displayScientificName(e, taxonNames) && (
              <em>{displayScientificName(e, taxonNames)}</em>
            )}
            <p className="score-line">
              BirdNET confidence <strong>{e.confidence.toFixed(3)}</strong>
            </p>
            <p className="observation-time">
              {formatTime(e.start_ms)} – {formatTime(e.end_ms)}
            </p>
            <button className="subtle" onClick={() => onInspect(e)}>
              Review observation <Icon name="arrow" size={13} />
            </button>
          </article>
        ))
      )}
    </>
  );
}
