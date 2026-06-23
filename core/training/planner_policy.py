"""
ZeroWall — Learned Mutation Planner (host-side inference)
=========================================================
The on-device-trained planner, served WITHOUT a heavy runtime dependency.

Training (see train.py) runs in PyTorch on the DGX Spark GPU and exports the
learned weights to a small `.npz`. This module loads those weights and runs the
forward pass in pure NumPy, so the live defense loop stays lightweight (no torch
on the serving host) — the same "train heavy on GPU, serve light" split the
project uses for Triton/RAPIDS.

This is tier-1 of the Mutation Planner cascade:
    LearnedPlanner (this) -> Triton deterministic -> Python fallback
If no trained weights exist yet (cold start), `available` is False and the
cascade transparently falls through to the next tier.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from core.training.features import TRANSFORMS, encode_context
from core.training.schema import RankedTransformPlan, validate_plan

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path(__file__).parent.parent.parent / "artifacts" / "models" / "planner"
WEIGHTS_FILE = "planner.npz"
META_FILE = "planner_meta.json"


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(x, 0.0)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class LearnedPlanner:
    """Loads GPU-trained weights and ranks transforms for an attack context."""

    def __init__(self, model_dir: Optional[Path] = None):
        self.model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
        self.available = False
        self.meta: Dict[str, Any] = {}
        self._W1 = self._b1 = self._W2 = self._b2 = None
        self._transforms = TRANSFORMS
        self._load()

    def _load(self) -> None:
        weights_path = self.model_dir / WEIGHTS_FILE
        if not weights_path.exists():
            logger.info("[LearnedPlanner] no trained weights at %s (cold start)", weights_path)
            return
        try:
            data = np.load(weights_path, allow_pickle=False)
            self._W1, self._b1 = data["W1"], data["b1"]
            self._W2, self._b2 = data["W2"], data["b2"]
            meta_path = self.model_dir / META_FILE
            if meta_path.exists():
                self.meta = json.loads(meta_path.read_text())
                self._transforms = self.meta.get("transforms", TRANSFORMS)
            self.available = True
            logger.info(
                "[LearnedPlanner] loaded weights (trained_at=%s, examples=%s, backend=%s)",
                self.meta.get("trained_at"), self.meta.get("n_examples"),
                self.meta.get("train_backend"),
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[LearnedPlanner] failed to load weights: %s", e)
            self.available = False

    def _forward(self, x: np.ndarray) -> np.ndarray:
        h = _relu(x @ self._W1 + self._b1)
        return _sigmoid(h @ self._W2 + self._b2)

    def predict(self, attack_context: Dict[str, Any]) -> Optional[RankedTransformPlan]:
        """Return a validated RankedTransformPlan, or None if unavailable."""
        if not self.available:
            return None
        x = np.asarray(encode_context(attack_context), dtype=np.float32)
        scores = self._forward(x)
        entries = [
            {
                "transform": t,
                "confidence": float(scores[i]),
                "rationale": f"learned policy: P(effective | {attack_context.get('payload_type','?')}) = {float(scores[i]):.2f}",
            }
            for i, t in enumerate(self._transforms)
        ]
        try:
            return validate_plan(
                entries,
                source_tier="learned",
                model=f"zerowall-planner-{self.meta.get('version','v1')}",
            )
        except Exception as e:
            logger.warning("[LearnedPlanner] plan validation failed: %s", e)
            return None
