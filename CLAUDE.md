# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ZeroWall is a multi-agent AI Moving Target Defense (MTD) system built for the NVIDIA DGX Spark hackathon. When an attack is detected, it generates behavior-preserving code mutation candidates, replays known exploits against each, verifies functional correctness with tests, scores risk, and deploys the winning hardened variant. The intended runtime is a CUDA/GPU DGX Spark box; CPU-only development works via fallbacks (pandas instead of cuDF, mock inference clients).

**Safety:** All "vulnerabilities," exploits, and deploys are simulated and target only the local demo FastAPI app (in-memory state, predefined non-harmful HTTP payloads). There is no real offensive tooling. Preserve this property when editing the target app or exploit agent.

## Commands

```bash
# Install (CPU dev)
pip install -r requirements.core.txt
cd apps/target-fastapi && pip install -r requirements.txt && cd ../..

# Run the target app (the attack surface) standalone
cd apps/target-fastapi && uvicorn main:app --port 8000

# Target app tests — these are the SAME tests the Verifier Agent runs per candidate
cd apps/target-fastapi && pytest                    # all tests
cd apps/target-fastapi && pytest test_app.py::test_name   # single test

# OpenClaw CLI (typer app) — main control surface
python -m core.orchestrator.openclaw_cli interactive   # interactive prompt: /defend /replay /status /benchmark /simulate-alert
python -m core.orchestrator.openclaw_cli defend --endpoint "/data" --payload-type "path-traversal"
python -m core.orchestrator.openclaw_cli benchmark --burst-size 50 --with-defense

# Dashboard
streamlit run dashboard/streamlit_app.py            # http://localhost:8501

# Scripted flows
bash scripts/run_demo.sh        # end-to-end demo (expects target app running on :8000)
bash scripts/run_benchmark.sh
bash scripts/seed_attack.sh

# Full GPU stack
docker-compose up -d            # services: target-app, triton, vllm, zerowall-core, dashboard
```

Default ports: target `8000`, Triton HTTP `8080`/gRPC `8081`/metrics `8082`, vLLM `8088`, dashboard `8501`, OpenClaw `9000`. Most are overridable via env vars (see `.env.example`; copy to `.env`).

## Architecture

The system is a **synchronous-entry / async-internal defense pipeline**. `core/orchestrator/defense_loop.py` (`DefenseLoop`) is the coordinator — read it first; it wires every other component together. `run_defense_cycle()` is sync and wraps `asyncio.run(_async_defense_cycle())`. One cycle:

1. **Baseline** — Exploit Agent replays payloads against current active source to measure the "before" exploit rate.
2. **Mutation Agent** (`core/agents/mutation_agent.py`) — asks Triton's `mutation-planner` model which transform types to use, emits N `MutationPlan` candidates (default 10, configurable 8–20 via `MUTATION_CANDIDATE_COUNT`).
3. **Apply transforms** — each plan runs through the safe transform engine to produce mutated source.
4. **Verifier Agent** (`core/agents/verifier_agent.py`) — runs in a thread pool (`_parallel_verify`) because pytest is subprocess-based; runs the target app's pytest suite + optional bandit against each candidate.
5. **Exploit Agent** (`core/agents/exploit_agent.py`) — async HTTP replay (`_parallel_exploit`) on passing candidates only; a candidate "blocks" if `exploit_success_rate < 0.5`.
6. **Risk Agent** (`core/agents/risk_agent.py`) — uses Triton's `risk-scorer` to pick a winner and recommend deploy/reject/rollback.
7. **Explanation Agent** (`core/agents/explanation_agent.py`) — calls vLLM for a human-facing summary.

Per-step latencies and counts are recorded to the Telemetry Collector throughout.

### Safe transform engine — the core safety invariant
`core/transforms/base.py` holds a registry (`register_transform` decorator → `_TRANSFORM_REGISTRY`, keyed by `TransformType`). **The AI model only selects the transform TYPE and high-level params; actual code edits are made by deterministic libcst-based transformers** that are behavior-preserving by construction. There is no free-form AI code generation. When adding a transform: subclass `BaseTransformer`, set `name` to a `TransformType`, decorate with `@register_transform`, and add an import line to the "Auto-register transforms" block in `defense_loop.py` (transforms self-register only when their module is imported). `swap_validators.py` is the primary security-hardening transform.

### Inference clients (the NVIDIA boundary)
`inference/clients/triton_client.py` (Triton HTTP v2) and `inference/clients/vllm_client.py` (OpenAI-compatible) are thin client layers — all GPU inference routes through them. The vLLM client is deliberately swappable to TRT-LLM by changing the base URL. Triton models live in `inference/triton-model-repo/{mutation-planner,risk-scorer}/` (each has `config.pbtxt` + `1/model.py`). Agents take a client instance via constructor injection, so they can be tested against mocks.

### Telemetry & analytics
`core/telemetry/collector.py` writes events to JSONL (`telemetry_data/telemetry.jsonl`). `core/telemetry/rapids_analytics.py` is the **cuDF-on-GPU path with a pandas-CPU fallback** — gated by `RAPIDS_ENABLED`; the active backend ("cuDF-GPU" vs "pandas-CPU") surfaces on the dashboard. Keep both code paths working.

### Shared types
`core/models.py` defines the data contracts (`DefenseCycle`, `CandidateResult`, `MutationPlan`, `TransformType`, `CandidateStatus`, etc.) passed between every stage. Changes here ripple across agents, transforms, and the orchestrator.

## Conventions

- Source layout assumes module execution from the repo root (`python -m core.orchestrator...`); paths like the target app source are resolved relative to file location (`Path(__file__).parent...`), not CWD.
- The target app's `test_app.py` is dual-purpose: it's the app's own test suite AND the correctness oracle the Verifier Agent runs against every mutation candidate. Don't weaken it casually.
- PRs: the `.cursor/commands/pr.md` convention is to always use the GitHub CLI (`gh`) with a descriptive title, committing first if needed.
