"""
ZeroWall Core API Server
========================
Exposes the DefenseLoop as a REST API on port 9000.
Used by the Streamlit dashboard and external tooling.
"""

import logging
import os
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ZeroWall Core API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-init the DefenseLoop so the server starts even if Triton/vLLM aren't ready
_defense_loop = None


def get_defense_loop():
    global _defense_loop
    if _defense_loop is None:
        from core.orchestrator.defense_loop import DefenseLoop
        _defense_loop = DefenseLoop(
            target_url=f"http://{os.getenv('TARGET_HOST', 'target-app')}:{os.getenv('TARGET_PORT', '8000')}",
            triton_host=os.getenv("TRITON_HOST", "triton"),
            triton_port=int(os.getenv("TRITON_HTTP_PORT", "8000")),
            vllm_host=os.getenv("VLLM_HOST", "vllm"),
            vllm_port=int(os.getenv("VLLM_PORT", "8000")),
        )
    return _defense_loop


class DefendRequest(BaseModel):
    attack_context: Dict[str, Any] = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": "zerowall-core"}


@app.get("/status")
def status():
    try:
        loop = get_defense_loop()
        return loop.get_status()
    except Exception as e:
        logger.warning(f"Status check failed: {e}")
        return {"status": "initializing", "error": str(e)}


@app.post("/defend")
def defend(req: DefendRequest):
    try:
        loop = get_defense_loop()
        cycle = loop.run_defense_cycle(req.attack_context)
        return {
            "cycle_id": cycle.cycle_id,
            "action": cycle.action,
            "winner_id": cycle.winner_id,
            "cycle_latency_s": cycle.cycle_latency_s,
        }
    except Exception as e:
        logger.error(f"Defense cycle failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/cycles")
def cycles():
    try:
        loop = get_defense_loop()
        return {"total": len(loop._cycles), "cycles": [
            {
                "cycle_id": c.cycle_id,
                "action": c.action,
                "winner_id": c.winner_id,
                "latency_s": c.cycle_latency_s,
            }
            for c in loop._cycles[-10:]  # last 10
        ]}
    except Exception as e:
        return {"total": 0, "cycles": [], "error": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")
