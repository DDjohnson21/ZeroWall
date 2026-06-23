"""
ZeroWall — Self-Play Data Generation
====================================
Drives the defense loop against a rotating set of attacks to generate real,
labeled training data for the Mutation Planner. Each cycle launches every
candidate, attacks it, and records whether the transform actually worked — so
the corpus is grounded in observed outcomes, not synthetic guesses.

This is the "gets smarter under sustained attack" engine: run it, then train.

Usage:
    python -m core.training.selfplay --rounds 4
"""

from __future__ import annotations

import argparse
import logging

from core.orchestrator.defense_loop import DefenseLoop
from core.training.feedback import FeedbackRecorder

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("zerowall.selfplay")

# The attack distribution we train against — one per vulnerable endpoint class.
ATTACK_SCENARIOS = [
    {"endpoint": "/data", "payload_type": "path-traversal", "source_ip": "10.0.0.5"},
    {"endpoint": "/run", "payload_type": "command-injection", "source_ip": "10.0.0.6"},
    {"endpoint": "/search", "payload_type": "sql-injection", "source_ip": "10.0.0.7"},
]


def run_selfplay(rounds: int = 4, candidate_count: int = 8) -> int:
    rec = FeedbackRecorder()
    before = rec.count()
    loop = DefenseLoop(candidate_count=candidate_count)

    total = 0
    for r in range(rounds):
        for scenario in ATTACK_SCENARIOS:
            cycle = loop.run_defense_cycle(dict(scenario))
            n_blocked = sum(
                1 for c in cycle.candidates
                if c.verifier_pass and c.exploit_attempts > 0 and c.exploit_success_rate < 0.5
            )
            total += len(cycle.candidates)
            print(
                f"[selfplay] round {r+1}/{rounds} {scenario['payload_type']:18s} "
                f"action={cycle.action:7s} blocking_candidates={n_blocked}/{len(cycle.candidates)}"
            )

    after = rec.count()
    print(f"[selfplay] feedback examples: {before} -> {after} (+{after - before})")
    return after - before


def main() -> None:
    ap = argparse.ArgumentParser(description="ZeroWall self-play data generation")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--candidates", type=int, default=8)
    args = ap.parse_args()
    run_selfplay(rounds=args.rounds, candidate_count=args.candidates)


if __name__ == "__main__":
    main()
