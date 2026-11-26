# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from app.inference.labels import apply_tiers, visit_classification
from app.schemas import AnalysisSettings, Candidate, Classification


def candidate(taxon_id: int, score: float, group: str, name: str = "x") -> Candidate:
    return Candidate(taxon_id=taxon_id, scientific_name=f"Genus {name}", common_name=name, group=group, score=score)


def likely(top_k: list[Candidate]) -> Classification:
    top = top_k[0]
    return Classification(
        broad_group=top.group, scientific_name=top.scientific_name, common_name=top.common_name,
        score=top.score, margin=round(top.score - top_k[1].score, 6), status="candidate",
        top_k=top_k, display_label=f"{top.common_name} — candidate", certainty="likely",
    )


CONFIG = AnalysisSettings(species_threshold=0.33)


def test_the_bowl_with_frog_otter_and_bee_candidates_is_an_unidentified_animal():
    c = apply_tiers(likely([
        candidate(1, 0.41, "Amphibia", "Narrow-mouthed Frog"), candidate(2, 0.37, "Mammalia", "Otter"),
        candidate(3, 0.36, "Hymenoptera", "Sweat Bee"), candidate(4, 0.35, "Amphibia"),
        candidate(5, 0.34, "Mammalia"),
    ]), CONFIG)
    assert c.display_label == "Unidentified animal" and c.common_name is None
    assert c.certainty == "unknown" and c.broad_group == "organism" and len(c.top_k) == 5


def test_low_similarity_or_small_gap_is_probable_not_likely():
    birds = [candidate(i, s, "Aves", f"b{i}") for i, s in enumerate((0.42, 0.37, 0.36, 0.35, 0.34))]
    assert apply_tiers(likely(birds), CONFIG).certainty == "probable"
    close = [candidate(i, s, "Aves", f"b{i}") for i, s in enumerate((0.55, 0.54, 0.40, 0.39, 0.38))]
    assert apply_tiers(likely(close), CONFIG).certainty == "probable"


def cat_frame(score: float, gap: float) -> Classification:
    top_k = [candidate(41948, score, "Mammalia", "Rusty-spotted Cat"), candidate(2, score - gap, "Mammalia", "Civet"),
             candidate(3, score - gap - 0.01, "Mammalia"), candidate(4, 0.3, "Mammalia"), candidate(5, 0.29, "Mammalia")]
    return apply_tiers(likely(top_k), CONFIG)


def test_a_visit_is_likely_from_its_best_agreeing_frames_not_its_latest():
    frames = [cat_frame(0.48, 0.03), cat_frame(0.47, 0.025), cat_frame(0.49, 0.021)]
    weak = cat_frame(0.44, 0.0)  # the latest frame is weak
    visit = visit_classification([*frames, weak], weak, CONFIG)
    assert visit.certainty == "likely" and visit.common_name == "Rusty-spotted Cat"
    assert visit.score == 0.48 and visit.margin == 0.025  # medians of the passing frames
    # more weak frames never drop it again
    later = visit_classification([*frames, *[weak] * 20], weak, CONFIG)
    assert later.certainty == "likely"


def test_a_half_frame_visit_is_held_at_probable():
    frames = [cat_frame(0.48, 0.03), cat_frame(0.47, 0.025), cat_frame(0.49, 0.021)]
    big = [(0.2, 0.1, 1.0, 1.0)] * 3  # the 15:12 remount: 0.72 of the picture
    held = visit_classification(frames, frames[-1], CONFIG, boxes=big)
    assert held.certainty == "probable" and held.unknown_reason.startswith("SIZE")
    assert held.unknown_reason.startswith("SIZE (median)")
    # The remount: mostly a quarter of the picture, once nearly all of it.
    remount = [(0.5, 0.5, 1.0, 1.0)] * 3 + [(0.03, 0.03, 1.0, 1.0)]
    once = visit_classification(frames, frames[-1], CONFIG, boxes=remount)
    assert once.certainty == "probable" and once.unknown_reason.startswith("SIZE (largest)")
    # Last night's cat: boxes of 0.12-0.15 of the picture stay Likely.
    cat_boxes = [(0.63, 0.32, 0.97, 0.77), (0.74, 0.25, 0.97, 0.84), (0.70, 0.30, 0.97, 0.80)]
    assert visit_classification(frames, frames[-1], CONFIG, boxes=cat_boxes).certainty == "likely"


def test_two_good_frames_are_not_yet_likely():
    frames = [cat_frame(0.48, 0.03), cat_frame(0.47, 0.025)]
    assert visit_classification(frames, frames[-1], CONFIG).certainty == "probable"


def test_the_bowl_never_becomes_likely():
    bowl = [apply_tiers(likely([
        candidate(1, 0.41, "Amphibia", "Frog"), candidate(2, 0.39, "Amphibia"),
        candidate(3, 0.38, "Mammalia"), candidate(4, 0.37, "Amphibia"), candidate(5, 0.36, "Amphibia"),
    ]), CONFIG) for _ in range(50)]
    assert visit_classification(bowl, bowl[-1], CONFIG).certainty != "likely"


def test_a_clear_bird_stays_likely():
    birds = [candidate(i, s, "Aves", f"b{i}") for i, s in enumerate((0.53, 0.47, 0.44, 0.40, 0.39))]
    c = apply_tiers(likely(birds), CONFIG)
    assert c.certainty == "likely" and c.common_name == "b0"
