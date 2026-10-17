import hashlib
from pathlib import Path

import httpx


def download_checked(url: str, target: Path, expected_md5: str, expected_size: int) -> None:
    """Download known, small upstream weights with a timeout and atomic cache insertion."""
    if expected_size > 5_000_000_000:
        raise ValueError("This model exceeds the configured 5 GB approval limit")
    if target.exists() and target.stat().st_size == expected_size:
        with target.open("rb") as file:
            if hashlib.file_digest(file, "md5").hexdigest() == expected_md5:
                return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    output.write(chunk)
                    if output.tell() > expected_size:
                        raise ValueError("Unexpected model download size")
        with temporary.open("rb") as file:
            if (
                temporary.stat().st_size != expected_size
                or hashlib.file_digest(file, "md5").hexdigest() != expected_md5
            ):
                raise ValueError("Model integrity check failed")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
