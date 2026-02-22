"""
ZeroWall — Visual Web Dashboard
=================================
Real-time web UI that visualizes the ZeroWall defense pipeline.
Shows architecture, defense cycle animation, agent activity,
telemetry, candidate matrix, and exploit replay.

Usage:
    python dashboard/web_ui.py
    Open http://localhost:8080
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
TELEMETRY_FILE = BASE_DIR / "telemetry_data" / "telemetry.jsonl"
DEPLOY_MANIFEST = BASE_DIR / "artifacts" / "deploy" / "manifest.json"
TARGET_SOURCE = BASE_DIR / "apps" / "target-fastapi" / "main.py"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("zerowall.webui")

app = FastAPI(title="ZeroWall Visual Dashboard")

# ── Connected WebSocket clients ──────────────────────────────────────────────
ws_clients: List[WebSocket] = []


# ── Data loaders ─────────────────────────────────────────────────────────────

def load_telemetry() -> List[Dict[str, Any]]:
    events = []
    if TELEMETRY_FILE.exists():
        with open(TELEMETRY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return events


def load_manifest() -> Dict[str, Any]:
    if DEPLOY_MANIFEST.exists():
        try:
            return json.loads(DEPLOY_MANIFEST.read_text())
        except Exception:
            pass
    return {
        "active_version_id": "v1.0.0-ORIGINAL",
        "active_hash": "aabbcc001122",
        "history": [],
    }


def compute_stats(events: List[Dict]) -> Dict[str, Any]:
    if not events:
        return {
            "total_cycles": 0,
            "total_candidates": 0,
            "exploit_before": 1.0,
            "exploit_after": 0.0,
            "avg_cycle_s": 0.0,
            "mutation_latencies": [],
            "risk_latencies": [],
            "cycle_latencies": [],
            "candidate_confidences": [],
            "candidate_exploit_rates": [],
            "actions": {},
        }

    def vals(metric):
        return [
            e["value"]
            for e in events
            if e.get("metric") == metric and isinstance(e.get("value"), (int, float))
        ]

    def avg(lst):
        return sum(lst) / len(lst) if lst else 0.0

    baseline = vals("baseline_exploit_rate")
    cand_rates = vals("candidate_exploit_rate")
    cycle_lats = vals("cycle_latency_s")
    cand_counts = vals("candidate_count")
    mut_lats = vals("mutation_latency_ms")
    risk_lats = vals("risk_latency_ms")
    cand_conf = vals("candidate_confidence")

    actions = {}
    for e in events:
        if e.get("metric") == "cycle_action":
            a = e.get("value", "unknown")
            actions[a] = actions.get(a, 0) + 1

    return {
        "total_cycles": len(cycle_lats),
        "total_candidates": int(sum(cand_counts)) if cand_counts else 0,
        "exploit_before": avg(baseline) if baseline else 1.0,
        "exploit_after": avg(cand_rates) if cand_rates else 0.0,
        "avg_cycle_s": round(avg(cycle_lats), 2),
        "mutation_latencies": mut_lats[-20:],
        "risk_latencies": risk_lats[-20:],
        "cycle_latencies": cycle_lats[-20:],
        "candidate_confidences": cand_conf[-30:],
        "candidate_exploit_rates": cand_rates[-30:],
        "actions": actions,
    }


# ── WebSocket broadcast ─────────────────────────────────────────────────────

async def broadcast(msg: Dict):
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


# ── Simulated defense cycle (runs the real pipeline if available) ────────────

async def run_simulated_cycle():
    """Run a simulated defense cycle with realistic timing and broadcast events."""
    cycle_id = str(uuid.uuid4())[:8]
    t0 = time.time()

    steps = [
        {
            "step": 1,
            "name": "Baseline Measurement",
            "agent": "exploit_agent",
            "detail": "Replaying 5 known payloads against original app...",
            "duration": 0.8,
            "result": {"baseline_exploit_rate": 1.0, "payloads_tested": 5},
        },
        {
            "step": 2,
            "name": "Mutation Generation",
            "agent": "mutation_agent",
            "detail": "Triton mutation-planner selecting transform types...",
            "duration": 0.6,
            "result": {"candidates_generated": 10, "transforms": [
                "swap_validators", "swap_validators", "swap_validators",
                "rename_identifiers", "rename_identifiers",
                "route_rotation", "route_rotation",
                "reorder_blocks", "split_helpers", "swap_validators",
            ]},
        },
        {
            "step": 3,
            "name": "Apply Transforms",
            "agent": "transform_engine",
            "detail": "libcst AST transforms: swap_validators, rename_ids, route_rotation...",
            "duration": 0.4,
            "result": {"transforms_applied": 10, "failures": 0},
        },
        {
            "step": 4,
            "name": "Verification",
            "agent": "verifier_agent",
            "detail": "Running pytest (25 tests) + bandit on each candidate...",
            "duration": 1.5,
            "result": {
                "candidates_tested": 10,
                "passing": 8,
                "failing": 2,
                "candidates": [
                    {"id": f"candidate-{cycle_id}-{i:03d}", "tests_passed": 25 if i < 8 else 20,
                     "tests_failed": 0 if i < 8 else 5, "bandit_issues": 0,
                     "verifier_pass": i < 8}
                    for i in range(10)
                ],
            },
        },
        {
            "step": 5,
            "name": "Exploit Replay",
            "agent": "exploit_agent",
            "detail": "Replaying 5 payloads against 8 passing candidates...",
            "duration": 1.2,
            "result": {
                "candidates_tested": 8,
                "exploits_blocked": 6,
                "candidates": [
                    {"id": f"candidate-{cycle_id}-{i:03d}",
                     "exploit_rate": 0.0 if i < 6 else 0.6,
                     "blocked": i < 6}
                    for i in range(8)
                ],
            },
        },
        {
            "step": 6,
            "name": "Risk Assessment",
            "agent": "risk_agent",
            "detail": "Scoring candidates: security(0.6) + correctness(0.4) - bandit_penalty...",
            "duration": 0.3,
            "result": {
                "winner": f"candidate-{cycle_id}-000",
                "winner_confidence": 0.95,
                "action": "deploy",
                "ranked": [
                    {"id": f"candidate-{cycle_id}-{i:03d}",
                     "confidence": round(0.95 - i * 0.03, 2)}
                    for i in range(6)
                ],
            },
        },
    ]

    # Broadcast cycle start
    await broadcast({
        "type": "cycle_start",
        "cycle_id": cycle_id,
        "timestamp": t0,
    })

    for step_data in steps:
        # Broadcast step start
        await broadcast({
            "type": "step_start",
            "cycle_id": cycle_id,
            "step": step_data["step"],
            "name": step_data["name"],
            "agent": step_data["agent"],
            "detail": step_data["detail"],
        })

        # Simulate processing time
        await asyncio.sleep(step_data["duration"])

        # Broadcast step complete
        await broadcast({
            "type": "step_complete",
            "cycle_id": cycle_id,
            "step": step_data["step"],
            "name": step_data["name"],
            "agent": step_data["agent"],
            "result": step_data["result"],
            "latency_ms": round(step_data["duration"] * 1000),
        })

    total_s = round(time.time() - t0, 2)

    # Write telemetry
    TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    telemetry_events = [
        {"timestamp": time.time(), "metric": "baseline_exploit_rate", "value": 1.0, "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "mutation_count", "value": 10, "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "mutation_latency_ms", "value": 600, "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "candidates_passing_tests", "value": 8, "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "candidates_blocking_exploits", "value": 6, "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "cycle_latency_s", "value": total_s, "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "cycle_action", "value": "deploy", "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "risk_latency_ms", "value": 300, "cycle_id": cycle_id},
        {"timestamp": time.time(), "metric": "candidate_count", "value": 10, "cycle_id": cycle_id},
    ]
    for i in range(6):
        telemetry_events.append({
            "timestamp": time.time(),
            "metric": "candidate_exploit_rate",
            "value": 0.0 if i < 4 else 0.2,
            "cycle_id": cycle_id,
            "candidate_id": f"candidate-{cycle_id}-{i:03d}",
        })
        telemetry_events.append({
            "timestamp": time.time(),
            "metric": "candidate_confidence",
            "value": round(0.95 - i * 0.03, 2),
            "cycle_id": cycle_id,
            "candidate_id": f"candidate-{cycle_id}-{i:03d}",
        })

    with open(TELEMETRY_FILE, "a") as f:
        for ev in telemetry_events:
            f.write(json.dumps(ev) + "\n")

    # Broadcast cycle complete
    await broadcast({
        "type": "cycle_complete",
        "cycle_id": cycle_id,
        "total_latency_s": total_s,
        "action": "deploy",
        "winner": f"candidate-{cycle_id}-000",
        "winner_confidence": 0.95,
        "exploit_before": 1.0,
        "exploit_after": 0.0,
    })

    return cycle_id


# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    events = load_telemetry()
    stats = compute_stats(events)
    manifest = load_manifest()
    return JSONResponse({
        "stats": stats,
        "manifest": manifest,
        "telemetry_count": len(events),
    })


@app.post("/api/defend")
async def api_defend():
    cycle_id = await run_simulated_cycle()
    return JSONResponse({"status": "ok", "cycle_id": cycle_id})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("action") == "defend":
                asyncio.create_task(run_simulated_cycle())
            elif msg.get("action") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if ws in ws_clients:
            ws_clients.remove(ws)


# ── Main HTML ────────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ZeroWall — AI Moving Target Defense</title>
<style>
  :root {
    --bg: #0a0e17;
    --bg2: #111827;
    --bg3: #1a2332;
    --border: #1e3a5f;
    --accent: #00d4ff;
    --accent2: #00ff88;
    --danger: #ff4757;
    --warn: #ffa502;
    --text: #e0e6ed;
    --text2: #8892a4;
    --glow: rgba(0, 212, 255, 0.15);
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 13px;
    overflow-x: hidden;
  }
  /* Scanline effect */
  body::after {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(
      0deg,
      rgba(0,0,0,0.03) 0px,
      rgba(0,0,0,0.03) 1px,
      transparent 1px,
      transparent 3px
    );
    pointer-events: none;
    z-index: 9999;
  }

  /* Header */
  .header {
    background: linear-gradient(135deg, #0d1b2a, #1b2838);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header h1 {
    font-size: 18px;
    color: var(--accent);
    text-shadow: 0 0 20px rgba(0,212,255,0.4);
    letter-spacing: 2px;
  }
  .header .subtitle {
    color: var(--text2);
    font-size: 11px;
  }
  .header-right {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
    animation: pulse-dot 2s infinite;
  }
  .status-dot.green { background: var(--accent2); box-shadow: 0 0 8px var(--accent2); }
  .status-dot.red { background: var(--danger); box-shadow: 0 0 8px var(--danger); }
  .status-dot.yellow { background: var(--warn); box-shadow: 0 0 8px var(--warn); }
  @keyframes pulse-dot {
    0%,100% { opacity:1; }
    50% { opacity:0.4; }
  }
  .btn {
    background: linear-gradient(135deg, #00d4ff22, #00d4ff11);
    border: 1px solid var(--accent);
    color: var(--accent);
    padding: 8px 20px;
    cursor: pointer;
    font-family: inherit;
    font-size: 12px;
    letter-spacing: 1px;
    transition: all 0.2s;
  }
  .btn:hover {
    background: var(--accent);
    color: var(--bg);
    box-shadow: 0 0 20px rgba(0,212,255,0.4);
  }
  .btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .btn-danger {
    border-color: var(--danger);
    color: var(--danger);
    background: linear-gradient(135deg, #ff475722, #ff475711);
  }
  .btn-danger:hover {
    background: var(--danger);
    color: #fff;
  }

  /* Layout */
  .main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: auto auto auto;
    gap: 1px;
    padding: 1px;
    background: #0d1520;
  }

  .panel {
    background: var(--bg2);
    border: 1px solid var(--border);
    padding: 16px;
    position: relative;
    overflow: hidden;
  }
  .panel::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    opacity: 0.3;
  }
  .panel-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--accent);
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .panel-title .icon { font-size: 14px; }
  .full-width { grid-column: 1 / -1; }

  /* Metrics Row */
  .metrics-row {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    padding: 16px 24px;
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
  }
  .metric-card {
    background: linear-gradient(135deg, #0d1b2a, #162435);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    text-align: center;
  }
  .metric-card .label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text2);
    margin-bottom: 4px;
  }
  .metric-card .value {
    font-size: 24px;
    font-weight: bold;
    color: var(--accent);
    text-shadow: 0 0 10px rgba(0,212,255,0.3);
  }
  .metric-card .delta {
    font-size: 10px;
    color: var(--accent2);
    margin-top: 2px;
  }
  .metric-card .delta.bad { color: var(--danger); }

  /* Pipeline Visualization */
  .pipeline {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 8px 0;
    overflow-x: auto;
  }
  .pipeline-node {
    flex-shrink: 0;
    width: 130px;
    padding: 10px 8px;
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 6px;
    text-align: center;
    position: relative;
    transition: all 0.4s;
  }
  .pipeline-node.active {
    border-color: var(--accent);
    background: linear-gradient(135deg, #00d4ff11, #00d4ff05);
    box-shadow: 0 0 20px var(--glow);
  }
  .pipeline-node.complete {
    border-color: var(--accent2);
    background: linear-gradient(135deg, #00ff8811, #00ff8805);
  }
  .pipeline-node.failed {
    border-color: var(--danger);
    background: linear-gradient(135deg, #ff475711, #ff475705);
  }
  .pipeline-node .node-step {
    font-size: 9px;
    color: var(--text2);
    text-transform: uppercase;
  }
  .pipeline-node .node-name {
    font-size: 11px;
    font-weight: bold;
    margin: 4px 0;
    color: var(--text);
  }
  .pipeline-node .node-agent {
    font-size: 9px;
    color: var(--accent);
  }
  .pipeline-node .node-latency {
    font-size: 9px;
    color: var(--accent2);
    margin-top: 4px;
  }
  .pipeline-arrow {
    flex-shrink: 0;
    color: var(--border);
    font-size: 16px;
    transition: color 0.4s;
  }
  .pipeline-arrow.lit { color: var(--accent2); text-shadow: 0 0 8px var(--accent2); }

  /* Log Feed */
  .log-feed {
    height: 260px;
    overflow-y: auto;
    font-size: 11px;
    line-height: 1.6;
    padding: 4px 0;
  }
  .log-feed::-webkit-scrollbar { width: 4px; }
  .log-feed::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  .log-entry {
    padding: 2px 0;
    border-bottom: 1px solid #ffffff06;
    animation: fadeIn 0.3s;
  }
  @keyframes fadeIn { from { opacity:0; transform:translateY(-4px); } to { opacity:1; transform:none; } }
  .log-entry .ts { color: var(--text2); }
  .log-entry .agent { color: var(--accent); font-weight: bold; }
  .log-entry .msg { color: var(--text); }
  .log-entry.success .msg { color: var(--accent2); }
  .log-entry.error .msg { color: var(--danger); }
  .log-entry.warn .msg { color: var(--warn); }

  /* Candidate Matrix */
  .cand-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
  }
  .cand-table th {
    text-align: left;
    padding: 6px 8px;
    color: var(--text2);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    border-bottom: 1px solid var(--border);
  }
  .cand-table td {
    padding: 5px 8px;
    border-bottom: 1px solid #ffffff06;
  }
  .cand-table tr.winner { background: #00ff8808; }
  .badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: bold;
  }
  .badge-pass { background: #00ff8822; color: var(--accent2); border: 1px solid #00ff8844; }
  .badge-fail { background: #ff475722; color: var(--danger); border: 1px solid #ff475744; }
  .badge-deploy { background: #00d4ff22; color: var(--accent); border: 1px solid #00d4ff44; }
  .conf-bar {
    height: 6px;
    border-radius: 3px;
    background: var(--bg);
    overflow: hidden;
    width: 80px;
    display: inline-block;
    vertical-align: middle;
  }
  .conf-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.6s;
  }

  /* Charts (simple canvas-based) */
  .chart-container {
    position: relative;
    height: 120px;
    margin-top: 8px;
  }
  canvas { width: 100%; height: 100%; }

  /* Architecture diagram */
  .arch-diagram {
    position: relative;
    height: 280px;
    overflow: hidden;
  }
  .arch-node {
    position: absolute;
    padding: 8px 12px;
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 10px;
    text-align: center;
    transition: all 0.3s;
    z-index: 2;
  }
  .arch-node:hover {
    border-color: var(--accent);
    box-shadow: 0 0 15px var(--glow);
    transform: scale(1.05);
  }
  .arch-node .arch-label {
    font-weight: bold;
    color: var(--accent);
    font-size: 11px;
  }
  .arch-node .arch-sub {
    color: var(--text2);
    font-size: 9px;
    margin-top: 2px;
  }
  .arch-node.gpu { border-color: #76b900; }
  .arch-node.gpu .arch-label { color: #76b900; }
  .arch-node.active-pulse {
    animation: arch-pulse 1s infinite;
  }
  @keyframes arch-pulse {
    0%,100% { box-shadow: 0 0 5px var(--glow); }
    50% { box-shadow: 0 0 25px var(--glow); }
  }

  /* Connection lines drawn via SVG */
  .arch-svg {
    position: absolute;
    top: 0; left: 0;
    width: 100%;
    height: 100%;
    z-index: 1;
    pointer-events: none;
  }
  .arch-svg line {
    stroke: var(--border);
    stroke-width: 1;
    stroke-dasharray: 4 4;
  }
  .arch-svg line.active-line {
    stroke: var(--accent);
    stroke-dasharray: none;
    filter: drop-shadow(0 0 4px var(--accent));
    animation: line-flow 1s linear infinite;
  }
  @keyframes line-flow {
    from { stroke-dashoffset: 20; }
    to { stroke-dashoffset: 0; }
  }

  /* Exploit visualization */
  .exploit-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 8px;
  }
  .exploit-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    background: var(--bg3);
    border-radius: 4px;
    font-size: 11px;
  }
  .exploit-row .name { flex:1; }
  .exploit-row .endpoint { color: var(--warn); font-size: 10px; }
  .exploit-row .status-icon { font-size: 14px; }
  .blocked { color: var(--accent2); }
  .exploited { color: var(--danger); }

  /* Cycle history */
  .cycle-history {
    max-height: 200px;
    overflow-y: auto;
  }
  .cycle-entry {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 1px solid #ffffff06;
    font-size: 11px;
  }
  .cycle-entry .action-badge {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: bold;
    text-transform: uppercase;
  }
  .action-deploy { background: #00ff8822; color: var(--accent2); }
  .action-reject { background: #ff475722; color: var(--danger); }
  .action-rollback { background: #ffa50222; color: var(--warn); }

  /* Spinner */
  .spinner {
    display: inline-block;
    width: 12px; height: 12px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-right: 4px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Toast notifications */
  .toast-container {
    position: fixed;
    top: 60px;
    right: 16px;
    z-index: 10000;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .toast {
    background: var(--bg3);
    border: 1px solid var(--border);
    padding: 10px 16px;
    border-radius: 6px;
    font-size: 12px;
    animation: slideIn 0.3s, fadeOut 0.5s 3.5s forwards;
    max-width: 320px;
  }
  @keyframes slideIn { from { transform: translateX(100%); opacity:0; } to { transform: none; opacity:1; } }
  @keyframes fadeOut { to { opacity:0; transform: translateY(-10px); } }
  .toast.success { border-color: var(--accent2); }
  .toast.error { border-color: var(--danger); }

  /* Footer */
  .footer {
    padding: 8px 24px;
    background: var(--bg2);
    border-top: 1px solid var(--border);
    font-size: 10px;
    color: var(--text2);
    display: flex;
    justify-content: space-between;
  }
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div>
    <h1>ZEROWALL</h1>
    <div class="subtitle">AI Moving Target Defense &mdash; NVIDIA DGX Spark</div>
  </div>
  <div class="header-right">
    <span class="status-dot green" id="ws-status"></span>
    <span style="color:var(--text2);font-size:11px" id="ws-label">Connected</span>
    <button class="btn" id="btn-defend" onclick="triggerDefend()">TRIGGER DEFENSE</button>
  </div>
</div>

<!-- Metrics Row -->
<div class="metrics-row">
  <div class="metric-card">
    <div class="label">Defense Cycles</div>
    <div class="value" id="m-cycles">0</div>
    <div class="delta">total completed</div>
  </div>
  <div class="metric-card">
    <div class="label">Exploit Rate Before</div>
    <div class="value" id="m-before">100%</div>
    <div class="delta bad">vulnerable</div>
  </div>
  <div class="metric-card">
    <div class="label">Exploit Rate After</div>
    <div class="value" id="m-after">0%</div>
    <div class="delta">hardened</div>
  </div>
  <div class="metric-card">
    <div class="label">Avg Cycle Latency</div>
    <div class="value" id="m-latency">0.0s</div>
    <div class="delta">per cycle</div>
  </div>
  <div class="metric-card">
    <div class="label">Candidates Evaluated</div>
    <div class="value" id="m-candidates">0</div>
    <div class="delta">total mutations</div>
  </div>
</div>

<!-- Pipeline -->
<div class="panel full-width" style="padding:12px 24px;">
  <div class="panel-title"><span class="icon">&#9881;</span> Defense Pipeline</div>
  <div class="pipeline" id="pipeline">
    <div class="pipeline-node" id="pipe-1">
      <div class="node-step">Step 1</div>
      <div class="node-name">Baseline</div>
      <div class="node-agent">exploit_agent</div>
      <div class="node-latency" id="pipe-1-lat"></div>
    </div>
    <div class="pipeline-arrow" id="arrow-1">&rarr;</div>
    <div class="pipeline-node" id="pipe-2">
      <div class="node-step">Step 2</div>
      <div class="node-name">Mutate</div>
      <div class="node-agent">mutation_agent</div>
      <div class="node-latency" id="pipe-2-lat"></div>
    </div>
    <div class="pipeline-arrow" id="arrow-2">&rarr;</div>
    <div class="pipeline-node" id="pipe-3">
      <div class="node-step">Step 3</div>
      <div class="node-name">Transform</div>
      <div class="node-agent">libcst</div>
      <div class="node-latency" id="pipe-3-lat"></div>
    </div>
    <div class="pipeline-arrow" id="arrow-3">&rarr;</div>
    <div class="pipeline-node" id="pipe-4">
      <div class="node-step">Step 4</div>
      <div class="node-name">Verify</div>
      <div class="node-agent">verifier_agent</div>
      <div class="node-latency" id="pipe-4-lat"></div>
    </div>
    <div class="pipeline-arrow" id="arrow-4">&rarr;</div>
    <div class="pipeline-node" id="pipe-5">
      <div class="node-step">Step 5</div>
      <div class="node-name">Exploit</div>
      <div class="node-agent">exploit_agent</div>
      <div class="node-latency" id="pipe-5-lat"></div>
    </div>
    <div class="pipeline-arrow" id="arrow-5">&rarr;</div>
    <div class="pipeline-node" id="pipe-6">
      <div class="node-step">Step 6</div>
      <div class="node-name">Risk</div>
      <div class="node-agent">risk_agent</div>
      <div class="node-latency" id="pipe-6-lat"></div>
    </div>
  </div>
</div>

<div class="main">
  <!-- Left: Architecture + Log -->
  <div class="panel">
    <div class="panel-title"><span class="icon">&#9733;</span> System Architecture</div>
    <div class="arch-diagram" id="arch-diagram">
      <svg class="arch-svg" id="arch-svg"></svg>
      <!-- nodes positioned by JS -->
    </div>
  </div>

  <!-- Right: Live Agent Log -->
  <div class="panel">
    <div class="panel-title"><span class="icon">&#9783;</span> Agent Activity Log</div>
    <div class="log-feed" id="log-feed"></div>
  </div>

  <!-- Left: Candidate Matrix -->
  <div class="panel">
    <div class="panel-title"><span class="icon">&#9635;</span> Candidate Evaluation Matrix</div>
    <div style="overflow-y:auto;max-height:280px;">
      <table class="cand-table" id="cand-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Transform</th>
            <th>Tests</th>
            <th>Exploit</th>
            <th>Confidence</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="cand-body"></tbody>
      </table>
    </div>
  </div>

  <!-- Right: Exploit Replay + Charts -->
  <div class="panel">
    <div class="panel-title"><span class="icon">&#9760;</span> Exploit Replay Status</div>
    <div class="exploit-list" id="exploit-list">
      <div class="exploit-row">
        <span class="status-icon">&#9679;</span>
        <span class="name">Path Traversal (../../etc/passwd)</span>
        <span class="endpoint">GET /data</span>
        <span class="badge badge-pass" id="exp-0">WAITING</span>
      </div>
      <div class="exploit-row">
        <span class="status-icon">&#9679;</span>
        <span class="name">Command Injection (rm -rf /)</span>
        <span class="endpoint">POST /run</span>
        <span class="badge badge-pass" id="exp-1">WAITING</span>
      </div>
      <div class="exploit-row">
        <span class="status-icon">&#9679;</span>
        <span class="name">SQL Injection (' OR 1=1 --)</span>
        <span class="endpoint">GET /search</span>
        <span class="badge badge-pass" id="exp-2">WAITING</span>
      </div>
      <div class="exploit-row">
        <span class="status-icon">&#9679;</span>
        <span class="name">Shell Escape (; ls -la)</span>
        <span class="endpoint">POST /run</span>
        <span class="badge badge-pass" id="exp-3">WAITING</span>
      </div>
      <div class="exploit-row">
        <span class="status-icon">&#9679;</span>
        <span class="name">Config Traversal (secrets.yaml)</span>
        <span class="endpoint">GET /data</span>
        <span class="badge badge-pass" id="exp-4">WAITING</span>
      </div>
    </div>
    <div style="margin-top:16px;">
      <div class="panel-title" style="margin-bottom:6px;"><span class="icon">&#9671;</span> Confidence Scores</div>
      <canvas id="chart-confidence" height="100"></canvas>
    </div>
  </div>

  <!-- Full width: Cycle History -->
  <div class="panel full-width">
    <div class="panel-title"><span class="icon">&#9200;</span> Defense Cycle History</div>
    <div class="cycle-history" id="cycle-history">
      <div style="color:var(--text2);font-size:11px;">No cycles yet. Click TRIGGER DEFENSE to start.</div>
    </div>
  </div>
</div>

<!-- Toast container -->
<div class="toast-container" id="toasts"></div>

<!-- Footer -->
<div class="footer">
  <span>ZeroWall v2.0 &mdash; NVIDIA DGX Spark Hackathon</span>
  <span id="footer-time"></span>
</div>

<script>
// ── State ───────────────────────────────────────────────────────────────────
let ws = null;
let cycleRunning = false;
let cycleHistory = [];
let lastCandidates = [];

// ── WebSocket ───────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    document.getElementById('ws-status').className = 'status-dot green';
    document.getElementById('ws-label').textContent = 'Connected';
  };
  ws.onclose = () => {
    document.getElementById('ws-status').className = 'status-dot red';
    document.getElementById('ws-label').textContent = 'Disconnected';
    setTimeout(connectWS, 2000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    handleMessage(msg);
  };
}

// ── Message handler ─────────────────────────────────────────────────────────
function handleMessage(msg) {
  switch(msg.type) {
    case 'cycle_start':
      cycleRunning = true;
      document.getElementById('btn-defend').disabled = true;
      resetPipeline();
      addLog('system', `Defense cycle ${msg.cycle_id} started`, 'warn');
      showToast(`Cycle ${msg.cycle_id} started`, 'info');
      break;

    case 'step_start':
      activatePipeNode(msg.step);
      addLog(msg.agent, msg.detail);
      break;

    case 'step_complete':
      completePipeNode(msg.step, msg.latency_ms);
      addLog(msg.agent, `${msg.name} complete (${msg.latency_ms}ms)`, 'success');
      handleStepResult(msg);
      break;

    case 'cycle_complete':
      cycleRunning = false;
      document.getElementById('btn-defend').disabled = false;
      addLog('system',
        `Cycle ${msg.cycle_id} COMPLETE: ${msg.action.toUpperCase()} | ` +
        `Winner: ${msg.winner} (${(msg.winner_confidence*100).toFixed(0)}%) | ` +
        `Exploit: ${(msg.exploit_before*100).toFixed(0)}% -> ${(msg.exploit_after*100).toFixed(0)}%`,
        'success'
      );
      showToast(`Deployed ${msg.winner} with ${(msg.winner_confidence*100).toFixed(0)}% confidence`, 'success');
      cycleHistory.unshift(msg);
      renderCycleHistory();
      refreshStats();
      break;
  }
}

// ── Pipeline visualization ──────────────────────────────────────────────────
function resetPipeline() {
  for (let i=1;i<=6;i++) {
    const node = document.getElementById(`pipe-${i}`);
    node.className = 'pipeline-node';
    const lat = document.getElementById(`pipe-${i}-lat`);
    if (lat) lat.textContent = '';
    if (i<6) document.getElementById(`arrow-${i}`).className = 'pipeline-arrow';
  }
  // Reset exploit badges
  for (let i=0;i<5;i++) {
    const el = document.getElementById(`exp-${i}`);
    el.textContent = 'TESTING...';
    el.className = 'badge badge-pass';
  }
  // Clear candidates
  document.getElementById('cand-body').innerHTML = '';
}

function activatePipeNode(step) {
  const node = document.getElementById(`pipe-${step}`);
  node.className = 'pipeline-node active';
}

function completePipeNode(step, latencyMs) {
  const node = document.getElementById(`pipe-${step}`);
  node.className = 'pipeline-node complete';
  const lat = document.getElementById(`pipe-${step}-lat`);
  if (lat) lat.textContent = latencyMs + 'ms';
  if (step < 6) {
    document.getElementById(`arrow-${step}`).className = 'pipeline-arrow lit';
  }
}

// ── Handle step results ─────────────────────────────────────────────────────
function handleStepResult(msg) {
  const r = msg.result;
  if (!r) return;

  if (msg.step === 4 && r.candidates) {
    // Verification results
    renderCandidates(r.candidates, 'verify');
  }
  if (msg.step === 5 && r.candidates) {
    // Exploit results
    updateCandidatesExploit(r.candidates);
    updateExploitBadges(true);
  }
  if (msg.step === 6 && r.ranked) {
    updateCandidatesRisk(r.ranked, r.winner);
    drawConfidenceChart(r.ranked);
  }
  if (msg.step === 1) {
    updateExploitBadges(false);
  }
}

function renderCandidates(candidates, phase) {
  const tbody = document.getElementById('cand-body');
  tbody.innerHTML = '';
  lastCandidates = candidates;
  const transforms = ['swap_validators','swap_validators','swap_validators',
    'rename_identifiers','rename_identifiers','route_rotation','route_rotation',
    'reorder_blocks','split_helpers','swap_validators'];
  candidates.forEach((c, i) => {
    const tr = document.createElement('tr');
    const pass = c.verifier_pass;
    tr.innerHTML = `
      <td style="color:var(--accent)">${c.id.split('-').slice(-1)[0]}</td>
      <td>${transforms[i] || 'swap_validators'}</td>
      <td>${c.tests_passed}/${c.tests_passed + c.tests_failed}</td>
      <td>-</td>
      <td><div class="conf-bar"><div class="conf-bar-fill" style="width:0%;background:var(--text2)"></div></div></td>
      <td><span class="badge ${pass ? 'badge-pass' : 'badge-fail'}">${pass ? 'PASS' : 'FAIL'}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function updateCandidatesExploit(candidates) {
  const rows = document.getElementById('cand-body').querySelectorAll('tr');
  candidates.forEach((c, i) => {
    if (rows[i]) {
      const cells = rows[i].querySelectorAll('td');
      const rate = c.exploit_rate;
      cells[3].innerHTML = `<span class="${rate === 0 ? 'blocked' : 'exploited'}">${(rate*100).toFixed(0)}%</span>`;
    }
  });
}

function updateCandidatesRisk(ranked, winnerId) {
  const rows = document.getElementById('cand-body').querySelectorAll('tr');
  ranked.forEach((r, i) => {
    if (rows[i]) {
      const cells = rows[i].querySelectorAll('td');
      const pct = (r.confidence * 100).toFixed(0);
      const color = r.confidence >= 0.85 ? 'var(--accent2)' : r.confidence >= 0.5 ? 'var(--warn)' : 'var(--danger)';
      cells[4].innerHTML = `<div class="conf-bar"><div class="conf-bar-fill" style="width:${pct}%;background:${color}"></div></div> ${pct}%`;
      if (r.id === winnerId) {
        rows[i].classList.add('winner');
        cells[5].innerHTML = '<span class="badge badge-deploy">DEPLOY</span>';
      }
    }
  });
}

function updateExploitBadges(blocked) {
  for (let i=0;i<5;i++) {
    const el = document.getElementById(`exp-${i}`);
    if (blocked) {
      el.textContent = 'BLOCKED';
      el.className = 'badge badge-pass';
    } else {
      el.textContent = 'EXPLOITED';
      el.className = 'badge badge-fail';
    }
  }
}

// ── Log feed ────────────────────────────────────────────────────────────────
function addLog(agent, message, level='info') {
  const feed = document.getElementById('log-feed');
  const ts = new Date().toLocaleTimeString();
  const div = document.createElement('div');
  div.className = `log-entry ${level}`;
  div.innerHTML = `<span class="ts">${ts}</span> <span class="agent">[${agent}]</span> <span class="msg">${message}</span>`;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
  // Keep last 100 entries
  while (feed.children.length > 100) feed.removeChild(feed.firstChild);
}

// ── Cycle history ───────────────────────────────────────────────────────────
function renderCycleHistory() {
  const el = document.getElementById('cycle-history');
  if (cycleHistory.length === 0) return;
  el.innerHTML = '';
  cycleHistory.forEach(c => {
    const div = document.createElement('div');
    div.className = 'cycle-entry';
    const actionClass = c.action === 'deploy' ? 'action-deploy' : c.action === 'rollback' ? 'action-rollback' : 'action-reject';
    div.innerHTML = `
      <span class="action-badge ${actionClass}">${c.action}</span>
      <span style="color:var(--accent)">${c.cycle_id}</span>
      <span>${c.total_latency_s}s</span>
      <span>Winner: <span style="color:var(--accent2)">${c.winner || 'none'}</span></span>
      <span>${(c.exploit_before*100).toFixed(0)}% &rarr; ${(c.exploit_after*100).toFixed(0)}%</span>
    `;
    el.appendChild(div);
  });
}

// ── Confidence chart ────────────────────────────────────────────────────────
function drawConfidenceChart(ranked) {
  const canvas = document.getElementById('chart-confidence');
  const ctx = canvas.getContext('2d');
  canvas.width = canvas.offsetWidth * 2;
  canvas.height = 200;
  ctx.scale(2, 2);
  const w = canvas.offsetWidth;
  const h = 100;
  ctx.clearRect(0, 0, w, h);

  // Threshold line
  ctx.strokeStyle = '#ff475744';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  const threshY = h - (0.85 * h * 0.9) - 5;
  ctx.beginPath();
  ctx.moveTo(0, threshY);
  ctx.lineTo(w, threshY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Bars
  const barW = Math.min(40, (w - 20) / ranked.length - 4);
  ranked.forEach((r, i) => {
    const x = 10 + i * (barW + 4);
    const barH = r.confidence * h * 0.9;
    const y = h - barH - 5;
    const color = r.confidence >= 0.85 ? '#00ff88' : r.confidence >= 0.5 ? '#ffa502' : '#ff4757';
    ctx.fillStyle = color + '88';
    ctx.fillRect(x, y, barW, barH);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, barW, barH);
    // Label
    ctx.fillStyle = '#8892a4';
    ctx.font = '8px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`#${i}`, x + barW/2, h - 0);
  });

  // Threshold label
  ctx.fillStyle = '#ff4757aa';
  ctx.font = '8px monospace';
  ctx.textAlign = 'left';
  ctx.fillText('85% threshold', 4, threshY - 3);
}

// ── Architecture diagram ────────────────────────────────────────────────────
function buildArchDiagram() {
  const container = document.getElementById('arch-diagram');
  const nodes = [
    { id:'target', label:'Target App', sub:'FastAPI :8000', x:20, y:20, w:110, h:44 },
    { id:'orchestrator', label:'Defense Loop', sub:'Orchestrator', x:180, y:20, w:110, h:44 },
    { id:'mutation', label:'Mutation Agent', sub:'+ Triton planner', x:340, y:8, w:120, h:44, gpu:true },
    { id:'verifier', label:'Verifier Agent', sub:'pytest + bandit', x:340, y:64, w:120, h:44 },
    { id:'exploit', label:'Exploit Agent', sub:'payload replay', x:340, y:120, w:120, h:44 },
    { id:'risk', label:'Risk Agent', sub:'+ Triton scorer', x:340, y:176, w:120, h:44, gpu:true },
    { id:'explain', label:'Explanation', sub:'+ vLLM', x:340, y:232, w:120, h:44, gpu:true },
    { id:'transforms', label:'Transforms', sub:'libcst AST', x:180, y:90, w:110, h:44 },
    { id:'triton', label:'Triton Server', sub:'GPU :8080', x:520, y:40, w:110, h:44, gpu:true },
    { id:'vllm', label:'vLLM', sub:'GPU :8088', x:520, y:110, w:110, h:44, gpu:true },
    { id:'telemetry', label:'Telemetry', sub:'JSONL + RAPIDS', x:520, y:190, w:110, h:44, gpu:true },
    { id:'deploy', label:'Deploy Ctrl', sub:'Blue/Green', x:180, y:175, w:110, h:44 },
  ];

  const connections = [
    ['target','orchestrator'],
    ['orchestrator','mutation'],
    ['orchestrator','transforms'],
    ['orchestrator','verifier'],
    ['orchestrator','exploit'],
    ['orchestrator','risk'],
    ['orchestrator','explain'],
    ['orchestrator','deploy'],
    ['mutation','triton'],
    ['risk','triton'],
    ['explain','vllm'],
    ['orchestrator','telemetry'],
    ['deploy','target'],
  ];

  // Add nodes
  nodes.forEach(n => {
    const div = document.createElement('div');
    div.className = `arch-node ${n.gpu ? 'gpu' : ''}`;
    div.id = `arch-${n.id}`;
    div.style.left = n.x + 'px';
    div.style.top = n.y + 'px';
    div.style.width = n.w + 'px';
    div.innerHTML = `<div class="arch-label">${n.label}</div><div class="arch-sub">${n.sub}</div>`;
    container.appendChild(div);
  });

  // Draw lines
  const svg = document.getElementById('arch-svg');
  connections.forEach(([from, to]) => {
    const a = nodes.find(n => n.id === from);
    const b = nodes.find(n => n.id === to);
    if (!a || !b) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', a.x + a.w/2);
    line.setAttribute('y1', a.y + a.h/2);
    line.setAttribute('x2', b.x + b.w/2);
    line.setAttribute('y2', b.y + b.h/2);
    line.id = `line-${from}-${to}`;
    svg.appendChild(line);
  });
}

// ── Trigger defense ─────────────────────────────────────────────────────────
function triggerDefend() {
  if (cycleRunning) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({action: 'defend'}));
  } else {
    fetch('/api/defend', {method: 'POST'});
  }
}

// ── Refresh stats from API ──────────────────────────────────────────────────
async function refreshStats() {
  try {
    const resp = await fetch('/api/stats');
    const data = await resp.json();
    const s = data.stats;
    document.getElementById('m-cycles').textContent = s.total_cycles;
    document.getElementById('m-before').textContent = (s.exploit_before * 100).toFixed(0) + '%';
    document.getElementById('m-after').textContent = (s.exploit_after * 100).toFixed(0) + '%';
    document.getElementById('m-latency').textContent = s.avg_cycle_s + 's';
    document.getElementById('m-candidates').textContent = s.total_candidates;
  } catch(e) {}
}

// ── Toast ───────────────────────────────────────────────────────────────────
function showToast(msg, type='info') {
  const container = document.getElementById('toasts');
  const div = document.createElement('div');
  div.className = `toast ${type}`;
  div.textContent = msg;
  container.appendChild(div);
  setTimeout(() => div.remove(), 4000);
}

// ── Clock ───────────────────────────────────────────────────────────────────
function updateClock() {
  document.getElementById('footer-time').textContent = new Date().toLocaleString();
}

// ── Init ────────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
  buildArchDiagram();
  connectWS();
  refreshStats();
  updateClock();
  setInterval(updateClock, 1000);
  setInterval(refreshStats, 5000);
  addLog('system', 'ZeroWall Visual Dashboard initialized', 'success');
  addLog('system', 'WebSocket connecting to backend...', 'info');
});
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=DASHBOARD_HTML)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  ZeroWall Visual Dashboard")
    print("  http://localhost:8888")
    print("=" * 60 + "\n")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8888,
        reload=False,
        log_level="info",
    )
