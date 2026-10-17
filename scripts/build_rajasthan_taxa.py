import argparse
import json

from app.config import settings
from app.taxonomy.inaturalist import DEFAULT_LIMITS, RefreshRequest, TaxaService

parser = argparse.ArgumentParser(
    description="Build local Rajasthan species candidates using official iNaturalist aggregates"
)
parser.add_argument("--minimum-observations", type=int, default=1)
parser.add_argument("--limits", help="JSON mapping of group names to limits")
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
parser.add_argument("--refresh", action="store_true", help="Bypass API response cache")
args = parser.parse_args()
settings.prepare()
service = TaxaService(settings.data_dir)
additional_ids = (
    sorted(set(service.read().additional_taxon_ids + args.include_taxon))
    if args.include_taxon
    else None
)
result = service.refresh(
    RefreshRequest(
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
