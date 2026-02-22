"""
ZeroWall — Risk Agent
======================
Combines verifier + exploit outputs to compute a deployment
confidence score and recommend an action for each candidate.

Scoring formula:
  security_score = 1.0 - exploit_success_rate   (higher = more secure)
  correctness_score = tests_passed / total_tests  (higher = more correct)
  bandit_penalty = bandit_issues * 0.05
  confidence = (security_score * 0.6 + correctness_score * 0.4) - bandit_penalty

Decision thresholds:
  confidence >= 0.85 → deploy
  confidence < 0.85  → reject
  If no candidate qualifies → rollback recommendation
"""

import time
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

from core.models import CandidateResult, CandidateStatus, DefenseCycle
from inference.clients.triton_client import TritonClient

logger = logging.getLogger(__name__)


DEPLOY_THRESHOLD = 0.85
MIN_TESTS_PASS_RATIO = 0.90


@dataclass
class RiskAssessment:
    """Risk assessment result for a defense cycle."""
    winner_id: Optional[str]
    action: str           # deploy | reject | rollback
    winner_confidence: float
    reasoning: str
    ranked_candidates: List[Tuple[str, float]]  # (candidate_id, confidence)


class RiskAgent:
    """
    Scores candidates and recommends the best action.
    Uses Triton risk-scorer model when available.
    """

    def __init__(
        self,
        triton_client: Optional[TritonClient] = None,
        deploy_threshold: float = DEPLOY_THRESHOLD,
    ):
        self.triton_client = triton_client
        self.deploy_threshold = deploy_threshold

    def assess(self, candidates: List[CandidateResult]) -> RiskAssessment:
        """
        Score all candidates and return a risk assessment.
        """
        logger.info(f"[RiskAgent] Assessing {len(candidates)} candidates")
        t_start = time.time()

        scored = []
        for candidate in candidates:
            score = self._score_candidate(candidate)
            candidate.confidence_score = score
            candidate.risk_score = 1.0 - score
            scored.append((candidate.candidate_id, score, candidate))

        # Sort by confidence descending
        scored.sort(key=lambda x: x[1], reverse=True)
        ranked = [(cid, score) for cid, score, _ in scored]

        # Pick winner
        winner_id = None
        action = "reject"
        winner_confidence = 0.0

        for cid, score, candidate in scored:
            if (
                score >= self.deploy_threshold
                and candidate.verifier_pass
                and candidate.exploit_success_rate < 0.5
            ):
                winner_id = cid
                action = "deploy"
                winner_confidence = score
                candidate.status = CandidateStatus.DEPLOYED
                break

        if winner_id is None:
            # Check if original was better (all candidates failed → rollback)
            if all(c.exploit_success_rate >= 0.8 for c in candidates):
                action = "rollback"
                reasoning = (
                    f"All {len(candidates)} candidates remain vulnerable "
                    f"(exploit success rate ≥80%). Recommending rollback to last known safe version."
                )
            else:
                reasoning = (
                    f"No candidate reached confidence threshold of {self.deploy_threshold:.0%}. "
                    f"Best was {ranked[0][0]} at {ranked[0][1]:.1%}. Rejecting all."
                )
        else:
            reasoning = (
                f"Deploying {winner_id} with {winner_confidence:.1%} confidence. "
                f"Exploit success rate: {[c for c in candidates if c.candidate_id == winner_id][0].exploit_success_rate:.0%}, "
                f"Tests: all passing."
            )

        elapsed_ms = (time.time() - t_start) * 1000
        logger.info(
            f"[RiskAgent] Assessment complete in {elapsed_ms:.1f}ms: "
            f"action={action}, winner={winner_id}"
        )

        return RiskAssessment(
            winner_id=winner_id,
            action=action,
            winner_confidence=winner_confidence,
            reasoning=reasoning,
            ranked_candidates=ranked,
        )

    def _score_candidate(self, candidate: CandidateResult) -> float:
        """Compute confidence score for a single candidate."""
        # Security: how often does exploit fail?
        security_score = 1.0 - candidate.exploit_success_rate

        # Correctness: test pass ratio
        total_tests = candidate.tests_passed + candidate.tests_failed + candidate.tests_errors
        if total_tests > 0:
            correctness_score = candidate.tests_passed / total_tests
        else:
            correctness_score = 0.0  # No tests = no confidence

        # Bandit penalty
        bandit_penalty = min(candidate.bandit_issues * 0.05, 0.30)

        # Model confidence bonus from mutation planner
        model_bonus = candidate.plan.model_confidence * 0.05

        # Combined score
        score = (
            security_score * 0.60
            + correctness_score * 0.40
            - bandit_penalty
            + model_bonus
        )
        return max(0.0, min(1.0, score))
