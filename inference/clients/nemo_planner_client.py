"""
ZeroWall — NeMo Planner Client (tier-1 of the Mutation Planner cascade)
======================================================================
Serves the NeMo LoRA-fine-tuned Mutation Planner LLM and returns a validated
`RankedTransformPlan`. The fine-tuned adapter is served behind an
OpenAI-compatible endpoint (vLLM `--enable-lora`, or TRT-LLM), so this client is
a thin, swappable layer — exactly like `VLLMClient`.

Serving contract (must match training, see core/training/nemo_sft_dataset.py):
  * The model is prompted with the SAME prompt template it was fine-tuned on
    (loaded from the SFT data dir so train/serve never drift).
  * The model returns STRICT JSON: {"plan": [{transform, confidence, rationale}]}.
  * Output passes through `validate_plan()` — the same gate every tier uses — so
    a hallucinated/malformed plan is rejected and the cascade falls through to
    the next tier. A planner LLM can NEVER inject code; it only ranks transform
    TYPES the deterministic engine knows how to apply.

If the endpoint is unreachable or no adapter is loaded, `available` is False and
`predict()` returns None — the cycle still completes via the lower tiers.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from core.training.schema import RankedTransformPlan, validate_plan, PlannerValidationError

logger = logging.getLogger(__name__)

# Where the SFT step wrote the exact prompt the model was trained on.
SFT_DIR = Path(__file__).parent.parent.parent / "training_data" / "nemo_sft"
# Where nemo_finetune wrote the adapter meta (its presence => a model was trained).
ADAPTER_META = (
    Path(__file__).parent.parent.parent
    / "artifacts" / "models" / "planner-llm" / "planner_llm_meta.json"
)

# Fallback prompt (used only if the SFT dir wasn't shipped). Kept consistent
# with nemo_sft_dataset.PROMPT_TEMPLATE.
_FALLBACK_SYSTEM = (
    "You are ZeroWall's Mutation Planner. Rank behavior-preserving code "
    "transform TYPES most→least likely to neutralize the attack. Respond with "
    'STRICT JSON: {"plan":[{"transform":<name>,"confidence":<0..1>,'
    '"rationale":<short>}]}. Only use transforms from the menu.'
)
_FALLBACK_TEMPLATE = (
    "{system}\n\nAttack context:\n- endpoint: {endpoint}\n"
    "- payload_type: {payload_type}\n- detail: {detail}\n\n"
    "Transform menu (legal values): {menu}\n\nReturn the ranked JSON plan now:"
)


class NeMoPlannerClient:
    """Tier-1 planner: the NeMo LoRA-fine-tuned LLM served via OpenAI API."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        model: Optional[str] = None,
        timeout_s: float = 8.0,
        require_adapter: bool = True,
    ):
        host = host or os.getenv("PLANNER_LLM_HOST", "localhost")
        port = port or int(os.getenv("PLANNER_LLM_PORT", "8088"))
        # The LoRA module name registered with `vllm serve --lora-modules`.
        self.model = model or os.getenv("PLANNER_LLM_MODEL", "zerowall-planner")
        self.base_url = f"http://{host}:{port}/v1"
        self.timeout_s = timeout_s
        self._latency_log: list = []

        self._system, self._template = self._load_prompt()
        # Only advertise availability if a fine-tuned adapter was actually
        # produced — prevents the cascade from leaning on an untrained base model.
        self.adapter_present = ADAPTER_META.exists()
        self.require_adapter = require_adapter

    # ── prompt loading (train/serve parity) ──────────────────────────────────
    def _load_prompt(self) -> tuple[str, str]:
        sys_path = SFT_DIR / "system_instruction.txt"
        tpl_path = SFT_DIR / "prompt_template.txt"
        if sys_path.exists() and tpl_path.exists():
            return sys_path.read_text().strip(), tpl_path.read_text()
        return _FALLBACK_SYSTEM, _FALLBACK_TEMPLATE

    @property
    def available(self) -> bool:
        """Tier is usable only if an adapter exists AND the server is healthy."""
        if self.require_adapter and not self.adapter_present:
            return False
        return self.is_healthy()

    def is_healthy(self) -> bool:
        try:
            root = self.base_url.split("/v1")[0]
            resp = httpx.get(f"{root}/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    # ── inference ─────────────────────────────────────────────────────────────
    def predict(self, attack_context: Dict[str, Any]) -> Optional[RankedTransformPlan]:
        """Return a validated RankedTransformPlan, or None to fall through."""
        from core.training.features import (
            TRANSFORMS,
            normalize_endpoint,
            normalize_payload_type,
        )

        prompt = self._template.format(
            system=self._system,
            endpoint=normalize_endpoint(attack_context.get("endpoint")),
            payload_type=normalize_payload_type(attack_context.get("payload_type")),
            detail=str(attack_context.get("detail", "no extra detail provided")),
            menu=", ".join(TRANSFORMS),
        )

        try:
            raw = self._complete(prompt)
        except Exception as e:
            logger.warning("[NeMoPlanner] inference failed: %s", e)
            return None

        try:
            plan = validate_plan(raw, source_tier="nemo", model=f"nemo-lora:{self.model}")
            logger.info(
                "[NeMoPlanner] valid plan: %s",
                [c.transform_type.value for c in plan.top(3)],
            )
            return plan
        except PlannerValidationError as e:
            # The whole point of the gate: a bad LLM plan is dropped, not trusted.
            logger.warning("[NeMoPlanner] plan rejected by validator: %s", e)
            return None

    def _complete(self, prompt: str, max_tokens: int = 256) -> str:
        t0 = time.time()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,            # deterministic, auditable plans
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        resp = httpx.post(
            f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout_s
        )
        resp.raise_for_status()
        latency_ms = (time.time() - t0) * 1000
        self._latency_log.append({"latency_ms": latency_ms, "timestamp": t0})
        logger.info("[NeMoPlanner] inference %.1fms", latency_ms)
        return resp.json()["choices"][0]["message"]["content"]

    def get_latency_log(self) -> list:
        return self._latency_log.copy()
