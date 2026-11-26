# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Rats and mice at night (rule since 23 Nov 2026): grain put out for the birds brings rats
and mice after dark, hundreds of visits a night. Between sunset and sunrise (the same
sun clock as the night-insect rule), a visit whose card shows a rat or mouse name is not
kept: while it is open it is hidden and silent (RODENT_NIGHT, "Rat or mouse at night");
when it closes, its records, its review history and the recordings only it uses are
removed. A recording shared with another visit stays. A visit confirmed, corrected,
marked unsure or posted is never removed. Only a count per night is kept (System shows
it). By day nothing changes. Fixed behaviour, no setting.

The same removal served the one-off clean-up of 23 Nov. Removed records are listed in
purged_events, so a later re-import of the JSONL mirrors never brings them back.

No score at night (since 24 Nov 2026, for black "Unknown
organism" cards): a picture visit that closes in true night (sun_phase "night", not
twilight) with no species score on any of its frames is removed the same way. One scored
frame keeps it; a verdict or a post keeps it; by day and in twilight nothing changes.

Cost: the rat rule reads the closing visit's records once (visit_card); in true night the
no-score rule adds one more scan of that visit's records in the session (no_score), by
json_extract on visit_id within the job. Accepted; no index for now.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.inference.labels import counted_classification, visit_classification

# Every rat, mouse and bandicoot-rat of the group "Mouse or rat" (Muridae) in the
# Rajasthan taxa; the group's other members are kept, see KEPT.
RODENT_TAXA = {
    44705: "House Mouse",  # Mus musculus
    44698: "Common Indian Field Mouse",  # Mus booduga
    45664: "Greater Bandicoot-rat",  # Bandicota indica
    44575: "Black Rat",  # Rattus rattus
    44576: "Brown Rat",  # Rattus norvegicus
    44546: "Oriental House Rat",  # Rattus tanezumi
    45618: "Cutch Rock Rat",  # Cremnomys cutchicus
    45637: "Indian Bush Rat",  # Golunda ellioti
}
KEPT = {
    44653: "Indian Gerbil",  # Tatera indica
    44208: "Indian Hairy-footed Gerbil",  # Gerbillus gleadowi
    44676: "Indian Desert Jird",  # Meriones hurrianae
}
GROUP_FAMILY = 44185  # Muridae in groups.json
GROUP_LABEL = "Mouse or rat"
RODENT_GROUP = f"{GROUP_LABEL} (species uncertain)"
RODENT_NAMES = frozenset({*RODENT_TAXA.values(), RODENT_GROUP})
HIDDEN = "RODENT_NIGHT"
LABEL = "Rat or mouse at night"
PROTECTED = ("correct", "corrected", "unknown")  # Confirm, Correct, Unsure: the verdict wins
BATCH = 50  # visits per transaction: short, well under the 30 s busy timeout


def plain(label: str | None) -> str:
    return (label or "").replace(" — candidate", "").rstrip("?").strip()


def is_rodent(name: str | None) -> bool:
    """A card name that is a rat or a mouse."""
    return plain(name) in RODENT_NAMES


def card_name(row: dict[str, Any] | None, events: list[Any], tiers: Any = None) -> str:
    """The name a visit's card shows while it has no verdict: the same choice as
    EventStore.encounters (counted tier from the visit row, else the frames' tier)."""
    visual = [e for e in events if getattr(e, "modality", None) == "visual"]
    if not visual:
        return ""
    latest = visual[-1].classification
    if row and row.get("tier"):
        candidates = sorted({c.taxon_id: c for e in visual for c in e.classification.top_k or []}.values(),
                            key=lambda c: -c.score)
        shown = counted_classification(latest, row, candidates)
    elif tiers is not None:
        shown = visit_classification([e.classification for e in visual], latest, tiers,
                                     boxes=[e.bbox_norm for e in visual])
    else:
        shown = latest
    return plain(shown.display_label or shown.common_name or shown.scientific_name)


