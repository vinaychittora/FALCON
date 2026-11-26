# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Domestic and feral animals that research-grade wildlife lists leave out.

iNaturalist marks captive and domestic animals as casual, so a regional
research-grade list has no cattle, goats, camels or dogs. Without them, the
classifier must force a cow onto the nearest wild species (for example nilgai).
`make taxa ARGS=--include-domestic` adds these species explicitly, and labels mark
them as domestic so they are never presented as wild candidates.
"""

from typing import Any, Protocol


class TaxonLookup(Protocol):
    def __call__(self, path: str, params: dict[str, Any]) -> dict[str, Any]: ...


DOMESTIC_SPECIES = {
    "Canis familiaris": "Domestic dog",
    "Felis catus": "Domestic cat",
    "Bos taurus": "Cattle",
    "Bubalus bubalis": "Domestic water buffalo",
    "Capra hircus": "Domestic goat",
    "Ovis aries": "Domestic sheep",
    "Camelus dromedarius": "Dromedary camel",
    "Equus asinus": "Donkey",
    "Equus caballus": "Horse",
}
_NAMES = {name.casefold() for name in DOMESTIC_SPECIES}


def is_domestic(scientific_name: str | None) -> bool:
    return scientific_name is not None and scientific_name.casefold() in _NAMES


def resolve_domestic_ids(lookup: TaxonLookup) -> tuple[list[int], list[str]]:
    """Resolve the preset to active iNaturalist species IDs by exact scientific name."""
    ids: list[int] = []
    missing: list[str] = []
    for name in DOMESTIC_SPECIES:
        results = lookup("taxa", {"q": name, "rank": "species", "is_active": "true", "per_page": 30})
        matches = [
            item["id"] for item in results.get("results", [])
            if str(item.get("name", "")).casefold() == name.casefold() and item.get("rank") == "species"
        ]
        if len(matches) == 1:
            ids.append(int(matches[0]))
        else:
            missing.append(name)
    return sorted(set(ids)), missing
