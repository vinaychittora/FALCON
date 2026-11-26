# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Keep marked, thin the rest (rule since 14 Nov 2026).

Recordings and sound recordings of visits confirmed or corrected are kept for good.
Discarded / Not-an-animal ones lose their media soon after the verdict (since 24 Nov
2026: discarded evidence is cleaned up as early as possible): an hourly pass
removes them once the newest verdict on them is an hour old, so Undo inside that hour
still gives the footage back. Ones FALCON hid by itself go after 7 days; all others after
60 days: the video or sound, and the friends' small copy. The record, its picture and every
detail stay; a sound record keeps its spectrogram (made first if missing). Every
removal is written to data/logs/retention.jsonl. The very first run only writes a
dry-run report (data/logs/retention-dry-run.json); removals start the run after.

The full run is once a day at 03:30 India time, a quiet hour at the bowl; the hourly pass
looks only at discarded media.
"""

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.media.sound_cleanup import read_wav, spectrogram_png
from app.services.stays import small_copy_path

log = logging.getLogger("falcon.retention")
KEEP_DAYS = 60
FAST_DAYS = 7
# Discard / Not an animal: an hour after the newest verdict, so a wrong discard can be undone.
REJECTED_AGE = timedelta(hours=1)
HOURLY = 3600.0  # seconds between the discard-only passes
MARKED = ("correct", "corrected")  # Confirm, Correct: kept for good
REJECTED = ("false_positive", "discarded")  # Not an animal, Discard: gone an hour after the verdict
# Visits FALCON hid by itself (never shown): gone after a week unless reviewed.
HIDDEN = ("STILL", "UNIDENTIFIED", "SMALL", "CANDIDATE", "INSECT_NIGHT", "GLIMPSE", "RODENT_NIGHT")
RUN_AT_UTC = (22, 0)  # 03:30 IST


@dataclass
class Candidate:
    evidence_id: str
    media_kind: str
    captured_at: str
    path: Path | None
    size_bytes: int
    rejected: bool = False  # due because every link is Discard / Not an animal: re-checked before removal


def candidates(connection: Any, root: Path, now: datetime, only_rejected: bool = False) -> list[Candidate]:
    """Media due for thinning (since 14 Nov 2026):

    - any linked record Confirmed or Corrected: kept for good;
    - every linked record Discarded / Not an animal: removed an hour after the newest verdict;
    - every linked record Discarded / Not an animal, or hidden by FALCON and never
      reviewed: removed 7 days after the record (or the verdict, if later);
    - otherwise (unreviewed, Probable, Likely, Unsure): removed after 60 days.

    only_rejected (the hourly pass): just the first kind, found in SQL first.
    """
    marks = ",".join("?" * len(REJECTED))
    rejected_only = (
        " AND EXISTS (SELECT 1 FROM evidence_links l WHERE l.evidence_id=e.evidence_id)"
        " AND NOT EXISTS (SELECT 1 FROM evidence_links l JOIN observations o ON o.event_id=l.event_id"
        f" WHERE l.evidence_id=e.evidence_id AND o.review_status NOT IN ({marks}))"
    ) if only_rejected else ""
    rows = connection.execute(
        "SELECT e.evidence_id, e.payload FROM evidence e WHERE e.status IN ('ready','partial') "
        "AND e.captured_at < ?" + rejected_only,
        ((now - REJECTED_AGE).isoformat(), *(REJECTED if only_rejected else ())),
    ).fetchall()
    found = []
    for row in rows:
        links = connection.execute(
            "SELECT o.review_status, json_extract(o.payload,'$.review.updated_at') AS reviewed, "
            "(SELECT v.hidden_reason FROM visits v WHERE v.visit_id=json_extract(o.payload,'$.visit_id')) AS hidden "
            "FROM evidence_links l JOIN observations o ON o.event_id=l.event_id WHERE l.evidence_id=?",
            (row["evidence_id"],),
        ).fetchall()
        statuses = [link["review_status"] for link in links]
        if any(status in MARKED for status in statuses):
            continue
        payload = json.loads(row["payload"])
        since = datetime.fromisoformat(payload["captured_at"])
        fast = bool(links) and all(
            link["review_status"] in REJECTED
            or (link["review_status"] == "unreviewed" and link["hidden"] in HIDDEN)
            for link in links
        )
        rejected = bool(links) and all(status in REJECTED for status in statuses)
        if only_rejected and not rejected:
            continue
        if fast:
            for link in links:
                if link["reviewed"]:
                    since = max(since, datetime.fromisoformat(link["reviewed"]))
        wait = REJECTED_AGE if rejected else timedelta(days=FAST_DAYS if fast else KEEP_DAYS)
        if now - since < wait:
            continue
        relative = payload.get("relative_path")
        found.append(Candidate(
            row["evidence_id"], payload["media_kind"], payload["captured_at"],
            root / relative if relative else None, int(payload.get("size_bytes") or 0), rejected,
        ))
    return found


def run(database: Any, root: Path, logs: Path, now: datetime | None = None, hourly: bool = False) -> dict[str, Any]:
    """The daily run, or with hourly=True the discard-only pass (never a dry run)."""
    now = now or datetime.now(UTC)
    logs.mkdir(parents=True, exist_ok=True)
    journal, dry = logs / "retention.jsonl", logs / "retention-dry-run.json"
    if hourly and not dry.exists():
        return {"dry_run": False, "removed": 0, "bytes": 0, "skipped": "the first daily run has not happened"}
    with database.connection() as connection:
        found = candidates(connection, root, now, only_rejected=hourly)
    if not dry.exists():
        report = {
            "at": now.isoformat(timespec="seconds"), "would_remove": len(found),
            "bytes": sum(c.size_bytes for c in found),
            "items": [{"evidence_id": c.evidence_id, "kind": c.media_kind, "captured_at": c.captured_at}
                      for c in found],
        }
        dry.write_text(json.dumps(report, indent=1))
        return {"dry_run": True, **{k: report[k] for k in ("would_remove", "bytes")}}
    removed = freed = 0
    for item in found:
        try:
            gone = _remove(database, item, journal, now, "hourly" if hourly else "daily", recheck=item.rejected)
            if gone is not None:
                freed += gone
                removed += 1
        except Exception as exc:  # noqa: BLE001 - one bad file never stops the rest
            log.warning("retention: %s not thinned (%s)", item.evidence_id, type(exc).__name__)
    result: dict[str, Any] = {"dry_run": False, "removed": removed, "bytes": freed}
    if not hourly:
        try:
            result["hidden_cleared"] = clear_hidden(database, root, journal, now)
        except Exception as exc:  # noqa: BLE001 - the media part above already ran
            log.warning("retention: hidden records not cleared (%s)", type(exc).__name__)
    return result


def hidden_due(connection: Any, now: datetime) -> dict[str, list[str]]:
    """Visits and sound bouts FALCON hid (what Review's Hidden status lists by default: field
    recordings only, never tests), with no verdict on any record and no post, older than
    HIDDEN_CLEAR_DAYS: {group key: record ids}.

    A record's age counts from the LATER of its capture time and when it was written, so a
    wrong node clock never shortens the 7 days; a record without a readable time never counts
    as old, and a group without any readable time stays."""
    from app.storage.jsonl import (
        ENCOUNTER_KEY_SQL,
        HIDDEN_CLEAR_DAYS,
        HIDDEN_GROUP_SQL,
        tables,
    )
    from app.storage.observation_context import capture_time_sql, origin_sql

    available = tables(connection)
    captured, written = f"julianday({capture_time_sql(available)})", "julianday(e.recorded_at)"
    newest = f"COALESCE(max({captured}, {written}), {captured}, {written})"
    cut = (now - timedelta(days=HIDDEN_CLEAR_DAYS)).isoformat()
    keys = {row[0] for row in connection.execute(
        f"SELECT {ENCOUNTER_KEY_SQL} AS k FROM observations e WHERE ({origin_sql(available)})='live' GROUP BY k "
        "HAVING MAX(e.review_status!='unreviewed')=0 "
        f"AND MAX({newest}) < julianday(?) "
        f"AND {HIDDEN_GROUP_SQL}", (cut,))}
    if not keys:
        return {}
    found: dict[str, list[str]] = {}
    for event_id, key in connection.execute(f"SELECT e.event_id, {ENCOUNTER_KEY_SQL} FROM observations e"):
        if key in keys:
            found.setdefault(key, []).append(event_id)
    return found


def clear_hidden(database: Any, root: Path, journal: Path, now: datetime) -> dict[str, Any]:
    """Hidden records cleared (since 24 Nov 2026): hidden records not reviewed
    within 7 days of capture go completely, records and the recordings only they
    use, through the same removal as the rats at night. Any verdict or a post keeps them."""
    from app.services.rodents import purge_visits

    with database.connection() as connection:
        due = hidden_due(connection, now)
    if not due:
        return {"visits": 0, "records": 0, "bytes": 0}
    done = purge_visits(database, root, list(due), reason="hidden-7-days", events=due, unreviewed_only=True)
    line = {"at": now.isoformat(timespec="seconds"), "pass": "hidden-clear", "visits": len(done.removed),
            "kept": len(done.kept), "records": done.rows.get("observations", 0), "files": len(done.files),
            "bytes": done.bytes}
    with journal.open("a") as output:
        output.write(json.dumps(line) + "\n")
    return {"visits": len(done.removed), "records": line["records"], "bytes": done.bytes}


def _still_rejected(database: Any, evidence_id: str) -> bool:
    """Right before removal: every linked record is still Discard / Not an animal (an Undo
    in the meantime keeps the footage)."""
    with database.connection() as connection:
        statuses = [r[0] for r in connection.execute(
            "SELECT o.review_status FROM evidence_links l JOIN observations o ON o.event_id=l.event_id "
            "WHERE l.evidence_id=?", (evidence_id,))]
    return bool(statuses) and all(s in REJECTED for s in statuses)


def _remove(database: Any, item: Candidate, journal: Path, now: datetime, pass_name: str = "daily",
            recheck: bool = False) -> int | None:
    if recheck and not _still_rejected(database, item.evidence_id):
        return None
    freed = 0
    if item.path and item.path.exists():
        if item.media_kind == "audio":
            picture = item.path.with_name(f"{item.path.stem}.spectrogram.png")
            if not picture.exists():
                samples, rate = read_wav(item.path.read_bytes())
                picture.write_bytes(spectrogram_png(samples, rate))
        for extra in (small_copy_path(item.path), item.path.with_name(f"{item.path.stem}.clean-v2.wav")):
            if extra.exists():
                freed += extra.stat().st_size
                extra.unlink()
        freed += item.path.stat().st_size
        item.path.unlink()
    message = (
        "Recording removed by the keep-marked rule (confirmed and corrected visits are kept "
        "for good); the picture and all details are kept."
    )
    with database.connection() as connection:
        connection.execute(
            "UPDATE evidence SET status='removed', payload=json_set(payload,'$.status','removed',"
            "'$.message',?) WHERE evidence_id=? AND status IN ('ready','partial')",
            (message, item.evidence_id),
        )
    with journal.open("a") as output:
        output.write(json.dumps({
            "at": now.isoformat(timespec="seconds"), "evidence_id": item.evidence_id,
            "kind": item.media_kind, "captured_at": item.captured_at, "bytes": freed, "pass": pass_name,
        }) + "\n")
    return freed


def status(database: Any, root: Path, now: datetime | None = None) -> dict[str, Any]:
    """For System: space used by recordings, per day, kept for good, next thinning."""
    now = now or datetime.now(UTC)
    marked = ",".join(f"'{m}'" for m in MARKED)
    with database.connection() as connection:
        used = connection.execute(
            "SELECT COALESCE(SUM(json_extract(payload,'$.size_bytes')),0) FROM evidence "
            "WHERE status IN ('ready','partial')").fetchone()[0]
        week = connection.execute(
            "SELECT COALESCE(SUM(json_extract(payload,'$.size_bytes')),0) FROM evidence "
            "WHERE status IN ('ready','partial') AND captured_at >= ?",
            ((now - timedelta(days=7)).isoformat(),)).fetchone()[0]
        kept = connection.execute(
            "SELECT COUNT(DISTINCT l.evidence_id) FROM evidence_links l JOIN observations o ON o.event_id=l.event_id "
            f"JOIN evidence e ON e.evidence_id=l.evidence_id WHERE o.review_status IN ({marked}) "
            "AND e.status IN ('ready','partial')").fetchone()[0]
        oldest = connection.execute(
            "SELECT MIN(e.captured_at) FROM evidence e WHERE e.status IN ('ready','partial') AND NOT EXISTS ("
            "SELECT 1 FROM evidence_links l JOIN observations o ON o.event_id=l.event_id "
            f"WHERE l.evidence_id=e.evidence_id AND o.review_status IN ({marked}))").fetchone()[0]
    small = sum(p.stat().st_size for p in root.glob("*.small.mp4")) if root.exists() else 0
    first = (datetime.fromisoformat(oldest) + timedelta(days=KEEP_DAYS)).date().isoformat() if oldest else None
    return {
        "used_bytes": int(used) + small, "per_day_bytes": int(week) // 7, "kept_for_good": int(kept),
        "keep_days": KEEP_DAYS, "first_thinning": first,
    }


class RetentionJob:
    """The full run once a day at 03:30 India time, and the discard-only pass every hour
    in between (the first one an hour after start); stop() ends the thread."""

    def __init__(self, database: Any, root: Path, logs: Path):
        self.database, self.root, self.logs = database, root, logs
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="falcon-retention", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def next_run(now: datetime) -> datetime:
        at = now.replace(hour=RUN_AT_UTC[0], minute=RUN_AT_UTC[1], second=0, microsecond=0)
        return at if at > now else at + timedelta(days=1)

    @staticmethod
    def next_step(now: datetime, last_hourly: datetime) -> tuple[float, bool]:
        """Seconds to wait and whether the step after it is the daily run."""
        daily = (RetentionJob.next_run(now) - now).total_seconds()
        hourly = max(0.0, (last_hourly + timedelta(seconds=HOURLY) - now).total_seconds())
        return (daily, True) if daily <= hourly else (hourly, False)

    def _loop(self) -> None:
        last_hourly = datetime.now(UTC)
        while True:
            wait, daily = self.next_step(datetime.now(UTC), last_hourly)
            if self._stop.wait(max(1.0, wait)):
                return
            try:
                result = run(self.database, self.root, self.logs, hourly=not daily)
                if daily or result.get("removed"):
                    log.info("retention (%s): %s", "daily" if daily else "hourly", result)
            except Exception as exc:  # noqa: BLE001
                log.warning("retention run failed: %s", type(exc).__name__)
            last_hourly = datetime.now(UTC)  # the daily run covers the hour too
