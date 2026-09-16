# 🛡️ ZeroWall — AI-Guided Adaptive Self-Hardening on NVIDIA DGX Spark

> [!IMPORTANT]
> **Hackathon proof of concept — not production security software.**
> ZeroWall demonstrates a safe, local adaptive-hardening workflow on NVIDIA DGX Spark. Its vulnerabilities, attacks, and deployments target only the included simulated FastAPI application. Do not expose the demo services to untrusted networks or use them to protect production systems.

---

## 📋 Table of Contents
- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Architecture](#architecture)
- [NVIDIA Stack Usage](#nvidia-stack)
- [NVIDIA Requirement Mapping](#requirement-mapping)
- [Demo Instructions](#demo)
- [Benchmark Evidence](#benchmark)
- [Screenshot Checklist](#screenshots)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Overview

ZeroWall is an **MTD-inspired, multi-agent adaptive self-hardening system** that runs entirely on NVIDIA DGX Spark. It selects from audited transformations; it never lets a model write arbitrary source code.

When an attack is detected, ZeroWall:
1. Generates **8–20 behavior-preserving code mutation candidates** via a safe deterministic transformer
2. **Replays known exploits** against each candidate in parallel
3. **Runs test suites** to verify functional correctness is preserved
4. **Scores risk** using a weighted confidence model (served via Triton)
5. **Deploys the winning variant** and rolls back if post-deploy checks fail

Every published version combines an audited security guard with a distinct structural layout. The live gate proves the new worker loaded the exact artifact, preserves normal traffic, and blocks replayed attacks before the deployment is accepted.

---

## Problem Statement

Static defenses fail against adaptive attackers and manual patch cycles are slow. ZeroWall demonstrates a constrained response loop: detect, propose audited variants, test, attack, score, publish, verify live, and automatically restore the previous artifact on failure.

---

## Architecture

```
                         ┌──────────────────────────────────────────────────┐
                         │              NVIDIA DGX Spark                    │
                         │                                                  │
  ┌──────────┐           │  ┌─────────────────────────────────────────────┐ │
  │ Attacker │──exploit──►  │         ZeroWall Core Engine                │ │
  └──────────┘           │  │                                             │ │
                         │  │  ┌──────────────────────────────────────┐   │ │
  ┌──────────────┐        │  │  │    Defense Loop Orchestrator         │   │ │
  │ OpenClaw CLI │──────►  │  │  │  (defense_loop.py)                 │   │ │
  │ /defend      │        │  │  │  1. Mutation Agent ─────────────────┼──►│ │
  │ /replay      │        │  │  │  2. Safe Transform Engine (libcst)  │   │ │
  │ /status      │        │  │  │  3. Verifier Agent (pytest+bandit)  │   │ │
  │ /benchmark   │        │  │  │  4. Exploit Agent (HTTP replay)     │   │ │
  │ /alert       │        │  │  │  5. Risk Agent ─────────────────────┼──►│ │
  └──────────────┘        │  │  │  6. Explanation Agent               │   │ │
                         │  │  └──────────────────────────────────────┘   │ │
                         │  │                                             │ │
  ┌──────────────┐        │  │  ┌──────────────┐  ┌───────────────────┐  │ │
  │  Streamlit   │◄───────├──┤  │    Triton    │  │  vLLM Server      │  │ │
  │  Dashboard   │        │  │  │  Inference   │  │ (local LLM         │  │ │
  └──────────────┘        │  │  │  Server      │  │  reasoning)        │  │ │
                         │  │  │  • mutation- │  │                   │  │ │
  ┌──────────────┐        │  │  │    planner   │  └───────────────────┘  │ │
  │    RAPIDS    │◄───────├──┤  │  • risk-     │                         │ │
  │  Analytics   │        │  │  │    scorer    │  ┌───────────────────┐  │ │
  │  (cuDF GPU)  │        │  │  └──────────────┘  │  Deploy Controller│  │ │
  └──────────────┘        │  │                    │  (blue/green swap) │  │ │
                         │  │                    └───────────────────┘  │ │
                         │  └─────────────────────────────────────────┘ │
                         │                                                │
                         │  ┌──────────────────────────────────────────┐  │
                         │  │    Target FastAPI App (attack surface)   │  │
                         │  │    v1: vulnerable → vN: hardened         │  │
                         │  └──────────────────────────────────────────┘  │
                         └──────────────────────────────────────────────────┘
```

---

## NVIDIA Stack Usage <a name="nvidia-stack"></a>

### 1. 🖥️ Triton Inference Server
**What we use it for:** Serving two small, dynamically batched policy endpoints:
- `mutation-planner` — selects transform types for each defense cycle
- `risk-scorer` — scores candidate confidence with batched inference

**Evidence in code:**
- `inference/triton-model-repo/mutation-planner/config.pbtxt` + `1/model.py`
- `inference/triton-model-repo/risk-scorer/config.pbtxt` + `1/model.py`
- `inference/clients/triton_client.py` — all agent calls route through Triton HTTP API
- Triton inference latency logged in telemetry and displayed on dashboard

**Docker service:** `docker-compose.yml` → service `triton`

### 2. ⚡ vLLM (Local LLM Runtime — TRT-LLM upgrade path)
**What we use it for:** Local GPU LLM inference for:
- Mutation Agent narrative reasoning
- Explanation Agent judge-facing summaries

**Why vLLM and not TRT-LLM directly:** vLLM ships with an OpenAI-compatible API that integrates in minutes. The system is designed with a thin client layer (`inference/clients/vllm_client.py`) so swapping to TRT-LLM requires only pointing the base URL at a TRT-LLM server — both expose the same API. On a production DGX Spark with available time, TRT-LLM provides higher token/s throughput.

**Evidence in code:**
- `inference/clients/vllm_client.py`
- `core/agents/explanation_agent.py` — calls vLLM for generation
- Per-call latency logged and shown in benchmark output

**Docker service:** `docker-compose.yml` → service `vllm`

### 3. 🌊 RAPIDS cuDF
**What we use it for:** GPU-accelerated telemetry analytics:
- Exploit success rate before vs after defense cycles
- Defense cycle latency statistics (mean, p95)
- Candidate evaluation counts
- Rolling exploit rate trends for dashboard
- Inference latency breakdown per agent

**Evidence in code:**
- `core/telemetry/rapids_analytics.py` — primary cuDF path with pandas fallback
- Uses `cudf.DataFrame` for all analytics operations on DGX Spark
- Backend shown in dashboard ("cuDF-GPU" vs "pandas-CPU")
- Analytics output feeds real-time Streamlit charts

---

## NVIDIA Requirement Mapping <a name="requirement-mapping"></a>

### Why DGX Spark is the production-performance path
| Reason | Detail |
|--------|--------|
| Triton model serving | Reproducible model lifecycle and dynamic batching; the current tiny NumPy policies run on CPU |
| vLLM LLM inference | Requires GPU; float16 models won't fit in CPU RAM |
| RAPIDS cuDF | Uses CUDA for production analytics, with a pandas development fallback |
| Local LLM reasoning | vLLM runs the optional explanation/planner LLM locally on the DGX GPU |
| Parallel evaluation | Candidate tests and isolated HTTP replay benefit from DGX capacity but also run in CPU development mode |

### NVIDIA Components Used
| Component | Role | Evidence |
|-----------|------|----------|
| Triton Inference Server | Multi-model serving | `inference/triton-model-repo/` |
| vLLM | Local LLM inference (TRT-LLM path) | `inference/clients/vllm_client.py` |
| RAPIDS cuDF | GPU DataFrame analytics | `core/telemetry/rapids_analytics.py` |

### Why this is an Advanced AI System
- **Multi-agent pipeline**: 5 specialized agents (Mutation, Exploit, Verifier, Risk, Explanation)
- **Not a chatbot**: No human in the loop during defense cycle
- **Autonomous decision-making**: Risk Agent recommends deploy/reject/rollback
- **Safe code generation**: Deterministic AST transforms controlled by AI model output
- **Continuous adaptation**: Each cycle produces a different hardened variant

---

## Demo Instructions <a name="demo"></a>

### Prerequisites
```bash
# Clone and setup
cp .env.example .env
# Edit .env: set HF_TOKEN, VLLM_MODEL, GPU counts

# Install local deps (for running outside Docker)
pip install -r requirements.core.txt
cd apps/target-fastapi && pip install -r requirements.txt && cd ../..
```

### Full Docker Demo (DGX Spark)
```bash
# Start all services
docker-compose up -d

# Wait for health checks (Triton takes ~30s)
docker-compose ps

# Run the demo flow
bash scripts/run_demo.sh

# Open dashboard
open http://localhost:8501
```

### Step-by-Step Manual Demo
```bash
# 1. Start the managed target (standalone, no Docker)
# This serves artifacts/deploy/active/main.py and reloads atomic deployments.
bash scripts/run_target.sh &

# 2. Verify normal request
curl http://localhost:8000/health

# 3. Seed exploit attack
bash scripts/seed_attack.sh

# 4. Open OpenClaw CLI (interactive)
python -m core.orchestrator.openclaw_cli interactive
# Then type: /simulate-alert
# Then type: /defend
# Then type: /status

# 5. Open dashboard
streamlit run dashboard/streamlit_app.py
```

### Verification
```bash
# Includes target contracts, every transform, real live hot-swap, telemetry,
# and an injected post-deploy failure that must roll back.
pytest -q
# Expected: 36 passed
```

### OpenClaw Commands Reference
| Command | Description |
|---------|-------------|
| `/defend` | Start defense cycle |
| `/replay` | Replay exploit against active version |
| `/status` | Show system status |
| `/benchmark` | Run burst benchmark |
| `/simulate-alert` | Inject mock IDS alert |

---

## Benchmark Evidence <a name="benchmark"></a>

Run the benchmark to produce hard numbers:

```bash
bash scripts/run_benchmark.sh
# Or: python -m core.orchestrator.openclaw_cli benchmark --burst-size 50 --with-defense
```

**Output files:**
- `artifacts/benchmark/benchmark_summary.json`
- `artifacts/benchmark/benchmark_summary.csv`
- Rich terminal table printed automatically

**Expected metrics on DGX Spark:**

| Metric | Expected (DGX Spark) | Notes |
|--------|----------------------|-------|
| Mutation candidates / cycle | 10 | Configurable 8–20 |
| Defense cycle latency | 5–15s | Depends on test suite size |
| Exploit replays / cycle | 10×5 = 50 | 10 candidates × 5 payloads |
| Triton inference latency | <50ms | Per model call |
| vLLM inference latency | <2s | Explanation generation |
| Burst throughput | 100+ rps | With cuDF analytics |
| Exploit success rate delta | >80% reduction | Vulnerable → hardened |

---

## Screenshot Checklist <a name="screenshots"></a>

For live demo evidence, capture and place in `artifacts/`:

- [ ] `artifacts/gpu_screenshot.png` — DGX dashboard GPU utilization during benchmark
- [ ] `artifacts/dashboard_screenshot.png` — Streamlit dashboard with real data
- [ ] `artifacts/benchmark_terminal.png` — Rich terminal benchmark table
- [ ] `artifacts/openclaw_defend.png` — OpenClaw CLI defense cycle output
- [ ] `artifacts/exploit_before.png` — Exploit success before defense cycle
- [ ] `artifacts/exploit_after.png` — Exploit blocked after deployment

---

## Project Structure

```
/ZeroWall
├── apps/target-fastapi/        # Vulnerable demo FastAPI app
│   ├── main.py                 # 3 simulated vulnerable endpoints
│   ├── managed_runner.py       # Serves/reloads the managed deployment slot
│   ├── test_app.py             # 25+ unit tests (verifier uses these)
│   ├── requirements.txt
│   └── Dockerfile
├── core/
│   ├── agents/                 # 5 ZeroWall agents
│   │   ├── mutation_agent.py   # Generates 8–20 candidate plans
│   │   ├── exploit_agent.py    # Replays known attack payloads
│   │   ├── verifier_agent.py   # Runs pytest + bandit
│   │   ├── risk_agent.py       # Scores + recommends action
│   │   └── explanation_agent.py # Judge-facing summaries
│   ├── transforms/             # Safe deterministic AST transforms
│   │   ├── base.py             # Transform registry
│   │   ├── rename_identifiers.py
│   │   ├── reorder_blocks.py
│   │   ├── split_helpers.py
│   │   ├── swap_validators.py  # PRIMARY security hardening transform
│   │   └── route_rotation.py
│   ├── orchestrator/
│   │   ├── defense_loop.py     # Main multi-agent coordinator
│   │   └── openclaw_cli.py     # OpenClaw command interface
│   ├── deploy/
│   │   └── controller.py       # Blue/green deploy + rollback
│   ├── telemetry/
│   │   ├── collector.py        # Event collection → JSONL
│   │   └── rapids_analytics.py # cuDF GPU analytics
│   └── benchmark/
│       └── burst_sim.py        # Burst attack benchmark suite
├── inference/
│   ├── triton-model-repo/      # Triton model repository
│   │   ├── mutation-planner/   # Transform type selector model
│   │   └── risk-scorer/        # Candidate risk scoring model
│   └── clients/
│       ├── triton_client.py    # Triton HTTP v2 client
│       └── vllm_client.py      # vLLM OpenAI-compatible client
├── dashboard/
│   └── streamlit_app.py        # Judge-facing metrics dashboard
├── scripts/
│   ├── run_demo.sh             # End-to-end demo flow
│   ├── run_benchmark.sh        # Benchmark runner
│   └── seed_attack.sh          # Seed known exploit payloads
├── docker-compose.yml          # All services: target, triton, vllm, core, dashboard
├── Dockerfile.core             # ZeroWall core engine container
├── requirements.core.txt
└── .env.example
```

---

## Safety Disclaimer <a name="disclaimer"></a>

See [SECURITY.md](SECURITY.md) for safe-testing boundaries and private vulnerability reporting.

> ⚠️ **HACKATHON SAFETY NOTICE**
>
> ZeroWall is built for safe, controlled demonstration purposes only.
>
> - The "vulnerable" endpoints do NOT expose real system resources, execute real commands, or perform any harmful operations
> - All simulated vulnerabilities are sandboxed in an in-memory dictionary
> - Exploit payloads target ONLY the local demo FastAPI container — no external network probing
> - No real offensive tooling is included in this project
> - The deploy controller only writes the local, versioned demo deployment slot
> - All "exploits" are pre-defined, non-harmful HTTP requests that trigger simulated response patterns

This project demonstrates an *MTD-inspired adaptive hardening pipeline*; it is not a general-purpose autonomous patcher. Real deployment would use actual vulnerability detection, but safety is the top priority for this demonstration.

---

## License

ZeroWall is licensed under the [Apache License 2.0](LICENSE).
