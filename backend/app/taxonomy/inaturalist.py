import hashlib
import json
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, Field, field_validator

from app.taxonomy.cache import atomic_json

DEFAULT_LIMITS = {
    "Aves": 1000,
    "Mammalia": 1000,
    "Reptilia": 1000,
    "Amphibia": 1000,
    "Lepidoptera": 1000,
    "Odonata": 1000,
    "Hymenoptera": 1000,
    "Insecta": 1000,
    "Arachnida": 1000,
}


class Taxon(BaseModel):
    taxon_id: int
    scientific_name: str
    common_name: str | None = None
    rank: str = "species"
    group: str
    iconic_group: str
    observation_count: int
    ancestry: list[int] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=lambda: ["regional_research_observations"])


class GroupCoverage(BaseModel):
    query_taxon_id: int
    api_total_species: int | None = None
    scanned_species: int = 0
    eligible_species: int = 0
    selected_species: int = 0
    excluded_by_minimum: int = 0
    excluded_other_group: int = 0
    excluded_invalid_or_duplicate: int = 0
    omitted_by_limit: int = 0
    scan_complete: bool = True
    truncated: bool = False


class TaxaCache(BaseModel):
    version: str = "empty"
    refreshed_at: str | None = None
    place_id: int | None = None
    place_name: str = "Rajasthan, India"
    taxa: list[Taxon] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=lambda: DEFAULT_LIMITS.copy())
    minimum_observations: int = 1
    coverage: dict[str, GroupCoverage] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    additional_taxon_ids: list[int] = Field(default_factory=list)
    coverage_basis: str = "Rajasthan research-grade photo observations; active species only"
    refreshing: bool = False
    error: str | None = None


class RefreshRequest(BaseModel):
    limits: dict[str, int] = Field(default_factory=lambda: DEFAULT_LIMITS.copy())
    minimum_observations: int = Field(default=1, ge=1, le=10000)
    # Omitted preserves existing explicit selections during refresh. [] clears them.
    additional_taxon_ids: list[Annotated[int, Field(gt=0)]] | None = Field(
        default=None, max_length=100
    )

    @field_validator("limits")
    @classmethod
    def valid_limits(cls, limits: dict[str, int]) -> dict[str, int]:
        if set(limits) - set(DEFAULT_LIMITS) or any(n < 0 or n > 1000 for n in limits.values()):
            raise ValueError("Limits must be 0–1000 for supported groups")
        return limits


