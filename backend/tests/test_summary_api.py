"""Species counts per period, one row per session, and the resolved-only live feed."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import AudioEvent, Candidate, Classification, DetectorResult, VisualEvent

SOURCE = "e" * 24
SESSION = "33333333-4444-5555-6666-777777777777"
OTHER_SOURCE = "f" * 24
OTHER_SESSION = "44444444-5555-6666-7777-888888888888"
START = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)


def visual(track: str, seconds: float, *, status: str = "candidate", group: str = "Aves",
           name: str = "Pavo cristatus", common: str = "Indian Peafowl", source: str = SOURCE,
           session: str = SESSION, detector: str = "animal") -> VisualEvent:
    classification = Classification(status="unknown", broad_group=group, display_label="Unknown organism")
    if status == "candidate":
        classification = Classification(
            scientific_name=name, common_name=common, score=0.4, status="candidate",
            display_label=common, broad_group=group,
            top_k=[Candidate(taxon_id=1, scientific_name=name, common_name=common, group=group, score=0.4)],
        )
    elif status == "non_wildlife":
        classification = Classification(status="non_wildlife", display_label="person", broad_group="person")
    return VisualEvent(
        job_id=session, source_id=source, source_filename="Camera", timestamp_ms=int(seconds * 1000),
        duration_ms=500, track_id=track, bbox_norm=(0.2, 0.2, 0.6, 0.6),
        detector=DetectorResult(label=detector, score=0.8, model="MegaDetector"),
        classification=classification, models={}, source_kind="live", time_basis="server_receive_time",
        captured_at=(START + timedelta(seconds=seconds)).isoformat(),
    )


def test_summary_counts_visits_per_species_and_sessions_list_each_run(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        app.state.evidence.register_session(SESSION, SOURCE, "Backyard camera", START, {})
        app.state.evidence.finish_session(SESSION, START + timedelta(hours=2), "stopped", {"visual_frames": 10})
        app.state.evidence.register_session(OTHER_SESSION, OTHER_SOURCE, "Pond node", START + timedelta(days=1), {})
        peafowl = [visual("t1", 10 + i * 0.5) for i in range(4)]              # one visit, four frames
        again = visual("t2", 60)                                               # a second peafowl visit
        unknown_bird = visual("t3", 90, status="unknown", group="Aves")        # unknown bird
        unresolved = visual("t4", 120, status="unknown", group="organism")     # nothing known
        person = visual("t5", 150, status="non_wildlife", detector="person")
        crow = visual("t6", 200, name="Corvus splendens", common="House Crow")
        later = visual("t7", 86400 + 10, source=OTHER_SOURCE, session=OTHER_SESSION)
        call = AudioEvent(
            job_id=SESSION, source_id=SOURCE, source_filename="Camera", start_ms=300000, end_ms=303000,
            scientific_name="Psittacula krameri", common_name="Rose-ringed Parakeet", confidence=0.7, models={},
            source_kind="live", time_basis="server_receive_time", captured_at=(START + timedelta(seconds=300)).isoformat(),
        )
        for event in [*peafowl, again, unknown_bird, unresolved, person, crow, later, call]:
            app.state.events.append(event)
        # The reviewer corrects the crow to a raven and rejects the second peafowl visit.
        client.post("/api/detections/encounters/review", json={
            "encounter_ids": [f"{SESSION}:t2"], "review": {"status": "false_positive"},
        })
        raven = next(t for t in app.state.taxa.read().taxa if t.scientific_name == "Corvus corax") if any(
            t.scientific_name == "Corvus corax" for t in app.state.taxa.read().taxa) else None
        if raven:
            client.post("/api/detections/encounters/review", json={
                "encounter_ids": [f"{SESSION}:t6"], "review": {"status": "corrected", "corrected_taxon_id": raven.taxon_id},
            })

        summary = client.get("/api/summary", params={"scope": "live"}).json()
        totals = summary["totals"]
        # t1, t3, t4, t6, t7 and the call count; t2 is rejected and t5 is a person (both left out).
        assert totals["visits"] == 6 and totals["records"] == 9
        assert totals["visual"] == 5 and totals["audio"] == 1
        assert totals["identified"] == 4 and totals["unresolved"] == 2
        names = {item["scientific_name"]: item for item in summary["species"]}
        assert names["Pavo cristatus"]["visits"] == 2 and names["Pavo cristatus"]["visual"] == 2
        assert names["Psittacula krameri"]["audio"] == 1
        assert summary["species_count"] == 3  # peafowl, the crow or its correction, the parakeet
        groups = {item["group"]: item["visits"] for item in summary["groups"]}
        assert groups["Aves"] >= 4 and groups["organism"] == 1
        assert names["Pavo cristatus"]["first_seen"].startswith("2026-10-18T06:00:10")

        everything = client.get("/api/summary", params={"scope": "live", "review": "everything"}).json()
        assert everything["totals"]["visits"] == 8 and everything["totals"]["not_animal"] == 2
        verified = client.get("/api/summary", params={"scope": "live", "review": "verified"}).json()
        assert verified["totals"]["visits"] == (1 if raven else 0)

        window = client.get("/api/summary", params={
            "scope": "live", "captured_from": (START + timedelta(hours=12)).isoformat(),
        }).json()
        assert window["totals"]["visits"] == 1 and window["species"][0]["scientific_name"] == "Pavo cristatus"
        per_source = client.get("/api/summary", params={"scope": "live", "source_id": OTHER_SOURCE}).json()
        assert per_source["totals"]["visits"] == 1

        sessions = client.get("/api/sessions").json()
        assert sessions["active_session_id"] is None
        rows = {row["session_id"]: row for row in sessions["sessions"]}
        first = rows[SESSION]
        assert first["name"] == "Backyard camera" and first["status"] == "stopped"
        assert first["duration_ms"] == 7200000 and first["visits"] == 5 and first["records"] == 8
        assert first["unresolved"] == 2 and first["species_count"] == 3
        assert first["active"] is False and first["clips"] == 0
        second = rows[OTHER_SESSION]
        assert second["ended_at"] is None and second["duration_ms"] is None and second["visits"] == 1
        windowed = client.get("/api/sessions", params={
            "captured_from": (START + timedelta(hours=12)).isoformat(),
        }).json()["sessions"]
        assert [row["session_id"] for row in windowed] == [OTHER_SESSION]

        # The live feed hides unresolved visits and people by default, newest visit first.
        feed = client.get("/api/detections/encounters", params={
            "scope": "live", "resolved_only": "true", "order": "first_seen", "source_id": SOURCE,
        }).json()
        assert feed["hidden_unresolved"] == 2
        assert [item["encounter_id"] for item in feed["encounters"]] == [
            call.event_id, f"{SESSION}:t6", f"{SESSION}:t3", f"{SESSION}:t2", f"{SESSION}:t1",
        ]
        latest = client.get("/api/detections/encounters", params={"scope": "live", "source_id": SOURCE}).json()
        assert latest["hidden_unresolved"] == 0 and latest["total"] == 7
        # Review hides one-frame picture visits ("glimpses") when asked; sound stays.
        single = {i["encounter_id"] for i in latest["encounters"] if i["modality"] == "visual" and i["records"] == 1}
        trimmed = client.get("/api/detections/encounters", params={
            "scope": "live", "source_id": SOURCE, "hide_glimpses": "true",
        }).json()
        assert single and trimmed["hidden_glimpses"] == len(single)
        assert trimmed["total"] == 7 - len(single)
        assert not single & {i["encounter_id"] for i in trimmed["encounters"]}
        records = client.get("/api/detections", params={"scope": "live", "resolved_only": "true"}).json()
        assert records["total"] == 9
