"""Resolve legacy correction labels for display without changing scientific evidence."""

from collections.abc import Sequence
from typing import TypeVar, cast

from app.schemas import AudioEvent, VisualEvent
from app.taxonomy.inaturalist import TaxaService

Observation = TypeVar("Observation", bound=VisualEvent | AudioEvent)


def resolve_review_names(
    events: Sequence[Observation], taxonomy: TaxaService
) -> list[Observation]:
    pending = [
        event for event in events
        if event.review.status == "corrected" and not event.review.corrected_common_name
    ]
    if not pending:
        return list(events)
    taxa = taxonomy.read().taxa
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
