"""
ZeroWall — Mutation Planner Output Schema & Validation Layer
============================================================
The Mutation Planner (NeMo-fine-tuned) must emit a STRUCTURED, RANKED plan —
never free-form natural language. This module defines that contract and the
validation layer that every model output must pass before it is allowed to
enter the defense loop.

WHY THIS EXISTS (challenge #2 from the design notes):
    A fine-tuned LLM can drift into prose, hallucinate transform names, or
    return malformed JSON. None of that is allowed to reach the safe transform
    engine. `validate_plan()` is the gate: parse → validate → coerce → or reject.
    If it rejects, the cascade falls through to the next tier, guaranteeing the
    defense cycle always completes.

Expected raw model output (JSON):
    {
      "plan": [
        {"transform": "swap_validators", "confidence": 0.93, "rationale": "..."},
        {"transform": "route_rotation", "confidence": 0.71, "rationale": "..."},
        ...
      ]
    }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from core.models import TransformType

logger = logging.getLogger(__name__)

# Every transform the safe engine knows how to apply. The model is NOT allowed
# to invent names outside this set — anything else is dropped during validation.
VALID_TRANSFORMS = {t.value for t in TransformType}


class PlannerValidationError(ValueError):
    """Raised when a model's raw output cannot be coerced into a valid plan."""


@dataclass
class TransformChoice:
    """One ranked entry in a mutation plan."""
    transform_type: TransformType
    confidence: float
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transform": self.transform_type.value,
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
        }


@dataclass
class RankedTransformPlan:
    """
    A validated, ranked plan emitted by the Mutation Planner.

    `choices` is ordered most→least recommended. The Mutation Agent expands
    this into N concrete candidates, biased toward the top of the ranking.
    """
    choices: List[TransformChoice] = field(default_factory=list)
    source_tier: str = "unknown"   # nemo | learned | triton | deterministic
    model: str = "unknown"
    raw: Optional[str] = None

    def __post_init__(self):
        # Defensive: keep the ranking sorted by confidence (desc) and stable.
        self.choices.sort(key=lambda c: c.confidence, reverse=True)

    @property
    def is_empty(self) -> bool:
        return len(self.choices) == 0

    def top(self, n: int) -> List[TransformChoice]:
        return self.choices[:n]

    def weighted_sequence(self, count: int) -> List[TransformChoice]:
        """
        Expand the ranked plan into `count` concrete choices.

        The highest-confidence transform is always seeded first (security
        impact matters most), then the remaining slots are filled by walking
        the ranking proportionally to confidence. Deterministic — no RNG — so
        the same plan always expands the same way (reproducibility for audit).
        """
        if self.is_empty:
            return []

        # Normalise confidences into integer slot allocations.
        total_conf = sum(max(c.confidence, 0.0) for c in self.choices) or 1.0
        sequence: List[TransformChoice] = []

        # Guarantee the top choice leads.
        sequence.append(self.choices[0])

        remaining = count - 1
        if remaining > 0:
            allocations = [
                max(1, round(remaining * (c.confidence / total_conf)))
                for c in self.choices
            ]
            for choice, n_slots in zip(self.choices, allocations):
                for _ in range(n_slots):
                    if len(sequence) >= count:
                        break
                    sequence.append(choice)

        # Pad (round-robin) or trim to exactly `count`.
        i = 0
        while len(sequence) < count:
            sequence.append(self.choices[i % len(self.choices)])
            i += 1
        return sequence[:count]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan": [c.to_dict() for c in self.choices],
            "source_tier": self.source_tier,
            "model": self.model,
        }


def _coerce_confidence(value: Any) -> float:
    """Best-effort coercion of a confidence value into [0, 1]."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.5
    if f < 0.0:
        return 0.0
    if f > 1.0:
        # Some models emit 0-100; rescale.
        return min(f / 100.0, 1.0) if f <= 100.0 else 1.0
    return f


def validate_plan(
    raw_output: Union[str, Dict[str, Any]],
    source_tier: str = "unknown",
    model: str = "unknown",
) -> RankedTransformPlan:
    """
    Parse and validate a raw planner output into a RankedTransformPlan.

    Accepts either a JSON string or an already-parsed dict. Tolerates a few
    common model quirks (markdown fences, a bare list, alternate key names)
    but REJECTS anything that yields zero valid transforms.

    Raises:
        PlannerValidationError if no valid transform choices can be recovered.
    """
    data: Any = raw_output

    if isinstance(raw_output, str):
        text = raw_output.strip()
        # Strip markdown code fences a fine-tuned model might still emit.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise PlannerValidationError(f"output is not valid JSON: {e}")

    # Accept {"plan": [...]}, {"choices": [...]}, or a bare [...].
    if isinstance(data, dict):
        entries = data.get("plan") or data.get("choices") or data.get("transforms")
    elif isinstance(data, list):
        entries = data
    else:
        raise PlannerValidationError(f"unexpected output type: {type(data)}")

    if not isinstance(entries, list) or not entries:
        raise PlannerValidationError("plan contains no transform entries")

    choices: List[TransformChoice] = []
    seen: set = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("transform") or entry.get("transform_type") or entry.get("name") or "")
        name = str(name).strip().lower()
        if name not in VALID_TRANSFORMS:
            logger.debug("[validate_plan] dropping unknown transform: %r", name)
            continue
        if name in seen:
            continue  # de-dup; ranking is per transform type
        seen.add(name)
        choices.append(
            TransformChoice(
                transform_type=TransformType(name),
                confidence=_coerce_confidence(entry.get("confidence", 0.75)),
                rationale=str(entry.get("rationale", ""))[:280],
            )
        )

    if not choices:
        raise PlannerValidationError(
            "no recognised transforms in plan (all entries invalid/hallucinated)"
        )

    return RankedTransformPlan(
        choices=choices,
        source_tier=source_tier,
        model=model,
        raw=raw_output if isinstance(raw_output, str) else json.dumps(raw_output),
    )
