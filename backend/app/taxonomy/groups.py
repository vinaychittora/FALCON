# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Groups for group-level Likely ("Cat (species uncertain)"): family for vertebrates
and other animals, order for insects. Built once from iNaturalist ancestor names and
stored as data/taxa/groups.json: {taxon_id: [group_id, group_name, display_name]}.

    python -m app.taxonomy.groups data/taxa/rajasthan_taxa.json data/taxa/groups.json
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.inaturalist.org/v1/taxa/"
INSECTS = 47158  # Insecta: grouped by order (Lepidoptera, Hymenoptera, Odonata, ...)


# Plain names for the groups a backyard in Kota sees most (iNaturalist's are plural or
# technical: "Felids", "Butterflies and Moths").
PLAIN = {
    "Felidae": "Cat", "Canidae": "Dog", "Viverridae": "Civet", "Herpestidae": "Mongoose",
    "Muridae": "Mouse or rat", "Soricidae": "Shrew", "Sciuridae": "Squirrel", "Erinaceidae": "Hedgehog",
    "Leporidae": "Hare", "Hystricidae": "Porcupine", "Pteropodidae": "Fruit bat", "Vespertilionidae": "Bat",
    "Gekkonidae": "Gecko", "Agamidae": "Agamid lizard", "Scincidae": "Skink", "Varanidae": "Monitor lizard",
    "Colubridae": "Colubrid snake", "Elapidae": "Cobra or krait", "Viperidae": "Viper",
    "Bufonidae": "Toad", "Dicroglossidae": "Frog", "Microhylidae": "Narrow-mouthed frog", "Ranidae": "Frog",
    "Columbidae": "Pigeon or dove", "Psittaculidae": "Parakeet", "Muscicapidae": "Flycatcher or chat",
    "Pycnonotidae": "Bulbul", "Leiothrichidae": "Babbler", "Sturnidae": "Myna or starling", "Corvidae": "Crow",
    "Passeridae": "Sparrow", "Nectariniidae": "Sunbird", "Phasianidae": "Peafowl, partridge or quail",
    "Accipitridae": "Hawk or eagle", "Strigidae": "Owl", "Ardeidae": "Heron or egret", "Picidae": "Woodpecker",
    "Lepidoptera": "Butterfly or moth", "Hymenoptera": "Bee, wasp or ant", "Odonata": "Dragonfly or damselfly",
    "Coleoptera": "Beetle", "Hemiptera": "True bug", "Orthoptera": "Grasshopper or cricket", "Diptera": "Fly",
    "Mantodea": "Mantis", "Salticidae": "Jumping spider",
}


def singular(name: str) -> str:
    """"Cats" -> "Cat", "Typical Owls" -> "Typical Owl"; leaves "Grass" and compound
    names ("Ducks, Geese, and Swans") alone."""
    if "," in name or " and " in name:
        return name
    words = name.split()
    last = words[-1]
    if last.endswith("ies") and len(last) > 4:
        last = last[:-3] + "y"
    elif last.endswith(("ches", "shes", "sses", "xes")):
        last = last[:-2]
    elif last.endswith("s") and not last.endswith(("ss", "us", "is")):
        last = last[:-1]
    return " ".join([*words[:-1], last])


def fetch(ids: list[int]) -> dict[int, dict]:
    found: dict[int, dict] = {}
    for start in range(0, len(ids), 30):
        chunk = ids[start:start + 30]
        request = urllib.request.Request(API + ",".join(map(str, chunk)), headers={"User-Agent": "FALCON-taxa/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            for item in json.load(response)["results"]:
                found[item["id"]] = {"rank": item.get("rank"), "name": item.get("name"),
                                     "common": item.get("preferred_common_name")}
        time.sleep(1.1)  # iNaturalist asks for at most about one request a second
    return found


def build(taxa_path: Path, out_path: Path) -> dict[str, list]:
    taxa = json.loads(taxa_path.read_text())["taxa"]
    ancestors = sorted({a for t in taxa for a in t.get("ancestry", [])[:-1]})
    known = fetch(ancestors)
    groups: dict[str, list] = {}
    for taxon in taxa:
        ancestry = taxon.get("ancestry", [])[:-1]
        rank = "order" if INSECTS in ancestry else "family"
        group_id = next((a for a in reversed(ancestry) if known.get(a, {}).get("rank") == rank), None)
        if group_id is None:  # no such rank in the lineage: the nearest named ancestor
            group_id = ancestry[-1] if ancestry else taxon["taxon_id"]
        info = known.get(group_id, {})
        common = singular(info.get("common") or info.get("name") or taxon["group"])
        display = PLAIN.get(info.get("name") or "", common[:1].upper() + common[1:])
        groups[str(taxon["taxon_id"])] = [group_id, info.get("name") or taxon["group"], display]
    out_path.write_text(json.dumps(groups, indent=0))
    return groups


if __name__ == "__main__":
    result = build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{len(result)} species, {len({g[0] for g in result.values()})} groups")
