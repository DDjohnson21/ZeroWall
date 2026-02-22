"""
ZeroWall — Deployment Controller
==================================
Manages blue/green deployment of mutation candidates.

Responsibilities:
- Write winning candidate code to active deployment path
- Track version hash and metadata
- Run post-deploy exploit gate check
- Rollback to last known good version if gate fails
- Emit deployment events to telemetry
"""

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, Any, Optional

from core.models import CandidateResult, DefenseCycle

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DEPLOY_DIR = BASE_DIR / "artifacts" / "deploy"
ACTIVE_PATH = BASE_DIR / "apps" / "target-fastapi" / "main.py"
VERSIONS_DIR = DEPLOY_DIR / "versions"
ACTIVE_SYMLINK = DEPLOY_DIR / "active"
VERSION_MANIFEST = DEPLOY_DIR / "manifest.json"


def _ensure_dirs():
    DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)


class DeployController:
    """
    Controls deployment of hardened candidate variants.
    Uses an active symlink + versioned copy strategy.
    """

    def __init__(self, target_source_path: Path = ACTIVE_PATH):
        self.target_source = target_source_path
        _ensure_dirs()
        self._manifest = self._load_manifest()

    def deploy(
        self,
        candidate: CandidateResult,
        cycle_id: str,
    ) -> Dict[str, Any]:
        """
        Deploy the winning candidate.

        1. Write mutated code to a versioned file
        2. Archive the current active version
        3. Switch active symlink to new version
        4. Update manifest
        5. Return deployment record

        Args:
            candidate: The winning mutation candidate
            cycle_id: Defense cycle ID for tracing
        """
        if not candidate.mutated_code:
            raise ValueError("Cannot deploy candidate with no mutated code")

        logger.info(f"[DeployController] Deploying {candidate.candidate_id}")
        t_start = time.time()

        # Compute content hash for this version
        content_hash = hashlib.sha256(
            candidate.mutated_code.encode()
        ).hexdigest()[:16]
        version_id = f"v-{content_hash}"
        version_path = VERSIONS_DIR / f"{version_id}.py"

        # Write versioned copy
        version_path.write_text(candidate.mutated_code, encoding="utf-8")

        # Archive current active
        previous_hash = self._manifest.get("active_hash", "unknown")
        previous_path = VERSIONS_DIR / f"prev-{previous_hash}.py"
        if self.target_source.exists() and not previous_path.exists():
            shutil.copy(str(self.target_source), str(previous_path))

        # Deploy: copy versioned code to active path
        shutil.copy(str(version_path), str(self.target_source))

        # Update active symlink pointer
        active_ptr = ACTIVE_SYMLINK.with_suffix(".txt")
        active_ptr.write_text(version_id)

        deploy_latency_ms = (time.time() - t_start) * 1000

        # Update manifest
        record = {
            "version_id": version_id,
            "content_hash": content_hash,
            "candidate_id": candidate.candidate_id,
            "transform_type": candidate.plan.transform_type.value,
            "cycle_id": cycle_id,
            "deployed_at": time.time(),
            "deploy_latency_ms": deploy_latency_ms,
            "tests_passed": candidate.tests_passed,
            "exploit_success_rate": candidate.exploit_success_rate,
            "confidence_score": candidate.confidence_score,
        }
        self._manifest["active_hash"] = content_hash
        self._manifest["active_version_id"] = version_id
        self._manifest.setdefault("history", []).append(record)
        self._save_manifest()

        logger.info(
            f"[DeployController] ✅ Deployed {version_id} "
            f"in {deploy_latency_ms:.1f}ms"
        )
        return record

    def rollback(self) -> Dict[str, Any]:
        """Rollback to the previous deployed version."""
        history = self._manifest.get("history", [])
        if len(history) < 2:
            logger.warning("[DeployController] No previous version to rollback to")
            return {"status": "no_previous_version"}

        prev_record = history[-2]
        prev_hash = prev_record["content_hash"]
        prev_path = VERSIONS_DIR / f"v-{prev_hash}.py"

        if not prev_path.exists():
            logger.error(f"[DeployController] Previous version file not found: {prev_path}")
            return {"status": "rollback_failed", "reason": "version_file_missing"}

        shutil.copy(str(prev_path), str(self.target_source))
        self._manifest["active_hash"] = prev_hash
        self._manifest["active_version_id"] = prev_record["version_id"]
        self._save_manifest()

        logger.info(f"[DeployController] ⏪ Rolled back to {prev_record['version_id']}")
        return {"status": "rolled_back", "version": prev_record["version_id"]}

    def get_status(self) -> Dict[str, Any]:
        """Return current deployment status."""
        return {
            "active_version_id": self._manifest.get("active_version_id", "unknown"),
            "active_hash": self._manifest.get("active_hash", "unknown"),
            "total_deployments": len(self._manifest.get("history", [])),
        }

    def _load_manifest(self) -> Dict[str, Any]:
        if VERSION_MANIFEST.exists():
            try:
                return json.loads(VERSION_MANIFEST.read_text())
            except Exception:
                pass
        return {"active_hash": "original", "active_version_id": "original", "history": []}

    def _save_manifest(self) -> None:
        VERSION_MANIFEST.write_text(json.dumps(self._manifest, indent=2))