def visit_card(database: Any, visit_id: str, tiers: Any = None) -> tuple[dict[str, Any] | None, str]:
    """The visit row and its card name, read from the database."""
    from app.storage.jsonl import adapter

    with database.connection() as connection:
        found = connection.execute("SELECT job_id, hidden_reason, payload FROM visits WHERE visit_id=?",
                                   (visit_id,)).fetchone()
        row = None if found is None else {"hidden_reason": found[1], **json.loads(found[2])}
        query = ("SELECT payload FROM observations WHERE job_id=? AND json_extract(payload,'$.visit_id')=? "
                 "ORDER BY timestamp_ms") if found else (
                 "SELECT payload FROM observations WHERE json_extract(payload,'$.visit_id')=? ORDER BY timestamp_ms")
        payloads = [r[0] for r in connection.execute(query, (found[0], visit_id) if found else (visit_id,))]
    events = [adapter.validate_json(p) for p in payloads]
    if row and row.get("hidden_reason") == "INSECT_NIGHT":
        return row, "Insect (night, not identified)"
    return row, card_name(row, events, tiers)


def no_score(database: Any, visit_id: str) -> bool:
    """True when the visit has picture frames and none of them carries a species score."""
    with database.connection() as connection:
        found = connection.execute("SELECT job_id FROM visits WHERE visit_id=?", (visit_id,)).fetchone()
        where = "json_extract(payload,'$.visit_id')=? AND modality='visual'" + (" AND job_id=?" if found else "")
        frames, scored = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(COALESCE(json_extract(payload,'$.classification.score'), 0) > 0), 0) "
            f"FROM observations WHERE {where}", (visit_id, found[0]) if found else (visit_id,),
        ).fetchone()
    return frames > 0 and scored == 0


def night_of(moment: datetime, lon: float | None) -> date:
    """The evening a night began: the date 12 hours before local solar time at the site."""
    hours = (lon or 0.0) / 15.0
    return (moment.astimezone(UTC) + timedelta(hours=hours) - timedelta(hours=12)).date()


def _media_files(root: Path, relative: str | None) -> list[Path]:
    if not relative:
        return []
    base = (root / relative).resolve()
    if base.parent != root.resolve():
        return []  # never outside the evidence folder
    return [base, base.with_name(f"{base.stem}.small.mp4"), base.with_name(f"{base.stem}.spectrogram.png"),
            base.with_name(f"{base.stem}.clean-v2.wav"), base.with_name(f"{base.stem}.clean.wav")]


@dataclass
class Purged:
    visits: int = 0
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # a verdict or a post protects them
    rows: dict[str, int] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    bytes: int = 0
    pending: set[str] = field(default_factory=set)  # recordings still being written

    def add(self, table: str, count: int) -> None:
        self.rows[table] = self.rows.get(table, 0) + count


def purge_visits(database: Any, root: Path, visit_ids: Iterable[str], *, reason: str,
                 trash: Path | None = None, events: dict[str, list[str]] | None = None,
                 unreviewed_only: bool = False) -> Purged:
    """Remove these visits with everything only they use, unless a verdict or a post
    protects them. Files go to `trash` when given (to check first), else are deleted.
    `events` gives the record ids of groups without a visit row (old records, sound bouts);
    with `unreviewed_only`, a group with any reviewed record (even Discard) is kept."""
    result = Purged()
    ids = list(dict.fromkeys(visit_ids))
    for start in range(0, len(ids), BATCH):
        _purge_batch(database, root, ids[start:start + BATCH], reason, trash, result, events, unreviewed_only)
    return result


