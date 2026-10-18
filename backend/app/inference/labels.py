import numpy as np
from numpy.typing import NDArray

from app.inference.classifier_models import classifier_specs
from app.schemas import AnalysisSettings, Candidate, Classification, ModelEvidence
from app.taxonomy.domestic import is_domestic
from app.taxonomy.inaturalist import Taxon

GROUP_NAMES = {
    "Aves": "bird",
    "Mammalia": "mammal",
    "Reptilia": "reptile",
    "Amphibia": "amphibian",
    "Lepidoptera": "butterfly/moth",
    "Odonata": "dragonfly/damselfly",
    "Hymenoptera": "bee/wasp/ant",
    "Insecta": "insect",
    "Arachnida": "arachnid",
}


def classify_label(
    scores: NDArray[np.float32] | None,
    taxa: list[Taxon],
    config: AnalysisSettings,
    detail: str | None = None,
) -> Classification:
    if scores is None or not len(scores):
        return Classification(unknown_reason=detail or "No usable crop yet")
    indices = np.argsort(scores)[::-1][:5]
    candidates = [
        Candidate(
            taxon_id=taxa[i].taxon_id,
            scientific_name=taxa[i].scientific_name,
            common_name=taxa[i].common_name,
            group=taxa[i].group,
            score=round(float(scores[i]), 6),
        )
        for i in indices
    ]
    top = candidates[0]
    margin = top.score - candidates[1].score if len(candidates) > 1 else 0
    reason = detail
    if reason is None and top.score < config.species_threshold:
        reason = "Low similarity score"
    if reason is None and margin < config.ambiguity_margin:
        reason = "Ambiguous top candidates"
    # A broad group is only suggested if the strongest alternatives agree and score is usable.
    group = (
        top.group
        if top.score >= config.species_threshold
        and all(c.group == top.group for c in candidates[:3])
        else "organism"
    )
    return Classification(
        broad_group=group,
        scientific_name=None if reason else top.scientific_name,
        common_name=None if reason else top.common_name,
        score=top.score,
        margin=round(margin, 6),
        status="unknown" if reason else "candidate",
        unknown_reason=reason,
        top_k=candidates,
        display_label=f"Unknown {GROUP_NAMES.get(group, 'organism')}"
        if reason
        else f"{top.common_name or top.scientific_name} — "
        + ("domestic animal candidate" if is_domestic(top.scientific_name) else "candidate"),
    )


def classify_models(
    scores: dict[str, NDArray[np.float32]],
    taxa: list[Taxon],
    config: AnalysisSettings,
    detail: str | None = None,
) -> Classification:
    """Classify each model independently, requiring two qualified matches for agreement."""
    specs = classifier_specs(config.classifier_mode)
    decisions = [classify_label(scores.get(spec.key), taxa, config, detail) for spec in specs]
    primary = decisions[0]
    primary.model_evidence = [
        ModelEvidence(
            model=spec.model_id,
            version=spec.revision,
            status="candidate" if decision.status == "candidate" else "unknown",
            score=decision.score,
            margin=decision.margin,
            top_k=decision.top_k,
            unknown_reason=decision.unknown_reason,
        )
        for spec, decision in zip(specs, decisions, strict=True)
    ]
    if config.classifier_mode != "ensemble":
        return primary
    qualified = all(decision.status == "candidate" for decision in decisions)
    top_ids = [decision.top_k[0].taxon_id if decision.top_k else None for decision in decisions]
    if qualified and top_ids[0] == top_ids[1]:
        primary.consensus = "agree"
        return primary
    primary.status = "unknown"
    primary.scientific_name = None
    primary.common_name = None
    if all(taxon_id is not None for taxon_id in top_ids) and top_ids[0] != top_ids[1]:
        primary.consensus = "disagree"
        primary.unknown_reason = "Models suggest different species"
    else:
        primary.consensus = "insufficient_evidence"
        primary.unknown_reason = "Both models must provide an unambiguous species match"
    if detail:
        primary.unknown_reason = f"{detail}; {primary.unknown_reason}"
    if any(decision.broad_group != primary.broad_group for decision in decisions):
        primary.broad_group = "organism"
    primary.display_label = f"Unknown {GROUP_NAMES.get(primary.broad_group, 'organism')}"
    return primary
