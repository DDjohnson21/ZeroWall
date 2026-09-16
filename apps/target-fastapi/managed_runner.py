"""Run the demo target from ZeroWall's shared, reloadable deployment slot."""

import hashlib
import json
import os
import shutil
from pathlib import Path

import uvicorn


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _enabled(name: str, default: str = "true") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def prepare_active_source() -> tuple[Path, Path]:
    deploy_dir = Path(
        os.environ.get("ZEROWALL_DEPLOY_DIR", str(REPO_ROOT / "artifacts" / "deploy"))
    )
    original = Path(os.environ.get("ZEROWALL_ORIGINAL_SOURCE", str(HERE / "main.py")))
    active = deploy_dir / "active" / "main.py"
    manifest = deploy_dir / "manifest.json"

    active.parent.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "versions").mkdir(parents=True, exist_ok=True)

    if _enabled("ZEROWALL_RESET_ON_START") or not active.exists():
        shutil.copy2(original, active)
        content_hash = hashlib.sha256(active.read_bytes()).hexdigest()[:16]
        initial = {
            "active_hash": content_hash,
            "active_version_id": "original",
            "previous_hash": None,
            "previous_version_id": None,
            "history": [],
        }
        manifest.write_text(json.dumps(initial, indent=2), encoding="utf-8")

    os.environ["ZEROWALL_MANIFEST_PATH"] = str(manifest)
    return active, manifest


def main() -> None:
    active, _ = prepare_active_source()
    uvicorn.run(
        "main:app",
        app_dir=str(active.parent),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
        reload_dirs=[str(active.parent)],
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
