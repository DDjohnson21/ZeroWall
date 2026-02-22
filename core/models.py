"""
ZeroWall — Shared Models and Configuration
==========================================
Dataclasses shared across all agents and orchestrator components.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import time


class TransformType(str, Enum):
    RENAME_IDENTIFIERS = "rename_identifiers"
    REORDER_BLOCKS = "reorder_blocks"
    SPLIT_HELPERS = "split_helpers"
    SWAP_VALIDATORS = "swap_validators"
    ROUTE_ROTATION = "route_rotation"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    TESTS_PASS = "tests_pass"
    TESTS_FAIL = "tests_fail"
    EXPLOIT_BLOCKED = "exploit_blocked"
    EXPLOIT_VULNERABLE = "exploit_vulnerable"
    DEPLOYED = "deployed"
    REJECTED = "rejected"


@dataclass
class MutationPlan:
    """A plan produced by the Mutation Agent for one code variant."""
    candidate_id: str
    transform_type: TransformType
    transform_params: Dict[str, Any]
    source_path: str
    diff_summary: str = ""
    model_confidence: float = 0.0


@dataclass
class CandidateResult:
    """Full evaluation result for one mutation candidate."""
    candidate_id: str
    plan: MutationPlan
    mutated_code: Optional[str] = None
    status: CandidateStatus = CandidateStatus.PENDING

    # Verifier results
    tests_passed: int = 0
    tests_failed: int = 0
    tests_errors: int = 0
    verifier_pass: bool = False
    bandit_issues: int = 0

    # Exploit results
    exploit_attempts: int = 0
    exploit_successes: int = 0
    exploit_failures: int = 0
    exploit_success_rate: float = 0.0
    exploit_latency_ms: float = 0.0

    # Risk scoring
    risk_score: float = 0.0          # 0=safe, 1=dangerous
    confidence_score: float = 0.0    # 0=low, 1=high confidence to deploy

    # Timing
    eval_start_time: float = field(default_factory=time.time)
    eval_end_time: float = 0.0
    eval_latency_s: float = 0.0


@dataclass
class DefenseCycle:
    """Container for a complete ZeroWall defense cycle."""
    cycle_id: str
    trigger_timestamp: float
    attack_payload: Dict[str, Any]
    source_path: str

    # Produced during the cycle
    candidates: List[CandidateResult] = field(default_factory=list)
    winner_id: Optional[str] = None
    deploy_hash: Optional[str] = None
    action: str = "pending"   # deploy | reject | rollback

    # Timing
    cycle_start: float = field(default_factory=time.time)
    cycle_end: float = 0.0
    cycle_latency_s: float = 0.0

    # Inference telemetry
    mutation_inference_latency_ms: float = 0.0
    risk_inference_latency_ms: float = 0.0
    explanation_inference_latency_ms: float = 0.0


@dataclass
class ExploitPayload:
    """Represents a known attack payload for replay testing."""
    payload_id: str
    name: str
    target_endpoint: str
    method: str               # GET | POST
    params: Dict[str, str] = field(default_factory=dict)
    body: Dict[str, Any] = field(default_factory=dict)
    expected_vuln_indicator: str = ""    # string to look for in response = vuln confirmed
    description: str = ""
