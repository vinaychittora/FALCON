# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Keep import-time FastAPI initialization away from the user's saved records."""

import os
import tempfile

_test_data = tempfile.TemporaryDirectory(prefix="falcon-test-app-")
os.environ["DATA_DIR"] = _test_data.name


def pytest_unconfigure() -> None:
    _test_data.cleanup()
