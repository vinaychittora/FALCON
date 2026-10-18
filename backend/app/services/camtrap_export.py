"""Clean research export in Camera Trap Data Package format (Camtrap DP 1.0).

Camtrap DP (https://camtrap-dp.tdwg.org) is the TDWG exchange standard for
camera-trap data, read by GBIF, Agouti, Wildlife Insights and the camtrapdp /
camtraptor R packages. A FALCON live session becomes a deployment, each saved
encounter clip a media record and each observation an event-level observation.
Discarded records are never exported; the review filter decides whether
unreviewed machine identifications and rejected detections are included.

FALCON-specific detail (frame bounding boxes, model scores, review state,
detection-time weather) is kept in an extra `falcon_observations` table, and
periodic weather readings in an `environment` table, both described inline.
"""

import csv
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from app.schemas import AudioEvent, Event, VisualEvent
from app.schemas_evidence import EvidenceRecord, EvidenceSession
from app.services.evidence_export import (
    OBSERVATION_COLUMNS,
    SENSOR_COLUMNS,
    _csv_value,
    _observation_row,
)
from app.services.review_names import resolve_review_names
from app.storage.evidence import EvidenceStore
from app.storage.jsonl import SCORE_SQL, adapter
from app.storage.observation_context import capture_time_sql, enrich_events, origin_sql, tables
from app.taxonomy.inaturalist import TaxaService

PROFILE = "https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0/camtrap-dp-profile.json"
SCHEMA = "https://raw.githubusercontent.com/tdwg/camtrap-dp/1.0/{}-table-schema.json"
DEPLOYMENT_COLUMNS = [
    "deploymentID", "locationID", "locationName", "latitude", "longitude", "coordinateUncertainty",
    "deploymentStart", "deploymentEnd", "setupBy", "cameraID", "cameraModel", "cameraDelay", "cameraHeight",
    "cameraDepth", "cameraTilt", "cameraHeading", "detectionDistance", "timestampIssues", "baitUse",
    "featureType", "habitat", "deploymentGroups", "deploymentTags", "deploymentComments",
]
MEDIA_COLUMNS = [
    "mediaID", "deploymentID", "captureMethod", "timestamp", "filePath", "filePublic", "fileName",
    "fileMediatype", "exifData", "favorite", "mediaComments",
]
CAMTRAP_OBSERVATION_COLUMNS = [
    "observationID", "deploymentID", "mediaID", "eventID", "eventStart", "eventEnd", "observationLevel",
    "observationType", "cameraSetupType", "scientificName", "count", "lifeStage", "sex", "behavior",
    "individualID", "individualPositionRadius", "individualPositionAngle", "individualSpeed", "bboxX", "bboxY",
    "bboxWidth", "bboxHeight", "classificationMethod", "classifiedBy", "classificationTimestamp",
    "classificationProbability", "observationTags", "observationComments",
]
LICENSES = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
}
REVIEW_FILTERS = {
    # Human-confirmed or human-corrected identifications only.
    "verified": ("correct", "corrected"),
    # Plus unreviewed machine identifications (marked classificationMethod=machine).
    "candidates": ("correct", "corrected", "unreviewed"),
    # Plus reviewer-marked unknowns and rejected detections (exported as blank).
    "everything": ("correct", "corrected", "unreviewed", "unknown", "false_positive"),
}
EXPORT_FREE_SPACE_RESERVE = 512 * 1024**2


class ExportError(ValueError):
    """The request cannot produce a valid package; the message is shown to the user."""


@dataclass
class ExportRequest:
    captured_from: datetime | None = None
    captured_to: datetime | None = None
    source_id: str | None = None
    modalities: tuple[str, ...] = ("visual", "audio")
    review: Literal["verified", "candidates", "everything"] = "candidates"
    min_score: float | None = None
    include_media: bool = True
    include_environment: bool = True
    title: str = "FALCON wildlife observations"
    project_title: str = "FALCON field monitoring"
    contact_name: str = ""
    contact_email: str | None = None
    license: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    coordinate_uncertainty_m: int | None = None
    location_name: str | None = None


