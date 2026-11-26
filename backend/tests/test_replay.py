# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from app.research.replay import BaselineEngine, Obs, fb_checks, run
from app.schemas import AnalysisSettings

CONFIG = AnalysisSettings(species_threshold=0.33, still_object_minutes=3)
CAT = [(41948, "Rusty-spotted Cat", "Mammalia", 0.48), (2, "Civet", "Mammalia", 0.45), (3, "x", "Mammalia", 0.40),
       (4, "y", "Mammalia", 0.39), (5, "z", "Mammalia", 0.38)]
BOWL = [(1, "Frog", "Amphibia", 0.41), (2, "Otter", "Mammalia", 0.39), (3, "Bee", "Hymenoptera", 0.38),
        (4, "Gecko", "Reptilia", 0.37), (5, "Frog 2", "Amphibia", 0.36)]


def obs(t: float, box, top, label: str, track: str = "t1", detector: float = 0.8) -> Obs:
    return Obs(t=t, job="job", track=track, box=box, detector=detector, top=top, classified=True,
               light="night", event_id=f"{track}-{t}", label=label)


def test_floor_filters_and_engine_forms_visits():
    stream = [obs(i * 0.5, (0.4 + i * 0.02, 0.5, 0.5 + i * 0.02, 0.6), CAT, "cat") for i in range(8)]
    stream.append(obs(5.0, (0.9, 0.5, 0.95, 0.55), BOWL, "hood", track="t2", detector=0.6))
    visits, fed = run(BaselineEngine(CONFIG), stream, floor=0.75)
    assert fed == 8 and len(visits) == 1
    assert visits[0].tier == "likely" and visits[0].bell_at is not None


def test_fb_checks_read_cat_hood_and_glimpses():
    stream = [obs(i * 0.5, (0.4 + i * 0.02, 0.5, 0.5 + i * 0.02, 0.6), CAT, "cat") for i in range(8)]
    stream += [obs(100.0 + i * 30, (0.91, 0.46, 0.97, 0.61), BOWL, "hood", track=f"h{i}") for i in range(3)]
    stream += [obs(500.0 + i * 60, (0.39 + i * 0.03, 0.69, 0.45 + i * 0.03, 0.75), BOWL, "small-animal",
                   track=f"s{i}") for i in range(5)]
    engine = BaselineEngine(CONFIG)
    visits, _ = run(engine, stream, floor=0.5)
    results = {name: ok for name, ok, _ in fb_checks(engine, visits, stream)}
    assert results["cat: 1 visit"] and results["cat: Likely"] and results["cat: 1 bell"]
    assert results["23:42 animal: every box kept, hidden, no bell"]
    assert results["23:42 animal: no spot within 0.1 frame"]
    assert results["hood: 0 visits"]  # one-frame hood tracks are glimpses
