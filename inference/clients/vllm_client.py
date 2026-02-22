"""
ZeroWall — vLLM Inference Client
==================================
OpenAI-compatible client for the local vLLM server.

Used by:
  - Mutation Agent: narrative reasoning about transform selection
  - Explanation Agent: judge-facing defense summary generation

vLLM is chosen for DGX Spark because:
  - OpenAI-compatible API (easy integration)
  - Optimized for NVIDIA GPUs (PagedAttention, continuous batching)
  - Supports tensor parallelism across DGX GPUs
  - No cloud dependency — fully local inference

TensorRT-LLM note: The architecture is designed so swapping vLLM for
TRT-LLM requires only changing this client. Both expose OpenAI-compatible
APIs. TRT-LLM is the preferred production path for maximum DGX throughput.
"""

import time
import logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class VLLMClient:
    """
    Client for the local vLLM OpenAI-compatible server.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8088,
        model: str = "microsoft/phi-2",
        timeout_s: float = 30.0,
    ):
        self.base_url = f"http://{host}:{port}/v1"
        self.model = model
        self.timeout_s = timeout_s
        self._latency_log: list = []

    def is_healthy(self) -> bool:
        """Check if vLLM server is available."""
        try:
            resp = httpx.get(f"http://{self.base_url.split('/v1')[0]}/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def complete(
        self,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate a completion from the local vLLM server.

        Args:
            prompt: Input prompt
            max_tokens: Max tokens to generate
            temperature: Sampling temperature (low = deterministic)
            system_prompt: Optional system message

        Returns:
            Generated text string
        """
        t_start = time.time()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()

            latency_ms = (time.time() - t_start) * 1000
            self._latency_log.append({
                "operation": "complete",
                "latency_ms": latency_ms,
                "tokens": max_tokens,
                "timestamp": t_start,
            })
            logger.info(f"[VLLMClient] Completion in {latency_ms:.1f}ms")

            data = resp.json()
            return data["choices"][0]["message"]["content"]

        except Exception as e:
            latency_ms = (time.time() - t_start) * 1000
            logger.warning(f"[VLLMClient] Error ({latency_ms:.1f}ms): {e}")
            raise

    def get_latency_log(self) -> list:
        """Return logged inference latencies for telemetry."""
        return self._latency_log.copy()

    def get_models(self) -> list:
        """List available models on vLLM server."""
        try:
            resp = httpx.get(f"{self.base_url}/models", timeout=5.0)
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception:
            return []
