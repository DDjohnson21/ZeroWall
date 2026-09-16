# 🛡️ ZeroWall — AI-Guided Adaptive Self-Hardening on NVIDIA DGX Spark

> [!IMPORTANT]
> **Hackathon proof of concept — not production security software.**
> ZeroWall demonstrates a safe, local adaptive-hardening workflow designed for NVIDIA DGX Spark, with CPU fallbacks for development. Its bundled vulnerabilities, attacks, and deployments target the included simulated FastAPI application. Do not expose the demo services to untrusted networks or use them to protect production systems.

## Why I Built ZeroWall

ZeroWall started with a simple question: what if defenders could adapt software
faster than attackers could exploit it?

Most security response is reactive: detect an issue, patch it, redeploy, and
verify that nothing broke. The longer-term vision for ZeroWall is a continuous
adaptive-defense model **(currently initiated by an operator or mock-alert
trigger for demonstration and testing purposes)**: generate constrained
defensive variants, test them, replay known exploits, and publish only a
candidate that passes live verification.

Inspired by moving target defense, I used locally trained models and NVIDIA DGX
Spark to explore whether learned policies could rank vetted security
transformations from observed outcomes. The models do not generate arbitrary
patches or replace security rules; they select among registered safeguards while
tests, acceptance gates, and rollback remain in control.

---

