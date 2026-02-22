"""
ZeroWall — Triton Inference Server Client
==========================================
HTTP client wrapper for Triton Inference Server.
Routes agent inference calls through Triton-served models.

Models served:
  - mutation-planner : selects transform types for candidates
  - risk-scorer      : validates candidate risk scores

Falls back gracefully when Triton is unreachable (dev mode).
"""

import time
import logging
import json
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class TritonClient:
    """
    Client for Triton Inference Server HTTP API (v2 protocol).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        timeout_s: float = 10.0,
    ):
        self.base_url = f"http://{host}:{port}"
        self.timeout_s = timeout_s
        self._healthy: Optional[bool] = None
        self._latency_log: list = []

    def is_healthy(self) -> bool:
        """Check if Triton server is available."""
        try:
            resp = httpx.get(
                f"{self.base_url}/v2/health/ready",
                timeout=2.0,
            )
            self._healthy = resp.status_code == 200
        except Exception:
            self._healthy = False
        return self._healthy

    def infer(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        model_version: str = "1",
    ) -> Dict[str, Any]:
        """
        Send inference request to Triton model.
        Uses Triton HTTP Inference Protocol v2.

        Returns model output dict.
        """
        t_start = time.time()

        # Build Triton v2 request payload
        # For hackathon: using BYTES input type (JSON-serialized context)
        input_bytes = json.dumps(inputs).encode("utf-8")
        payload = {
            "inputs": [
                {
                    "name": "INPUT",
                    "shape": [1, len(input_bytes)],
                    "datatype": "BYTES",
                    "data": [input_bytes.decode("utf-8")],
                }
            ],
            "outputs": [{"name": "OUTPUT"}],
        }

        try:
            resp = httpx.post(
                f"{self.base_url}/v2/models/{model_name}/infer",
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            latency_ms = (time.time() - t_start) * 1000
            self._latency_log.append({
                "model": model_name,
                "latency_ms": latency_ms,
                "timestamp": t_start,
            })
            logger.info(
                f"[TritonClient] {model_name} inference: {latency_ms:.1f}ms"
            )

            output = resp.json()
            # Parse output bytes back to dict
            raw = output.get("outputs", [{}])[0].get("data", ["{}"])[0]
            return json.loads(raw) if isinstance(raw, str) else {}

        except Exception as e:
            latency_ms = (time.time() - t_start) * 1000
            logger.warning(f"[TritonClient] {model_name} error ({latency_ms:.1f}ms): {e}")
            raise

    def get_model_stats(self, model_name: str) -> Dict[str, Any]:
        """Fetch Triton model statistics for benchmarking."""
        try:
            resp = httpx.get(
                f"{self.base_url}/v2/models/{model_name}/stats",
                timeout=5.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"[TritonClient] Stats error for {model_name}: {e}")
            return {}

    def get_latency_log(self) -> list:
        """Return logged inference latencies for telemetry."""
        return self._latency_log.copy()

    def get_server_metrics(self) -> str:
        """Fetch Prometheus metrics from Triton (for GPU utilization etc.)."""
        try:
            resp = httpx.get(f"{self.base_url}/metrics", timeout=5.0)
            return resp.text
        except Exception:
            return ""
