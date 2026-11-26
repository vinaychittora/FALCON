# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from app.inference.insects import InsectNight
from app.schemas import AnalysisSettings

MOTH = ["Lepidoptera", "Lepidoptera", "Insecta", "Aves", "Lepidoptera"]
CAT = ["Mammalia", "Mammalia", "Mammalia", "Mammalia", "Mammalia"]
BAT_OR_MOTH = ["Mammalia", "Lepidoptera", "Insecta", "Lepidoptera", "Mammalia"]  # top-1 a bat


def visit(frames: list[list[str] | None], night: bool = True) -> InsectNight:
    stats = InsectNight()
    for groups in frames:
        stats.add(night, groups)
    return stats


def test_an_insect_at_night_is_hidden():
    assert visit([MOTH] * 4 + [CAT]).hidden


def test_most_of_the_top_five_insect_hides_it_too():
    assert visit([BAT_OR_MOTH] * 3).hidden


def test_a_tiny_unclassified_visit_at_night_counts_as_an_insect():
    assert visit([None, None]).hidden


def test_animals_at_night_and_insects_by_day_stay():
    assert not visit([CAT] * 5).hidden  # cats, rodents, geckos, bats: never affected
    assert not visit([["Aves"] * 5] * 5).hidden  # owls, nightjars
    assert not visit([MOTH] * 5, night=False).hidden  # by day nothing changes


def test_the_rule_is_fixed_not_a_setting():
    assert "ignore_insects_at_night" not in AnalysisSettings.model_fields
