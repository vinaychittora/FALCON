"""Build an inspected source-only release without copying local Git history or data.

Uses only Python's standard library. Findings contain paths and categories, never
matching source text or secret values. Run --help for the publication workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

MANIFEST = ".public-release-files"
ASSETS = ".public-release-assets.json"
RECEIPT = "PUBLIC_RELEASE_MANIFEST.json"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
FORBIDDEN_PARTS = {
    ".git", ".venv", ".birdnet-venv", ".tools", "node_modules", "data",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist",
    "test-results", "playwright-report", "private", "recordings", "uploads",
}
FORBIDDEN_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".jsonl", ".key", ".pem", ".p12",
    ".mp4", ".mov", ".mkv", ".avi", ".wav", ".flac", ".mp3", ".m4a",
    ".ckpt", ".pt", ".pth", ".onnx", ".safetensors", ".log", ".zip",
    ".tar", ".gz", ".jpg", ".jpeg", ".webp", ".gif", ".exe", ".dll",
}
BINARY_ASSET_PATHS = {
    "frontend/public/icons/falcon-192.png",
    "frontend/public/icons/falcon-512.png",
}
PERSONAL_PATH = re.compile(
    r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]+(?:users[\\/]+[^/\\\s]+|[^/\\\s]+[\\/])"
    r"|/home/(?!user(?:[/\s]|$)|example(?:[/\s]|$))[a-z0-9_.-]+/|/mnt/[a-z]/)"
)
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{25,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "api_secret": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
}
URL = re.compile(r"(?:rtsps?|https?)://[^\s\"'<>`]+", re.IGNORECASE)
IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
COORDINATE = re.compile(
    r"(?i)[\"']?(?:site_lat|site_lon|latitude|longitude)[\"']?\s*[:=]\s*-?\d+\.\d+"
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|api_key|access_token|secret_key|camera_password)[\"']?\s*[:=]\s*"
    r"[\"']([^\"'\r\n]{4,})[\"']"
)
SYNTHETIC_VALUES = {
    "fixture-secret", "fixture-password", "fixture", "password", "secret",
    "p@ss:word", "second-secret", "redacted", "<redacted>", "<password>", "your_password",
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    category: str
    line: int = 0


class ReleaseError(Exception):
    """A safe error message containing no source data or credentials."""


def is_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return "/tests/" in f"/{path}" or name.startswith("test_") or ".test." in name


def is_fixture_host(host: str) -> bool:
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(
        (".test", ".invalid", ".example")
    )


def forbidden_path(path: str) -> bool:
    relative = PurePosixPath(path)
    parts = tuple(part.lower() for part in relative.parts)
    if (
        not path or relative.is_absolute() or ".." in parts or "\\" in path
        or ":" in path or relative.as_posix() != path
        or any(part in FORBIDDEN_PARTS for part in parts)
    ):
        return True
    name = relative.name.lower()
    if name.startswith(".env") and path != ".env.example":
        return True
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    if parts[0] == "models" and path != "models/README.md":
        return True
    if parts[0] == "docs" and (
        "validation" in name or "benchmark" in name or "environment-audit" in name
        or name.endswith(".json")
    ):
        return True
    return False


def scan_content(path: str, data: bytes) -> list[Finding]:
    """Conservative heuristic check; manual review is still required before publishing."""
    if len(data) > MAX_SOURCE_BYTES:
        return [Finding(path, "oversized_source")]
    if path in BINARY_ASSET_PATHS:
        return []  # Exact content hashes are checked separately, never arbitrary PNGs.
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Finding(path, "unapproved_binary")]
    if "\x00" in content:
        return [Finding(path, "unapproved_binary")]
    results: set[Finding] = set()
    fixture = is_test(path)
    for number, line in enumerate(content.splitlines(), 1):
        if PERSONAL_PATH.search(line):
            results.add(Finding(path, "personal_absolute_path", number))
        for category, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                results.add(Finding(path, category, number))
        if COORDINATE.search(line) and not fixture:
            results.add(Finding(path, "precise_location_assignment", number))
        for match in SENSITIVE_ASSIGNMENT.finditer(line):
            value = match.group(1)
            if value.lower() not in SYNTHETIC_VALUES:
                results.add(Finding(path, "literal_credential_assignment", number))
        for match in URL.finditer(line):
            try:
                parsed = urlsplit(match.group(0))
                host = parsed.hostname or ""
                if parsed.username and not (fixture and is_fixture_host(host)):
                    results.add(Finding(path, "url_userinfo", number))
            except ValueError:
                results.add(Finding(path, "malformed_url", number))
        # Lockfiles contain four-component package versions; only inspect URL hosts there.
        candidates = [
            m.group(0) for m in IP.finditer(line)
            if not re.match(r"/\d{1,2}\b", line[m.end():])
        ]
        if path.endswith(".lock"):
            candidates = []
            for match in URL.finditer(line):
                try:
                    candidates.append(urlsplit(match.group(0)).hostname or "")
                except ValueError:
                    pass  # The URL check above already emitted a safe finding.
        for candidate in candidates:
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if (
                address.version == 4
                and any(address in ipaddress.ip_network(net) for net in (
                    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
                ))
            ):
                results.add(Finding(path, "private_network_address", number))
    return sorted(results)


def read_regular(root: Path, path: str) -> bytes:
    """Reject symlinks in every path component, even if they resolve inside the tree."""
    target = root
    for part in PurePosixPath(path).parts:
        target = target / part
        if target.is_symlink():
            raise ReleaseError(f"Symlink is not permitted: {path}")
    if not target.is_file():
        raise ReleaseError(f"Required release file is missing: {path}")
    if target.stat().st_size > MAX_SOURCE_BYTES:
        raise ReleaseError(f"Release file exceeds the size limit: {path}")
    return target.read_bytes()


def release_files(root: Path) -> list[str]:
    try:
        text = read_regular(root, MANIFEST).decode("utf-8")
    except UnicodeDecodeError:
        raise ReleaseError("The release allowlist must be UTF-8 text") from None
    paths = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    if len(paths) != len(set(paths)):
        raise ReleaseError("Duplicate paths in the release allowlist")
    for path in paths:
        if forbidden_path(path):
            raise ReleaseError(f"Forbidden path in the release allowlist: {path}")
    if MANIFEST not in paths or ASSETS not in paths:
        raise ReleaseError("The release allowlist and reviewed asset hashes must include themselves")
    return sorted(paths)


def inspect_release(root: Path) -> tuple[dict[str, bytes], list[Finding]]:
    payloads = {path: read_regular(root, path) for path in release_files(root)}
    findings = [finding for path, data in payloads.items() for finding in scan_content(path, data)]
    try:
        assets = json.loads(payloads[ASSETS])
        if not isinstance(assets, dict) or set(assets) != BINARY_ASSET_PATHS:
            raise ValueError
        for path, expected_hash in assets.items():
            if path not in payloads or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
                raise ValueError
            data = payloads[path]
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(data).hexdigest() != expected_hash:
                findings.append(Finding(path, "unreviewed_binary_asset"))
    except (TypeError, ValueError):
        raise ReleaseError("Reviewed asset hash manifest is invalid") from None
    return payloads, sorted(set(findings))


def export_release(root: Path, destination: Path) -> dict[str, object]:
    destination = destination.absolute()
    # An export is a separate checkout: never write inside the source or a symlinked parent.
    if destination == root or root in destination.parents:
        raise ReleaseError("Choose an export directory outside the working repository")
    if destination.exists() or destination.is_symlink():
        raise ReleaseError("The export destination already exists; choose a new directory")
    if not destination.parent.is_dir() or destination.parent.resolve() != destination.parent:
        raise ReleaseError("The export parent must exist and must not be a symlink")
    payloads, findings = inspect_release(root)
    if findings:
        print_findings(findings)
        raise ReleaseError("Release scan failed; no export was created")
    receipt = {
        "format": 1,
        "files": {path: hashlib.sha256(data).hexdigest() for path, data in payloads.items()},
    }
    destination.mkdir(mode=0o700)
    for path, data in payloads.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if (root / path).stat().st_mode & 0o111 else 0o644)
    (destination / RECEIPT).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return {"exported_files": len(payloads), "history_copied": False, "scan": "passed"}


def inspect_public_base(root: Path, base: str, payloads: dict[str, bytes]) -> list[Finding]:
    """Permit one already-public README/license root commit, never development ancestry."""
    findings: list[Finding] = []
    if not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", base):
        raise ReleaseError("The public base must be a complete Git commit hash")
    base = base.lower()

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)

    try:
        head = git("rev-parse", "HEAD").decode().strip()
        parents = git("rev-list", "--parents", "-n", "1", "HEAD").decode().split()
        ancestors = git("rev-list", "--parents", "-n", "1", base).decode().split()
        all_commits = set(git("rev-list", "--all", "--reflog").decode().split())
        if parents != [head, base] or ancestors != [base] or all_commits != {base, head}:
            return [Finding(".git", "unexpected_public_base_history")]
        tree = git("ls-tree", "-r", "-z", base).decode().strip("\0").split("\0")
        paths: set[str] = set()
        for row in tree:
            metadata, path = row.split("\t", 1)
            mode, kind, oid = metadata.split()
            paths.add(path)
            if path not in {"README.md", "LICENSE"} or kind != "blob" or mode not in {"100644", "100755"}:
                findings.append(Finding(".git", "unexpected_public_base_files"))
                continue
            size = int(git("cat-file", "-s", oid))
            if size > MAX_SOURCE_BYTES:
                findings.append(Finding(f"public-base/{path}", "oversized_source"))
                continue
            data = git("cat-file", "blob", oid)
            findings.extend(scan_content(f"public-base/{path}", data))
            if path == "LICENSE" and payloads.get("LICENSE") != data:
                findings.append(Finding("LICENSE", "public_base_license_changed"))
        if paths != {"README.md", "LICENSE"}:
            findings.append(Finding(".git", "unexpected_public_base_files"))
    except (subprocess.SubprocessError, ValueError, UnicodeDecodeError):
        findings.append(Finding(".git", "unreadable_public_base"))
    return findings


def verify_release(
    root: Path, allow_git: bool = False, public_base_commit: str | None = None
) -> dict[str, object]:
    """Verify the complete export, including absence of unlisted files before first commit."""
    allow_git = allow_git or public_base_commit is not None
    payloads, findings = inspect_release(root)
    expected = set(payloads) | {RECEIPT}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if allow_git and (relative == ".git" or relative.startswith(".git/")):
            continue
        if path.is_symlink():
            findings.append(Finding(relative, "symlink"))
        elif path.is_file() and relative not in expected:
            findings.append(Finding(relative, "unlisted_export_file"))
    try:
        receipt = json.loads(read_regular(root, RECEIPT))
        current = {path: hashlib.sha256(data).hexdigest() for path, data in payloads.items()}
        if receipt != {"format": 1, "files": current}:
            findings.append(Finding(RECEIPT, "export_content_changed"))
    except (ValueError, ReleaseError):
        findings.append(Finding(RECEIPT, "missing_or_invalid_receipt"))
    if allow_git:
        if not (root / ".git").is_dir() or (root / ".git").is_symlink():
            raise ReleaseError("Verification requires a standalone Git repository in the export")
        # Only a deliberate initial commit, or a child of the inspected public root, is permitted.
        count = subprocess.run(
            ["git", "rev-list", "--all", "--count"], cwd=root,
            check=False, capture_output=True, text=True,
        )
        valid_counts = {"2"} if public_base_commit else {"0", "1"}
        if count.returncode or count.stdout.strip() not in valid_counts:
            findings.append(Finding(".git", "unexpected_git_history"))
        else:
            if public_base_commit:
                findings.extend(inspect_public_base(root, public_base_commit, payloads))
            staged = subprocess.run(
                ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True,
            )
            indexed = set(staged.stdout.decode("utf-8").strip("\0").split("\0")) - {""}
            if indexed and indexed != expected:
                findings.append(Finding(".git", "unexpected_git_index"))
            if count.stdout.strip() != "0":
                committed = subprocess.check_output(
                    ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"], cwd=root,
                )
                committed_paths = set(committed.decode("utf-8").strip("\0").split("\0")) - {""}
                if committed_paths != expected:
                    findings.append(Finding(".git", "unexpected_committed_files"))
                dirty = subprocess.run(
                    ["git", "diff", "HEAD", "--exit-code", "--quiet"], cwd=root, check=False,
                    capture_output=True,
                )
                if dirty.returncode:
                    findings.append(Finding(".git", "committed_export_does_not_match"))
    if findings:
        print_findings(sorted(set(findings)))
        raise ReleaseError("Export verification failed")
    result: dict[str, object] = {"verified_files": len(payloads), "scan": "passed"}
    if public_base_commit:
        result["public_base_matches"] = True
        result["preserved_public_commits"] = 1
    return result


def history_findings(root: Path) -> tuple[int, list[Finding]]:
    """Inspect all objects reachable through refs/reflogs, plus unreachable blobs.

    This intentionally reports historical private artifacts even when absent in HEAD.
    It never prints file contents, deletes objects or changes repository history.
    """
    result = subprocess.run(
        ["git", "rev-list", "--objects", "--all", "--reflog"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    objects = {row.split(" ", 1)[0]: row.partition(" ")[2] for row in result.stdout.splitlines()}
    loose = subprocess.run(
        ["git", "fsck", "--full", "--unreachable", "--no-reflogs"],
        cwd=root, capture_output=True, text=True, check=True,
    )
    for row in loose.stdout.splitlines():
        fields = row.split()
        if len(fields) == 3 and fields[:2] == ["unreachable", "blob"]:
            objects.setdefault(fields[2], "<unreachable-blob>")
    findings: set[Finding] = set()
    count = 0
    for oid, path in objects.items():
        kind = subprocess.check_output(["git", "cat-file", "-t", oid], cwd=root, text=True).strip()
        if kind != "blob":
            continue
        count += 1
        path = path or "<historical-blob>"
        if forbidden_path(path):
            findings.add(Finding(path, "private_artifact_in_history"))
        size = int(subprocess.check_output(["git", "cat-file", "-s", oid], cwd=root, text=True))
        if size > MAX_SOURCE_BYTES:
            findings.add(Finding(path, "large_blob_in_history"))
            continue
        content = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=root)
        findings.update(scan_content(path, content))
    return count, sorted(findings)


def print_findings(findings: Iterable[Finding]) -> None:
    print(json.dumps([asdict(finding) for finding in findings], indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "history", "export", "verify"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path, help="New sibling directory for export")
    history = parser.add_mutually_exclusive_group()
    history.add_argument("--allow-initial-git", action="store_true", help="Verify a new zero/one-commit Git repository")
    history.add_argument("--public-base-commit", help="Verify one release commit after an inspected public README/license root commit")
    args = parser.parse_args()
    if (args.allow_initial_git or args.public_base_commit) and args.command != "verify":
        parser.error("Git history options are supported only by verify")
    root = args.root.resolve()
    try:
        if args.command == "history":
            count, findings = history_findings(root)
            print(json.dumps({"historical_blobs_checked": count, "findings": [asdict(f) for f in findings]}, indent=2))
            return 1 if findings else 0
        if args.command == "export":
            if args.destination is None:
                parser.error("export requires --destination")
            result = export_release(root, args.destination)
        elif args.command == "verify":
            result = verify_release(root, args.allow_initial_git, args.public_base_commit)
        else:
            payloads, findings = inspect_release(root)
            print_findings(findings)
            result = {"checked_files": len(payloads), "scan": "failed" if findings else "passed"}
            print(json.dumps(result))
            return 1 if findings else 0
        print(json.dumps(result))
        return 0
    except (ReleaseError, OSError, subprocess.SubprocessError) as exc:
        # OS/tool errors may include local paths or command output; do not echo them.
        message = str(exc) if isinstance(exc, ReleaseError) else "File or Git operation failed"
        print(f"Release blocked: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
