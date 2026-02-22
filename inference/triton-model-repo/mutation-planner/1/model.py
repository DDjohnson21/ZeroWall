"""
ZeroWall Triton Backend — Mutation Planner
==========================================
Python backend model for Triton Inference Server.
Selects transform types for mutation candidates based on attack context.
"""

import json
import numpy as np
import triton_python_backend_utils as pb_utils

# Available transform types and their default weights
TRANSFORM_WEIGHTS = {
    "swap_validators":    0.45,
    "rename_identifiers": 0.20,
    "route_rotation":     0.20,
    "reorder_blocks":     0.10,
    "split_helpers":      0.05,
}

TRANSFORMS = list(TRANSFORM_WEIGHTS.keys())
WEIGHTS = list(TRANSFORM_WEIGHTS.values())


class TritonPythonModel:

    def initialize(self, args):
        self.model_config = json.loads(args["model_config"])

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
            attack_context_hash = hash(str(ctx)) % 10000

            # Deterministic weighted selection seeded by attack context
            import random
            rng = random.Random(attack_context_hash)
            chosen = rng.choices(TRANSFORMS, weights=WEIGHTS, k=count)

            result = {
                "transform_scores": {
                    t: TRANSFORM_WEIGHTS[t] + rng.uniform(-0.05, 0.05)
                    for t in TRANSFORMS
                },
                "recommended_sequence": chosen[:count],
                "model": "mutation-planner-v1",
                "backend": "triton-python",
            }

            out_bytes = json.dumps(result).encode("utf-8")
            out_tensor = pb_utils.Tensor(
                "OUTPUT",
                np.array([out_bytes], dtype=object),
            )
            responses.append(pb_utils.InferenceResponse(output_tensors=[out_tensor]))

        return responses

    def finalize(self):
        pass
