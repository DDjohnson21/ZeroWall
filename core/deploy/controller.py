"""
ZeroWall deployment controller.

Writes immutable version artifacts, atomically switches the managed active source,
and keeps enough transaction metadata to perform an immediate verified rollback.
"""

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core.models import CandidateResult

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DEFAULT_DEPLOY_DIR = BASE_DIR / "artifacts" / "deploy"
ORIGINAL_PATH = BASE_DIR / "apps" / "target-fastapi" / "main.py"


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class DeployController:
    """Manage the versioned source slot consumed by the live target runner."""

    def __init__(
        self,
        target_source_path: Optional[Path] = None,
        deploy_dir: Optional[Path] = None,
        original_path: Path = ORIGINAL_PATH,
    ):
        self.deploy_dir = Path(
            deploy_dir or os.environ.get("ZEROWALL_DEPLOY_DIR") or DEFAULT_DEPLOY_DIR
        )
        self.active_path = Path(
            target_source_path or (self.deploy_dir / "active" / "main.py")
        )
        self.target_source = self.active_path
        self.versions_dir = self.deploy_dir / "versions"
        self.manifest_path = self.deploy_dir / "manifest.json"
        self.active_pointer = self.deploy_dir / "active.txt"
        self.original_path = Path(original_path)

        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.active_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.active_path.exists() and self.original_path.exists():
            _atomic_write(self.active_path, self.original_path.read_bytes())

        self._manifest = self._load_manifest()
        if not self.manifest_path.exists():
            self._save_manifest()

    def _initial_manifest(self) -> Dict[str, Any]:
        active_hash = (
            _hash_bytes(self.active_path.read_bytes())
            if self.active_path.exists()
            else "missing"
        )
        return {
            "active_hash": active_hash,
            "active_version_id": "original",
            "previous_hash": None,
            "previous_version_id": None,
            "history": [],
        }

    def deploy(self, candidate: CandidateResult, cycle_id: str) -> Dict[str, Any]:
        """Atomically publish a candidate and return its rollback transaction."""
        if not candidate.mutated_code:
            raise ValueError("Cannot deploy candidate with no mutated code")

        started = time.time()
        new_content = candidate.mutated_code.encode("utf-8")
        content_hash = _hash_bytes(new_content)
        version_id = f"v-{content_hash}"
        version_path = self.versions_dir / f"{version_id}.py"

        current_content = self.active_path.read_bytes()
        previous_hash = _hash_bytes(current_content)
        previous_version_id = self._manifest.get("active_version_id", "original")
        previous_path = self.versions_dir / f"v-{previous_hash}.py"

        if not previous_path.exists():
            _atomic_write(previous_path, current_content)
        if not version_path.exists():
            _atomic_write(version_path, new_content)

        record = {
            "version_id": version_id,
            "content_hash": content_hash,
            "candidate_id": candidate.candidate_id,
            "transform_type": candidate.plan.transform_type.value,
            "cycle_id": cycle_id,
            "deployed_at": time.time(),
            "deploy_latency_ms": 0.0,
            "tests_passed": candidate.tests_passed,
            "exploit_success_rate": candidate.exploit_success_rate,
            "confidence_score": candidate.confidence_score,
            "previous_hash": previous_hash,
            "previous_version_id": previous_version_id,
            "post_deploy_verified": False,
        }

        _atomic_write(self.active_path, new_content)
        record["deploy_latency_ms"] = (time.time() - started) * 1000

        self._manifest["previous_hash"] = previous_hash
        self._manifest["previous_version_id"] = previous_version_id
        self._manifest["active_hash"] = content_hash
        self._manifest["active_version_id"] = version_id
        self._manifest.setdefault("history", []).append(record)
        self._save_manifest()
        _atomic_write(self.active_pointer, version_id.encode("utf-8"))

        logger.info(
            "[DeployController] published %s in %.1fms; awaiting live gate",
            version_id,
            record["deploy_latency_ms"],
        )
        return record

    def confirm(self, record: Dict[str, Any], live_exploit_rate: float) -> None:
        """Mark a published version as proven live and safe."""
        for item in reversed(self._manifest.get("history", [])):
            if item.get("cycle_id") == record.get("cycle_id"):
                item["post_deploy_verified"] = True
                item["live_exploit_success_rate"] = live_exploit_rate
                item["verified_at"] = time.time()
                break
        self._save_manifest()

    def rollback(self, deployment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Atomically restore the exact version preceding a deployment."""
        previous_hash = (
            deployment.get("previous_hash") if deployment else None
        ) or self._manifest.get("previous_hash")
        previous_version_id = (
            deployment.get("previous_version_id") if deployment else None
        ) or self._manifest.get("previous_version_id")

        if not previous_hash:
            return {"status": "no_previous_version"}

        previous_path = self.versions_dir / f"v-{previous_hash}.py"
        if not previous_path.exists():
            return {
                "status": "rollback_failed",
                "reason": "version_file_missing",
                "path": str(previous_path),
            }

        _atomic_write(self.active_path, previous_path.read_bytes())
        self._manifest["active_hash"] = previous_hash
        self._manifest["active_version_id"] = previous_version_id or f"v-{previous_hash}"
        self._manifest["previous_hash"] = None
        self._manifest["previous_version_id"] = None
        self._manifest.setdefault("history", []).append(
            {
                "event": "rollback",
                "rolled_back_at": time.time(),
                "restored_hash": previous_hash,
                "restored_version_id": self._manifest["active_version_id"],
                "failed_cycle_id": (deployment or {}).get("cycle_id"),
            }
        )
        self._save_manifest()
        _atomic_write(
            self.active_pointer,
            str(self._manifest["active_version_id"]).encode("utf-8"),
        )
        logger.warning(
            "[DeployController] rolled back to %s",
            self._manifest["active_version_id"],
        )
        return {
            "status": "rolled_back",
            "version": self._manifest["active_version_id"],
            "content_hash": previous_hash,
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "active_version_id": self._manifest.get("active_version_id", "unknown"),
            "active_hash": self._manifest.get("active_hash", "unknown"),
            "total_deployments": sum(
                1
                for item in self._manifest.get("history", [])
                if item.get("version_id")
            ),
            "last_deploy_verified": next(
                (
                    item.get("post_deploy_verified", False)
                    for item in reversed(self._manifest.get("history", []))
                    if item.get("version_id")
                ),
                False,
            ),
        }

    def _load_manifest(self) -> Dict[str, Any]:
        if self.manifest_path.exists():
            try:
                data = json.loads(self.manifest_path.read_text())
                if isinstance(data, dict):
                    data.setdefault("history", [])
                    return data
            except (OSError, ValueError):
                logger.warning("[DeployController] ignoring invalid manifest")
        return self._initial_manifest()

    def _save_manifest(self) -> None:
        _atomic_write(
            self.manifest_path,
            json.dumps(self._manifest, indent=2).encode("utf-8"),
        )