@dataclass
class Selection:
    events: list[Event] = field(default_factory=list)
    sessions: dict[str, EvidenceSession] = field(default_factory=dict)
    media: dict[str, EvidenceRecord] = field(default_factory=dict)
    links: dict[str, list[str]] = field(default_factory=dict)
    environment_count: int = 0
    environment_bounds: tuple[str, str] | None = None


def camtrap_time(value: str | datetime) -> str:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _where(connection: sqlite3.Connection, request: ExportRequest) -> tuple[str, list[Any]]:
    available = tables(connection)
    statuses = REVIEW_FILTERS[request.review]
    modalities = [value for value in request.modalities if value in {"visual", "audio"}] or ["visual", "audio"]
    conditions = [
        # Camtrap DP needs real capture times: live sessions only, never uploaded test files.
        f"({origin_sql(available)})='live'",
        f"e.review_status IN ({','.join('?' * len(statuses))})",
        f"e.modality IN ({','.join('?' * len(modalities))})",
    ]
    args: list[Any] = [*statuses, *modalities]
    if request.review != "everything":
        conditions.append(
            "(e.modality='audio' OR e.review_status IN ('correct','corrected') OR "
            "COALESCE(json_extract(e.payload,'$.classification.status'),'')!='non_wildlife')"
        )
    if request.source_id:
        conditions.append("e.source_id=?")
        args.append(request.source_id)
    if request.min_score is not None:
        # A reviewer's decision outranks the model score.
        conditions.append(f"(e.review_status IN ('correct','corrected') OR {SCORE_SQL}>=?)")
        args.append(request.min_score)
    for operator, moment in ((">=", request.captured_from), ("<=", request.captured_to)):
        if moment is not None:
            conditions.append(f"julianday({capture_time_sql(available)}){operator}julianday(?)")
            args.append(moment.astimezone(UTC).isoformat())
    return " WHERE " + " AND ".join(conditions), args


def select(store: EvidenceStore, request: ExportRequest, taxonomy: TaxaService | None) -> Selection:
    selection = Selection()
    sessions = {session.session_id: session for session in store.sessions(source_id=request.source_id)}
    with store.database.connection() as connection:
        connection.execute("BEGIN")
        where, args = _where(connection, request)
        rows = connection.execute(
            "SELECT e.payload FROM observations e" + where + " ORDER BY e.source_id,e.job_id,e.timestamp_ms,e.event_id",
            args,
        ).fetchall()
        events = enrich_events(connection, [adapter.validate_json(row["payload"]) for row in rows])
        if taxonomy is not None:
            events = resolve_review_names(events, taxonomy)
        selection.events = [event for event in events if event.captured_at]
        event_ids = [event.event_id for event in selection.events]
        if event_ids and "evidence_links" in tables(connection):
            for start in range(0, len(event_ids), 500):
                chunk = event_ids[start:start + 500]
                for link in connection.execute(
                    f"SELECT event_id, evidence_id FROM evidence_links WHERE event_id IN ({','.join('?' * len(chunk))})",
                    chunk,
                ):
                    selection.links.setdefault(link["event_id"], []).append(link["evidence_id"])
    for evidence_id in sorted({value for values in selection.links.values() for value in values}):
        try:
            record = store.get(evidence_id)
        except KeyError:
            continue
        if record.status in {"ready", "partial"}:
            selection.media[evidence_id] = record
    selection.links = {
        event_id: [value for value in values if value in selection.media] for event_id, values in selection.links.items()
    }
    used = {event.job_id for event in selection.events} | {record.session_id for record in selection.media.values()}
    selection.sessions = {session_id: session for session_id, session in sessions.items() if session_id in used}
    if request.include_environment:
        bounds = _environment_bounds(request, selection)
        if bounds:
            with store.database.connection() as connection:
                if "sensor_readings" in tables(connection):
                    selection.environment_count = connection.execute(
                        "SELECT COUNT(*) FROM sensor_readings WHERE julianday(observed_at)>=julianday(?) "
                        "AND julianday(observed_at)<=julianday(?)", bounds,
                    ).fetchone()[0]
                    selection.environment_bounds = bounds
    return selection


