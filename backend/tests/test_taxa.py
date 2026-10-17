from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.taxonomy.cache import atomic_json
from app.taxonomy.inaturalist import INaturalist, RefreshRequest, TaxaCache, TaxaService


def test_taxa_resolution_dedup_and_response_cache(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("places/autocomplete"):
            results = [
                {"name": "Rajasthan", "display_name": "Rajasthan, IN", "admin_level": 10, "id": 99}
            ]
        elif request.url.path.endswith("taxa/autocomplete"):
            results = [{"id": 3, "name": "Aves", "is_active": True}]
        else:
            assert request.url.params["place_id"] == "99"
            assert request.url.params["quality_grade"] == "research"
            results = [
                {
                    "count": 10,
                    "taxon": {"id": 1, "name": "Test bird", "rank": "species", "is_active": True},
                },
                {"count": 9, "taxon": {"id": 1, "name": "Test bird", "rank": "species"}},
                {
                    "count": 8,
                    "taxon": {"id": 2, "name": "Inactive", "rank": "species", "is_active": False},
                },
                {"count": 7, "taxon": {"id": 3, "name": "A genus", "rank": "genus"}},
                {"count": 1, "taxon": {"id": 4, "name": "Too rare", "rank": "species"}},
            ]
        return httpx.Response(200, json={"results": results})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.inaturalist.org/v1/"
    ) as client:
        api = INaturalist(tmp_path, client, interval=0)
        request = RefreshRequest(limits={"Aves": 200}, minimum_observations=3)
        result = api.build(request)
        assert len(result.taxa) == 1 and result.place_id == 99
        assert result.taxa[0].scientific_name == "Test bird"
        api.build(request)
        assert len(calls) == 3


def _place() -> dict:
    return {"name": "Rajasthan", "display_name": "Rajasthan, IN", "admin_level": 10, "id": 99}


def _row(taxon_id: int, count: int = 1, **extra: object) -> dict:
    return {
        "count": count,
        "taxon": {
            "id": taxon_id,
            "name": f"Species {taxon_id}",
            "rank": "species",
            "is_active": True,
            **extra,
        },
    }


def test_small_cap_reports_omitted_species_across_pages(tmp_path: Path) -> None:
    pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("places/autocomplete"):
            return httpx.Response(200, json={"results": [_place()]})
        if request.url.path.endswith("taxa/autocomplete"):
            return httpx.Response(200, json={"results": [{"id": 3, "name": "Aves"}]})
        page = int(request.url.params["page"])
        pages.append(page)
        rows = [_row(i) for i in range(1, 201)] if page == 1 else [_row(201)]
        return httpx.Response(200, json={"total_results": 201, "results": rows})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test/"
    ) as client:
        result = INaturalist(tmp_path, client, interval=0).build(RefreshRequest(limits={"Aves": 2}))
    assert pages == [1, 2]
    assert len(result.taxa) == 2
    stats = result.coverage["Aves"]
    assert stats.eligible_species == 201
    assert stats.omitted_by_limit == 199 and stats.truncated and stats.scan_complete
    assert "199 eligible species omitted" in result.warnings[0]


def test_default_includes_one_observation_and_unrepresented_insect_orders(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("places/autocomplete"):
            return httpx.Response(200, json={"results": [_place()]})
        if request.url.path.endswith("taxa/autocomplete"):
            group = request.url.params["q"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": {"Insecta": 100, "Hymenoptera": 101}[group],
                            "name": group,
                        }
                    ]
                },
            )
        # Both records are returned from the class query, but the explicit disabled
        # bee/wasp order must remain disabled instead of leaking through Insecta.
        assert request.url.params["taxon_id"] == "100"
        return httpx.Response(
            200,
            json={
                "total_results": 2,
                "results": [
                    _row(1, ancestor_ids=[100, 101]),
                    _row(2, ancestor_ids=[100, 102]),
                ],
            },
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test/"
    ) as client:
        result = INaturalist(tmp_path, client, interval=0).build(
            RefreshRequest(limits={"Insecta": 1000, "Hymenoptera": 0})
        )
    assert [t.taxon_id for t in result.taxa] == [2]
    assert result.taxa[0].observation_count == 1
    assert result.coverage["Insecta"].excluded_other_group == 1
    assert result.coverage["Insecta"].truncated is False
    assert any("Hymenoptera is disabled" in warning for warning in result.warnings)


def test_explicit_species_has_honest_nonregional_provenance(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("places/autocomplete"):
            return httpx.Response(200, json={"results": [_place()]})
        if request.url.path.endswith("taxa/100"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        _row(
                            100,
                            ancestors=[{"name": "Insecta"}, {"name": "Hymenoptera"}],
                            iconic_taxon_name="Insecta",
                            ancestor_ids=[10, 20],
                        )["taxon"]
                    ]
                },
            )
        assert request.url.params["taxon_id"] == "100"
        return httpx.Response(200, json={"results": []})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test/"
    ) as client:
        result = INaturalist(tmp_path, client, interval=0).build(
            RefreshRequest(limits={}, additional_taxon_ids=[100, 100])
        )
    assert result.additional_taxon_ids == [100]
    assert result.taxa[0].group == "Hymenoptera"
    assert result.taxa[0].observation_count == 0
    assert result.taxa[0].provenance == ["explicit_taxon_selection"]
    assert "not evidence of local occurrence" in result.warnings[0]


@pytest.mark.parametrize("rank, active", [("genus", True), ("species", False)])
def test_explicit_selection_rejects_genus_and_inactive_synonym(
    tmp_path: Path,
    rank: str,
    active: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("places/autocomplete"):
            return httpx.Response(200, json={"results": [_place()]})
        return httpx.Response(
            200, json={"results": [_row(100, rank=rank, is_active=active)["taxon"]]}
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://example.test/"
    ) as client:
        with pytest.raises(ValueError, match="active species"):
            INaturalist(tmp_path, client, interval=0).build(
                RefreshRequest(limits={}, additional_taxon_ids=[100])
            )


def test_refresh_request_rejects_unsupported_limits() -> None:
    with pytest.raises(ValidationError, match="supported groups"):
        RefreshRequest(limits={"made-up-group": 12})
    with pytest.raises(ValidationError, match="supported groups"):
        RefreshRequest(limits={"Aves": 1001})


def test_refresh_retains_explicit_selections_and_preserves_cache_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TaxaService(tmp_path)
    original = TaxaCache(version="before", additional_taxon_ids=[123])
    atomic_json(service.path, original.model_dump())
    captured = []

    def build(self: INaturalist, request: RefreshRequest, refresh: bool = False) -> TaxaCache:
        captured.append(request.additional_taxon_ids)
        return original.model_copy(update={"version": "after"})

    monkeypatch.setattr(INaturalist, "build", build)
    service.refresh(RefreshRequest(limits={"Aves": 1000}))
    assert captured == [[123]]
    assert service.read().version == "after"
    previous = service.path.read_bytes()

    def fail(self: INaturalist, request: RefreshRequest, refresh: bool = False) -> TaxaCache:
        raise ValueError("Provider unavailable")

    monkeypatch.setattr(INaturalist, "build", fail)
    with pytest.raises(ValueError, match="Provider unavailable"):
        service.refresh(RefreshRequest())
    assert service.path.read_bytes() == previous
    assert service.read().error == "Provider unavailable"
    assert service.read().refreshing is False
