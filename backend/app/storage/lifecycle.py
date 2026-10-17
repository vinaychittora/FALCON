"""Reentrant process and thread lock for temporary-data ownership transitions."""

import fcntl
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_registry_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_held = threading.local()


@contextmanager
def lifecycle_lock(root: Path) -> Iterator[None]:
    key = str(root.resolve())
    with _registry_guard:
        mutex = _locks.setdefault(key, threading.RLock())
    with mutex:
        held: set[str] = getattr(_held, "roots", set())
        _held.roots = held
        if key in held:
            yield
            return
        directory = root / "private"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink():
            raise ValueError("Private lifecycle directory cannot be a symbolic link")
        descriptor = os.open(
            directory / "test-sessions.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
        finally:
            os.close(descriptor)
