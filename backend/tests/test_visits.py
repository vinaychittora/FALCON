"""Spec P2 cases: visits form from motion, time and identity; scenery is learned."""

from app.inference.visits import VisitEngine

BOWL = (0.20, 0.61, 0.78, 1.0)
BIRD = [(1, "Oriental Magpie-Robin", "Aves", 0.53), (2, "Indian Robin", "Aves", 0.47), (3, "x", "Aves", 0.44),
        (4, "y", "Aves", 0.43), (5, "z", "Aves", 0.42)]
CAT_AT_SPOT = [(9, "Rusty-spotted Cat", "Mammalia", 0.50), (8, "Civet", "Mammalia", 0.45),
               (7, "x", "Mammalia", 0.40), (6, "y", "Mammalia", 0.39), (5, "z", "Mammalia", 0.38)]
BOWL_TOP = [(1, "Frog", "Amphibia", 0.41), (2, "Otter", "Mammalia", 0.40), (3, "Bee", "Hymenoptera", 0.39),
            (4, "Gecko", "Reptilia", 0.38), (5, "Frog 2", "Amphibia", 0.37)]


def jitter(box, k):
    d = 0.002 * ((k % 5) - 2)
    return (box[0] + d, box[1], box[2] + d, box[3])


def learn_bowl(engine: VisitEngine, until: float = 600.0) -> list:
    """U1: the bowl pops up twice every 20 s for 10 minutes, never moving."""
    results, closed = [], []
    t, k = 0.0, 0
    while t < until:
        track = f"bowl{k}"
        for dt in (0.0, 0.5):
            results.append(engine.observe(track, jitter(BOWL, k), t + dt, BOWL_TOP, "night"))
        k += 1
        t += 20
        closed += engine.tick(t)
    return results, closed  # type: ignore[return-value]


