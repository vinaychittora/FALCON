"""Keep BirdNET checkpoint downloads reusable outside the Python environment."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
package = (
    root / ".birdnet-venv/lib/python3.11/site-packages/birdnet_analyzer/checkpoints"
)
target = root / "models/birdnet/checkpoints"
target.parent.mkdir(parents=True, exist_ok=True)
if not package.is_symlink():
    if package.exists() and not target.exists():
        package.rename(target)
    elif package.exists() and target.exists():
        raise RuntimeError(
            "Two BirdNET caches exist; keep them for manual reconciliation"
        )
    target.mkdir(parents=True, exist_ok=True)
    package.symlink_to(target, target_is_directory=True)