def _environment_bounds(request: ExportRequest, selection: Selection) -> tuple[str, str] | None:
    start = request.captured_from
    end = request.captured_to
    if start is None or end is None:
        moments = [datetime.fromisoformat(session.started_at) for session in selection.sessions.values()]
        moments += [datetime.fromisoformat(session.ended_at) for session in selection.sessions.values() if session.ended_at]
        if not moments:
            return None
        start = start or min(moments)
        end = end or max(moments)
    return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()


def _event_window(event: Event) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(str(event.captured_at))
    if isinstance(event, VisualEvent):
        return start, start + timedelta(milliseconds=max(0, event.duration_ms))
    return start, start + timedelta(milliseconds=max(0, event.end_ms - event.start_ms))


def _identity(event: Event) -> tuple[str, str | None, str | None]:
    """(observationType, scientificName, common name) following review decisions."""
    status = event.review.status
    if status == "false_positive":
        return "blank", None, None
    if status == "corrected":
        return "animal", event.review.corrected_scientific_name, event.review.corrected_common_name
    if isinstance(event, AudioEvent):
        return ("unknown", None, None) if status == "unknown" else ("animal", event.scientific_name, event.common_name)
    classification = event.classification
    if classification.status == "non_wildlife":
        label = (event.detector.label or "").lower()
        return ("human" if "person" in label or "human" in label else "vehicle" if "vehicle" in label else "unknown"), None, None
    if status == "unknown" or classification.status != "candidate":
        return "animal", None, None
    return "animal", classification.scientific_name, classification.common_name


HUMAN = {"correct", "corrected", "false_positive", "unknown"}


def encounter_key(event: Event) -> str:
    return f"{event.job_id}:{event.track_id}" if isinstance(event, VisualEvent) else event.event_id


def group_encounters(events: list[Event]) -> list[list[Event]]:
    """One animal visit per group: a visual track's frame records, or one sound detection."""
    groups: dict[str, list[Event]] = {}
    for event in events:
        groups.setdefault(encounter_key(event), []).append(event)
    for members in groups.values():
        members.sort(key=lambda item: _event_window(item)[0])
    return sorted(groups.values(), key=lambda members: (members[0].job_id, _event_window(members[0])[0]))


def decisive(members: list[Event]) -> Event:
    """The record whose identification represents the visit: the latest human review, else the
    latest machine result (a track's classification accumulates evidence over its frames)."""
    reviewed = [event for event in members if event.review.status in HUMAN]
    if reviewed:
        return max(reviewed, key=lambda event: event.review.updated_at or "")
    return members[-1]


def _tags(members: list[Event], links: list[str]) -> str:
    event = decisive(members)
    values = [f"modality:{event.modality}", f"reviewStatus:{event.review.status}"]
    visual = [item for item in members if isinstance(item, VisualEvent)]
    if visual:
        values.append(f"frames:{len(visual)}")
        detector = [item.detector.score for item in visual if item.detector.score is not None]
        if detector:
            values.append(f"maxDetectorConfidence:{max(detector):.3f}")
        if isinstance(event, VisualEvent):
            if event.classification.score is not None:
                values.append(f"visualSimilarity:{event.classification.score:.3f}")
            values.append(f"broadGroup:{event.classification.broad_group}")
    elif isinstance(event, AudioEvent):
        values.append(f"birdnetConfidence:{event.confidence:.3f}")
    if links:
        values.append("evidence:" + ",".join(links))
    return " | ".join(values)


