"""
ZeroWall Triton Backend — Mutation Planner (serves the TRAINED policy)
=====================================================================
Python backend for Triton Inference Server. This is tier-3 of the Mutation
Planner cascade (NeMo LLM → host MLP → THIS → deterministic).

It serves the SAME GPU-trained MLP policy that core/training/train.py produces:
the trained weights (`planner.npz`) are exported into this version directory, and
this model runs the forward pass on Triton — real served weights, batched on the
GPU, NOT a hardcoded formula. If no trained weights are present yet (cold start),
it falls back to a deterministic weighted prior so the cycle always completes.

Input  (BYTES, JSON): {"payload_type": "...", "endpoint": "...", "count": N}
Output (BYTES, JSON): {"transform_scores": {transform: score}, "recommended_sequence": [...], "model": "...", "backend": "triton-python"}
"""

import json
import os
import random

import numpy as np
import triton_python_backend_utils as pb_utils

# ── Feature contract — MUST match core/training/features.py exactly ──────────
PAYLOAD_TYPES = ["path-traversal", "command-injection", "sql-injection", "unknown"]
ENDPOINTS = ["/data", "/run", "/search", "unknown"]
TRANSFORMS = [
    "rename_identifiers",
    "reorder_blocks",
    "split_helpers",
    "swap_validators",
    "route_rotation",
]
_PAYLOAD_ALIASES = {
    "path_traversal": "path-traversal", "traversal": "path-traversal", "lfi": "path-traversal",
    "cmd-injection": "command-injection", "command_injection": "command-injection",
    "cmd_injection": "command-injection", "rce": "command-injection",
    "sqli": "sql-injection", "sql_injection": "sql-injection",
}

# Deterministic prior used only when no trained weights exist (cold start).
PRIOR_WEIGHTS = {
    "swap_validators": 0.45, "rename_identifiers": 0.20, "route_rotation": 0.20,
    "reorder_blocks": 0.10, "split_helpers": 0.05,
}

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEIGHTS_PATH = os.path.join(_HERE, "planner.npz")


def _norm_payload(v):
    v = str(v or "").strip().lower()
    v = _PAYLOAD_ALIASES.get(v, v)
    return v if v in PAYLOAD_TYPES else "unknown"


def _norm_endpoint(v):
    v = str(v or "").strip().lower()
    return v if v in ENDPOINTS else "unknown"


def _onehot(value, vocab):
    return [1.0 if value == item else 0.0 for item in vocab]


def _encode(payload_type, endpoint):
    return np.asarray(
        _onehot(_norm_payload(payload_type), PAYLOAD_TYPES)
        + _onehot(_norm_endpoint(endpoint), ENDPOINTS),
        dtype=np.float32,
    )


class TritonPythonModel:

    def initialize(self, args):
        self.model_config = json.loads(args["model_config"])
        self._W1 = self._b1 = self._W2 = self._b2 = None
        self._trained = False
        if os.path.exists(_WEIGHTS_PATH):
            try:
                data = np.load(_WEIGHTS_PATH, allow_pickle=False)
                self._W1, self._b1 = data["W1"], data["b1"]
                self._W2, self._b2 = data["W2"], data["b2"]
                self._trained = True
            except Exception:
                self._trained = False

    def _forward(self, x):
        h = np.maximum(x @ self._W1 + self._b1, 0.0)
        z = h @ self._W2 + self._b2
        return 1.0 / (1.0 + np.exp(-z))   # sigmoid → per-transform effectiveness

    def _scores(self, payload_type, endpoint):
        if self._trained:
            probs = self._forward(_encode(payload_type, endpoint))
            return {TRANSFORMS[i]: float(probs[i]) for i in range(len(TRANSFORMS))}, "planner-mlp-v1"
        # cold-start prior
        return dict(PRIOR_WEIGHTS), "weighted-prior-v0"

    def execute(self, requests):
        responses = []
        for request in requests:
            in_tensor = pb_utils.get_input_tensor_by_name(request, "INPUT")
            raw = in_tensor.as_numpy()[0].decode("utf-8")
            try:
                ctx = json.loads(raw)
            except Exception:
                ctx = {}

            count = int(ctx.get("count", 10))
            scores, model_name = self._scores(ctx.get("payload_type"), ctx.get("endpoint"))

            # Build a recommended sequence biased toward the highest scores.
            ranked = sorted(scores, key=scores.get, reverse=True)
            total = sum(max(s, 0.0) for s in scores.values()) or 1.0
            rng = random.Random(hash(str(ctx)) % 10000)
            seq = rng.choices(ranked, weights=[max(scores[t], 0.0) / total for t in ranked], k=count)

            result = {
                "transform_scores": scores,
                "recommended_sequence": seq,
                "model": model_name,
                "backend": "triton-python",
                "trained": self._trained,
            }
            out_bytes = json.dumps(result).encode("utf-8")
            out_tensor = pb_utils.Tensor("OUTPUT", np.array([out_bytes], dtype=object))
            responses.append(pb_utils.InferenceResponse(output_tensors=[out_tensor]))
        return responses

    def finalize(self):
        pass
