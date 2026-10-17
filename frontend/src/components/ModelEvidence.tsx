import { consensusLabel, speciesModelName } from "../api/models";
import type { VisualEvent } from "../types";
import { scientificSubtitle } from "../api/names";

export default function ModelEvidence({
  classification,
}: {
  classification: VisualEvent["classification"];
}) {
  const evidence = classification.model_evidence ?? [];
  if (evidence.length === 0) return null;
  const consensus = consensusLabel(classification);
  return (
    <div className="model-evidence" aria-label="Species model evidence">
      {consensus && (
        <p className={`model-consensus ${classification.consensus}`}>
          {consensus}
        </p>
      )}
      {evidence.map((item) => (
        <section className="model-evidence-item" key={item.model}>
          <div className="model-evidence-heading">
            <strong title={`${item.model} · ${item.version}`}>
              {speciesModelName(item.model)}
            </strong>
            <span>
              {item.status === "candidate" ? "Candidate" : "Uncertain"}
            </span>
          </div>
          <p className="model-evidence-score">
            Similarity {item.score?.toFixed(3) ?? "—"} · top-two margin{" "}
            {item.margin?.toFixed(3) ?? "—"}
          </p>
          {item.top_k.map((candidate) => (
            <div className="alternative" key={candidate.taxon_id}>
              <span>
                {candidate.common_name || candidate.scientific_name}
                {scientificSubtitle(
                  candidate.common_name || candidate.scientific_name,
                  candidate.scientific_name,
                ) && <small>{candidate.scientific_name}</small>}
              </span>
              <code>{candidate.score.toFixed(3)}</code>
            </div>
          ))}
          {item.unknown_reason && (
            <p className="model-evidence-reason">{item.unknown_reason}</p>
          )}
        </section>
      ))}
      <p className="model-evidence-caption">
        Each score belongs to its model. Similarity is not a probability.
        {evidence.length > 1 &&
          " Agreement supports a suggestion; it does not verify the species."}
      </p>
    </div>
  );
}
