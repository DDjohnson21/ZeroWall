"""
ZeroWall — Planner Feature Encoding
===================================
Shared, deterministic feature contract used by BOTH the GPU training step
and the host-side (numpy) inference path. Keeping a single source of truth
here guarantees the model is served with exactly the features it was trained
on — a common cause of silent train/serve skew.

A defense cycle's attack context is encoded into a fixed-width one-hot vector
over (payload_type, endpoint). The model maps that vector to an effectiveness
score per transform type. Unseen categories fall into an explicit "unknown"
bucket rather than being dropped, so the planner degrades gracefully on novel
attacks instead of crashing.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.models import TransformType

# Canonical, ordered vocabularies. Order is part of the contract — appending is
# safe (old weights still align); reordering is NOT.
PAYLOAD_TYPES: List[str] = [
    "path-traversal",
    "command-injection",
    "sql-injection",
    "unknown",
]

ENDPOINTS: List[str] = [
    "/data",
    "/run",
    "/search",
    "unknown",
]

# The label space: one effectiveness score per transform, in a fixed order.
TRANSFORMS: List[str] = [t.value for t in TransformType]

FEATURE_DIM = len(PAYLOAD_TYPES) + len(ENDPOINTS)
LABEL_DIM = len(TRANSFORMS)

# Common spellings the upstream IDS / CLI might emit, normalised to our vocab.
_PAYLOAD_ALIASES = {
    "path_traversal": "path-traversal",
    "traversal": "path-traversal",
    "lfi": "path-traversal",
    "cmd-injection": "command-injection",
    "command_injection": "command-injection",
    "cmd_injection": "command-injection",
    "rce": "command-injection",
    "sqli": "sql-injection",
    "sql_injection": "sql-injection",
}


def normalize_payload_type(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    v = _PAYLOAD_ALIASES.get(v, v)
    return v if v in PAYLOAD_TYPES else "unknown"


def normalize_endpoint(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    return v if v in ENDPOINTS else "unknown"


def _onehot(value: str, vocab: List[str]) -> List[float]:
    return [1.0 if value == item else 0.0 for item in vocab]


def encode_context(attack_context: Dict[str, Any]) -> List[float]:
    """Encode an attack context dict into the fixed-width feature vector."""
    payload = normalize_payload_type(
        attack_context.get("payload_type") or attack_context.get("payload-type")
    )
    endpoint = normalize_endpoint(attack_context.get("endpoint"))
    return _onehot(payload, PAYLOAD_TYPES) + _onehot(endpoint, ENDPOINTS)


def context_key(attack_context: Dict[str, Any]) -> str:
    """Stable grouping key for dataset aggregation."""
    return f"{normalize_payload_type(attack_context.get('payload_type'))}|{normalize_endpoint(attack_context.get('endpoint'))}"