def _events_of(connection: Any, visit_ids: list[str]) -> dict[str, list[str]]:
    """Each visit's record ids: through its job's index when the visit row knows the job."""
    marks = ",".join("?" * len(visit_ids))
    jobs = dict(connection.execute(f"SELECT visit_id, job_id FROM visits WHERE visit_id IN ({marks})", visit_ids))
    found: dict[str, list[str]] = {v: [] for v in visit_ids}
    by_job: dict[str, list[str]] = {}
    for visit_id in visit_ids:
        if jobs.get(visit_id):
            by_job.setdefault(jobs[visit_id], []).append(visit_id)
    for job, members in by_job.items():
        m = ",".join("?" * len(members))
        for event_id, visit_id in connection.execute(
                f"SELECT event_id, json_extract(payload,'$.visit_id') FROM observations WHERE job_id=? "
                f"AND json_extract(payload,'$.visit_id') IN ({m})", [job, *members]):
            found[visit_id].append(event_id)
    rest = [v for v in visit_ids if not jobs.get(v)]
    if rest:  # no visit row, or no job: the slower search, only for these
        m = ",".join("?" * len(rest))
        for event_id, visit_id in connection.execute(
                f"SELECT event_id, json_extract(payload,'$.visit_id') FROM observations "
                f"WHERE json_extract(payload,'$.visit_id') IN ({m})", rest):
            found[visit_id].append(event_id)
    return found


def _protected(connection: Any, visit_id: str, events: list[str]) -> bool:
    posts = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inat_posts'").fetchone()
    if posts and connection.execute("SELECT 1 FROM inat_posts WHERE encounter_id=? LIMIT 1", (visit_id,)).fetchone():
        return True
    for chunk in _chunks(events):
        marks = ",".join("?" * len(chunk))
        if connection.execute(f"SELECT 1 FROM observations WHERE event_id IN ({marks}) AND review_status IN "
                              f"({','.join('?' * len(PROTECTED))}) LIMIT 1", [*chunk, *PROTECTED]).fetchone():
            return True
    return False


def _reviewed(connection: Any, events: list[str]) -> bool:
    for chunk in _chunks(events):
        marks = ",".join("?" * len(chunk))
        if connection.execute(f"SELECT 1 FROM observations WHERE event_id IN ({marks}) AND review_status!='unreviewed' "
                              "LIMIT 1", chunk).fetchone():
            return True
    return False


