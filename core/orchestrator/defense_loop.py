"""
ZeroWall — Defense Loop Orchestrator
======================================
Coordinates the full multi-agent defense pipeline:

1. Receive attack alert
2. Mutation Agent → generate N candidate plans
3. For each candidate (parallel where safe):
   a. Apply safe transform → mutated code
   b. Verifier Agent → run tests
   c. Exploit Agent → replay attack
4. Risk Agent → score + pick winner
5. Deploy Controller → deploy winner
6. Explanation Agent → generate summary
7. Emit telemetry events

This is the core ZeroWall AI system that runs on DGX Spark.
"""

import asyncio
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.models import (
    CandidateResult,
    CandidateStatus,
    DefenseCycle,
    MutationPlan,
    TransformType,
)
from core.agents.mutation_agent import MutationAgent
from core.agents.exploit_agent import ExploitAgent
from core.agents.verifier_agent import VerifierAgent
from core.agents.risk_agent import RiskAgent, RiskAssessment
from core.agents.explanation_agent import ExplanationAgent
from core.transforms.base import apply_transform
from core.telemetry.collector import TelemetryCollector
from inference.clients.triton_client import TritonClient
from inference.clients.vllm_client import VLLMClient

# Auto-register transforms
import core.transforms.rename_identifiers  # noqa
import core.transforms.reorder_blocks       # noqa
import core.transforms.split_helpers        # noqa
import core.transforms.swap_validators      # noqa
import core.transforms.route_rotation       # noqa

logger = logging.getLogger(__name__)

TARGET_SOURCE_PATH = Path(__file__).parent.parent.parent / "apps" / "target-fastapi" / "main.py"