def test_u1_bowl_pops_are_never_a_visit_and_become_a_spot():
    engine = VisitEngine()
    results, closed = learn_bowl(engine)
    assert not any(r.promoted_now for r in results)
    assert all(c.hidden in {"STILL", "GLIMPSE"} for c in closed)
    assert len(engine.spots) == 1 and engine.spots[0].kind == "scenery"
    first_hit = next(i for i, r in enumerate(results) if r.action == "hit")
    assert 180 <= (first_hit // 2) * 20 <= 200  # the spot exists after 3 minutes
    assert all(r.action == "hit" for r in results[first_hit:])


def test_u3_bird_entering_over_the_edge_is_a_visit_at_frame_two_and_stays_open():
    engine = VisitEngine()
    box = (0.92, 0.50, 0.98, 0.56)
    first = engine.observe("b", box, 0.0, BIRD)
    hop = (0.83, 0.50, 0.89, 0.56)  # 1.5 sizes in from the right edge
    second = engine.observe("b", hop, 0.5, BIRD)
    assert first.action == "record" and first.promoted_now is None
    assert second.promoted_now in {"MOTION", "EDGE"}
    for i in range(1, 481):  # 240 s still, drinking, qualifying
        engine.observe("b", hop, 0.5 + i * 0.5, BIRD)
        assert not engine.tick(0.5 + i * 0.5)
    assert "b" in engine.open


def test_u3b_leaf_gust_closes_after_three_still_minutes_then_becomes_scenery():
    engine = VisitEngine()
    leaf = (0.40, 0.70, 0.46, 0.76)
    gust = (0.436, 0.70, 0.496, 0.76)  # 0.6 of its size
    engine.observe("leaf", leaf, 0.0, BOWL_TOP)
    assert engine.observe("leaf", gust, 0.5, BOWL_TOP).promoted_now == "MOTION"
    closed_at = spot_at = None
    t = 0.5
    while t < 400:
        t += 0.5
        decision = engine.observe("leaf", gust, t, BOWL_TOP)
        for c in engine.tick(t):
            closed_at = closed_at or (t, c.reason)
        if decision.action == "hit" and spot_at is None:
            spot_at = t
    assert closed_at is not None and closed_at[1] == "AUTOCLOSE_STILL" and 180 <= closed_at[0] <= 182
    assert spot_at is not None and 360 <= spot_at <= 365


def test_u6_a_bird_box_inside_the_bowl_spot_is_no_hit():
    engine = VisitEngine()
    learn_bowl(engine)
    assert engine.spot_for((0.30, 0.65, 0.67, 1.0)) is None  # 0.14 inside the 0.22 spot
    near = (0.21, 0.62, 0.78, 0.98)  # IoU about 0.9
    assert engine.spot_for(near) is not None


def test_u10_after_a_restart_the_bowl_is_a_hit_at_once_and_a_visit_continues(tmp_path):
    engine = VisitEngine()
    _, _ = learn_bowl(engine)
    t = 600.0
    cat = (0.40, 0.30, 0.55, 0.50)
    engine.observe("cat", (0.30, 0.30, 0.45, 0.50), t, CAT_AT_SPOT)
    assert engine.observe("cat", cat, t + 0.5, CAT_AT_SPOT).promoted_now == "MOTION"
    engine.close_all(t + 1)
    path = tmp_path / "scenery.json"
    engine.save(path, t + 1)
    fresh = VisitEngine()
    fresh.load(path, t + 30)
    assert fresh.observe("bowl-new", BOWL, t + 30, BOWL_TOP, "night").action == "hit"
    later = (0.42, 0.31, 0.57, 0.51)  # IoU about 0.6 with the last cat box
    again = fresh.observe("cat-new", later, t + 40, CAT_AT_SPOT)
    assert again.visit_id == "cat" and again.state == "visit"
    (closed,) = [c for c in fresh.close_all(t + 50) if c.visit_id == "cat"]
    assert closed.continuations == 1  # logged per visit for the night report


def test_u13_identity_promotes_a_still_animal_at_the_spot_but_not_the_bowl():
    engine = VisitEngine()
    learn_bowl(engine)
    results = [engine.observe("cat-at-bowl", BOWL, 700 + i, CAT_AT_SPOT) for i in range(6)]
    assert [r.action for r in results[:5]] == ["hit"] * 5
    assert results[5].promoted_now == "IDENTITY_AT_SPOT" and results[5].action == "record"
    bowl = [engine.observe("bowl-again", BOWL, 800 + i, BOWL_TOP) for i in range(6)]
    assert all(r.action == "hit" for r in bowl)


def test_u14_spots_are_forgotten_after_two_days_unless_hit():
    engine = VisitEngine()
    learn_bowl(engine)
    engine.observe("bowl-later", BOWL, 600 + 47 * 3600, BOWL_TOP)  # a hit refreshes the spot
    assert engine.spots
    engine.expire(600 + 47 * 3600 + 2 * 24 * 3600 + 1)
    assert not engine.spots


def test_a_bird_landing_twice_on_the_same_perch_is_never_a_spot():
    engine = VisitEngine()
    perch = (0.60, 0.40, 0.66, 0.46)
    for visit, start in enumerate((0.0, 600.0, 1200.0)):  # three landings 10 minutes apart
        track = f"bird{visit}"
        engine.observe(track, (0.70, 0.40, 0.76, 0.46), start, BIRD)  # flies in
        for i in range(1, 400):  # then sits on the perch, drinking, for over 3 minutes
            decision = engine.observe(track, perch, start + i * 0.5, BIRD)
            assert decision.action == "record" and decision.state == "visit"
        engine.tick(start + 400)
    # Promoted tracks never feed position memory: no spot, and nothing remembered at the
    # perch (only the arrival boxes, seen before each landing was a visit).
    assert not engine.spots
    assert not [p for p in engine.positions if p.box[0] < 0.65]


def test_glimpse_and_unidentified_hidden_reasons():
    engine = VisitEngine()
    engine.observe("g", (0.5, 0.5, 0.52, 0.52), 0.0, BIRD)
    (glimpse,) = engine.tick(11.0)
    assert glimpse.hidden == "GLIMPSE"
    engine.observe("u", (0.1, 0.5, 0.2, 0.6), 20.0, BOWL_TOP)
    engine.observe("u", (0.25, 0.5, 0.35, 0.6), 20.5, BOWL_TOP)
    (moved,) = engine.close_all(21.0)
    assert moved.promoted == "MOTION" and moved.hidden == "UNIDENTIFIED"
