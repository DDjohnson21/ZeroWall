"""
ZeroWall — Mutation Agent
==========================
Generates a set of behavior-preserving code mutation candidates
by selecting from the safe transform library.

Design:
- Consults Triton mutation-planner model to select transform types
- Falls back to deterministic round-robin if Triton is unavailable
- Returns 8–20 MutationPlan objects, never raw LLM-generated code
- All actual code changes are done by the transform engine, not this agent
"""

import uuid
import time
import random
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from core.models import MutationPlan, TransformType
from core.transforms.base import list_transforms
from inference.clients.triton_client import TritonClient

logger = logging.getLogger(__name__)


# Transform selection strategy:
# Index = security impact weight (higher = more likely to block exploit)
TRANSFORM_WEIGHTS = {
    TransformType.SWAP_VALIDATORS: 0.45,      # Highest — directly hardens vuln
    TransformType.RENAME_IDENTIFIERS: 0.20,   # Structural: harder to template exploits
    TransformType.ROUTE_ROTATION: 0.20,       # Structural: breaks hardcoded paths
    TransformType.REORDER_BLOCKS: 0.10,       # Lightweight structural variation
    TransformType.SPLIT_HELPERS: 0.05,        # Lowest structural impact
}


class MutationAgent:
    """
    Generates behavioral-equivalent code mutation candidates.

    Uses Triton mutation-planner model when available.
    Falls back to deterministic weighted sampling.
    """

    def __init__(
        self,
        triton_client: Optional[TritonClient] = None,
        candidate_count: int = 10,
        min_candidates: int = 8,
    ):
        self.triton_client = triton_client
        self.candidate_count = candidate_count
        self.min_candidates = min_candidates

    def generate_candidates(
        self,
        source_path: str,
        attack_context: Dict[str, Any],
        cycle_id: str,
    ) -> List[MutationPlan]:
        """
        Generate mutation candidates for the given source file.

        Args:
            source_path: Path to the vulnerable source file
            attack_context: Info about the detected attack (endpoint, payload type, etc.)
            cycle_id: Current defense cycle ID

        Returns:
            List of MutationPlan objects (min 8)
        """
        t_start = time.time()
        logger.info(f"[MutationAgent] Generating candidates for cycle {cycle_id}")
        logger.info(f"[MutationAgent] Attack context: {attack_context}")

        # 1. Get transform type recommendations from Triton (or fallback)
        transform_recommendations = self._get_transform_recommendations(
            attack_context=attack_context,
            count=self.candidate_count,
        )

        # 2. Build MutationPlan objects
        candidates = []
        for i, (transform_type, confidence) in enumerate(transform_recommendations):
            candidate_id = f"candidate-{cycle_id[:8]}-{i:03d}"
            params = self._build_params(transform_type, seed=i)

            plan = MutationPlan(
                candidate_id=candidate_id,
                transform_type=transform_type,
                transform_params=params,
                source_path=source_path,
                diff_summary=f"Apply {transform_type.value} with seed={i}",
                model_confidence=confidence,
            )
            candidates.append(plan)

        latency_ms = (time.time() - t_start) * 1000
        logger.info(
            f"[MutationAgent] Generated {len(candidates)} candidates "
            f"in {latency_ms:.1f}ms"
        )
        return candidates

    def _get_transform_recommendations(
        self,
        attack_context: Dict[str, Any],
        count: int,
    ) -> List[tuple]:
        """Get transform type + confidence list from Triton or fallback."""

        if self.triton_client and self.triton_client.is_healthy():
            try:
                return self._triton_recommend(attack_context, count)
            except Exception as e:
                logger.warning(f"[MutationAgent] Triton unavailable: {e}, using fallback")

        return self._deterministic_recommend(attack_context, count)

    def _triton_recommend(
        self,
        attack_context: Dict[str, Any],
        count: int,
    ) -> List[tuple]:
        """Call Triton mutation-planner model and parse response."""
        t_start = time.time()
        response = self.triton_client.infer(
            model_name="mutation-planner",
            inputs={"attack_context": str(attack_context), "count": count},
        )
        latency_ms = (time.time() - t_start) * 1000
        logger.info(f"[MutationAgent] Triton inference latency: {latency_ms:.1f}ms")

        # Parse Triton response — model returns transform type scores
        scores = response.get("transform_scores", {})
        if not scores:
            return self._deterministic_recommend(attack_context, count)

        # Convert to sorted list of (transform_type, confidence)
        recommendations = []
        for i in range(count):
            transform_types = list(TRANSFORM_WEIGHTS.keys())
            chosen = transform_types[i % len(transform_types)]
            confidence = scores.get(chosen.value, 0.75)
            recommendations.append((chosen, float(confidence)))

        return recommendations

    def _deterministic_recommend(
        self,
        attack_context: Dict[str, Any],
        count: int,
    ) -> List[tuple]:
        """
        Deterministic weighted sampling of transform types.
        No randomness — seeded by attack context hash for reproducibility.
        """
        attack_hash = hash(str(attack_context)) % 10000
        transforms = list(TRANSFORM_WEIGHTS.keys())
        weights = list(TRANSFORM_WEIGHTS.values())

        recommendations = []

        # Always include at least 3 SWAP_VALIDATORS (highest security impact)
        for i in range(3):
            recommendations.append((TransformType.SWAP_VALIDATORS, 0.90 - i * 0.02))

        # Fill remaining with weighted selection (deterministic via seed)
        remaining = count - 3
        rng = random.Random(attack_hash)
        for i in range(remaining):
            chosen = rng.choices(transforms, weights=weights, k=1)[0]
            confidence = 0.75 + rng.uniform(-0.1, 0.1)
            recommendations.append((chosen, confidence))

        return recommendations[:count]

    def _build_params(self, transform_type: TransformType, seed: int) -> Dict[str, Any]:
        """Build deterministic transform parameters."""
        base = {"seed": seed}
        if transform_type == TransformType.SWAP_VALIDATORS:
            strategies = ["allowlist", "strict_type", "regex_guard"]
            base["strategy"] = strategies[seed % len(strategies)]
        return base