class DefenseLoop:
    """
    Main ZeroWall defense orchestrator.
    Coordinates all agents and produces a complete defense cycle result.
    """

    def __init__(
        self,
        target_url: str = "http://localhost:8000",
        triton_host: str = "localhost",
        triton_port: int = 8080,
        vllm_host: str = "localhost",
        vllm_port: int = 8088,
        candidate_count: int = 10,
        workers: int = 4,
        telemetry: Optional[TelemetryCollector] = None,
    ):
        # Inference clients
        self.triton = TritonClient(host=triton_host, port=triton_port)
        self.vllm = VLLMClient(host=vllm_host, port=vllm_port)

        # Agents
        self.mutation_agent = MutationAgent(
            triton_client=self.triton,
            candidate_count=candidate_count,
        )
        self.exploit_agent = ExploitAgent(base_url=target_url, workers=workers)
        self.verifier_agent = VerifierAgent(run_bandit=True)
        self.risk_agent = RiskAgent(triton_client=self.triton)
        self.explanation_agent = ExplanationAgent(vllm_client=self.vllm)

        self.telemetry = telemetry or TelemetryCollector()
        self.target_url = target_url
        self.candidate_count = candidate_count
        self._active_version_hash: str = "aabbcc001122"
        self._active_source: str = TARGET_SOURCE_PATH.read_text() if TARGET_SOURCE_PATH.exists() else ""
        self._cycles: List[DefenseCycle] = []

    def run_defense_cycle(
        self,
        attack_context: Dict[str, Any],
        source_path: Optional[str] = None,
    ) -> DefenseCycle:
        """
        Run a complete defense cycle synchronously.

        Args:
            attack_context: Info about the detected attack
            source_path: Override source file path (default: target app main.py)

        Returns:
            Completed DefenseCycle with winner, action, and explanation
        """
        return asyncio.run(self._async_defense_cycle(attack_context, source_path))

    async def _async_defense_cycle(
        self,
        attack_context: Dict[str, Any],
        source_path: Optional[str] = None,
    ) -> DefenseCycle:
        cycle_id = str(uuid.uuid4())
        cycle_start = time.time()
        src_path = source_path or str(TARGET_SOURCE_PATH)

        logger.info(f"\n{'='*60}")
        logger.info(f"[DefenseLoop] 🛡️  Starting defense cycle {cycle_id[:8]}")
        logger.info(f"[DefenseLoop] Attack: {attack_context}")
        logger.info(f"{'='*60}")

        cycle = DefenseCycle(
            cycle_id=cycle_id,
            trigger_timestamp=cycle_start,
            attack_payload=attack_context,
            source_path=src_path,
        )

        # ── Step 1: Measure baseline exploit rate ─────────────────────────
        logger.info(f"[DefenseLoop] Step 1/6: Measuring baseline exploit rate...")
        baseline_candidate = CandidateResult(
            candidate_id="baseline",
            plan=MutationPlan(
                candidate_id="baseline",
                transform_type=TransformType.RENAME_IDENTIFIERS,
                transform_params={},
                source_path=src_path,
            ),
            mutated_code=self._active_source,
        )
        baseline_candidate = await self.exploit_agent.replay_against_candidate(
            baseline_candidate, self.target_url
        )
        before_rate = baseline_candidate.exploit_success_rate
        logger.info(f"[DefenseLoop] Baseline exploit success rate: {before_rate:.0%}")
        self.telemetry.record("baseline_exploit_rate", before_rate, cycle_id=cycle_id)

        # ── Step 2: Generate mutation candidates ──────────────────────────
        t_mutation = time.time()
        logger.info(f"[DefenseLoop] Step 2/6: Generating mutation candidates...")
        plans = self.mutation_agent.generate_candidates(
            source_path=src_path,
            attack_context=attack_context,
            cycle_id=cycle_id,
        )
        mutation_latency_ms = (time.time() - t_mutation) * 1000
        cycle.mutation_inference_latency_ms = mutation_latency_ms
        logger.info(
            f"[DefenseLoop] Generated {len(plans)} candidates "
            f"in {mutation_latency_ms:.0f}ms"
        )
        self.telemetry.record("mutation_count", len(plans), cycle_id=cycle_id)
        self.telemetry.record("mutation_latency_ms", mutation_latency_ms, cycle_id=cycle_id)

        # ── Step 3: Apply transforms + build CandidateResult objects ─────
        logger.info(f"[DefenseLoop] Step 3/6: Applying transforms...")
        source_code = Path(src_path).read_text() if Path(src_path).exists() else self._active_source
        candidates = []
        for plan in plans:
            try:
                mutated_code, description = apply_transform(
                    source_code,
                    plan.transform_type,
                    plan.transform_params,
                )
                plan.diff_summary = description
                candidate = CandidateResult(
                    candidate_id=plan.candidate_id,
                    plan=plan,
                    mutated_code=mutated_code,
                )
                candidates.append(candidate)
            except Exception as e:
                logger.warning(f"[DefenseLoop] Transform failed for {plan.candidate_id}: {e}")

        cycle.candidates = candidates

        # ── Step 4: Verify candidates (parallel) ─────────────────────────
        logger.info(f"[DefenseLoop] Step 4/6: Running verification ({len(candidates)} candidates)...")
        verified = await self._parallel_verify(candidates)
        passing = [c for c in verified if c.verifier_pass]
        logger.info(
            f"[DefenseLoop] Verification: {len(passing)}/{len(verified)} candidates pass tests"
        )
        self.telemetry.record("candidates_passing_tests", len(passing), cycle_id=cycle_id)

        # ── Step 5: Exploit replay on passing candidates ──────────────────
        logger.info(
            f"[DefenseLoop] Step 5/6: Exploit replay on {len(passing)} passing candidates..."
        )
        if passing:
            replayed = await self._parallel_exploit(passing)
            blocked = [c for c in replayed if c.exploit_success_rate < 0.5]
            logger.info(
                f"[DefenseLoop] Exploit results: {len(blocked)}/{len(replayed)} block all exploits"
            )
            self.telemetry.record("candidates_blocking_exploits", len(blocked), cycle_id=cycle_id)

            # Update candidates list with replayed results
            replayed_ids = {c.candidate_id for c in replayed}
            cycle.candidates = replayed + [c for c in verified if c.candidate_id not in replayed_ids]
        else:
            cycle.candidates = verified

        # ── Step 6: Risk assessment ───────────────────────────────────────
        t_risk = time.time()
        logger.info(f"[DefenseLoop] Step 6/6: Risk assessment...")
        assessment = self.risk_agent.assess(cycle.candidates)
        risk_latency_ms = (time.time() - t_risk) * 1000
        cycle.risk_inference_latency_ms = risk_latency_ms

        cycle.winner_id = assessment.winner_id
        cycle.action = assessment.action

        if assessment.winner_id:
            cycle.deploy_hash = hashlib.md5(
                assessment.winner_id.encode()
            ).hexdigest()[:12]

        # ── Generate explanation ──────────────────────────────────────────
        winner = next(
            (c for c in cycle.candidates if c.candidate_id == assessment.winner_id),
            None
        )
        t_exp = time.time()
        explanation = self.explanation_agent.explain(cycle, assessment, winner, before_rate)
        cycle.explanation_inference_latency_ms = (time.time() - t_exp) * 1000

        # ── Finalize cycle timing ─────────────────────────────────────────
        cycle.cycle_end = time.time()
        cycle.cycle_latency_s = cycle.cycle_end - cycle_start

        # ── Emit telemetry ────────────────────────────────────────────────
        self.telemetry.record("cycle_latency_s", cycle.cycle_latency_s, cycle_id=cycle_id)
        self.telemetry.record("cycle_action", cycle.action, cycle_id=cycle_id)
        self.telemetry.record("risk_latency_ms", risk_latency_ms, cycle_id=cycle_id)
        self._cycles.append(cycle)

        logger.info(f"\n{'='*60}")
        logger.info(f"[DefenseLoop] 🏁 Cycle {cycle_id[:8]} complete in {cycle.cycle_latency_s:.2f}s")
        logger.info(f"[DefenseLoop] Action: {cycle.action.upper()}")
        logger.info(f"[DefenseLoop] Winner: {cycle.winner_id}")
        logger.info(f"\n{explanation}")
        logger.info(f"{'='*60}\n")

        return cycle

    async def _parallel_verify(self, candidates: List[CandidateResult]) -> List[CandidateResult]:
        """Run verifier on all candidates using thread pool (pytest is subprocess-based)."""
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, self.verifier_agent.verify_candidate, c)
            for c in candidates
        ]
        return list(await asyncio.gather(*tasks))

    async def _parallel_exploit(self, candidates: List[CandidateResult]) -> List[CandidateResult]:
        """Replay exploits against all passing candidates in parallel."""
        tasks = [
            self.exploit_agent.replay_against_candidate(c, self.target_url)
            for c in candidates
        ]
        return list(await asyncio.gather(*tasks))

    def get_status(self) -> Dict[str, Any]:
        """Return current state for OpenClaw CLI status command."""
        last = self._cycles[-1] if self._cycles else None
        return {
            "active_version_hash": self._active_version_hash,
            "total_cycles": len(self._cycles),
            "last_cycle_id": last.cycle_id if last else None,
            "last_action": last.action if last else None,
            "last_cycle_latency_s": last.cycle_latency_s if last else None,
            "last_winner": last.winner_id if last else None,
            "triton_healthy": self.triton.is_healthy(),
            "vllm_healthy": self.vllm.is_healthy(),
        }