## 📋 Table of Contents
- [Why I Built ZeroWall](#why-i-built-zerowall)
- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Architecture](#architecture)
- [NVIDIA Stack Usage](#nvidia-stack)
- [NVIDIA Requirement Mapping](#requirement-mapping)
- [Demo Instructions](#demo)
- [Benchmarking](#benchmark)
- [Screenshot Checklist](#screenshots)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Overview

ZeroWall is an **MTD-inspired, multi-agent adaptive-hardening proof of concept** designed for NVIDIA DGX Spark. It can also run in CPU development mode through deterministic, NumPy, and pandas fallbacks. Models select from registered transformations; they never write arbitrary source code.

When an operator or mock alert supplies attack context, ZeroWall:
1. Generates a configurable set of **benign-contract-preserving mutation candidates** (10 by default)
2. **Runs tests** to reject candidates that break the target contract
3. **Replays known exploits** against passing candidates in parallel
4. **Scores risk** through Triton when available, with a local weighted-formula fallback
5. **Deploys the winning variant** and rolls back if post-deploy checks fail

Candidates are published only after verification and scoring. The live gate confirms that the managed worker loaded the exact artifact, preserves representative normal traffic, and blocks the predefined replay set before accepting the deployment.

---

## Problem Statement

Static defenses fail against adaptive attackers and manual patch cycles are slow. ZeroWall demonstrates a constrained response loop: receive an alert, propose registered variants, test, replay, score, publish, verify live, and automatically restore the previous artifact on failure.

---

## Architecture

```text
┌──────────────────────┐       attack context       ┌────────────────────────┐
│ Operator / Mock IDS  │ ─────────────────────────► │ ZeroWall Core API / CLI│
│ /defend /simulate... │                            └───────────┬────────────┘
└──────────────────────┘                                        │
                                                                ▼
┌────────────────────── NVIDIA DGX Spark or local development host ──────────────────────┐
│                                                                                        │
│  ┌────────────────────────── ZeroWall Core Engine ───────────────────────────────────┐  │
│  │                                                                                  │  │
│  │  ┌──────────────────────── Defense Loop Orchestrator ──────────────────────────┐  │  │
│  │  │  1. Baseline replay       4. Verifier Agent: pytest + optional Bandit      │  │  │
│  │  │  2. Mutation Agent        5. Exploit Agent: isolated HTTP replay           │  │  │
│  │  │  3. Transform Engine      6. Risk Agent → deploy or reject                 │  │  │
│  │  │                             Explanation Agent → cycle summary              │  │  │
│  │  └──────────────┬──────────────────────┬──────────────────────┬───────────────┘  │  │
│  │                 │                      │                      │                  │  │
│  │                 ▼                      ▼                      ▼                  │  │
│  │  ┌────────────────────────┐  ┌────────────────────┐  ┌──────────────────────┐   │  │
│  │  │ Planner cascade        │  │ Candidate workers  │  │ Deployment Controller│   │  │
│  │  │ • NeMo adapter*        │  │ • temporary dirs   │  │ • immutable versions │   │  │
│  │  │ • learned NumPy policy │  │ • local processes  │  │ • atomic active slot │   │  │
│  │  │ • Triton policy*       │  │ • predefined replay│  │ • verified rollback  │   │  │
│  │  │ • deterministic fallback│ └────────────────────┘  └──────────┬───────────┘   │  │
│  │  └────────────────────────┘                                      │               │  │
│  │                                                                  ▼               │  │
│  │  ┌───────────────────┐  ┌───────────────────┐       ┌────────────────────────┐   │  │
│  │  │ Triton Server*    │  │ vLLM Server*      │       │ Versioned deploy volume│   │  │
│  │  │ planner + risk    │  │ explain + NeMo    │       └───────────┬────────────┘   │  │
│  │  └───────────────────┘  └───────────────────┘                   │                │  │
│  └──────────────────────────────────────────────────────────────────┼────────────────┘  │
│                                                                     ▼                   │
│  ┌──────────────────────┐   predefined HTTP   ┌─────────────────────────────────────┐   │
│  │ Seed script / replay │ ──────────────────► │ Managed FastAPI target              │   │
│  └──────────────────────┘                     │ vulnerable baseline → accepted build│   │
│                                               └─────────────────────────────────────┘   │
│                                                                                        │
│  JSONL telemetry ──► cuDF* or pandas analytics ──► Streamlit + Next.js dashboards      │
└────────────────────────────────────────────────────────────────────────────────────────┘

* Optional accelerated component; the defense loop has a local fallback.
```

### What happens during a defense cycle

```text
┌──────────────────────────┐
│ Operator or mock IDS     │
│ /defend  /simulate-alert │
└────────────┬─────────────┘
             │ attack context
             ▼
┌────────────────────────────────────────────────────────────────────┐
│ ZeroWall Defense Loop                                              │
│                                                                    │
│  1. Replay baseline exploits against the managed FastAPI target    │
│  2. Rank transforms: NeMo adapter* → NumPy → Triton* → fallback    │
│  3. Build registered CST/validator variants (10 by default)        │
│  4. Run pytest and optional Bandit checks in parallel              │
│  5. Boot passing variants in temporary local subprocesses          │
│  6. Replay predefined HTTP payloads and calculate risk             │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
          no safe winner                 safe winner
                │                             │
                ▼                             ▼
      ┌──────────────────┐       ┌──────────────────────────┐
      │ Reject candidates│       │ Versioned atomic publish │
      │ Target unchanged │       └────────────┬─────────────┘
      └──────────────────┘                    │ managed reload
                                              ▼
                                 ┌──────────────────────────┐
                                 │ Live acceptance gate     │
                                 │ • exact source hash      │
                                 │ • normal-request smoke   │
                                 │ • exploit replay         │
                                 └────────────┬─────────────┘
                                              │
                                  ┌───────────┴───────────┐
                                  │                       │
                                pass                    fail
                                  │                       │
                                  ▼                       ▼
                         ┌────────────────┐      ┌─────────────────┐
                         │ Confirm deploy │      │ Atomic rollback │
                         └───────┬────────┘      └────────┬────────┘
                                 └────────────┬───────────┘
                                              ▼
                           JSONL telemetry → cuDF*/pandas
                                      → dashboards

* Optional accelerated component; a local fallback is available.
```

---

## NVIDIA Stack Usage <a name="nvidia-stack"></a>

### 1. 🖥️ Triton Inference Server
**What it provides:** Two small, dynamically batched policy endpoints:
- `mutation-planner` — a planner-cascade fallback for ranking transform types
- `risk-scorer` — candidate confidence scoring when Triton is healthy

The planner cascade tries an optional NeMo adapter, the checked-in NumPy policy, Triton, and finally a deterministic fallback. Risk scoring also falls back to a local formula, so CPU development runs do not require Triton.

**Evidence in code:**
- `inference/triton-model-repo/mutation-planner/config.pbtxt` + `1/model.py`
- `inference/triton-model-repo/risk-scorer/config.pbtxt` + `1/model.py`
- `inference/clients/triton_client.py` — Triton HTTP v2 client
- Planner- and risk-stage latencies are recorded in telemetry and displayed on the dashboards

**Docker service:** `docker-compose.yml` → service `triton`

### 2. ⚡ vLLM (Local LLM Runtime — TRT-LLM upgrade path)
**What it provides:** Optional local GPU LLM inference for:
- NeMo/LoRA transform ranking when a trained adapter is present
- Explanation Agent judge-facing summaries, with a template fallback

**Why vLLM:** The included service exposes an OpenAI-compatible API and runs the configured local model. The clients are isolated behind a thin interface; another runtime, including a suitably configured TRT-LLM OpenAI-compatible server, can replace it. The repository does not include a trained NeMo adapter, so the default cascade skips that tier.

**Evidence in code:**
- `inference/clients/vllm_client.py`
- `core/agents/explanation_agent.py` — calls vLLM for generation
- LLM availability is reported by the CLI and operator dashboard

**Docker service:** `docker-compose.yml` → service `vllm`

### 3. 🌊 RAPIDS cuDF
**What it provides when installed:** GPU-accelerated telemetry analytics:
- Exploit success rate before vs after defense cycles
- Defense cycle latency statistics (mean, p95)
- Candidate evaluation counts
- Rolling exploit rate trends for dashboard
- Inference latency breakdown per agent

**Evidence in code:**
- `core/telemetry/rapids_analytics.py` — cuDF path with pandas fallback
- Uses `cudf.DataFrame` when cuDF is installed and `RAPIDS_ENABLED=true`
- Backend shown in dashboard ("cuDF-GPU" vs "pandas-CPU")
- Analytics output feeds real-time Streamlit charts

The portable `requirements.core.txt` and core Docker image install pandas, not
cuDF. Use a RAPIDS-compatible DGX environment to activate the GPU path; otherwise
the same analytics run through pandas.

---

## NVIDIA Requirement Mapping <a name="requirement-mapping"></a>

### Why DGX Spark is the accelerated demo path
| Reason | Detail |
|--------|--------|
| Triton model serving | Reproducible model lifecycle and dynamic batching; the current tiny NumPy policies run on CPU |
| vLLM LLM inference | The included vLLM container is configured for NVIDIA GPU execution |
| RAPIDS cuDF | Uses CUDA for analytics when installed, with a pandas fallback |
| Local LLM reasoning | vLLM runs the optional explanation/planner LLM locally on the DGX GPU |
| Parallel evaluation | Candidate tests and isolated HTTP replay benefit from DGX capacity but also run in CPU development mode |

### NVIDIA Components Integrated
| Component | Role | Evidence |
|-----------|------|----------|
| Triton Inference Server | Multi-model serving | `inference/triton-model-repo/` |
| vLLM | Local LLM inference (TRT-LLM path) | `inference/clients/vllm_client.py` |
| RAPIDS cuDF | Optional GPU DataFrame analytics | `core/telemetry/rapids_analytics.py` |

### Why this is an Advanced AI System
- **Multi-agent pipeline**: 5 specialized agents (Mutation, Exploit, Verifier, Risk, Explanation)
- **Not a chatbot**: No human in the loop during defense cycle
- **Autonomous decision-making**: Risk Agent recommends deploy/reject; the orchestrator rolls back a published candidate when its live gate fails
- **Constrained code changes**: Models rank registered deterministic CST transforms and validator guards
- **Variant generation**: Candidate layouts vary by transform and seed, although the selected winner may repeat

---

## Demo Instructions <a name="demo"></a>

### Prerequisites
```bash
# Copy configuration; edit only the services you intend to enable.
cp .env.example .env
# Optional examples: VLLM_MODEL, VLLM_TP_SIZE, and HF_TOKEN for gated models.

# For standalone Python development:
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.core.txt
pip install -r apps/target-fastapi/requirements.txt
```

### Full Docker Demo (DGX Spark)
```bash
# Start all services
docker compose up -d --build

# Watch service health; model startup time depends on the selected vLLM model.
docker compose ps

# Run the demo flow
bash scripts/run_demo.sh

# Visit the Streamlit dashboard at http://localhost:8501
# or the Next.js operator dashboard at http://localhost:3000
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
# Then type either /simulate-alert (which triggers defense) or /defend
# Then type: /status

# 5. Open dashboard
streamlit run dashboard/streamlit_app.py
```

### Verification
```bash
# Includes target contracts, every transform, real live hot-swap, telemetry,
# and an injected post-deploy failure that must roll back.
pytest -q
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

## Benchmarking <a name="benchmark"></a>

Run the benchmark against the active local target:

```bash
bash scripts/run_benchmark.sh
# Or: python -m core.orchestrator.openclaw_cli benchmark --burst-size 50 --with-defense
```

**Output files:**
- `artifacts/benchmark/benchmark_summary.json`
- `artifacts/benchmark/benchmark_summary.csv`
- Rich terminal table printed automatically

The report includes request throughput, average and p95 latency, exploit success
before and after defense, total defense-cycle time, retained candidate count,
planner/risk-stage latency, and the active analytics backend. Candidate count can
be lower than the configured value when duplicate or invalid variants are removed.
Results depend on hardware, model, concurrency, and warm-up state; this repository
does not claim canonical DGX Spark performance numbers.

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
│   ├── test_app.py             # Target contract tests used by the verifier
│   ├── requirements.txt
│   └── Dockerfile
├── core/
│   ├── agents/                 # 5 ZeroWall agents
│   │   ├── mutation_agent.py   # Generates candidate plans (10 by default)
│   │   ├── exploit_agent.py    # Replays known attack payloads
│   │   ├── verifier_agent.py   # Runs pytest + bandit
│   │   ├── risk_agent.py       # Scores + recommends action
│   │   └── explanation_agent.py # Judge-facing summaries
│   ├── transforms/             # Deterministic CST transforms and guards
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
│   │   └── controller.py       # Versioned atomic deploy + rollback
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
│       ├── triton_client.py       # Triton HTTP v2 client
│       ├── vllm_client.py         # vLLM completion client
│       └── nemo_planner_client.py # Optional adapter planner client
├── dashboard/
│   └── streamlit_app.py        # Judge-facing metrics dashboard
├── frontend/                    # Next.js operator dashboard
├── scripts/
│   ├── run_demo.sh             # End-to-end demo flow
│   ├── run_benchmark.sh        # Benchmark runner
│   └── seed_attack.sh          # Seed known exploit payloads
├── tests/                       # Transform and live deployment integration tests
├── docker-compose.yml          # Target, inference, core, and two dashboards
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
> - Simulated file, command, and query behavior uses in-memory fixtures rather than host resources
> - Bundled exploit commands default to the local demo target and perform no network scanning
> - No real offensive tooling is included in this project
> - The deploy controller only writes the local, versioned demo deployment slot
> - All "exploits" are pre-defined, non-harmful HTTP requests that trigger simulated response patterns

The CLI accepts a configurable target URL; do not point it at systems you do not own and control. This project demonstrates an *MTD-inspired adaptive-hardening pipeline* and is not a general-purpose detector or autonomous patcher. See [SECURITY.md](SECURITY.md) for the full boundary.

---

## License

ZeroWall is licensed under the [Apache License 2.0](LICENSE).
