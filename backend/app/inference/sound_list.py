# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""The birds FALCON names by sound: the birds recorded in Rajasthan (since 24 Nov 2026).

BirdNET still listens for every bird of North India (birdnet_north_india.txt), so nothing
is lost at the model. A call whose bird is not on this list is kept, but as "Unidentified
sound": BirdNET's guess stays on the record, the bout waits under Review's Hidden status
and is cleared after 7 days unless it is reviewed.

The list is a fixed file, made by scripts/birdnet_rajasthan.py from the Aves of
data/taxa/rajasthan_taxa.json and the BirdNET labels. Nothing here may import beyond the
standard library: the script runs in the BirdNET environment.
"""

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

RAJASTHAN_LIST = Path(__file__).with_name("birdnet_rajasthan.txt")
# BirdNET's English name -> the Rajasthan list's, where the two disagree on both names.
# Rajasthan's Rock Eagle-Owl is a different species from BirdNET's Eurasian Eagle-Owl,
# so that one stays out.
PAIRS = {
    "Barn Owl": "Eastern Barn Owl",
    "Cattle Egret": "Eastern Cattle-Egret",
    "Striated Heron": "Little Heron",
    "Lesser Sand-Plover": "Tibetan Sand-Plover",
}
# Not pairs: BirdNET has no Woolly-necked Stork, and its Red-rumped Swallow (Cecropis
# daurica) is on the Rajasthan list by its own name already.


def plain(name: str | None) -> str:
    """An English name for matching: no case, hyphens or spaces, Grey read as Gray."""
    return re.sub(r"[\s\-]", "", (name or "").casefold().replace("grey", "gray"))


def build(labels: Iterable[str], aves: Iterable[tuple[str, str | None]]) -> list[str]:
    """The BirdNET labels ("Scientific_Common") of the birds in `aves` (scientific, common).

    A label is on the list when its species is among them by scientific name; else by
    English name when exactly one entry on each side carries it; else by PAIRS."""
    birds = [label for label in labels if "_" in label]
    aves = list(aves)
    scientific = {name.casefold() for name, _ in aves}
    chosen = {label for label in birds if label.split("_", 1)[0].casefold() in scientific}
    matched = {label.split("_", 1)[0].casefold() for label in chosen}
    by_name: dict[str, list[str]] = defaultdict(list)
    for label in birds:
        by_name[plain(label.split("_", 1)[1])].append(label)
    local_names: dict[str, list[str]] = defaultdict(list)
    for name, common in aves:
        local_names[plain(common)].append(name)
    taken = {name.casefold() for name, _ in aves if name.casefold() in matched}
    for name, common in aves:
        key = plain(common)
        if not key or name.casefold() in taken or len(local_names[key]) != 1 or len(by_name.get(key, [])) != 1:
            continue
        label = by_name[key][0]
        if label.split("_", 1)[0].casefold() not in matched:
            chosen.add(label)
    commons = {plain(common) for _, common in aves}
    for theirs, ours in PAIRS.items():
        if plain(ours) in commons:
            chosen.update(by_name.get(plain(theirs), []))
    return sorted(chosen)


_names: frozenset[str] | None = None
_warned = False


def rajasthan_names(path: Path | None = None) -> frozenset[str] | None:
    """Scientific names (case-folded) on the list, or None when the file cannot be read:
    then every call is named as before, with one warning in the log. Never an empty list."""
    global _names, _warned
    if path is None and _names is not None:
        return _names
    try:
        lines = (path or RAJASTHAN_LIST).read_text(encoding="utf-8").splitlines()
        names = frozenset(line.split("_", 1)[0].strip().casefold() for line in lines if "_" in line)
        if not names:
            raise ValueError("the list is empty")
    except (OSError, UnicodeError, ValueError) as exc:
        if not _warned:
            logger.warning("Rajasthan sound list unreadable (%s); sounds are named as before", exc)
            _warned = True
        return None
    if path is None:
        _names = names
    return names


def outside_area(scientific: str, names: frozenset[str] | None) -> bool | None:
    """True for a bird not recorded in Rajasthan; None when the list is unavailable."""
    if names is None:
        return None
    return scientific.casefold() not in names
