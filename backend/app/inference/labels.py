# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
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


def broad_group(candidates: list[Candidate], config: AnalysisSettings) -> str:
    """The group (bird, mammal, ...) when the strongest candidates agree on it.

    A species can stay uncertain while the group is clear: a blurred bird still
    looks more like every bird than like any mammal. The group is suggested when
    the top candidate clears the lower group threshold, the leading group holds
    most of the top-five similarity mass and at least three of those candidates.
    """
    if not candidates:
        return "organism"
    top = candidates[0]
    if top.score < config.group_threshold:
        return "organism"
    if top.score >= config.species_threshold and all(c.group == top.group for c in candidates[:3]):
        return top.group
    weights: dict[str, float] = {}
    members: dict[str, int] = {}
    for candidate in candidates[:5]:
        weights[candidate.group] = weights.get(candidate.group, 0.0) + max(0.0, candidate.score)
        members[candidate.group] = members.get(candidate.group, 0) + 1
    total = sum(weights.values())
    leading = max(weights, key=lambda key: weights[key])
    if (
        total > 0
        and leading == top.group
        and weights[leading] / total >= 0.6
        and members[leading] >= min(3, len(candidates))
    ):
        return leading
    return "organism"


def genus_of(scientific_name: str | None) -> str | None:
    """The genus is the first word of a binomial name ("Pitta brachyura" -> "Pitta")."""
    if not scientific_name:
        return None
    first = scientific_name.strip().split(" ")[0]
    return first if first and first[0].isupper() else None


def either_label(names: list[str]) -> str:
    """"Indian or Mangrove Pitta" when the names share their last word, else "A or B"."""
    names = [name for name in names if name]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    shown = names[:3]
    words = [name.split(" ") for name in shown]
    shared = words[0][-1] if all(len(w) > 1 and w[-1] == words[0][-1] for w in words) else None
    if shared:
        heads = [" ".join(w[:-1]) for w in words]
        return ", ".join(heads[:-1]) + f" or {heads[-1]} {shared}"
    return ", ".join(shown[:-1]) + f" or {shown[-1]}"


def _display_name(candidate: Candidate) -> str:
    return candidate.common_name or candidate.scientific_name


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
    # The crop may be too poor for a species, but the group can still be evident.
    group = broad_group(candidates, config) if detail is None else "organism"
    group_name = GROUP_NAMES.get(group, "organism")
    certainty: str = "unknown"
    genus: str | None = None
    contenders: list[Candidate] = []
    label = f"Unknown {group_name}"
    if reason is None:
        certainty = "likely"
        genus = genus_of(top.scientific_name)
        label = f"{_display_name(top)} — " + (
            "domestic animal candidate" if is_domestic(top.scientific_name) else "candidate"
        )
    elif detail is None and reason == "Ambiguous top candidates":
        # Several look-alikes score within the margin of the best one. The best one
        # leads the label; the others ride along as contenders, with the genus when
        # they share it. The interface shows this tier in orange.
        contenders = [c for c in candidates if top.score - c.score < config.ambiguity_margin][:3]
        genera = {genus_of(c.scientific_name) for c in contenders}
        genus = genera.pop() if len(genera) == 1 else None
        certainty = "probable"
        label = _display_name(top)
    elif detail is None and top.score >= config.group_threshold:
        # Too weak for a name, but the best guess is worth showing as a faint guess (red).
        certainty = "possible"
        contenders = [top]
        label = f"{_display_name(top)}?"
    return Classification(
        broad_group=group,
        scientific_name=None if reason else top.scientific_name,
        common_name=None if reason else top.common_name,
        score=top.score,
        margin=round(margin, 6),
        status="unknown" if reason else "candidate",
        unknown_reason=reason,
        top_k=candidates,
        display_label=label,
        certainty=certainty,  # type: ignore[arg-type]
        genus=genus,
        contenders=contenders,
    )


def apply_tiers(classification: Classification, config: AnalysisSettings) -> Classification:
    """The stricter naming rules, applied to a fresh or a stored classification.

    - Candidates from ``mixed_groups`` or more groups (frog, otter, bee): the crop is
      nothing the model recognises. Named "Unidentified animal", no species, no group.
    - "Likely" needs similarity >= likely_similarity and a gap >= likely_margin;
      otherwise the record drops to "Probable" (name shown as a candidate only).
    """
    c = classification
    if c.status not in {"candidate", "unknown"}:
        return c
    top_k = c.top_k or []
    if len({candidate.group for candidate in top_k[:5]}) >= config.mixed_groups:
        c.status, c.scientific_name, c.common_name = "unknown", None, None
        c.unknown_reason = "Candidates from unrelated groups"
        c.broad_group, c.certainty, c.genus, c.contenders = "organism", "unknown", None, []
        c.display_label = "Unidentified animal"
        return c
    if c.certainty == "likely" and (
        (c.score or 0) < config.likely_similarity or (c.margin or 0) < config.likely_margin
    ):
        demote_to_probable(c, "Below the Likely floor")
    return c


def _passes(c: Classification, config: AnalysisSettings) -> bool:
    """One frame clears the Likely bar: similarity, gap and no more than two groups."""
    top_k = c.top_k or []
    if not top_k:
        return False
    margin = c.margin if c.margin is not None else (top_k[0].score - top_k[1].score if len(top_k) > 1 else 0.0)
    return (
        top_k[0].score >= config.likely_similarity
        and margin >= config.likely_margin
        and len({candidate.group for candidate in top_k[:5]}) < config.mixed_groups
    )