def observation_record(members: list[Event], links: dict[str, list[str]]) -> dict[str, Any]:
    """One event-level Camtrap DP observation per animal visit."""
    event = decisive(members)
    start = min(_event_window(item)[0] for item in members)
    end = max(_event_window(item)[1] for item in members)
    kind, scientific, _ = _identity(event)
    human = event.review.status in HUMAN
    probability = None
    if not human and isinstance(event, AudioEvent):
        probability = round(event.confidence, 4)
    classified_by = "FALCON reviewer" if human else (
        event.model if isinstance(event, AudioEvent) else event.models.get("classifier_model")
        or event.models.get("classifier_mode") or "FALCON visual pipeline"
    )
    evidence = sorted({value for item in members for value in links.get(item.event_id, [])})
    key = encounter_key(event)
    return {
        "observationID": key,
        "deploymentID": event.job_id,
        "mediaID": None,
        "eventID": key,
        "eventStart": camtrap_time(start),
        "eventEnd": camtrap_time(end),
        "observationLevel": "event",
        "observationType": kind,
        "scientificName": scientific if kind == "animal" else None,
        "classificationMethod": "human" if human else "machine",
        "classifiedBy": classified_by,
        "classificationTimestamp": camtrap_time(event.review.updated_at) if human and event.review.updated_at else camtrap_time(start),
        "classificationProbability": probability,
        "observationTags": _tags(members, evidence),
        "observationComments": event.review.notes,
    }


def _deployment(session: EvidenceSession, request: ExportRequest, fallback_end: datetime) -> dict[str, Any]:
    settings = session.settings or {}
    # Never end a deployment before its last saved observation or clip.
    end = max(datetime.fromisoformat(session.ended_at), fallback_end) if session.ended_at else fallback_end
    clock = settings.get("clock_synchronized")
    return {
        "deploymentID": session.session_id,
        "locationID": request.location_name or session.name,
        "locationName": request.location_name or session.name,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "coordinateUncertainty": request.coordinate_uncertainty_m,
        "deploymentStart": camtrap_time(session.started_at),
        "deploymentEnd": camtrap_time(max(end, datetime.fromisoformat(session.started_at))),
        "cameraID": session.source_id,
        "cameraModel": session.name,
        "timestampIssues": None if clock is None else not bool(clock),
        "baitUse": False,
        "deploymentTags": f"falconSource:{session.source_id} | sensorID:{settings.get('sensor_id') or 'none'}",
        "deploymentComments": "FALCON live session. Times are the inference computer's receive clock (UTC), "
        "not a camera capture clock.",
    }


def _media_record(record: EvidenceRecord, include_files: bool) -> dict[str, Any]:
    suffix = ".mp4" if record.mime_type == "video/mp4" else ".wav"
    comments = []
    if record.status == "partial":
        comments.append("partial clip: the stream was interrupted during capture")
    if not include_files:
        comments.append("file not included in this export")
    return {
        "mediaID": record.evidence_id,
        "deploymentID": record.session_id,
        "captureMethod": "activityDetection",
        "timestamp": camtrap_time(record.captured_at),
        "filePath": f"media/{record.evidence_id}{suffix}",
        "filePublic": False,
        "fileName": f"{record.evidence_id}{suffix}",
        "fileMediatype": record.mime_type,
        "exifData": json.dumps({"durationMs": record.duration_ms, "sha256": record.sha256, "status": record.status}),
        "favorite": False,
        "mediaComments": "; ".join(comments) or None,
    }


def _csv_lines(columns: list[str], rows: Iterable[dict[str, Any]]) -> Iterator[str]:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    yield output.getvalue()
    for row in rows:
        output.seek(0)
        output.truncate(0)
        writer.writerow({
            key: ("true" if value is True else "false" if value is False else _csv_value(value))
            for key, value in row.items()
        })
        yield output.getvalue()


def _validate(request: ExportRequest) -> None:
    if request.latitude is None or request.longitude is None:
        raise ExportError("Add the site latitude and longitude. Camtrap DP requires a location for each deployment.")
    if not request.contact_name.strip():
        raise ExportError("Add a contact name. Camtrap DP requires at least one contributor.")
    if request.license is not None and request.license not in LICENSES:
        raise ExportError("Choose a listed license or none.")
    if request.captured_from and request.captured_to and request.captured_from > request.captured_to:
        raise ExportError("The time window must start before it ends.")


