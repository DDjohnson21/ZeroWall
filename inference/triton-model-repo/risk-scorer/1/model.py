"""
ZeroWall Triton Backend — Risk Scorer (serves the TRAINED risk model)
====================================================================
Python backend for Triton Inference Server. Scores a mutation candidate's
deployment confidence by running the logistic-regression risk model trained on
real defense-cycle outcomes (core/training/train_risk.py). The trained weights
(`risk.npz`) are exported into this version directory and run here — a real
served model, batched on the GPU. If weights are absent (cold start), it falls
back to the original weighted formula so scoring always works.

Input  (BYTES, JSON): {"exploit_success_rate":.., "tests_passed":.., "total_tests":.., "bandit_issues":.., "model_confidence":..}
Output (BYTES, JSON): {"confidence_score":.., "risk_score":.., "model":.., "backend":"triton-python", "trained": bool}
"""

import json
import os

import numpy as np
import triton_python_backend_utils as pb_utils

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEIGHTS_PATH = os.path.join(_HERE, "risk.npz")


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


class TritonPythonModel:

    def initialize(self, args):
        self.model_config = json.loads(args["model_config"])
        self._w = self._b = None
        self._trained = False
        if os.path.exists(_WEIGHTS_PATH):
            try:
                data = np.load(_WEIGHTS_PATH, allow_pickle=False)
                self._w = data["w"].astype(np.float32)
                self._b = float(data["b"])
                self._trained = True
            except Exception:
                self._trained = False

    def _features(self, ctx):
        exploit_rate = float(ctx.get("exploit_success_rate", 1.0))
        test_pass = float(ctx.get("tests_passed", 0))
        test_total = float(ctx.get("total_tests", 1))
        security = 1.0 - exploit_rate
        correctness = test_pass / max(test_total, 1.0)
        return np.asarray([security, correctness], dtype=np.float32), security, correctness

    def _score(self, ctx):
        x, security, correctness = self._features(ctx)
        bandit_penalty = min(float(ctx.get("bandit_issues", 0)) * 0.05, 0.30)

        if self._trained:
            base = float(_sigmoid(float(x @ self._w + self._b)))
            model_name = "risk-logreg-v1"
        else:
            # cold-start formula (mirrors RiskAgent)
            model_bonus = float(ctx.get("model_confidence", 0.75)) * 0.05
            base = security * 0.60 + correctness * 0.40 + model_bonus
            model_name = "risk-formula-v0"

        score = max(0.0, min(1.0, base - bandit_penalty))
        return score, model_name

    def execute(self, requests):
        responses = []
        for request in requests:
            in_tensor = pb_utils.get_input_tensor_by_name(request, "INPUT")
            raw = in_tensor.as_numpy()[0].decode("utf-8")
            try:
                ctx = json.loads(raw)
            except Exception:
                ctx = {}

            score, model_name = self._score(ctx)
            result = {
                "confidence_score": round(score, 4),
                "risk_score": round(1.0 - score, 4),
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
