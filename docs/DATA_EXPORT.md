# Data export

FALCON exports field data in **Camtrap DP 1.0** (Camera Trap Data Package), the
[TDWG standard](https://camtrap-dp.tdwg.org) for camera-trap data. It can be published to
GBIF, imported into Agouti or Wildlife Insights, and read in R with
[camtrapdp](https://inbo.github.io/camtrapdp/) or in Python with
[frictionless](https://framework.frictionlessdata.io/). Make one from the **Export** page,
or with the API:

```
GET /api/exports/preview?captured_from=…&captured_to=…&review=verified
GET /api/exports/camtrap-dp?captured_from=2026-10-01T00:00:00Z&captured_to=2026-10-08T00:00:00Z
    &review=verified&latitude=..&longitude=..&contact_name=..&license=CC-BY-4.0
```

## What is selected

- **Field data only.** Live observations from sensor nodes and IP cameras; uploaded media
  tests are never exported (they have no real capture time).
- **Time window** on the capture time (UTC). Optional single session.
- **Review filter:**

  | Choice | Includes |
  | --- | --- |
  | `verified` | Confirmed and corrected by a reviewer |
  | `candidates` | Plus unreviewed machine identifications |
  | `everything` | Plus "unsure" and "not an animal" (exported as `blank`) |

  **Discarded records are never exported.** Unreviewed records can also be limited by a
  minimum model score; reviewed records are always kept.
- **Video and/or sound** detections, with or without clip files, with or without
  weather readings.

## Package contents

| File | One row per | Notes |
| --- | --- | --- |
| `datapackage.json` | | Profile, title, contact, license, project (opportunistic, activity detection, event-level), spatial (site point), temporal (dates), taxonomic list with iNaturalist taxon IDs and English names |
| `deployments.csv` | Live session | Start and end, site latitude/longitude and uncertainty, camera or node name, `timestampIssues` when the computer clock was not synchronized |
| `media.csv` + `media/` | Saved clip | 5-second MP4 video clips and WAV sound clips, `captureMethod=activityDetection`, `filePublic=false`, SHA-256 and duration in `exifData` |
| `observations.csv` | Animal visit | Event-level observation: one per visual track (all its frames) or per sound detection |
| `falcon_observations.csv` | Analyzed frame or sound window | FALCON detail: bounding box, detector confidence, visual similarity, original prediction, review and the weather reading at that moment |
| `environment.csv` | Weather reading | Temperature °C, humidity %, pressure hPa, rain-plate wet/dry, quality flag, node and server times |
| `README.md` | | Plain-language summary of the export |

All tables validate against the official Camtrap DP 1.0 schemas (checked with
`frictionless validate`, including the foreign keys between tables).

## How FALCON maps to Camtrap DP

| Camtrap DP field | From FALCON |
| --- | --- |
| `deploymentID` | Live session ID |
| `observationID`, `eventID` | `<session>:<track>` for a visual visit, the detection ID for sound |
| `eventStart`, `eventEnd` | First and last frame of the visit (UTC, computer receive clock) |
| `observationType` | `animal`; `blank` for "not an animal"; `human` / `vehicle` for those detector classes (only when non-wildlife logging is on) |
| `scientificName` | The reviewer's correction or confirmation; for unreviewed records the model's suggestion; empty when the species is unknown |
| `classificationMethod` | `human` after review, `machine` otherwise |
| `classifiedBy` | `FALCON reviewer`, or the model (BioCLIP model ID, BirdNET version) |
| `classificationProbability` | BirdNET confidence for unreviewed sound. Left empty for video: visual similarity is not a probability |
| `observationTags` | `modality`, `reviewStatus`, `frames`, `maxDetectorConfidence`, `visualSimilarity`, `broadGroup` or `birdnetConfidence`, linked `evidence` IDs |
| `observationComments` | Reviewer notes |
| `count` | Empty. A visit is not a count of individuals |

## Points to state when publishing

- Times come from the inference computer's receive clock, not a camera exposure clock.
  Sessions started without a synchronized clock are marked `timestampIssues=true`.
- Visual identifications are from BioCLIP (zero-shot, restricted to the local species
  list); sound from BirdNET. Unreviewed identifications are machine suggestions.
- Bounding boxes are in `falcon_observations.csv` per frame (left, top, right, bottom, 0–1),
  because Camtrap DP boxes belong to single images, not to events.
- Weather readings are periodic measurements, not detections. `surface_wet` is wetness of
  the rain plate (rain or dew), not a rainfall amount.
- Choose a license before publishing; without one, no reuse rights are granted. Check the
  [model licenses](model-licenses.md) too.
- Coordinates are exported as entered. Round them for sensitive species.

## Complete FALCON archive

`GET /api/evidence/export?scope=live` (the *Complete FALCON archive* link) writes every
field record, unfiltered, with the full review history, for backup and audit:
`observations.csv/jsonl`, `review_audit.jsonl`, `evidence.csv/jsonl` with media,
`sessions.json`, `sensor_readings.csv/jsonl` and `manifest.json` with SHA-256 checksums
of every file. It refuses to start when the export would eat into the 512 MB of free
space kept for live capture.
