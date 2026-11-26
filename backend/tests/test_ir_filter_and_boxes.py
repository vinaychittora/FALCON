# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.services.ir_filter import IrFilterLog


def picture(magenta: bool) -> np.ndarray:
    rgb = np.full((64, 64, 3), 120, dtype=np.uint8)
    if magenta:
        rgb[..., 0], rgb[..., 1], rgb[..., 2] = 170, 100, 165
    return rgb


def test_filter_switch_is_logged_once_after_three_agreeing_checks(tmp_path: Path) -> None:
    now = [0.0]
    log = IrFilterLog(tmp_path / "ir-filter.jsonl", clock=lambda: now[0])

    def check(magenta: bool) -> str | None:
        now[0] += 61
        return log.frame(picture(magenta), datetime(2026, 11, 15, 1, 30, tzinfo=UTC))

    assert [check(True) for _ in range(3)] == [None, None, None]  # the first state is not a switch
    assert log.state == "infrared"
    assert check(False) is None and check(True) is None  # hunting: no change counted
    assert [check(False) for _ in range(3)] == [None, None, "colour"]
    lines = [json.loads(line) for line in (tmp_path / "ir-filter.jsonl").read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["filter"] == "colour"


def test_boxes_endpoint_times_detections_from_the_recording_start(tmp_path: Path) -> None:
    from app.config import Settings
    from app.main import create_app
    from app.schemas import AnalysisSettings
    from tests.test_encounter_evidence import SESSION, SOURCE, START, visual
    from tests.test_retention import make

    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        app = client.app
        store, events = app.state.evidence, app.state.events  # type: ignore[attr-defined]
        store.register_session(SESSION, SOURCE, "Synthetic capture", START, AnalysisSettings())
        own = [visual(ms, track="a") for ms in (1000, 2000, 3000)]
        other = visual(2500, track="b")
        for event in [*own, other]:
            events.append(event)
        evidence_id = make(store, "video", 0, own[0].event_id)
        answer = client.get(f"/api/evidence/{evidence_id}/boxes?event_id={own[1].event_id}").json()
        assert answer["own_span"] == [1000, 3000]
        assert sorted((b["t"], b["own"]) for b in answer["boxes"]) == [
            (1000, True), (2000, True), (2500, False), (3000, True),
        ]
