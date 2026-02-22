"""
ZeroWall — Telemetry Collector
================================
Collects events from all agents and defense cycles.
Feeds into RAPIDS cuDF analytics pipeline.
"""

import json
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TELEMETRY_DIR = Path(__file__).parent.parent.parent / "telemetry_data"
TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


class TelemetryCollector:
    """
    Collects structured events from all ZeroWall components.
    Writes to JSONL file for RAPIDS analytics.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or TELEMETRY_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._events: List[Dict[str, Any]] = []
        self._log_file = self.output_dir / "telemetry.jsonl"

    def record(
        self,
        metric: str,
        value: Any,
        cycle_id: Optional[str] = None,
        agent: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a single telemetry event."""
        event = {
            "timestamp": time.time(),
            "metric": metric,
            "value": value,
            "cycle_id": cycle_id,
            "agent": agent,
            **(extra or {}),
        }
        self._events.append(event)
        # Write to JSONL
        with open(self._log_file, "a") as f:
            f.write(json.dumps(event) + "\n")

    def record_cycle(self, cycle) -> None:
        """Record a complete defense cycle summary."""
        from core.models import DefenseCycle
        self.record("cycle_complete", 1, cycle_id=cycle.cycle_id)
        self.record("cycle_latency_s", cycle.cycle_latency_s, cycle_id=cycle.cycle_id)
        self.record("candidate_count", len(cycle.candidates), cycle_id=cycle.cycle_id)
        self.record("action", cycle.action, cycle_id=cycle.cycle_id)
        self.record(
            "mutation_inference_latency_ms",
            cycle.mutation_inference_latency_ms,
            cycle_id=cycle.cycle_id,
            agent="mutation",
        )
        self.record(
            "risk_inference_latency_ms",
            cycle.risk_inference_latency_ms,
            cycle_id=cycle.cycle_id,
            agent="risk",
        )

        for c in cycle.candidates:
            self.record(
                "candidate_exploit_rate",
                c.exploit_success_rate,
                cycle_id=cycle.cycle_id,
                extra={"candidate_id": c.candidate_id},
            )
            self.record(
                "candidate_confidence",
                c.confidence_score,
                cycle_id=cycle.cycle_id,
                extra={"candidate_id": c.candidate_id},
            )

    def get_all_events(self) -> List[Dict[str, Any]]:
        return self._events.copy()

    def load_from_disk(self) -> List[Dict[str, Any]]:
        """Load all telemetry events from JSONL file."""
        events = []
        if self._log_file.exists():
            with open(self._log_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        return events
