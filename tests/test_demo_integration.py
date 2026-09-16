import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from core.deploy.controller import DeployController
from core.orchestrator.defense_loop import DefenseLoop
from core.telemetry.collector import TelemetryCollector
from core.telemetry.rapids_analytics import RapidsAnalytics
from core.training.feedback import FeedbackRecorder


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "apps" / "target-fastapi" / "main.py"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def managed_target(tmp_path):
    port = _free_port()
    deploy_dir = tmp_path / "deploy"
    env = os.environ.copy()
    env.update(
        {
            "PORT": str(port),
            "ZEROWALL_DEPLOY_DIR": str(deploy_dir),
            "ZEROWALL_ORIGINAL_SOURCE": str(ORIGINAL),
            "ZEROWALL_RESET_ON_START": "true",
            "LOG_LEVEL": "warning",
        }
    )
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "apps" / "target-fastapi" / "managed_runner.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/health", timeout=0.3).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("managed target did not become healthy")

    yield url, deploy_dir, tmp_path

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _loop(url: str, deploy_dir: Path, tmp_path: Path) -> DefenseLoop:
    loop = DefenseLoop(
        target_url=url,
        candidate_count=8,
        workers=4,
        telemetry=TelemetryCollector(tmp_path / "telemetry"),
        deploy_controller=DeployController(
            deploy_dir=deploy_dir,
            original_path=ORIGINAL,
        ),
        feedback_recorder=FeedbackRecorder(tmp_path / "feedback.jsonl"),
        live_gate_timeout_s=10,
    )
    loop.mutation_agent.nemo_planner = None
    loop.mutation_agent.learned_planner = None
    loop.mutation_agent.triton_client = None
    loop.risk_agent.triton_client = None
    loop.explanation_agent.vllm_client = None
    loop.verifier_agent.run_bandit = False
    return loop


def test_vulnerable_to_verified_live_hardening(managed_target):
    url, deploy_dir, tmp_path = managed_target
    before = httpx.get(
        f"{url}/data", params={"file": "../../etc/passwd"}
    )
    assert before.status_code == 200

    loop = _loop(url, deploy_dir, tmp_path)
    cycle = loop.run_defense_cycle(
        {
            "trigger": "integration-test",
            "endpoint": "/data",
            "payload_type": "path-traversal",
        }
    )

    after = httpx.get(
        f"{url}/data", params={"file": "../../etc/passwd"}
    )
    version = httpx.get(f"{url}/version").json()

    assert cycle.action == "deploy"
    assert cycle.deployment_verified is True
    assert cycle.baseline_exploit_rate == 1.0
    assert cycle.active_exploit_rate == 0.0
    assert after.status_code == 403
    assert version["loaded_source_hash"] == cycle.deploy_hash

    analytics = RapidsAnalytics(tmp_path / "telemetry").get_full_summary()
    assert analytics["exploit_rate"]["before"] == 1.0
    assert analytics["exploit_rate"]["after"] == 0.0
    assert analytics["candidates"]["total_cycles"] == 1


def test_failed_live_gate_restores_previous_source(managed_target):
    url, deploy_dir, tmp_path = managed_target
    original_hash = hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()[:16]
    loop = _loop(url, deploy_dir, tmp_path)

    async def fail_gate(_winner, _expected_hash):
        return False, "injected live-gate failure"

    loop._post_deploy_gate = fail_gate
    cycle = loop.run_defense_cycle(
        {
            "trigger": "rollback-test",
            "endpoint": "/data",
            "payload_type": "path-traversal",
        }
    )

    version = httpx.get(f"{url}/version").json()
    exploit = httpx.get(
        f"{url}/data", params={"file": "../../etc/passwd"}
    )

    assert cycle.action == "rollback"
    assert cycle.deployment_verified is False
    assert "injected live-gate failure" in cycle.deployment_error
    assert version["loaded_source_hash"] == original_hash
    assert exploit.status_code == 200
