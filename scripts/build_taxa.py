import argparse
import json

from app.config import settings
from app.taxonomy.domestic import resolve_domestic_ids
from app.taxonomy.inaturalist import DEFAULT_LIMITS, INaturalist, RefreshRequest, TaxaService

parser = argparse.ArgumentParser(
    description="Build the local species list from official iNaturalist research-grade aggregates"
)
parser.add_argument(
    "--place",
    help='iNaturalist place for the species list, e.g. "Kerala, India", "Kenya" or a numeric place '
    "ID (default: the current list's place, initially Rajasthan, India)",
)
parser.add_argument("--minimum-observations", type=int, default=1)
parser.add_argument(
    "--limits",
    help='JSON mapping of groups to species counts; null = no limit (default for every group), '
    '0 = leave the group out, e.g. \'{"Insecta": 0}\'',
)
selection = parser.add_mutually_exclusive_group()
selection.add_argument(
    "--include-taxon",
    type=int,
    action="append",
    default=None,
    help="Include a verified active iNaturalist species ID; repeat to select several. "
    "Selections are retained on later refreshes. No local-occurrence claim is made.",
)
selection.add_argument(
    "--clear-included", action="store_true", help="Clear explicit taxon selections"
)
parser.add_argument(
    "--include-domestic", action="store_true",
    help="Also include common domestic/feral animals (cattle, buffalo, goat, sheep, camel, "
    "dog, cat, donkey, horse). They are labelled as domestic, never as wild candidates.",
)
parser.add_argument("--refresh", action="store_true", help="Bypass API response cache")
args = parser.parse_args()
settings.prepare()
service = TaxaService(settings.data_dir)
requested = list(args.include_taxon or [])
if args.include_domestic:
    lookup = INaturalist(service.cache_dir)
    try:
        domestic_ids, missing = resolve_domestic_ids(lambda path, params: lookup.get(path, params, args.refresh))
    finally:
        lookup.client.close()
    requested += domestic_ids
    for name in missing:
        print(f"Warning: {name} did not resolve to one active iNaturalist species; not added.")
additional_ids = (
    sorted(set(service.read().additional_taxon_ids + requested))
    if requested
    else None
)
result = service.refresh(
    RefreshRequest(
        place=args.place,
        limits=json.loads(args.limits) if args.limits else DEFAULT_LIMITS,
        minimum_observations=args.minimum_observations,
        additional_taxon_ids=[] if args.clear_included else additional_ids,
    ),
    force=args.refresh,
)
print(
    json.dumps(
        {
            "total": len(result.taxa),
            "counts": result.counts,
            "version": result.version,
            "refreshed_at": result.refreshed_at,
            "coverage": {
                group: stats.model_dump() for group, stats in result.coverage.items()
            },
            "warnings": result.warnings,
            "additional_taxon_ids": result.additional_taxon_ids,
        },
        indent=2,
    )
)