def _purge_batch(database: Any, root: Path, visit_ids: list[str], reason: str,
                 trash: Path | None, result: Purged, events: dict[str, list[str]] | None = None,
                 unreviewed_only: bool = False) -> None:
    now = datetime.now(UTC).isoformat()
    doomed: list[tuple[str, str | None]] = []
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        found = _events_of(connection, visit_ids)
        for visit_id in visit_ids:
            if events is not None and not found[visit_id]:
                found[visit_id] = list(events.get(visit_id, []))
        chosen = []
        for visit_id in visit_ids:
            if _protected(connection, visit_id, found[visit_id]) or (
                    unreviewed_only and _reviewed(connection, found[visit_id])):
                result.kept.append(visit_id)
            else:
                chosen.append(visit_id)
        if not chosen:
            return
        events = [e for v in chosen for e in found[v]]
        touched: set[str] = set()
        for chunk in _chunks(events):
            marks = ",".join("?" * len(chunk))
            touched |= {row[0] for row in connection.execute(
                f"SELECT evidence_id FROM evidence_links WHERE event_id IN ({marks})", chunk)}
            result.add("evidence_links", connection.execute(
                f"DELETE FROM evidence_links WHERE event_id IN ({marks})", chunk).rowcount)
        for evidence_id in sorted(touched):
            if connection.execute("SELECT 1 FROM evidence_links WHERE evidence_id=? LIMIT 1", (evidence_id,)).fetchone():
                continue  # another visit uses it: the file stays
            row = connection.execute("SELECT status, payload FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
            if row is None:
                continue
            if row[0] == "pending":
                result.pending.add(evidence_id)  # still recording: removed by sweep() later
                continue
            doomed.append((evidence_id, json.loads(row[1]).get("relative_path")))
            result.add("evidence", connection.execute(
                "DELETE FROM evidence WHERE evidence_id=?", (evidence_id,)).rowcount)
        for chunk in _chunks(events):
            marks = ",".join("?" * len(chunk))
            result.add("observation_terms", connection.execute(
                f"DELETE FROM observation_terms WHERE event_id IN ({marks})", chunk).rowcount)
            result.add("review_audit", connection.execute(
                f"DELETE FROM review_audit WHERE event_id IN ({marks})", chunk).rowcount)
            connection.executemany("INSERT OR IGNORE INTO purged_events VALUES (?, ?, ?)",
                                   [(event_id, now, reason) for event_id in chunk])
            result.add("observations", connection.execute(
                f"DELETE FROM observations WHERE event_id IN ({marks})", chunk).rowcount)
        marks = ",".join("?" * len(chosen))
        result.add("visits", connection.execute(f"DELETE FROM visits WHERE visit_id IN ({marks})", chosen).rowcount)
        result.visits += len(chosen)
        result.removed += chosen
    _remove_files(root, doomed, trash, result)


def sweep(database: Any, root: Path, pending: set[str], *, trash: Path | None = None) -> Purged:
    """Recordings left by removed visits once they are written: removed if still unused."""
    result = Purged()
    doomed: list[tuple[str, str | None]] = []
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for evidence_id in sorted(pending):
            if connection.execute("SELECT 1 FROM evidence_links WHERE evidence_id=? LIMIT 1", (evidence_id,)).fetchone():
                pending.discard(evidence_id)  # a later visit took it over: it stays
                continue
            row = connection.execute("SELECT status, payload FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
            if row is None:
                pending.discard(evidence_id)
                continue
            if row[0] == "pending":
                result.pending.add(evidence_id)
                continue
            doomed.append((evidence_id, json.loads(row[1]).get("relative_path")))
            result.add("evidence", connection.execute("DELETE FROM evidence WHERE evidence_id=?", (evidence_id,)).rowcount)
            pending.discard(evidence_id)
    _remove_files(root, doomed, trash, result)
    return result


def _remove_files(root: Path, doomed: list[tuple[str, str | None]], trash: Path | None, result: Purged) -> None:
    for _, relative in doomed:
        for path in _media_files(root, relative):
            try:
                if not path.is_file():
                    continue
                size = path.stat().st_size
                if trash is not None:
                    trash.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), str(trash / path.name))
                else:
                    path.unlink()
                result.files.append(path.name)
                result.bytes += size
            except OSError:
                pass  # one stubborn file never stops the rest


def _chunks(items: list[str], size: int = 500) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


