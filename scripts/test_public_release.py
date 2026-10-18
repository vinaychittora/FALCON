"""Publication checks use generated secrets and media; never real user data."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from public_release import (
    ASSETS,
    BINARY_ASSET_PATHS,
    MANIFEST,
    RECEIPT,
    ReleaseError,
    export_release,
    forbidden_path,
    history_findings,
    inspect_release,
    scan_content,
    verify_release,
)


def seed_source(root: Path) -> Path:
    root.mkdir()
    files = {
        "README.md": b"# Example application\n",
        "LICENSE": b"Example public license\n",
        "app.py": b"print('hello')\n",
    }
    # Tiny synthetic payloads test the pinned-byte check, not image rendering.
    assets = {path: b"\x89PNG\r\n\x1a\n" + path.encode() for path in BINARY_ASSET_PATHS}
    files.update(assets)
    files[ASSETS] = json.dumps({p: hashlib.sha256(d).hexdigest() for p, d in assets.items()}).encode()
    files[MANIFEST] = ("\n".join(sorted({*files, MANIFEST})) + "\n").encode()
    for path, data in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def test_export_keeps_only_allowed_sources_and_never_history_or_private_data(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    for path in (".git/config", "data/observations.jsonl", ".env", "unlisted.py", "recording.mp4"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("private fixture")
    destination = tmp_path / "public"
    result = export_release(root, destination)
    assert result["history_copied"] is False
    assert (root / ".env").read_text() == "private fixture"
    assert not (destination / ".git").exists()
    assert not (destination / "data").exists()
    assert not (destination / "unlisted.py").exists()
    assert verify_release(destination)["scan"] == "passed"
    receipt = json.loads((destination / RECEIPT).read_text())
    assert set(receipt["files"]) == set((root / MANIFEST).read_text().splitlines())


@pytest.mark.parametrize("path", [
    "../outside", "/tmp/key", ".git/config", ".env.local", "data/settings.json",
    "backend/app/private/secret.py", "models/model.safetensors", "recordings/test.py",
    "docs/live-validation.md", "docs/result.json", "camera.key", "frame.jpg", "a\\b.py",
])
def test_denylist_cannot_be_overridden_by_allowlist(path: str) -> None:
    assert forbidden_path(path)


def test_export_scans_before_creating_destination_and_redacts_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = seed_source(tmp_path / "working")
    token = "ghp_" + "z" * 30
    (root / "app.py").write_text(f"TOKEN = '{token}'\n")
    destination = tmp_path / "public"
    with pytest.raises(ReleaseError, match="scan failed"):
        export_release(root, destination)
    assert not destination.exists()
    output = capsys.readouterr().out
    assert "github_token" in output
    assert token not in output


def test_export_refuses_existing_destination_and_source_subdirectory(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    with pytest.raises(ReleaseError, match="outside"):
        export_release(root, root / "public")
    with pytest.raises(ReleaseError, match="already exists"):
        export_release(root, tmp_path)


def test_export_rejects_symlinked_file_or_directory(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    outside = tmp_path / "hidden.py"
    outside.write_text("private data")
    (root / "app.py").unlink()
    (root / "app.py").symlink_to(outside)
    with pytest.raises(ReleaseError, match="Symlink"):
        inspect_release(root)
    (root / "app.py").unlink()
    (root / "app.py").write_text("pass")
    (root / "unsafe").symlink_to(tmp_path, target_is_directory=True)
    with (root / MANIFEST).open("a") as stream:
        stream.write("unsafe/hidden.py\n")
    with pytest.raises(ReleaseError, match="Symlink"):
        inspect_release(root)


def test_modified_binary_and_unapproved_binary_fail(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    asset = next(iter(BINARY_ASSET_PATHS))
    (root / asset).write_bytes(b"\x89PNG\r\n\x1a\nprivate photo")
    _, findings = inspect_release(root)
    assert any(f.category == "unreviewed_binary_asset" for f in findings)
    assert scan_content("photo.png", b"\x89PNG\r\n\x1a\n")[0].category == "unapproved_binary"


def test_verify_detects_changed_source_and_extra_private_files(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    destination = tmp_path / "public"
    export_release(root, destination)
    (destination / "app.py").write_text("print('changed')\n")
    with pytest.raises(ReleaseError, match="verification failed"):
        verify_release(destination)
    (destination / "app.py").write_bytes((root / "app.py").read_bytes())
    (destination / "private.txt").write_text("fixture data")
    with pytest.raises(ReleaseError, match="verification failed"):
        verify_release(destination)


def test_credentials_and_locations_are_detected_but_synthetic_tests_are_permitted() -> None:
    camera_url = "rtsp://" + "owner:secret@camera.test/stream1"
    assert any(f.category == "url_userinfo" for f in scan_content("app.py", camera_url.encode()))
    assert not scan_content("backend/tests/test_camera.py", camera_url.encode())
    local_path = "/home/" + "private-person/media/file.mp4"
    assert scan_content("README.md", local_path.encode())[0].category == "personal_absolute_path"
    coord = "latitude=" + "12.12345"
    assert scan_content("settings.py", coord.encode())[0].category == "precise_location_assignment"
    address = "rtsp://" + "192.168." + "9.8/stream1"
    assert scan_content("app.py", address.encode())[0].category == "private_network_address"
    # CUDA's four-component package version is not a camera address.
    assert not scan_content("backend/uv.lock", ('version = "10.' + '3.9.90"\n').encode())


def test_history_scans_deleted_secrets_without_disclosing_them(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (root / "forgotten.txt").write_text("ghp_" + "y" * 30)
    git("add", "forgotten.txt")
    git("commit", "-qm", "Initial fixture")
    (root / "forgotten.txt").unlink()
    git("add", "-u")
    git("commit", "-qm", "Delete fixture")
    count, findings = history_findings(root)
    assert count == 1
    assert any(f.path == "forgotten.txt" and f.category == "github_token" for f in findings)


def test_initial_git_verification_rejects_unexpected_history_and_committed_files(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    destination = tmp_path / "public"
    export_release(root, destination)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=destination, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    assert verify_release(destination, allow_git=True)["scan"] == "passed"
    git("add", "--all")
    git("commit", "-qm", "Initial public fixture")
    assert verify_release(destination, allow_git=True)["scan"] == "passed"
    (destination / "app.py").write_text("changed")
    with pytest.raises(ReleaseError, match="verification failed"):
        verify_release(destination, allow_git=True)
    (destination / "app.py").write_bytes((root / "app.py").read_bytes())
    git("commit", "--allow-empty", "-qm", "Unexpected second commit")
    with pytest.raises(ReleaseError, match="verification failed"):
        verify_release(destination, allow_git=True)


def test_invalid_asset_manifest_fails_safely(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    (root / ASSETS).write_text(json.dumps(sorted(BINARY_ASSET_PATHS)))
    with pytest.raises(ReleaseError, match="asset hash manifest is invalid"):
        inspect_release(root)


def seed_public_base_export(tmp_path: Path, base_variant: str = "clean") -> tuple[Path, str]:
    root = seed_source(tmp_path / "working")
    destination = tmp_path / "public"
    export_release(root, destination)

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=destination, stderr=subprocess.DEVNULL)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    if base_variant == "secret":
        (destination / "README.md").write_text("ghp_" + "z" * 30)
    if base_variant == "different_license":
        (destination / "LICENSE").write_text("A different license\n")
    git("add", "README.md", "LICENSE")
    if base_variant == "extra_file":
        (destination / "private.txt").write_text("private fixture")
        git("add", "private.txt")
    git("commit", "-qm", "Existing public initialization")
    base = git("rev-parse", "HEAD").decode().strip()
    (destination / "README.md").write_bytes((root / "README.md").read_bytes())
    (destination / "LICENSE").write_bytes((root / "LICENSE").read_bytes())
    (destination / "private.txt").unlink(missing_ok=True)
    if base_variant == "extra_ancestor":
        git("commit", "--allow-empty", "-qm", "Unexpected history")
    git("add", "--all")
    git("commit", "-qm", "Inspected public source release")
    return destination, base


def test_verification_preserves_an_existing_public_initialization(tmp_path: Path) -> None:
    destination, base = seed_public_base_export(tmp_path)
    result = verify_release(destination, public_base_commit=base)
    assert result["public_base_matches"] is True
    assert result["preserved_public_commits"] == 1
    with pytest.raises(ReleaseError, match="verification failed"):
        verify_release(destination, allow_git=True)
    with pytest.raises(ReleaseError, match="verification failed"):
        verify_release(destination, public_base_commit="0" * 40)


@pytest.mark.parametrize("variant", ["secret", "different_license", "extra_file", "extra_ancestor"])
def test_public_base_verification_rejects_private_or_unexpected_history(tmp_path: Path, variant: str) -> None:
    destination, base = seed_public_base_export(tmp_path, variant)
    with pytest.raises(ReleaseError, match="verification failed"):
        verify_release(destination, public_base_commit=base)


def test_public_base_requires_full_hash(tmp_path: Path) -> None:
    destination, base = seed_public_base_export(tmp_path)
    with pytest.raises(ReleaseError, match="complete Git commit hash"):
        verify_release(destination, public_base_commit=base[:8])


def test_hash_pinned_hardware_files_and_handbooks_may_be_published(tmp_path: Path) -> None:
    root = seed_source(tmp_path / "working")
    extra = {
        "hardware/FALCON-node-print-pack.zip": b"PK\x03\x04print pack",
        "hardware/renders/exploded.png": b"\x89PNG\r\n\x1a\nrender",
        "hardware/cad/stl/01_shell.stl": b"binary stl header\x00\x01",
        "docs/handbooks/FALCON-User-Handbook.pdf": b"%PDF-1.7 handbook",
    }
    assets = json.loads((root / ASSETS).read_text())
    for path, data in extra.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
        assets[path] = hashlib.sha256(data).hexdigest()
    (root / ASSETS).write_text(json.dumps(assets))
    (root / MANIFEST).write_text("\n".join(sorted({*(root / MANIFEST).read_text().split(), *extra})) + "\n")
    _, findings = inspect_release(root)
    assert findings == []
    (root / "docs/handbooks/FALCON-User-Handbook.pdf").write_bytes(b"%PDF-1.7 changed")
    _, findings = inspect_release(root)
    assert [f.category for f in findings] == ["unreviewed_binary_asset"]
    # A photo renamed to .pdf fails its signature even with a matching hash.
    photo = b"\xff\xd8\xff\xe0 jpeg"
    (root / "docs/handbooks/FALCON-User-Handbook.pdf").write_bytes(photo)
    assets["docs/handbooks/FALCON-User-Handbook.pdf"] = hashlib.sha256(photo).hexdigest()
    (root / ASSETS).write_text(json.dumps(assets))
    _, findings = inspect_release(root)
    assert [f.category for f in findings] == ["unreviewed_binary_asset"]


def test_archives_and_manufacturer_documents_stay_out_elsewhere() -> None:
    assert forbidden_path("backup.zip")
    assert forbidden_path("docs/handbooks/notes.zip") is False
    assert forbidden_path("hardware/manufacturer-references/camera.pdf")
    assert forbidden_path("hardware/PARTS.md") is False
    assert scan_content("hardware/renders/unlisted.png", b"\x89PNG\r\n\x1a\n")[0].category == "unapproved_binary"
