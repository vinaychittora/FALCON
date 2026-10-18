# Candidate coverage and the backyard audit

FALCON's visual classifier compares a crop against a local list of names. A species
missing from that list cannot be returned, even if the image model knows its
appearance. Expanding the list changes the candidate set; it does **not** train the
detector or establish identification accuracy.

## What was wrong

The initial cache contained 509 species. Birds were restricted to the 200 most
frequently observed eligible species, all groups required three research-grade
photo observations, and insects outside butterflies, moths, dragonflies and
damselflies were excluded. Those defaults removed plausible candidates without
showing the omissions.

The 17 October 2026 audit used the official iNaturalist API, resolved Rajasthan to
place 7215, and checked active taxon IDs and ancestry. The user's names describe
their expected animals; the checks below establish candidate availability, not
the identity of animals in the video.

| Requested animal | Verified iNaturalist taxon | Old list | Expanded list | Matching Rajasthan research-photo observations |
| --- | --- | --- | --- | ---: |
| Sulphur-bellied Warbler | [Phylloscopus griseolus, 117024](https://www.inaturalist.org/taxa/117024) | Missing | Included | 34 |
| Oriental Magpie-Robin | [Copsychus saularis, 204491](https://www.inaturalist.org/taxa/204491) | Included | Included | 386 |
| Garden lizard candidate | [Calotes versicolor, 31281](https://www.inaturalist.org/taxa/31281) | Included | Included | 260 |
| Common Tailorbird | [Orthotomus sutorius, 15347](https://www.inaturalist.org/taxa/15347) | Included | Included | 147 |
| Bumble bees | [Bombus, genus 52775](https://www.inaturalist.org/taxa/52775) | No bee coverage | No unverified species inserted | No species returned by the matching regional query |

The warbler ranked 229th by the refreshed bird observation counts, explaining its
exclusion by the former 200-bird cap. Magpie-robin, tailorbird and the garden
lizard candidate were already available. Their missed identifications therefore
require evaluation of detection proposals, crop quality and classification, not
just a longer species list.

"Garden lizard" alone is not a definitive species identification. Likewise,
"bumblebee" does not specify a species. `Bombus` is a genus (the API also has a
same-named subgenus). No `Bombus` species was fabricated or assigned a Rajasthan
occurrence. The expanded list includes verified regional honey-bee, carpenter-bee
and other Hymenoptera candidates. Whether the insect in the clip is one of these
requires examination of the original frames.

## Expanded cache

The rebuilt cache has **1,369 active species**, version `2e13f17128a4e5d0`, from
regional research-grade photo observations, with a minimum count of one.

| Group | Before | After |
| --- | ---: | ---: |
| Birds | 200 | 442 |
| Mammals | 47 | 66 |
| Reptiles | 54 | 76 |
| Amphibians | 10 | 12 |
| Butterflies and moths | 148 | 269 |
| Dragonflies and damselflies | 50 | 65 |
| Ants, bees, wasps and sawflies | 0 | 65 |
| Other insects | 0 | 293 |
| Arachnids | 0 | 81 |
| **Total** | **509** | **1,369** |

The complete Insecta query returned 692 species. The other-insects group excludes
the 399 assigned to the three separately represented insect orders. There are no
duplicate candidate IDs. All nine group queries finished, with **zero species
omitted by the new 1,000-per-group safety caps** in this snapshot.

This is complete for those API filters at that time, not a complete inventory of
Rajasthan's biodiversity. Species with no qualifying observations remain absent.
Research-grade observations can also contain errors. No observation images,
individual observation records or private locations were downloaded.

Ignored local audit artifacts:

- `data/cache/audit-before-taxa.json`: preserved 509-species cache.
- `data/taxa/rajasthan_taxa.json`: expanded candidate list and coverage metadata.
- `data/cache/taxa-expansion-report.json`: query counts and cap accounting.

## Refreshing and selecting candidates

From the WSL project directory:

```bash
source scripts/env.sh
python scripts/build_rajasthan_taxa.py
```

The builder uses a seven-day API-response cache. Add `--refresh` to fetch fresh
aggregates. `--minimum-observations` and `--limits` remain configurable. An omitted
group is not queried; a zero limit explicitly disables a group. Disabling a named
insect order also excludes it from the broader Insecta query.

Every group records the API total, scanned and eligible counts, selected count,
omissions caused by its cap, and whether its scan completed. A capped or
incomplete group produces an explicit warning. The builder counts eligible
species past the cap instead of silently stopping at the selected maximum.

To select an additional **known, active species** by canonical iNaturalist ID:

```bash
python scripts/build_rajasthan_taxa.py --include-taxon 117024
```

Repeat the option for multiple selections. The list is retained on subsequent
refreshes, unless `--clear-included` is supplied. The API accepts the corresponding
`additional_taxon_ids` list on `POST /api/taxa/refresh`; omitting it retains saved
selections and sending `[]` clears them. Explicit selections are marked in each
taxon's provenance. If a selected species has no matching regional observations,
its count is zero and a warning explains that inclusion is **not evidence of local
occurrence**. Genera and inactive synonyms are rejected instead of being presented
as species. Existing canonical IDs should be reviewed when iNaturalist changes
its taxonomy.

BioCLIP text embeddings are keyed by the taxa cache version and scientific names,
so the next analysis rebuilds them for the new list. Original events retain their
old model output and taxa version. They must be reanalysed to evaluate the new
candidate set.

## Evaluating improvement

Candidate recall is only the first check. Build a reviewed set of time intervals
and organism boxes from the user's backyard clip, including small birds, lizards
and insects. Measure whether the detector supplies a usable box before judging
top-k classification. Compare the original and expanded lists on the same crops,
keep an unknown option, and inspect false-positive cost as well as missed animals.
A larger list can introduce confusing alternatives and reduce top-1 margins;
lowering thresholds until a desired name appears is not an accuracy test.

For deployment, repeat the measured workload on the intended mini PC. Taxonomy
coverage is independent of GPU availability; achievable sampling rate and latency
depend on the detector, image encoder, input resolution and CPU.

Official sources: [iNaturalist API documentation](https://api.inaturalist.org/v1/docs/),
[API recommended practices](https://www.inaturalist.org/pages/api+recommended+practices),
[species-count endpoint schema](https://github.com/inaturalist/iNaturalistAPI/blob/main/lib/views/swagger_v1.yml.ejs).