class RodentWatch:
    """The rule inside one live session. While a visit is marked, every write to its row
    carries the mark (the reason it covers goes to hidden_before_rodent), so no reader ever
    sees a marked visit unmarked; only the decision to unmark takes it off. The open
    visit's card name comes from memory (latest frame, candidates so far), the closing one
    from the database."""

    def __init__(self, store: Any, session_id: str, night: Any, root: Path, count: NightCount,
                 on_count: Any = None, tiers: Any = None, log: Any = None, clock: Any = None,
                 dark: Any = None, noscore_count: NightCount | None = None):
        import logging
        import time

        self.store, self.session_id, self.night, self.root = store, session_id, night, root
        self.count, self.on_count, self.tiers = count, on_count, tiers
        # No score at night: `dark` is true night only (not twilight); None turns it off.
        self.dark, self.noscore_count = dark, noscore_count
        self.noscore: set[str] = set()  # closed visits waiting for removal by the no-score rule
        self.log = log or logging.getLogger("falcon.rodents")
        self.clock = clock or time.monotonic
        self.marked: dict[str, str | None] = {}  # visit -> the hidden reason the mark covers
        self.cards: dict[str, tuple[Any, dict[int, Any]]] = {}  # latest classification, candidates
        self.rows: dict[str, dict[str, Any]] = {}  # tier, name, taxon_id, reasons as last graded
        self.pending: set[str] = set()
        self._swept = 0.0
        self._warned: dict[str, float] = {}

    def warn(self, kind: str, message: str, *args: Any) -> None:
        """At most one warning per minute of each kind."""
        now = self.clock()
        if now - self._warned.get(kind, -1e9) >= 60:
            self._warned[kind] = now
            self.log.warning(message, *args, exc_info=True)

    def reason(self, visit_id: str, stored: dict[str, Any] | None) -> str | None:
        """The visit's own hidden reason, under the mark if there is one."""
        if visit_id in self.marked:
            return self.marked[visit_id]
        hidden = (stored or {}).get("hidden_reason")
        return (stored or {}).get("hidden_before_rodent") if hidden == HIDDEN else hidden

    def put(self, visit_id: str, hidden: str | None, **fields: Any) -> None:
        """Every write of an open visit's row goes through here (hidden = its own reason)."""
        if visit_id in self.marked:
            self.marked[visit_id] = hidden
            self.store.upsert(visit_id, self.session_id, HIDDEN, hidden_before_rodent=hidden, **fields)
        else:
            self.store.upsert(visit_id, self.session_id, hidden, **fields)

    def seen(self, event: Any) -> None:
        """A recorded frame of an open visit: its classification and candidates."""
        if not event.visit_id:
            return
        _, candidates = self.cards.get(event.visit_id, (None, {}))
        for candidate in event.classification.top_k or []:
            candidates[candidate.taxon_id] = candidate
        self.cards[event.visit_id] = (event.classification, candidates)

    def name(self, visit_id: str) -> str:
        """The open visit's card name, as EventStore.encounters would show it. A row without
        a tier is not judged while open."""
        row, card = self.rows.get(visit_id), self.cards.get(visit_id)
        if not row or not row.get("tier") or not card:
            return ""
        latest, candidates = card
        ranked = sorted(candidates.values(), key=lambda c: -c.score)
        shown = counted_classification(latest, row, ranked)
        return plain(shown.display_label or shown.common_name or shown.scientific_name)

    def graded(self, visit_id: str, fields: dict[str, Any], stored: dict[str, Any] | None, ring: bool) -> None:
        """A new tier or name: decide the mark for the new row, then write it all at once."""
        self.rows[visit_id] = {k: fields.get(k) for k in ("tier", "name", "taxon_id", "reasons")}
        own = self.reason(visit_id, stored)
        want = bool(self.night()) and is_rodent(self.name(visit_id))
        if want:
            self.marked[visit_id] = own
            self.store.upsert(visit_id, self.session_id, HIDDEN, hidden_before_rodent=own, **fields)
            return
        self.marked.pop(visit_id, None)
        if ring:
            from datetime import UTC, datetime
            fields = {**fields, "bell_at": datetime.now(UTC).isoformat()}  # Live shows it, the bell rings
        self.store.upsert(visit_id, self.session_id, own, hidden_before_rodent=None, **fields)

    def check(self, visit_id: str) -> None:
        """Every frame: the card can change with the latest frame alone. By day only a
        leftover mark comes off."""
        if not self.night():
            if visit_id in self.marked:
                self.store.upsert(visit_id, self.session_id, self.marked.pop(visit_id), hidden_before_rodent=None)
            return
        want = is_rodent(self.name(visit_id))
        if want and visit_id not in self.marked:
            own = self.reason(visit_id, self.store.get(visit_id))
            self.marked[visit_id] = own
            self.store.upsert(visit_id, self.session_id, HIDDEN, hidden_before_rodent=own)
        elif not want and visit_id in self.marked:
            self.store.upsert(visit_id, self.session_id, self.marked.pop(visit_id), hidden_before_rodent=None)

    def closing(self, visit_id: str, hidden: str | None, **fields: Any) -> bool:
        """The close write; True when the visit is to be removed (it is closed with the mark)."""
        rodent = False
        if self.night() and hidden != "INSECT_NIGHT":
            try:
                rodent = is_rodent(visit_card(self.store.database, visit_id, self.tiers)[1])
            except Exception:  # noqa: BLE001 - observation goes on
                self.warn("card", "rats and mice at night: a closing visit could not be judged")
                rodent = visit_id in self.marked  # keep what the open visit showed
        blank = False
        if not rodent and self.dark is not None:
            try:
                blank = bool(self.dark()) and no_score(self.store.database, visit_id)
            except Exception:  # noqa: BLE001 - observation goes on; the visit is kept
                blank = False
                self.warn("noscore", "no score at night: a closing visit could not be judged")
        self.marked.pop(visit_id, None)
        self.cards.pop(visit_id, None)
        self.rows.pop(visit_id, None)
        if rodent:
            self.store.upsert(visit_id, self.session_id, HIDDEN, hidden_before_rodent=hidden, **fields)
        elif blank:
            # Closed hidden (its own reason, else UNIDENTIFIED) and removed below; if the
            # removal fails it stays hidden and retention thins it.
            self.noscore.add(visit_id)
            self.store.upsert(visit_id, self.session_id, hidden or "UNIDENTIFIED", hidden_before_rodent=hidden, **fields)
        else:
            self.store.upsert(visit_id, self.session_id, hidden, hidden_before_rodent=None, **fields)
        return rodent or blank

    def remove(self, visit_ids: list[str]) -> Purged | None:
        """Remove closed rat and mouse visits, and closed no-score night visits;
        recordings still being written later. Returns the rats' result, else the no-score
        one (live.py does not use it; tests do)."""
        if self.pending and self.clock() - self._swept >= 30:
            self._swept = self.clock()
            try:
                sweep(self.store.database, self.root, self.pending)
            except Exception:  # noqa: BLE001
                self.warn("sweep", "rats and mice at night: a recording could not be removed")
        blank = [v for v in visit_ids if v in self.noscore]
        self.noscore.difference_update(blank)
        rats = [v for v in visit_ids if v not in set(blank)]
        gone = self._remove(blank, "noscore-night", self.noscore_count, "no score at night") if blank else None
        return self._remove(rats, "rodent-night", self.count, "rats and mice at night") if rats else gone

    def _remove(self, visit_ids: list[str], reason: str, count: NightCount | None, what: str) -> Purged | None:
        try:
            done = purge_visits(self.store.database, self.root, visit_ids, reason=reason)
        except Exception:  # noqa: BLE001 - they stay closed and hidden; retention thins them
            self.warn("purge", f"{what}: %d visit(s) could not be removed", len(visit_ids))
            return None
        self.pending |= done.pending
        for visit_id in done.kept:  # the verdict wins: its own reason back
            try:
                row = self.store.get(visit_id) or {}
                self.store.upsert(visit_id, self.session_id, row.get("hidden_before_rodent"), hidden_before_rodent=None)
            except Exception:  # noqa: BLE001
                self.warn("kept", f"{what}: a kept visit could not be shown again")
        if done.removed and count is not None:
            count.add(datetime.now(UTC), len(done.removed))
            if self.on_count:
                self.on_count()
        return done


class NightCount:
    """Visits not kept, per night (the evening's date), in a small JSON file under data/state
    (rodents-night.json for rats and mice, noscore-night.json for no-score pictures)."""

    def __init__(self, path: Path, lon: float | None):
        self.path, self.lon = path, lon
        self._lock = threading.Lock()

    def _read(self) -> dict[str, int]:
        try:
            data = json.loads(self.path.read_text())
            return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def add(self, moment: datetime, count: int = 1) -> None:
        with self._lock:
            counts = self._read()
            key = night_of(moment, self.lon).isoformat()
            counts[key] = counts.get(key, 0) + count
            for old in sorted(counts)[:-60]:  # two months are plenty
                counts.pop(old)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(counts))
                temporary.replace(self.path)
            except OSError:
                pass

    def recent(self) -> list[list[Any]]:
        """The two most recent nights with a count, newest first: [[evening date, count], ...]."""
        counts = {k: v for k, v in self._read().items() if v > 0}
        return [[k, counts[k]] for k in sorted(counts, reverse=True)[:2]]
