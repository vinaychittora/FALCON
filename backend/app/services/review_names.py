# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Resolve legacy correction labels for display without changing scientific evidence."""

import zlib
from collections.abc import Sequence
from functools import lru_cache
from typing import TypeVar, cast

from app.inference.birdnet import north_india_labels
from app.schemas import AudioEvent, VisualEvent
from app.taxonomy.inaturalist import TaxaService, Taxon

Observation = TypeVar("Observation", bound=VisualEvent | AudioEvent)


@lru_cache(maxsize=1)
def north_india_names() -> dict[str, str]:
    """Scientific to common name for every bird on the North India sound list."""
    pairs = (label.split("_", 1) for label in sorted(north_india_labels()))
    return {pair[0]: pair[1] for pair in pairs if len(pair) == 2}


def review_birds(known: Sequence[Taxon]) -> list[Taxon]:
    """Sound-list birds a reviewer may name that the local species list lacks.

    These are for naming records only. The camera classifier keeps reading the local list,
    so they never change what it can choose. A bird the local list holds under a newer
    scientific name is matched by its common name and not offered twice. The id is negative
    so it can never meet a real iNaturalist id, and stays the same between runs.
    """
    scientific = {taxon.scientific_name.casefold() for taxon in known}
    common = {taxon.common_name.casefold() for taxon in known if taxon.common_name}
    return [
        Taxon(
            taxon_id=-(zlib.crc32(name.casefold().encode()) + 1), scientific_name=name,
            common_name=label, group="Aves", iconic_group="Aves", observation_count=0,
            provenance=["north_india_sound_list"],
        )
        for name, label in north_india_names().items()
        if name.casefold() not in scientific and label.casefold() not in common
    ]


def review_taxa(taxonomy: TaxaService) -> list[Taxon]:
    """Every species a reviewer may name: the local list, then the added sound-list birds."""
    taxa = list(taxonomy.read().taxa)
    return taxa + review_birds(taxa)


def resolve_review_names(
    events: Sequence[Observation], taxonomy: TaxaService
) -> list[Observation]:
    pending = [
        event for event in events
        if event.review.status == "corrected" and not event.review.corrected_common_name
    ]
    if not pending:
        return list(events)
    taxa = review_taxa(taxonomy)
    by_id = {taxon.taxon_id: taxon for taxon in taxa}
    by_scientific = {taxon.scientific_name.casefold(): taxon for taxon in taxa}
    result = []
    for event in events:
        review = event.review
        if review.status == "corrected" and not review.corrected_common_name:
            taxon = by_id.get(review.corrected_taxon_id) if review.corrected_taxon_id else None
            if taxon is None and review.corrected_scientific_name:
                taxon = by_scientific.get(review.corrected_scientific_name.casefold())
            if taxon and taxon.common_name:
                # Copies affect this response only. Keep the original reviewer
                # decision, timestamp, audit, and model evidence intact.
                event = cast(Observation, event.model_copy(update={
                    "review": review.model_copy(update={"corrected_common_name": taxon.common_name})
                }))
        result.append(event)
    return result