def preview(store: EvidenceStore, request: ExportRequest, taxonomy: TaxaService | None) -> dict[str, Any]:
    selection = select(store, request, taxonomy)
    types: Counter[str] = Counter()
    species: Counter[tuple[str, str | None]] = Counter()
    methods: Counter[str] = Counter()
    for members in group_encounters(selection.events):
        event = decisive(members)
        kind, scientific, common = _identity(event)
        types[kind] += 1
        methods["human" if event.review.status in HUMAN else "machine"] += 1
        if kind == "animal" and scientific:
            species[(scientific, common)] += 1
    warnings = []
    if request.latitude is None or request.longitude is None:
        warnings.append("Site latitude and longitude are required for Camtrap DP.")
    if methods["machine"]:
        warnings.append(f"{methods['machine']} observations are unreviewed machine identifications.")
    unsynchronized = [s for s in selection.sessions.values() if s.settings.get("clock_synchronized") is False]
    if unsynchronized:
        warnings.append(f"{len(unsynchronized)} session(s) started without a synchronized clock.")
    return {
        "deployments": len(selection.sessions),
        "observations": sum(types.values()),
        "records": len(selection.events),
        "observation_types": dict(types),
        "classification": dict(methods),
        "species": [
            {"scientific_name": name, "common_name": common, "count": count}
            for (name, common), count in species.most_common()
        ],
        "media": len(selection.media),
        "media_bytes": sum(record.size_bytes for record in selection.media.values()),
        "environment_readings": selection.environment_count,
        "warnings": warnings,
    }


def _taxonomic(selection: Selection, taxonomy: TaxaService | None) -> list[dict[str, Any]]:
    by_name = {}
    if taxonomy is not None:
        by_name = {taxon.scientific_name: taxon for taxon in taxonomy.read().taxa}
    names: dict[str, str | None] = {}
    for members in group_encounters(selection.events):
        kind, scientific, common = _identity(decisive(members))
        if kind == "animal" and scientific:
            names.setdefault(scientific, common)
    result = []
    for name in sorted(names):
        entry: dict[str, Any] = {"scientificName": name}
        taxon = by_name.get(name)
        if taxon is not None:
            entry["taxonID"] = f"https://www.inaturalist.org/taxa/{taxon.taxon_id}"
        if names[name]:
            entry["vernacularNames"] = {"eng": names[name]}
        result.append(entry)
    return result


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "falcon"