SIZE_HOLD = 0.30  # a visit whose median box covers more of the frame stays Probable
SIZE_HOLD_LARGEST = 0.60  # ... or whose largest box does (the 15:12 remount: median 0.25, largest 0.94)


def visit_classification(
    frames: list[Classification], latest: Classification, config: AnalysisSettings,
    boxes: list[tuple[float, float, float, float]] | None = None,
) -> Classification:
    """The visit's tier (see ``_visit_classification``), held at Probable when its
    median box covers more than 30 % of the frame (reason SIZE): the 15:12 camera
    remount made half-frame "cats"; no animal at the bowl fills a third of the view."""
    result = _visit_classification(frames, latest, config)
    if boxes and result.certainty == "likely":
        areas = sorted((b[2] - b[0]) * (b[3] - b[1]) for b in boxes)
        reason = (
            "SIZE (median): the box covers more than 30 % of the picture" if areas[len(areas) // 2] > SIZE_HOLD
            else "SIZE (largest): a box covered more than 60 % of the picture" if areas[-1] > SIZE_HOLD_LARGEST
            else None
        )
        if reason:
            return demote_to_probable(result.model_copy(deep=True) if result is latest else result, reason)
    return result


def _visit_classification(
    frames: list[Classification], latest: Classification, config: AnalysisSettings,
) -> Classification:
    """A visit's tier from its best agreeing frames, not from its latest frame.

    The visit's species is the top-1 species of most frames (ties: higher mean
    similarity). The visit is Likely when at least ``likely_frames`` of those frames
    clear the bar; their median similarity and gap are shown. Frames only add to that
    count, so a visit can rise to Likely but never drops back on a single weak frame.
    Otherwise the latest frame is shown, at most Probable.
    """
    by_species: dict[int, list[Classification]] = {}
    for frame in frames:
        if frame.top_k:
            by_species.setdefault(frame.top_k[0].taxon_id, []).append(frame)
    if by_species:
        species = max(
            by_species,
            key=lambda key: (
                len(by_species[key]),
                float(np.mean([f.top_k[0].score for f in by_species[key]])),
            ),
        )
        passing = [frame for frame in by_species[species] if _passes(frame, config)]
        if len(passing) >= config.likely_frames:
            best = max(passing, key=lambda f: f.top_k[0].score)
            c = best.model_copy(deep=True)
            top = c.top_k[0]
            c.status, c.unknown_reason = "candidate", None
            c.scientific_name, c.common_name = top.scientific_name, top.common_name
            c.broad_group, c.certainty, c.contenders = top.group, "likely", []
            c.genus = genus_of(top.scientific_name)
            c.score = round(float(np.median([f.top_k[0].score for f in passing])), 6)
            c.margin = round(float(np.median([f.margin or 0.0 for f in passing])), 6)
            c.display_label = f"{_display_name(top)} — " + (
                "domestic animal candidate" if is_domestic(top.scientific_name) else "candidate"
            )
            return c
        count = len(passing)
    else:
        count = 0
    if latest.certainty == "likely":
        return demote_to_probable(
            latest.model_copy(deep=True),
            f"{count} of {config.likely_frames} agreeing frames clear the Likely bar",
        )
    return latest


def counted_classification(latest: Classification, row: dict, candidates: list[Candidate]) -> Classification:
    """How a Phase 1 visit is shown: from its counted tier (spec P5), not from the
    records' running mean. ``candidates`` are the visit's known candidates by score."""
    c = latest.model_copy(deep=True)
    tier, name, taxon_id = row.get("tier"), row.get("name"), row.get("taxon_id")
    species = next((cand for cand in candidates if cand.taxon_id == taxon_id), None)
    if tier == "likely" and name:
        c.status, c.certainty, c.unknown_reason, c.contenders = "candidate", "likely", None, []
        c.common_name = species.common_name if species else name
        c.scientific_name = species.scientific_name if species else None
        c.genus = genus_of(c.scientific_name)
        c.display_label = f"{c.common_name or name} — candidate"
        if species:
            c.broad_group = species.group
    elif tier == "likely_group" and name:
        # "Cat (species uncertain)": the group is earned, the species is not.
        c.status, c.certainty, c.unknown_reason, c.contenders = "candidate", "likely", None, []
        c.common_name, c.scientific_name, c.genus = name, None, None
        c.display_label = name
    elif name == "Unidentified animal":
        c.status, c.certainty, c.scientific_name, c.common_name = "unknown", "unknown", None, None
        c.broad_group, c.contenders, c.genus = "organism", [], None
        c.unknown_reason = "Candidates from unrelated groups"
        c.display_label = name
    elif tier == "probable" and species:
        demote_to_probable(c, "; ".join(row.get("reasons") or []) or "Not enough agreeing frames")
        c.contenders = [species]
        c.display_label = _display_name(species)
    return c


def demote_to_probable(c: Classification, reason: str) -> Classification:
    """Keep the best name as a candidate ("Probable"), never as an identification."""
    top = c.top_k[0] if c.top_k else None
    c.status, c.scientific_name, c.common_name = "unknown", None, None
    c.unknown_reason = reason
    c.certainty = "probable"
    c.contenders = [top] if top else []
    if top:
        c.display_label = _display_name(top)
    return c


def classify_models(
    scores: dict[str, NDArray[np.float32]],
    taxa: list[Taxon],
    config: AnalysisSettings,
    detail: str | None = None,
) -> Classification:
    """Classify with the species model and record its evidence (model and version)."""
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
    return primary
