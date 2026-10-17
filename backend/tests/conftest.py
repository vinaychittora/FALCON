"""Keep import-time FastAPI initialization away from the user's saved records."""

import os
import tempfile

_test_data = tempfile.TemporaryDirectory(prefix="falcon-test-app-")
os.environ["DATA_DIR"] = _test_data.name


def pytest_unconfigure() -> None:
    _test_data.cleanup()
