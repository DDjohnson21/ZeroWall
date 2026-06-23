"""
ZeroWall — Mutation Agent
==========================
Generates a set of behavior-preserving code mutation candidates by selecting
transform TYPES (never raw code) via a layered planner cascade:

    1. NeMoPlanner     — the NeMo LoRA-fine-tuned LLM (reads free-form attack
                         context, emits ranked JSON; served via vLLM/TRT-LLM)
    2. LearnedPlanner  — the on-device GPU-trained MLP policy (core/training)
    3. Triton          — the mutation-planner model served on Triton
    4. Deterministic   — a fixed weighted fallback

Whichever tier produces a valid, non-empty `RankedTransformPlan` first wins;
the others are the safety net so a defense cycle ALWAYS completes. The ranked
plan is expanded into N concrete candidates via `weighted_sequence`. All actual
code edits are performed downstream by the deterministic transform engine.
"""

import time
import random
import logging
from typing import List, Dict, Any, Optional

from core.models import MutationPlan, TransformType
from core.training.schema import (
    RankedTransformPlan,
    TransformChoice,
    validate_plan,
    PlannerValidationError,
)
from core.training.planner_policy import LearnedPlanner
from inference.clients.triton_client import TritonClient
from inference.clients.nemo_planner_client import NeMoPlannerClient

logger = logging.getLogger(__name__)


# Transform selection weights — security impact (higher = more likely to block).
TRANSFORM_WEIGHTS = {
    TransformType.SWAP_VALIDATORS: 0.45,      # Highest — directly hardens vuln
    TransformType.RENAME_IDENTIFIERS: 0.20,   # Structural: harder to template exploits
    TransformType.ROUTE_ROTATION: 0.20,       # Structural: breaks hardcoded paths
    TransformType.REORDER_BLOCKS: 0.10,       # Lightweight structural variation
    TransformType.SPLIT_HELPERS: 0.05,        # Lowest structural impact
}


class MutationAgent:
    """Generates behavioral-equivalent code mutation candidates via the cascade."""

    def __init__(
        self,
        triton_client: Optional[TritonClient] = None,
        candidate_count: int = 10,
        min_candidates: int = 8,
        learned_planner: Optional[LearnedPlanner] = None,
        nemo_planner: Optional[NeMoPlannerClient] = None,
    ):
        self.triton_client = triton_client
        self.candidate_count = candidate_count
        self.min_candidates = min_candidates
        # Tier 1: the NeMo LoRA-fine-tuned LLM (only active once an adapter is
        # trained AND its endpoint is up; otherwise the cascade skips it).
        self.nemo_planner = nemo_planner or NeMoPlannerClient()
        # Tier 2: the on-device trained MLP policy (auto-loads weights if present).
        self.learned_planner = learned_planner or LearnedPlanner()
        self.last_source_tier: str = "unknown"

    def generate_candidates(
        self,
        source_path: str,
        attack_context: Dict[str, Any],
        cycle_id: str,
    ) -> List[MutationPlan]:
        """Generate >= min_candidates mutation candidates for the source file."""
        t_start = time.time()
        logger.info(f"[MutationAgent] Generating candidates for cycle {cycle_id}")
        logger.info(f"[MutationAgent] Attack context: {attack_context}")

        plan = self._plan_cascade(attack_context, self.candidate_count)
        self.last_source_tier = plan.source_tier
        logger.info(
            f"[MutationAgent] planner tier={plan.source_tier} model={plan.model} "
            f"top={[c.transform_type.value for c in plan.top(3)]}"
        )

        sequence = plan.weighted_sequence(self.candidate_count)

        candidates: List[MutationPlan] = []
        for i, choice in enumerate(sequence):
            candidate_id = f"candidate-{cycle_id[:8]}-{i:03d}"
            params = self._build_params(choice.transform_type, seed=i)
            candidates.append(
                MutationPlan(
                    candidate_id=candidate_id,
                    transform_type=choice.transform_type,
                    transform_params=params,
                    source_path=source_path,
                    diff_summary=(
                        f"[{plan.source_tier}] apply {choice.transform_type.value} "
                        f"(seed={i}, conf={choice.confidence:.2f})"
                    ),
                    model_confidence=choice.confidence,
                )
            )

        latency_ms = (time.time() - t_start) * 1000
        logger.info(
            f"[MutationAgent] Generated {len(candidates)} candidates "
            f"in {latency_ms:.1f}ms (tier={plan.source_tier})"
        )
        return candidates

    # ── Planner cascade ──────────────────────────────────────────────────────
    def _plan_cascade(
        self, attack_context: Dict[str, Any], count: int
    ) -> RankedTransformPlan:
        # Tier 1 — NeMo LoRA-fine-tuned LLM (reads free-form context, ranks JSON)
        if self.nemo_planner and self.nemo_planner.available:
            try:
                p = self.nemo_planner.predict(attack_context)
                if p and not p.is_empty:
                    return p
            except Exception as e:
                logger.warning(f"[MutationAgent] NeMo planner failed: {e}")

        # Tier 2 — learned policy (GPU-trained MLP, served from numpy weights)
        if self.learned_planner and self.learned_planner.available:
            try:
                p = self.learned_planner.predict(attack_context)
                if p and not p.is_empty:
                    return p
            except Exception as e:
                logger.warning(f"[MutationAgent] learned planner failed: {e}")

        # Tier 3 — Triton-served mutation-planner model
        if self.triton_client and self.triton_client.is_healthy():
            try:
                p = self._triton_plan(attack_context, count)
                if p and not p.is_empty:
                    return p
            except Exception as e:
                logger.warning(f"[MutationAgent] Triton unavailable: {e}, using fallback")

        # Tier 4 — deterministic fallback (always succeeds)
        return self._deterministic_plan(attack_context)

    def _triton_plan(
        self, attack_context: Dict[str, Any], count: int
    ) -> RankedTransformPlan:
        t_start = time.time()
        response = self.triton_client.infer(
            model_name="mutation-planner",
            inputs={
                "payload_type": str(attack_context.get("payload_type", "unknown")),
                "endpoint": str(attack_context.get("endpoint", "unknown")),
                "count": count,
            },
        )
        logger.info(
            f"[MutationAgent] Triton inference latency: "
            f"{(time.time() - t_start) * 1000:.1f}ms"
        )
        scores = response.get("transform_scores", {})
        if not scores:
            return self._deterministic_plan(attack_context)
        entries = [
            {"transform": t, "confidence": float(c), "rationale": "triton mutation-planner"}
            for t, c in scores.items()
        ]
        return validate_plan(
            entries, source_tier="triton", model=response.get("model", "mutation-planner")
        )

    def _deterministic_plan(self, attack_context: Dict[str, Any]) -> RankedTransformPlan:
        """Fixed weighted plan, jittered deterministically by attack context."""
        attack_hash = hash(str(attack_context)) % 10000
        rng = random.Random(attack_hash)
        choices = [
            TransformChoice(
                transform_type=t,
                confidence=min(1.0, max(0.0, w + rng.uniform(-0.03, 0.03))),
                rationale="deterministic weighted fallback",
            )
            for t, w in TRANSFORM_WEIGHTS.items()
        ]
        return RankedTransformPlan(
            choices=choices, source_tier="deterministic", model="weighted-fallback-v1"
        )

    def _build_params(self, transform_type: TransformType, seed: int) -> Dict[str, Any]:
        base: Dict[str, Any] = {"seed": seed}
        if transform_type == TransformType.SWAP_VALIDATORS:
            strategies = ["allowlist", "strict_type", "regex_guard"]
            base["strategy"] = strategies[seed % len(strategies)]
        return base
