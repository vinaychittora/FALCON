# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Every first-party source file carries the licence notice (scripts/licence_notice.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "licence_notice.py"


def load():
    spec = importlib.util.spec_from_file_location("licence_notice", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_source_file_has_the_notice():
    notice = load()
    missing = [p for p in notice.files() if not notice.has_notice(
        (notice.ROOT / p).read_text(encoding="utf-8"), notice.kind(p) or "")]
    assert missing == []


def test_adding_is_idempotent_and_keeps_the_shebang_first():
    notice = load()
    text = "#!/usr/bin/env python3\nprint(1)\n"
    once = notice.with_notice(text, ".py")
    assert once.startswith("#!/usr/bin/env python3\n# Copyright (C) 2026 Vinay Chittora.")
    assert notice.with_notice(once, ".py") == once
    css = notice.with_notice(".a { color: red; }\n", ".css")
    assert css.startswith("/*\n * Copyright (C) 2026 Vinay Chittora.") and css.endswith(".a { color: red; }\n")
    ts = notice.with_notice("export const a = 1;\n", ".ts")
    assert ts.splitlines()[0] == "// Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md."
    assert len(notice.NOTICE_LINES) <= 4
