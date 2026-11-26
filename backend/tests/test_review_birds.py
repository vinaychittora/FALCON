# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Review can name every North India sound-list bird; the classifier's list stays as it is."""

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import AudioEvent
from app.services.review_names import north_india_names, review_birds
from app.taxonomy.inaturalist import TaxaCache, Taxon

ROBIN = Taxon(taxon_id=7, scientific_name="Copsychus saularis", common_name="Oriental Magpie-Robin",
              group="Aves", iconic_group="Aves", observation_count=5)
SHIKRA = Taxon(taxon_id=8, scientific_name="Tachyspiza badia", common_name="Shikra",
               group="Aves", iconic_group="Aves", observation_count=5)
SEDGE = "Acrocephalus schoenobaenus"


def heard() -> AudioEvent:
    return AudioEvent(
        job_id="job", source_id="a" * 24, source_filename="node", start_ms=0, end_ms=3000,
        scientific_name="Passer domesticus", common_name="House Sparrow", confidence=0.7, models={},
    )


def test_added_birds_skip_the_local_list_and_have_lasting_unique_ids() -> None:
    birds = review_birds([ROBIN, SHIKRA])
    names = {bird.scientific_name for bird in birds}
    assert SEDGE in names and ROBIN.scientific_name not in names
    assert "Accipiter badius" in north_india_names() and "Accipiter badius" not in names
    ids = [bird.taxon_id for bird in birds]
    assert len(set(ids)) == len(ids) and max(ids) < 0
    assert ids == [bird.taxon_id for bird in review_birds([ROBIN, SHIKRA])]


def test_a_sound_record_can_be_corrected_to_an_added_bird(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        cache = TaxaCache(taxa=[ROBIN, SHIKRA])
        app.state.taxa = SimpleNamespace(read=lambda: cache)
        app.state.events.append(heard())
        encounter = client.get("/api/detections/encounters").json()["encounters"][0]["encounter_id"]

        # The classifier's list is untouched; the extra names come from their own route.
        assert [t["taxon_id"] for t in client.get("/api/taxa").json()["taxa"]] == [7, 8]
        birds = client.get("/api/taxa/review-birds").json()
        sedge = next(b for b in birds if b["scientific_name"] == SEDGE)
        assert sedge["common_name"] == "Sedge Warbler"

        def correct(taxon_id: int) -> int:
            return client.post("/api/detections/encounters/review", json={
                "encounter_ids": [encounter],
                "review": {"status": "corrected", "corrected_taxon_id": taxon_id},
            }).status_code

        assert correct(sedge["taxon_id"]) == 200
        review = client.get("/api/detections").json()["events"][0]["review"]
        assert review["corrected_scientific_name"] == SEDGE
        assert review["corrected_common_name"] == "Sedge Warbler"
        assert client.get("/api/detections", params={"q": "sedge warbler"}).json()["total"] == 1

        assert correct(ROBIN.taxon_id) == 200  # corrections to local species work as before
        review = client.get("/api/detections").json()["events"][0]["review"]
        assert review["corrected_scientific_name"] == ROBIN.scientific_name
        assert correct(-1) == 422
