#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZeroWall Benchmark Script
# Runs burst benchmark and outputs performance evidence
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

TARGET_URL="${TARGET_URL:-http://localhost:8000}"
BURST_SIZE="${BURST_SIZE:-50}"
CONCURRENCY="${CONCURRENCY:-8}"

echo "🔥 ZeroWall Benchmark Mode"
echo "Target: ${TARGET_URL}"
echo "Burst: ${BURST_SIZE} requests | Concurrency: ${CONCURRENCY}"
echo ""

cd "$(dirname "$0")/.."
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

"${PYTHON_BIN}" -m core.orchestrator.openclaw_cli benchmark \
  --target-url "${TARGET_URL}" \
  --burst-size "${BURST_SIZE}" \
  --concurrency "${CONCURRENCY}" \
  --with-defense

echo ""
echo "📊 Results saved:"
echo "  JSON: artifacts/benchmark/benchmark_summary.json"
echo "  CSV:  artifacts/benchmark/benchmark_summary.csv"
