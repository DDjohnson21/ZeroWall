"""
ZeroWall — Feedback Recorder (closed-loop label generation)
===========================================================
Turns the *outcome* of a real defense cycle into supervised training labels for
the Mutation Planner. This is the heart of the "gets smarter under sustained
attack" thesis: the label is not guessed, it is what actually happened when the
candidate's code was launched and attacked.

For each candidate in a cycle we emit one example:
    features  = encode(attack_context)            (what kind of attack)
    transform = candidate.plan.transform_type     (what defense we tried)
    label     = 1.0 if it WORKED else 0.0         (passed tests AND blocked exploit)

"Worked" deliberately requires BOTH functional correctness (verifier_pass) and
security effect (exploit_success_rate < 0.5). A candidate that fails tests, or
that never actually blocked the exploit, is a negative example — so the planner
learns to prefer transforms that are both safe and effective for that attack.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.models import DefenseCycle, CandidateResult
from core.training.features import normalize_payload_type, normalize_endpoint

logger = logging.getLogger(__name__)

DEFAULT_FEEDBACK_PATH = (
    Path(__file__).parent.parent.parent / "training_data" / "feedback.jsonl"
)

# A candidate "blocks" the exploit below this success rate (mirrors defense_loop).
EXPLOIT_BLOCK_THRESHOLD = 0.5


def _candidate_effective(c: CandidateResult) -> float:
    """1.0 only if the candidate both passed tests AND was actually attacked
    and blocked the exploit. Unverified/untested candidates are negatives."""
    blocked = (c.exploit_attempts > 0) and (
        c.exploit_success_rate < EXPLOIT_BLOCK_THRESHOLD
    )
    return 1.0 if (c.verifier_pass and blocked) else 0.0


def cycle_to_examples(cycle: DefenseCycle) -> List[Dict[str, Any]]:
    """Convert one completed defense cycle into labeled training examples."""
    payload_type = normalize_payload_type(cycle.attack_payload.get("payload_type"))
    endpoint = normalize_endpoint(cycle.attack_payload.get("endpoint"))

    examples: List[Dict[str, Any]] = []
    for c in cycle.candidates:
        if c.candidate_id == "baseline":
            continue
        examples.append(
            {
                "cycle_id": cycle.cycle_id,
                "timestamp": time.time(),
                "payload_type": payload_type,
                "endpoint": endpoint,
                "transform": c.plan.transform_type.value,
                "verifier_pass": bool(c.verifier_pass),
                "exploit_success_rate": float(c.exploit_success_rate),
                "exploit_attempts": int(c.exploit_attempts),
                "label": _candidate_effective(c),
            }
        )
    return examples


class FeedbackRecorder:
    """Appends cycle outcomes to a JSONL feedback log (the training corpus)."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_FEEDBACK_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_cycle(self, cycle: DefenseCycle) -> int:
        """Record all examples from a cycle. Returns number of examples written."""
        examples = cycle_to_examples(cycle)
        if not examples:
            return 0
        with open(self.path, "a") as f:
            for ex in examples:
                f.write(json.dumps(ex) + "\n")
        logger.info(
            f"[FeedbackRecorder] wrote {len(examples)} examples -> {self.path.name}"
        )
        return len(examples)

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path) as f:
            return sum(1 for line in f if line.strip())
