# Evidence and scientific data export

Developer: **Vinay Chittora**.

FALCON exports a portable evidence archive. The Camtrap DP mapping below remains
a future interoperability target: this release does not claim Camtrap DP
conformance. The earlier observation-only download remains available as JSONL.

## Portable evidence archive

`GET /api/evidence/export?scope=live` downloads field observations and evidence;
an optional `source_id` limits it to one station session. `scope=all` retains the
older all-source export behavior, including uploaded test analyses. Field scope
includes durable live sessions and identifiable older live records; it excludes
known uploaded-file jobs. No records are deleted by a scope filter.
The archive contains `observations.csv`, `observations.jsonl`,
`review_audit.jsonl`, `evidence.csv`, `evidence.jsonl`, `sessions.json`,
`manifest.json`, a format guide
and retained media under `media/`. MP4 video and WAV acoustic evidence can be
opened without FALCON. Session settings exclude connection credentials. Archive
media paths use stable evidence IDs instead of machine-specific paths.
The review audit preserves each stored change, including its previous decision,
and follows the same source filter and database snapshot as the observations.

Field exports also contain `sensor_readings.csv` and `sensor_readings.jsonl`.
An unfiltered field export includes all local periodic readings, independent of
animal detections, with sensor IDs, observed/received timestamps, quality flags,
and explicit Celsius, percent and hPa fields. For a source-filtered export, only
readings matching a recorded session sensor ID and its time bounds are included.
The explicitly active live session is bounded by export creation time; old open
sessions left by a power loss are not treated as still running. Missing sensor bindings
or unavailable history produce a manifest warning and empty sensor tables;
FALCON does not invent an association. These identities do not assume a specific
Pi model or sensor hardware. Additional measurement types require a versioned
schema and a suitable device driver; schema 1.0 covers the current climate fields.

The manifest records SHA-256 checksums and byte sizes. Capture status remains
separate from archive status: failed captures stay in the tables, while missing
or changed files produce explicit export warnings. A changed file is marked
`checksum_mismatch`; its exported-byte checksum does not certify the original
capture. No data or media license is assigned automatically. CSV text that
could execute as a spreadsheet formula receives an apostrophe prefix; JSONL
preserves the original text and precision.

`GET /api/evidence` lists records, with optional `source_id`, `event_id`, `limit`
(default 100, maximum 500) and `offset`. `GET /api/evidence/{evidence_id}/media`
serves verified-path, retained evidence. Unavailable evidence returns 404. The
archive is assembled in a private temporary file and removed after delivery or
an interrupted download. Export includes all matching records, not only the
currently displayed page. Recording and reviews continue to persist in SQLite.

`GET /api/detections?scope=live` and `/api/detections/sources?scope=live` power the
field archive. Returned observations have `source_kind`, `captured_at`,
`time_basis` and `evidence_summaries`. Legacy live observations without a durable
session clock remain visible with an unknown date. Database insertion time is
never shown as capture time. Enrichment and filtering do not rewrite old records.

Each observation must keep the model prediction separate from the accepted
reviewed name. Keep model/version, detector confidence, species similarity,
alternative candidates, review status and review timestamp. Similarity is not
a calibrated probability. An acoustic detection is not proof that the animal
appears in the camera image. Repeated frames are not independent animal counts.

Retained evidence records include actual start/end times, MIME type, byte size,
capture clock source, source/session ID and observation links. They report missing,
truncated or failed captures explicitly. Do not invent an earlier capture time
from the time analysis finished. Existing imported files usually have relative
timestamps only; analysis time is not their recording date.

## Camtrap DP target

The target is **Camtrap DP 1.0.2**, the stable release listed by TDWG on
2026-10-17. It uses a package descriptor and three related tables. Pin schema
URLs to `1.0.2`, not `main`. See the [official release history](https://camtrap-dp.tdwg.org/changelog/).

The descriptor `datapackage.json` must provide `profile`, `created`,
`contributors`, `project`, `spatial`, `temporal`, `taxonomic` and `resources`.
The profile URL is
`https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/camtrap-dp-profile.json`.
Project metadata includes title, sampling design, capture method, whether
individual animals are identified, and observation level. Do not infer a
research design or ownership from the software developer's identity. A package
needs an actual project contributor. If licenses are declared, provide separate
data and media scopes. See the [package schema](https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/camtrap-dp-profile.json).

| Table | Required values and FALCON mapping |
| --- | --- |
| `deployments.csv` | `deploymentID`, WGS84 `latitude`/`longitude`, timezone-aware `deploymentStart`/`deploymentEnd`. These describe a real placement and completed observation interval; application startup alone is not deployment metadata. |
| `media.csv` | `mediaID`, `deploymentID`, capture `timestamp`, archive-relative `filePath`, explicit `filePublic`, and `fileMediatype`. Each retained file gets one row, even when linked to several detections. |
| `observations.csv` | `observationID`, `deploymentID`, `eventStart`, `eventEnd`, `observationLevel`, `observationType`. For media-based detections also populate `mediaID` with the evidence file's ID. |

These requirements come from the pinned [deployment schema](https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/deployments-table-schema.json),
[media schema](https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/media-table-schema.json)
and [observation schema](https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0.2/observations-table-schema.json).

Export validation must reject absent coordinates or trustworthy recording dates
instead of substituting zero coordinates or today's date. A live deployment
must be represented by a documented, completed survey segment or wait until it
ends. Retain actual gaps and downtime separately; an interval is not proof of
continuous survey effort.

For sensitive locations, apply an explicit generalization policy consistently
to deployment coordinates and package GeoJSON, and record
`coordinateUncertainty` and `coordinatePrecision`. Leaving required coordinates
blank does not produce a conforming package. Removing location names, EXIF and
free-text hints also matters. Default archive delivery does not grant public
access to evidence or assign it an open license.

## Classification and measurements

Use `observationLevel=media` for FALCON's frame/call detections; do not imply
mutually exclusive ecological encounters or recognized individuals. A reviewed
correction supplies the accepted scientific name and
`classificationMethod=human`. Unreviewed predictions stay marked
`classificationMethod=machine`. Keep original outputs and review status in a
documented additional resource. Do not turn a rejected bounding box into a
claim that its entire image is blank. Unknown identifications have no invented
species name. Leave `classificationProbability` empty for BioCLIP similarities.

The standard already provides `bboxX`, `bboxY`, `bboxWidth` and `bboxHeight`:
convert FALCON's normalized `(left, top, right, bottom)` to
`(left, top, right-left, bottom-top)`. A box must refer to the matching image;
a box from one frame cannot describe an entire moving five-second clip. Keep
frame timestamps in an additional resource when necessary. Climate readings
need a separate table with timestamps, sensor IDs, units, status, age and
foreign keys to deployments/observations. Missing readings stay null. TDWG
documents [bounding boxes and custom measurement resources](https://camtrap-dp.tdwg.org/faq/).

Camtrap DP permits audio media, so an audio file associated with a camera
deployment can be referenced. It is not a complete passive-acoustic metadata
standard: microphone calibration, channels, sample rate and annotation offsets
need documented additional fields/resources. A separate audio recorder should
not silently be described as a camera deployment.

Before claiming a conforming export, validate the descriptor against the pinned
profile, each table against its schema, foreign keys and unique IDs, media
existence and hashes, timestamp ordering, coordinate policy, and classification
provenance. Include the validation result and schema version in the archive.
