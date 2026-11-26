# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Spec P5 cases: a name is earned by counting classified frames."""

import json
from pathlib import Path

import pytest

from app.inference.tiers import GroupIndex, TierCounter
from app.inference.visits import VisitEngine

# A toy taxonomy: two cats (Felidae, group 1), a civet (group 2), birds (group 3), a frog.
GROUPS = GroupIndex({1: (1, "Cat"), 2: (1, "Cat"), 3: (2, "Civet"), 4: (3, "Robin"), 5: (3, "Robin"),
                     6: (4, "Frog"), 7: (5, "Bee"), 8: (6, "Gecko")})
BOX = (0.40, 0.40, 0.55, 0.60)


def frame(a: float, b: float, *, top_id: int = 1, second: int = 2, rest: list[tuple[int, str]] | None = None,
          outside: float | None = None) -> list[tuple[int, str, str, float]]:
    names = {1: "Rusty-spotted Cat", 2: "Jungle Cat", 3: "Civet", 4: "Magpie-Robin", 5: "Indian Robin",
             6: "Frog", 7: "Bee", 8: "Gecko"}
    iconic = {1: "Mammalia", 2: "Mammalia", 3: "Mammalia", 4: "Aves", 5: "Aves", 6: "Amphibia", 7: "Insecta",
              8: "Reptilia"}
    rest = rest if rest is not None else [(top_id, ""), (second, "")] + [(2 if top_id != 2 else 1, "")] * 3
    ids = [top_id, second] + [r[0] for r in rest[2:5]]
    scores = [a, b, b - 0.01, b - 0.02, b - 0.03]
    top = [(i, names[i], iconic[i], s) for i, s in zip(ids, scores, strict=True)]
    if outside is not None:
        top.append((3, "Civet", "Mammalia", outside))
    return top


def run(frames: list, times: list[float], boxes: list | None = None) -> TierCounter:
    counter = TierCounter(groups=GROUPS)
    for i, (t, top) in enumerate(zip(times, frames, strict=True)):
        counter.add(t, (boxes or [BOX] * len(frames))[i], top)
    return counter


def test_u8a_likely_by_counting_even_with_a_weak_latest_frame():
    good = frame(0.50, 0.46)  # gap 0.04
    weak = frame(0.46, 0.45)  # gap 0.01
    frames = [good] * 5 + [weak] * 17 + [frame(0.45, 0.44, top_id=2, second=1)] * 2
    times = [i * 0.6 for i in range(24)]
    best = run(frames, times).best
    assert best.tier == "likely" and best.name == "Rusty-spotted Cat"


def test_u8b_three_qualifying_frames_within_a_second_are_not_likely():
    best = run([frame(0.50, 0.46)] * 3, [0.0, 0.4, 0.8]).best
    assert best.tier != "likely" and "SPAN" in best.reasons


def test_u8c_all_cats_but_no_clear_species_is_group_likely():
    cats = frame(0.50, 0.49, top_id=1, second=2, rest=[(1, ""), (2, ""), (1, ""), (2, ""), (1, "")], outside=0.45)
    best = run([cats] * 4, [0.0, 0.8, 1.6, 2.4]).best
    assert best.tier == "likely_group" and best.name == "Cat (species uncertain)"


def test_u8d_three_groups_in_the_median_frame_is_unidentified():
    mixed = frame(0.46, 0.44, top_id=6, second=7, rest=[(6, ""), (7, ""), (8, ""), (8, ""), (8, "")])
    good = frame(0.50, 0.46)
    best = run([good, good, mixed, mixed, mixed], [0, 1, 2, 3, 4]).best
    assert best.tier == "probable" and best.name == "Unidentified animal"


def test_u8e_a_species_top_in_only_40_percent_is_probable():
    a = frame(0.50, 0.46, top_id=1)
    b = frame(0.47, 0.46, top_id=4, second=5, rest=[(4, ""), (5, ""), (6, ""), (5, ""), (5, "")])
    c = frame(0.47, 0.46, top_id=5, second=4, rest=[(5, ""), (4, ""), (6, ""), (4, ""), (4, "")])
    # A leads (3 of 7 frames, 43 %) over two others, and all 3 of its frames qualify.
    best = run([b, c, a, b, a, c, a], [i * 1.0 for i in range(7)]).best
    assert best.tier == "probable" and "MAJORITY" in best.reasons


def test_u8f_the_tier_never_falls():
    good = frame(0.50, 0.46)
    poor = frame(0.30, 0.29, top_id=6, second=7, rest=[(6, ""), (7, ""), (8, ""), (8, ""), (8, "")])
    counter = run([good] * 4, [0, 1, 2, 3])
    assert counter.best.tier == "likely"
    for i in range(20):
        counter.add(4 + i, BOX, poor)
    assert counter.best.tier == "likely"


def test_u8g_a_huge_box_is_held_at_probable():
    best = run([frame(0.50, 0.46)] * 4, [0, 1, 2, 3], boxes=[(0.0, 0.0, 0.7, 0.6)] * 4).best
    assert best.tier == "probable" and "SIZE" in best.reasons


def test_u5_a_still_bird_is_an_identity_visit_with_one_bell():
    engine, counter = VisitEngine(), TierCounter(groups=GROUPS)
    bird = [(4, "Magpie-Robin", "Aves", 0.53), (5, "Indian Robin", "Aves", 0.47), (5, "x", "Aves", 0.46),
            (5, "y", "Aves", 0.45), (5, "z", "Aves", 0.44)]
    promotions, likely_at = [], []
    for i in range(8):
        t = i * 1.0
        decision = engine.observe("bird", BOX, t, bird)
        if decision.promoted_now:
            promotions.append(decision.promoted_now)
        before = counter.best.tier if counter.best else None
        if counter.add(t, BOX, bird).tier == "likely" and before != "likely":
            likely_at.append(t)
    assert promotions == ["IDENTITY"] and len(likely_at) == 1


def test_u11_probable_then_group_then_species_rings_once():
    counter = TierCounter(groups=GROUPS)
    cats = frame(0.50, 0.49, top_id=1, second=2, rest=[(1, ""), (2, ""), (1, ""), (2, ""), (1, "")], outside=0.45)
    clear = frame(0.52, 0.47)
    bells = 0
    tiers = []
    for i, top in enumerate([cats] * 4 + [clear] * 6):
        before = counter.best.tier if counter.best else "unknown"
        after = counter.add(i * 0.8, BOX, top).tier
        tiers.append(after)
        if after.startswith("likely") and not before.startswith("likely"):
            bells += 1
    assert "probable" in tiers and "likely_group" in tiers and tiers[-1] == "likely" and bells == 1


def test_u17_every_rajasthan_species_has_a_group():
    path = Path(__file__).resolve().parents[2] / "data" / "taxa"
    if not (path / "groups.json").exists() or not (path / "rajasthan_taxa.json").exists():
        pytest.skip("needs data/taxa/groups.json and data/taxa/rajasthan_taxa.json (make taxa)")
    groups = json.loads((path / "groups.json").read_text())
    taxa = json.loads((path / "rajasthan_taxa.json").read_text())["taxa"]
    assert all(str(t["taxon_id"]) in groups and groups[str(t["taxon_id"])][2] for t in taxa)
    assert groups["41948"][2] == "Cat"  # Rusty-spotted Cat
