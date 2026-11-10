"""Clip retention plan (spec P6), REPORT ONLY: nothing is deleted.

The spec asks to keep clips of hidden records 48 h unless opened or reviewed, clips of
visits 30 days, at most 2 GB of new clips a day (oldest hidden clips first). The
owner's standing rule is that nothing is deleted automatically, so this only writes
what the rule *would* remove, for him to decide:

    python -m app.research.clip_retention   # -> data/diagnostics/clip-retention-DATE.json

"Opened" is not tracked yet; a reviewed record counts as kept.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

DATA = Path("/home/vinay/Workspace/FALCON/data")
HIDDEN = {"GLIMPSE", "STILL", "UNIDENTIFIED", "SMALL", "CANDIDATE"}
DAILY_CAP = 2 * 1024**3


def plan(data: Path = DATA, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    connection = sqlite3.connect(f"file:{data / 'falcon.sqlite3'}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT ev.evidence_id, ev.captured_at, json_extract(ev.payload,'$.size_bytes'), "
        "MAX(o.review_status!='unreviewed'), MAX(v.hidden_reason), MAX(json_extract(o.payload,'$.visit_id')) "
        "FROM evidence ev LEFT JOIN evidence_links l ON l.evidence_id=ev.evidence_id "
        "LEFT JOIN observations o ON o.event_id=l.event_id "
        "LEFT JOIN visits v ON v.visit_id=json_extract(o.payload,'$.visit_id') "
        "WHERE ev.status='ready' GROUP BY ev.evidence_id",
    ).fetchall()
    would_remove: list[dict] = []
    per_day: Counter[str] = Counter()
    per_hour: Counter[str] = Counter()
    for evidence_id, captured, size, reviewed, hidden, visit_id in rows:
        when = datetime.fromisoformat(captured)
        size = int(size or 0)
        per_day[when.date().isoformat()] += size
        per_hour[when.strftime("%Y-%m-%d %H:00")] += 1
        if reviewed or not visit_id:
            continue  # reviewed, or graded by the old rules: outside this rule
        age = now - when
        if (hidden in HIDDEN and age > timedelta(hours=48)) or age > timedelta(days=30):
            would_remove.append({"evidence_id": evidence_id, "captured_at": captured, "bytes": size,
                                 "reason": f"hidden {hidden} > 48 h" if hidden in HIDDEN else "> 30 days"})
    over_cap = {day: total for day, total in per_day.items() if total > DAILY_CAP}
    return {
        "made_at": now.isoformat(), "deleted": 0, "note": "report only: nothing is deleted",
        "would_remove": len(would_remove), "would_free_bytes": sum(r["bytes"] for r in would_remove),
        "days_over_2_GB": over_cap, "clips_per_hour": dict(sorted(per_hour.items())[-48:]),
        "items": would_remove[:500],
    }


if __name__ == "__main__":
    result = plan()
    out = DATA / "diagnostics" / f"clip-retention-{datetime.now(UTC):%Y-%m-%d}.json"
    out.write_text(json.dumps(result, indent=1))
    print(f"{result['would_remove']} clips ({result['would_free_bytes'] / 1e9:.2f} GB) would go; "
          f"days over 2 GB: {len(result['days_over_2_GB'])}; nothing deleted -> {out}")
