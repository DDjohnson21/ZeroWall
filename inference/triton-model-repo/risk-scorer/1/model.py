"""
ZeroWall Triton Backend — Risk Scorer
======================================
Python backend for Triton Inference Server.
Scores mutation candidate risk using a weighted formula.
Enables batched GPU inference for fast parallel candidate scoring.
"""

import json
import numpy as np
import triton_python_backend_utils as pb_utils


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

            exploit_rate = float(ctx.get("exploit_success_rate", 1.0))
            test_pass = float(ctx.get("tests_passed", 0))
            test_total = float(ctx.get("total_tests", 1))
            bandit = float(ctx.get("bandit_issues", 0))
            model_confidence = float(ctx.get("model_confidence", 0.75))

            # Scoring formula (mirrors RiskAgent for consistency)
            security_score = 1.0 - exploit_rate
            correctness_score = test_pass / max(test_total, 1)
            bandit_penalty = min(bandit * 0.05, 0.30)
            model_bonus = model_confidence * 0.05

            score = security_score * 0.60 + correctness_score * 0.40 - bandit_penalty + model_bonus
            score = max(0.0, min(1.0, score))

            result = {
                "confidence_score": round(score, 4),
                "risk_score": round(1.0 - score, 4),
                "security_component": round(security_score * 0.60, 4),
                "correctness_component": round(correctness_score * 0.40, 4),
                "model": "risk-scorer-v1",
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
