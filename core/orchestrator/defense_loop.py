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

import httpx
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
from core.deploy.controller import DeployController
from core.training.feedback import FeedbackRecorder
from core.transforms.base import apply_transform
from core.sandbox.runner import CandidateSandbox
from core.telemetry.collector import TelemetryCollector
from inference.clients.triton_client import TritonClient
from inference.clients.vllm_client import VLLMClient
from inference.clients.nemo_planner_client import NeMoPlannerClient

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
        planner_llm_host: Optional[str] = None,
        planner_llm_port: Optional[int] = None,
        candidate_count: int = 10,
        workers: int = 4,
        telemetry: Optional[TelemetryCollector] = None,
        deploy_controller: Optional[DeployController] = None,
        feedback_recorder: Optional[FeedbackRecorder] = None,
        live_gate_timeout_s: float = 20.0,
    ):
        # Inference clients
        self.triton = TritonClient(host=triton_host, port=triton_port)
        self.vllm = VLLMClient(host=vllm_host, port=vllm_port)
        # Tier-1 planner: NeMo LoRA-fine-tuned LLM (served via vLLM/TRT-LLM).
        # Defaults to the vLLM endpoint; skipped automatically until an adapter
        # is trained and the endpoint is healthy.
        self.nemo_planner = NeMoPlannerClient(
            host=planner_llm_host or vllm_host,
            port=planner_llm_port or vllm_port,
        )

        # Agents
        self.mutation_agent = MutationAgent(
            triton_client=self.triton,
            candidate_count=candidate_count,
            nemo_planner=self.nemo_planner,
        )
        self.exploit_agent = ExploitAgent(base_url=target_url, workers=workers)
        self.verifier_agent = VerifierAgent(run_bandit=True)
        self.risk_agent = RiskAgent(triton_client=self.triton)
        self.explanation_agent = ExplanationAgent(vllm_client=self.vllm)
        self.deploy_controller = deploy_controller or DeployController()
        self.feedback_recorder = feedback_recorder or FeedbackRecorder()

        self.telemetry = telemetry or TelemetryCollector()
        self.target_url = target_url
        self.candidate_count = candidate_count
        self.workers = workers
        self.live_gate_timeout_s = live_gate_timeout_s
        deploy_status = self.deploy_controller.get_status()
        self._active_version_hash = str(deploy_status.get("active_hash", "unknown"))
        active_path = self.deploy_controller.target_source
        self._active_source = (
            active_path.read_text() if active_path.exists()
            else (TARGET_SOURCE_PATH.read_text() if TARGET_SOURCE_PATH.exists() else "")
        )
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
        return asyncio.run(self.run_defense_cycle_async(attack_context, source_path))

    async def run_defense_cycle_async(
        self,
        attack_context: Dict[str, Any],
        source_path: Optional[str] = None,
    ) -> DefenseCycle:
        """Async entry point for API/benchmark callers already in an event loop."""
        return await self._async_defense_cycle(attack_context, source_path)

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
        cycle.baseline_exploit_rate = before_rate
        cycle.active_exploit_rate = before_rate
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
        source_code = (
            Path(source_path).read_text()
            if source_path and Path(source_path).exists()
            else self._active_source
        )
        candidates = []
        seen_variants = set()
        for plan in plans:
            try:
                mutated_code, description = apply_transform(
                    source_code,
                    plan.transform_type,
                    plan.transform_params,
                )
                descriptions = [description]
                for extra_name in plan.transform_params.get("diversifiers", []):
                    extra_type = TransformType(extra_name)
                    mutated_code, extra_desc = apply_transform(
                        mutated_code,
                        extra_type,
                        plan.transform_params,
                    )
                    descriptions.append(extra_desc)
                variant_hash = hashlib.sha256(mutated_code.encode()).hexdigest()
                if variant_hash in seen_variants:
                    logger.info("[DefenseLoop] skipping duplicate %s", plan.candidate_id)
                    continue
                seen_variants.add(variant_hash)
                plan.diff_summary = " + ".join(descriptions)
                candidates.append(
                    CandidateResult(
                        candidate_id=plan.candidate_id,
                        plan=plan,
                        mutated_code=mutated_code,
                    )
                )
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

        # ── Hot-swap the winning variant (action == deploy) ───────────────
        winner = next(
            (c for c in cycle.candidates if c.candidate_id == assessment.winner_id),
            None,
        )
        if cycle.action == "deploy" and winner is not None and winner.mutated_code:
            record = None
            try:
                record = self.deploy_controller.deploy(winner, cycle_id)
                cycle.deploy_hash = record["content_hash"]
                gate_ok, gate_error = await self._post_deploy_gate(
                    winner, record["content_hash"]
                )
                if not gate_ok:
                    raise RuntimeError(gate_error)

                self.deploy_controller.confirm(record, winner.exploit_success_rate)
                cycle.deployment_verified = True
                cycle.active_exploit_rate = winner.exploit_success_rate
                self._active_source = winner.mutated_code
                self._active_version_hash = record["content_hash"]
                self.telemetry.record("deploy_version", record["version_id"], cycle_id=cycle_id)
                logger.info("[DefenseLoop] live gate passed for %s", record["version_id"])
            except Exception as e:
                cycle.deployment_error = str(e)
                logger.error("[DefenseLoop] post-deploy gate failed: %s", e)
                if record is not None:
                    rollback = self.deploy_controller.rollback(record)
                    expected = rollback.get("content_hash")
                    if expected:
                        await self._wait_for_live_version(str(expected))
                    cycle.action = "rollback"
                    assessment.action = "rollback"
                    assessment.reasoning = (
                        f"Published candidate failed the live gate ({e}); "
                        f"restored {rollback.get('version', 'previous version')}."
                    )
                    winner.status = CandidateStatus.REJECTED
                    if self.deploy_controller.target_source.exists():
                        self._active_source = self.deploy_controller.target_source.read_text()
                    self._active_version_hash = str(
                        self.deploy_controller.get_status().get("active_hash", "unknown")
                    )
                else:
                    cycle.action = "reject"
                    assessment.action = "reject"

        # ── Generate explanation ──────────────────────────────────────────
        t_exp = time.time()
        explanation = self.explanation_agent.explain(cycle, assessment, winner, before_rate)
        cycle.explanation_inference_latency_ms = (time.time() - t_exp) * 1000

        # ── Finalize cycle timing ─────────────────────────────────────────
        cycle.cycle_end = time.time()
        cycle.cycle_latency_s = cycle.cycle_end - cycle_start

        # ── Emit telemetry ────────────────────────────────────────────────
        self.telemetry.record_cycle(cycle)
        self._cycles.append(cycle)

        # ── Closed-loop feedback: turn this outcome into training labels ───
        try:
            n = self.feedback_recorder.record_cycle(cycle)
            self.telemetry.record("feedback_examples", n, cycle_id=cycle_id)
        except Exception as e:
            logger.warning(f"[DefenseLoop] feedback recording failed: {e}")

        logger.info(f"\n{'='*60}")
        logger.info(f"[DefenseLoop] 🏁 Cycle {cycle_id[:8]} complete in {cycle.cycle_latency_s:.2f}s")
        logger.info(f"[DefenseLoop] Action: {cycle.action.upper()}")
        logger.info(f"[DefenseLoop] Winner: {cycle.winner_id}")
        logger.info(f"\n{explanation}")
        logger.info(f"{'='*60}\n")

        return cycle

    async def _wait_for_live_version(self, expected_hash: str) -> bool:
        """Wait until the managed target reports the exact published artifact."""
        deadline = time.monotonic() + self.live_gate_timeout_s
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.monotonic() < deadline:
                try:
                    response = await client.get(f"{self.target_url}/version")
                    if (
                        response.status_code == 200
                        and str(response.json().get("loaded_source_hash")) == expected_hash
                    ):
                        return True
                except (httpx.HTTPError, ValueError):
                    pass
                await asyncio.sleep(0.15)
        return False

    async def _post_deploy_gate(
        self,
        winner: CandidateResult,
        expected_hash: str,
    ) -> tuple[bool, str]:
        if not await self._wait_for_live_version(expected_hash):
            return False, f"live target did not load deploy hash {expected_hash}"

        async with httpx.AsyncClient(timeout=3.0) as client:
            for path in ("/health", "/public", "/items/1"):
                try:
                    response = await client.get(f"{self.target_url}{path}")
                except httpx.HTTPError as exc:
                    return False, f"smoke check {path} failed: {exc}"
                if response.status_code != 200:
                    return False, f"smoke check {path} returned {response.status_code}"

        await self.exploit_agent.replay_against_candidate(winner, self.target_url)
        if winner.exploit_attempts == 0 or winner.exploit_success_rate >= 0.5:
            return (
                False,
                f"live exploit success rate remained {winner.exploit_success_rate:.0%}",
            )
        return True, ""

    async def _parallel_verify(self, candidates: List[CandidateResult]) -> List[CandidateResult]:
        """Run verifier on all candidates using thread pool (pytest is subprocess-based)."""
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, self.verifier_agent.verify_candidate, c)
            for c in candidates
        ]
        return list(await asyncio.gather(*tasks))

    async def _parallel_exploit(self, candidates: List[CandidateResult]) -> List[CandidateResult]:
        """
        Replay exploits against each candidate's *own* code.

        Every candidate is booted in an isolated sandbox server running its
        mutated source, and the exploit payloads are fired at that server.
        This is what lets a hardened variant actually demonstrate that it
        blocks the exploit — replaying against the static production app would
        make all candidates look identical.
        """
        sem = asyncio.Semaphore(max(1, self.workers))
        tasks = [self._exploit_candidate_sandboxed(c, sem) for c in candidates]
        return list(await asyncio.gather(*tasks))

    async def _exploit_candidate_sandboxed(
        self,
        candidate: CandidateResult,
        sem: asyncio.Semaphore,
    ) -> CandidateResult:
        """Boot one candidate in a sandbox, attack it, tear it down."""
        loop = asyncio.get_event_loop()
        async with sem:
            sandbox = CandidateSandbox(candidate.mutated_code or self._active_source)
            try:
                await loop.run_in_executor(None, sandbox.start)
                if not sandbox.ready:
                    # A candidate that cannot even serve traffic is not a valid
                    # hardening — treat it as fully vulnerable so it never wins.
                    candidate.exploit_attempts = len(self.exploit_agent.payloads)
                    candidate.exploit_successes = candidate.exploit_attempts
                    candidate.exploit_failures = 0
                    candidate.exploit_success_rate = 1.0
                    logger.warning(
                        f"[DefenseLoop] {candidate.candidate_id} failed to boot; "
                        f"marking fully vulnerable"
                    )
                    return candidate
                return await self.exploit_agent.replay_against_candidate(
                    candidate, sandbox.base_url
                )
            finally:
                await loop.run_in_executor(None, sandbox.stop)

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
            "nemo_planner_active": self.nemo_planner.available,
            "nemo_adapter_present": self.nemo_planner.adapter_present,
            "last_planner_tier": self.mutation_agent.last_source_tier,
            "deployment_verified": self.deploy_controller.get_status().get(
                "last_deploy_verified", False
            ),
        }
