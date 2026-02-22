"""
ZeroWall — Explanation Agent
==============================
Generates a concise, judge-facing summary of the defense cycle result.
Calls Triton explanation model (or vLLM) when available.
Falls back to a template-based explanation.

Outputs a human-readable summary of:
- What changed (transform type + diff)
- Why it was selected (risk score rationale)
- Before vs After exploit results
- Tests preserved
"""

import time
import logging
from typing import Optional, List

from core.models import CandidateResult, DefenseCycle
from core.agents.risk_agent import RiskAssessment
from inference.clients.vllm_client import VLLMClient

logger = logging.getLogger(__name__)


EXPLANATION_PROMPT_TEMPLATE = """
You are a cybersecurity AI assistant summarizing a moving target defense cycle.

Defense Cycle: {cycle_id}
Action taken: {action}
Winner candidate: {winner_id}

Selected candidate details:
- Transform applied: {transform_type}
- Transform description: {transform_desc}
- Tests passed: {tests_passed}/{total_tests}
- Exploit success rate BEFORE: {before_rate:.0%}
- Exploit success rate AFTER: {after_rate:.0%}
- Risk confidence score: {confidence:.1%}

Write a 3-sentence summary for a judge explaining:
1. What code change was made
2. Why this candidate was selected
3. The security improvement achieved

Keep it concise and technical but clear.
"""


class ExplanationAgent:
    """
    Generates human-readable defense cycle summaries.
    Uses vLLM for generation when available, template fallback otherwise.
    """

    def __init__(self, vllm_client: Optional[VLLMClient] = None):
        self.vllm_client = vllm_client

    def explain(
        self,
        cycle: DefenseCycle,
        assessment: RiskAssessment,
        winner: Optional[CandidateResult],
        before_exploit_rate: float = 1.0,
    ) -> str:
        """
        Generate explanation for the defense cycle.

        Args:
            cycle: The completed defense cycle
            assessment: Risk agent assessment
            winner: The winning candidate (or None)
            before_exploit_rate: Exploit success rate on original version

        Returns:
            Human-readable summary string
        """
        t_start = time.time()
        logger.info(f"[ExplanationAgent] Generating explanation for cycle {cycle.cycle_id}")

        if winner is not None and self.vllm_client and self.vllm_client.is_healthy():
            try:
                explanation = self._llm_explain(cycle, assessment, winner, before_exploit_rate)
                latency_ms = (time.time() - t_start) * 1000
                logger.info(f"[ExplanationAgent] LLM explanation in {latency_ms:.1f}ms")
                return explanation
            except Exception as e:
                logger.warning(f"[ExplanationAgent] vLLM unavailable: {e}, using template")

        explanation = self._template_explain(cycle, assessment, winner, before_exploit_rate)
        latency_ms = (time.time() - t_start) * 1000
        logger.info(f"[ExplanationAgent] Template explanation in {latency_ms:.1f}ms")
        return explanation

    def _llm_explain(
        self,
        cycle: DefenseCycle,
        assessment: RiskAssessment,
        winner: CandidateResult,
        before_rate: float,
    ) -> str:
        """Call vLLM to generate explanation."""
        total_tests = winner.tests_passed + winner.tests_failed + winner.tests_errors
        prompt = EXPLANATION_PROMPT_TEMPLATE.format(
            cycle_id=cycle.cycle_id,
            action=assessment.action,
            winner_id=winner.candidate_id,
            transform_type=winner.plan.transform_type.value,
            transform_desc=winner.plan.diff_summary,
            tests_passed=winner.tests_passed,
            total_tests=total_tests,
            before_rate=before_rate,
            after_rate=winner.exploit_success_rate,
            confidence=assessment.winner_confidence,
        )
        return self.vllm_client.complete(prompt, max_tokens=256)

    def _template_explain(
        self,
        cycle: DefenseCycle,
        assessment: RiskAssessment,
        winner: Optional[CandidateResult],
        before_rate: float,
    ) -> str:
        """Template-based fallback explanation."""
        if assessment.action == "rollback":
            return (
                f"⚠️  ZeroWall Cycle {cycle.cycle_id[:8]}: ROLLBACK RECOMMENDED\n"
                f"All {len(cycle.candidates)} mutation candidates remained vulnerable. "
                f"Rolling back to last known safe version.\n"
                f"Reasoning: {assessment.reasoning}"
            )

        if assessment.action == "reject" or winner is None:
            return (
                f"❌  ZeroWall Cycle {cycle.cycle_id[:8]}: ALL CANDIDATES REJECTED\n"
                f"No candidate achieved sufficient confidence ({assessment.winner_confidence:.1%} < "
                f"{0.85:.1%} threshold).\n"
                f"Reasoning: {assessment.reasoning}"
            )

        total_tests = winner.tests_passed + winner.tests_failed + winner.tests_errors
        improvement = before_rate - winner.exploit_success_rate
        return (
            f"✅  ZeroWall Cycle {cycle.cycle_id[:8]}: DEPLOYED {winner.candidate_id}\n"
            f"Transform applied: '{winner.plan.transform_type.value}' — {winner.plan.diff_summary}\n"
            f"Security improvement: exploit success rate dropped from "
            f"{before_rate:.0%} → {winner.exploit_success_rate:.0%} "
            f"({improvement:.0%} reduction).\n"
            f"Tests: {winner.tests_passed}/{total_tests} passing. "
            f"Confidence score: {assessment.winner_confidence:.1%}.\n"
            f"Reasoning: {assessment.reasoning}"
        )