def build_camtrap_package(
    store: EvidenceStore, request: ExportRequest, taxonomy: TaxaService | None, *, version: str = "1.0",
) -> Path:
    """Write the package ZIP to a private temporary file; the caller deletes it after delivery."""
    _validate(request)
    selection = select(store, request, taxonomy)
    if not selection.events and not selection.media:
        raise ExportError("No observations match this time window and filter.")
    media_bytes = sum(record.size_bytes for record in selection.media.values()) if request.include_media else 0
    if shutil.disk_usage(store.root).free < media_bytes + EXPORT_FREE_SPACE_RESERVE + 64 * 1024**2:
        raise ExportError("Not enough free storage to build this export. Export a shorter time window or leave out media files.")
    created = datetime.now(UTC)
    last_seen: dict[str, datetime] = {}
    for event in selection.events:
        end = _event_window(event)[1]
        last_seen[event.job_id] = max(end, last_seen.get(event.job_id, end))
    for record in selection.media.values():
        moment = datetime.fromisoformat(record.captured_at) + timedelta(milliseconds=record.duration_ms)
        last_seen[record.session_id] = max(moment, last_seen.get(record.session_id, moment))
    deployments = [
        _deployment(session, request, last_seen.get(session.session_id, created))
        for session in sorted(selection.sessions.values(), key=lambda value: value.started_at)
    ]
    starts = [datetime.fromisoformat(session.started_at) for session in selection.sessions.values()]
    ends = [datetime.fromisoformat(row["deploymentEnd"].replace("Z", "+00:00")) for row in deployments]
    temporal_start = min(starts) if starts else request.captured_from or created
    temporal_end = max(ends) if ends else request.captured_to or created
    descriptor, filename = tempfile.mkstemp(prefix="falcon-camtrap-", suffix=".zip", dir=store.root)
    os.close(descriptor)
    path = Path(filename)
    try:
        with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            def write(name: str, chunks: Iterable[str]) -> None:
                with archive.open(name, "w", force_zip64=True) as target:
                    for chunk in chunks:
                        target.write(chunk.encode("utf-8"))

            write("deployments.csv", _csv_lines(DEPLOYMENT_COLUMNS, deployments))
            write("media.csv", _csv_lines(
                MEDIA_COLUMNS, (_media_record(record, request.include_media) for record in selection.media.values()),
            ))
            write("observations.csv", _csv_lines(CAMTRAP_OBSERVATION_COLUMNS, (
                observation_record(members, selection.links) for members in group_encounters(selection.events)
            )))
            write("falcon_observations.csv", _csv_lines(OBSERVATION_COLUMNS, (
                _observation_row(event, selection.links) for event in selection.events
            )))
            resources: list[dict[str, Any]] = [
                {"name": name, "path": f"{name}.csv", "profile": "tabular-data-resource", "format": "csv",
                 "mediatype": "text/csv", "encoding": "utf-8", "schema": SCHEMA.format(name)}
                for name in ("deployments", "media", "observations")
            ]
            resources.append({
                "name": "falcon_observations", "path": "falcon_observations.csv", "profile": "tabular-data-resource",
                "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
                "description": "FALCON detail for each analyzed frame or sound window: bounding box (0-1, "
                "left/top/right/bottom), model scores, original prediction, review decision and the weather reading "
                "at detection time. session_or_job_id plus the track in observations.csv eventID groups frames into visits.",
                "schema": {"fields": [{"name": column, "type": "string"} for column in OBSERVATION_COLUMNS]},
            })
            if selection.environment_bounds:
                bounds = selection.environment_bounds
                with store.database.connection() as connection:
                    readings = [json.loads(row["payload"]) for row in connection.execute(
                        "SELECT payload FROM sensor_readings WHERE julianday(observed_at)>=julianday(?) "
                        "AND julianday(observed_at)<=julianday(?) ORDER BY observed_at, reading_id", bounds,
                    )]
                write("environment.csv", _csv_lines(SENSOR_COLUMNS, readings))
                resources.append({
                    "name": "environment", "path": "environment.csv", "profile": "tabular-data-resource",
                    "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
                    "description": "Periodic weather readings from FALCON sensor nodes (node clock, UTC). "
                    "Temperature in °C, relative humidity in %, pressure in hPa; surface_wet is rain-plate "
                    "wetness (rain or dew), not a rainfall amount. These are not animal detections.",
                    "schema": {"fields": [
                        {"name": "schema_version", "type": "string"}, {"name": "reading_id", "type": "string"},
                        {"name": "sensor_id", "type": "string"}, {"name": "observed_at", "type": "datetime"},
                        {"name": "received_at", "type": "datetime"}, {"name": "temperature_c", "type": "number"},
                        {"name": "humidity_percent", "type": "number"}, {"name": "pressure_hpa", "type": "number"},
                        {"name": "surface_wet", "type": "boolean"}, {"name": "quality", "type": "string"},
                        {"name": "quality_note", "type": "string"},
                    ]},
                })
            if request.include_media:
                for record in selection.media.values():
                    try:
                        source = store.media_path(record)
                    except (OSError, ValueError):
                        continue
                    entry = ZipInfo(f"media/{record.evidence_id}{source.suffix.lower()}")
                    entry.compress_type = ZIP_STORED
                    with source.open("rb") as handle, archive.open(entry, "w", force_zip64=True) as target:
                        shutil.copyfileobj(handle, target, 1024 * 1024)
            contributor: dict[str, Any] = {"title": request.contact_name.strip(), "role": "contact"}
            if request.contact_email:
                contributor["email"] = request.contact_email
            package: dict[str, Any] = {
                "profile": PROFILE,
                "name": f"{_slug(request.title)}-{created.strftime('%Y%m%d')}",
                "id": str(uuid4()),
                "created": camtrap_time(created),
                "title": request.title,
                "description": "Wildlife observations recorded by FALCON (Field Acoustic, Lens & Climate Observation "
                "Node): MegaDetector and BioCLIP for video, BirdNET for sound. Each observation is one animal visit "
                "(a tracked sequence or a sound detection); separate visits by the same animal are not a count.",
                "version": version,
                "contributors": [contributor],
                "sources": [{"title": "FALCON", "version": version}],
                "project": {
                    "title": request.project_title, "samplingDesign": "opportunistic",
                    "captureMethod": ["activityDetection"], "individualAnimals": False, "observationLevel": ["event"],
                },
                "spatial": {"type": "Point", "coordinates": [request.longitude, request.latitude]},
                "temporal": {"start": temporal_start.date().isoformat(), "end": temporal_end.date().isoformat()},
                "taxonomic": _taxonomic(selection, taxonomy),
                "resources": resources,
            }
            if request.license:
                package["licenses"] = [
                    {"name": request.license, "path": LICENSES[request.license], "scope": scope}
                    for scope in ("data", "media")
                ]
            archive.writestr("datapackage.json", json.dumps(package, ensure_ascii=False, indent=2) + "\n")
            archive.writestr("README.md", _readme(request, selection, created))
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _readme(request: ExportRequest, selection: Selection, created: datetime) -> str:
    window = "all recorded time"
    if request.captured_from or request.captured_to:
        window = f"{camtrap_time(request.captured_from) if request.captured_from else 'start'} to " \
                 f"{camtrap_time(request.captured_to) if request.captured_to else 'now'}"
    review = {
        "verified": "human-verified identifications only",
        "candidates": "human-verified identifications and unreviewed machine identifications",
        "everything": "all records except discarded ones, including rejected detections (as blank)",
    }[request.review]
    return f"""# {request.title}

Camera Trap Data Package (Camtrap DP 1.0) exported by FALCON on {camtrap_time(created)}.

- Time window: {window} (UTC)
- Included: {review}; discarded records are never exported
- {len(selection.sessions)} deployments, {len(selection.media)} media files, {len(group_encounters(selection.events))} observations
  (animal visits) from {len(selection.events)} analyzed frames and sound windows

## Files

| File | Contents |
| --- | --- |
| `datapackage.json` | Package metadata: project, contact, location, time span, species list |
| `deployments.csv` | One row per FALCON live session (camera or sensor node, with start and end) |
| `media.csv` | Saved 5-second video clips (MP4) and sound clips (WAV) |
| `observations.csv` | One event-level observation per animal visit (a visual track or a sound detection) |
| `falcon_observations.csv` | FALCON detail per analyzed frame: bounding box, model scores, prediction, review, weather |
| `environment.csv` | Periodic temperature, humidity, pressure and rain-plate readings (if included) |
| `media/` | The clip files themselves (if included) |

## Reading the data

- `classificationMethod` is `human` when a reviewer confirmed or corrected the name and `machine` otherwise.
- For sound, `classificationProbability` is BirdNET's confidence. Visual similarity scores are not
  probabilities, so they appear only as `visualSimilarity` in `observationTags`.
- Times are UTC from the inference computer's receive clock. `timestampIssues` marks sessions that
  started without a synchronized clock.
- Load in R with `camtrapdp::read_camtrapdp("datapackage.json")`, or validate with
  `frictionless validate datapackage.json`.
"""
