# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
from app.inference.base import Proposal
from app.inference.pipeline import SECOND_BOX_FLOOR, second_boxes


def test_a_fainter_animal_next_to_a_confident_one_is_kept():
    robin = Proposal((0.50, 0.50, 0.60, 0.60), 0.80)
    sparrow = Proposal((0.38, 0.52, 0.42, 0.56), 0.42)  # beside the robin, fainter
    far = Proposal((0.02, 0.02, 0.05, 0.05), 0.42)  # fainter and far away: a leaf
    weakest = Proposal((0.45, 0.50, 0.48, 0.53), SECOND_BOX_FLOOR - 0.05)
    person = Proposal((0.40, 0.40, 0.45, 0.60), 0.42, "person")
    kept = second_boxes([robin, sparrow, far, weakest, person], 0.5)
    assert kept == [robin, sparrow]


def test_without_a_confident_animal_nothing_faint_enters():
    alone = Proposal((0.38, 0.52, 0.42, 0.56), 0.45)
    assert second_boxes([alone], 0.5) == []
    # Proposals without a score (motion blobs) pass as before.
    blob = Proposal((0.1, 0.1, 0.2, 0.2), None, "motion")
    assert second_boxes([blob], 0.5) == [blob]