class INaturalist:
    """Only aggregate endpoints: no observation coordinates or photo downloads."""

    def __init__(self, cache_dir: Path, client: httpx.Client | None = None, interval: float = 1.1):
        self.cache_dir = cache_dir
        self.client = client or httpx.Client(
            base_url="https://api.inaturalist.org/v1/",
            timeout=45,
            headers={
                "User-Agent": "FALCON/0.2 (local open-source wildlife research; aggregate taxa cache)"
            },
        )
        self.interval = interval
        self.last_request = 0.0

    def get(self, path: str, params: dict[str, Any], refresh: bool = False) -> dict[str, Any]:
        key = hashlib.sha256(json.dumps([path, params], sort_keys=True).encode()).hexdigest()
        target = self.cache_dir / f"{key}.json"
        if not refresh and target.exists() and time.time() - target.stat().st_mtime < 7 * 86400:
            return json.loads(target.read_text())
        for attempt in range(4):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            response = self.client.get(path, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    retry = response.headers.get("Retry-After", "")
                    time.sleep(min(60, float(retry) if retry.isdigit() else 2 ** (attempt + 1)))
                    continue
            response.raise_for_status()
            value: dict[str, Any] = response.json()
            atomic_json(target, value)
            return value
        raise RuntimeError("iNaturalist request failed")

    def build(self, request: RefreshRequest, refresh: bool = False) -> TaxaCache:
        places = self.get("places/autocomplete", {"q": "Rajasthan"}, refresh)["results"]
        matches = [
            p
            for p in places
            if p["name"] == "Rajasthan"
            and p.get("display_name") in {"Rajasthan, IN", "Rajasthan, India"}
            and p.get("admin_level") == 10
        ]
        if len(matches) != 1:
            raise ValueError("Could not unambiguously resolve Rajasthan, India")
        place = matches[0]
        taxa: dict[int, Taxon] = {}
        names: set[str] = set()
        group_ids: dict[str, int] = {}
        # Resolve even disabled groups: a disabled named insect order must not be
        # silently reintroduced through the broader Insecta query.
        for group in request.limits:
            results = self.get("taxa/autocomplete", {"q": group, "is_active": "true"}, refresh)[
                "results"
            ]
            matches = [t for t in results if t["name"] == group and t.get("is_active", True)]
            if len(matches) != 1:
                raise ValueError(f"Could not resolve taxon {group}")
            group_ids[group] = matches[0]["id"]
        coverage: dict[str, GroupCoverage] = {}
        warnings: list[str] = []
        for group, limit in request.limits.items():
            if not limit:
                warnings.append(f"{group} is disabled in this candidate list.")
                continue
            group_id = group_ids[group]
            stats = GroupCoverage(query_taxon_id=group_id)
            coverage[group] = stats
            seen_in_group: set[int] = set()
            for page in range(1, 51):
                data = self.get(
                    "observations/species_counts",
                    {
                        "place_id": place["id"],
                        "taxon_id": group_id,
                        "quality_grade": "research",
                        "photos": "true",
                        "rank": "species",
                        "per_page": 200,
                        "page": page,
                    },
                    refresh,
                )
                rows = data["results"]
                stats.api_total_species = data.get("total_results")
                stats.scanned_species += len(rows)
                for row in rows:
                    t = row["taxon"]
                    if row["count"] < request.minimum_observations:
                        stats.excluded_by_minimum += 1
                        continue
                    if (
                        t.get("rank") != "species"
                        or not t.get("is_active", True)
                        or t["id"] in seen_in_group
                    ):
                        stats.excluded_invalid_or_duplicate += 1
                        continue
                    seen_in_group.add(t["id"])
                    ancestry = self.ancestry(t)
                    if group == "Insecta" and any(
                        group_ids.get(order) in ancestry
                        for order in ("Lepidoptera", "Odonata", "Hymenoptera")
                        if order in group_ids
                    ):
                        stats.excluded_other_group += 1
                        continue
                    if t["id"] in taxa or t["name"] in names:
                        stats.excluded_invalid_or_duplicate += 1
                        continue
                    stats.eligible_species += 1
                    if stats.selected_species >= limit:
                        stats.omitted_by_limit += 1
                        continue
                    taxa[t["id"]] = self.to_taxon(t, group, row["count"])
                    names.add(t["name"])
                    stats.selected_species += 1
                # Count all eligible taxa even after the requested cap is reached.
                # This makes cap omissions visible rather than calling a top-N list complete.
                if (
                    len(rows) < 200
                    or (
                        stats.api_total_species is not None
                        and stats.scanned_species >= stats.api_total_species
                    )
                    or (rows and rows[-1]["count"] < request.minimum_observations)
                ):
                    break
            else:
                stats.scan_complete = False
            stats.truncated = bool(stats.omitted_by_limit) or not stats.scan_complete
            if stats.omitted_by_limit:
                warnings.append(
                    f"{group}: {stats.omitted_by_limit} eligible species omitted by the {limit} cap."
                )
            if not stats.scan_complete:
                warnings.append(
                    f"{group}: API scan stopped at 10,000 rows; coverage is incomplete."
                )
        additional_ids = sorted(set(request.additional_taxon_ids or []))
        for taxon_id in additional_ids:
            if taxon_id in taxa:
                taxa[taxon_id].provenance.append("explicit_taxon_selection")
                continue
            results = self.get(f"taxa/{taxon_id}", {}, refresh)["results"]
            if len(results) != 1 or results[0]["id"] != taxon_id:
                raise ValueError(f"Could not resolve explicit taxon {taxon_id}")
            t = results[0]
            if t.get("rank") != "species" or not t.get("is_active", True):
                raise ValueError(
                    f"Explicit taxon {taxon_id} must be an active species, not a genus or synonym"
                )
            supported = [a["name"] for a in t.get("ancestors", []) if a["name"] in DEFAULT_LIMITS]
            group = supported[-1] if supported else t.get("iconic_taxon_name")
            if group not in DEFAULT_LIMITS:
                raise ValueError(
                    f"Explicit taxon {taxon_id} is outside the supported wildlife groups"
                )
            counts = self.get(
                "observations/species_counts",
                {
                    "place_id": place["id"],
                    "taxon_id": taxon_id,
                    "quality_grade": "research",
                    "photos": "true",
                    "rank": "species",
                    "per_page": 200,
                    "page": 1,
                },
                refresh,
            )["results"]
            count = sum(r["count"] for r in counts if r["taxon"]["id"] == taxon_id)
            taxon = self.to_taxon(t, group, count)
            taxon.provenance = (["regional_research_observations"] if count else []) + [
                "explicit_taxon_selection"
            ]
            if t["name"] in names:
                raise ValueError(
                    f"Explicit taxon {taxon_id} duplicates an existing scientific name"
                )
            taxa[taxon_id] = taxon
            names.add(t["name"])
            if not count:
                warnings.append(
                    f"{t['name']} was explicitly included; no matching Rajasthan research-photo "
                    "observations were returned. This is not evidence of local occurrence."
                )
        if not taxa:
            raise ValueError("iNaturalist returned no eligible species; prior cache preserved")
        values = sorted(
            taxa.values(), key=lambda t: (t.group, -t.observation_count, t.scientific_name)
        )
        version = hashlib.sha256(
            json.dumps([t.model_dump() for t in values], sort_keys=True).encode()
        ).hexdigest()[:16]
        return TaxaCache(
            version=version,
            refreshed_at=datetime.now(UTC).isoformat(),
            place_id=place["id"],
            taxa=values,
            counts=dict(Counter(t.group for t in values)),
            limits=request.limits,
            minimum_observations=request.minimum_observations,
            coverage=coverage,
            warnings=warnings,
            additional_taxon_ids=additional_ids,
        )

    @staticmethod
    def ancestry(taxon: dict[str, Any]) -> list[int]:
        return taxon.get("ancestor_ids") or [
            int(i) for i in (taxon.get("ancestry") or "").split("/") if i
        ]

    @classmethod
    def to_taxon(cls, taxon: dict[str, Any], group: str, count: int) -> Taxon:
        return Taxon(
            taxon_id=taxon["id"],
            scientific_name=taxon["name"],
            common_name=taxon.get("preferred_common_name"),
            group=group,
            iconic_group=taxon.get("iconic_taxon_name", group),
            observation_count=count,
            ancestry=cls.ancestry(taxon),
        )


class TaxaService:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "taxa" / "rajasthan_taxa.json"
        self.cache_dir = data_dir / "cache" / "inat"
        self.lock = threading.Lock()
        self.error: str | None = None

    def read(self) -> TaxaCache:
        result = (
            TaxaCache.model_validate_json(self.path.read_text())
            if self.path.exists()
            else TaxaCache()
        )
        result.refreshing = self.lock.locked()
        result.error = self.error
        return result

    def refresh(self, request: RefreshRequest, force: bool = True) -> TaxaCache:
        if not self.lock.acquire(blocking=False):
            raise ValueError("Taxa refresh already running")
        self.error = None
        client = INaturalist(self.cache_dir)
        try:
            if request.additional_taxon_ids is None:
                request = request.model_copy(
                    update={
                        "additional_taxon_ids": self.read().additional_taxon_ids,
                    }
                )
            result = client.build(request, refresh=force)
            atomic_json(self.path, result.model_dump())
            return result
        except Exception as exc:
            self.error = str(exc)
            raise
        finally:
            client.client.close()
            self.lock.release()
