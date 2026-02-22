#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZeroWall Demo Script — End-to-End Judge Flow
# DISCLAIMER: All exploits are simulated and target the local demo app only.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

TARGET_URL="${TARGET_URL:-http://localhost:8000}"

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════╗"
echo "║   ZeroWall — NVIDIA DGX Spark Hackathon Demo    ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${RESET}"

echo -e "${BOLD}Step 1: Verify target app is running${RESET}"
echo -e "→ Checking ${TARGET_URL}/health ..."
HEALTH=$(curl -s ${TARGET_URL}/health)
echo -e "${GREEN}✓ Health check response: ${HEALTH}${RESET}"
echo ""

echo -e "${BOLD}Step 2: Normal requests work (pre-attack)${RESET}"
echo -e "→ GET /public ..."
curl -s ${TARGET_URL}/public | python3 -m json.tool
echo ""
echo -e "→ GET /items/1 ..."
curl -s ${TARGET_URL}/items/1 | python3 -m json.tool
echo ""

echo -e "${BOLD}Step 3: Trigger known exploit (SIMULATED — local demo app only)${RESET}"
echo -e "${RED}→ Simulated path traversal: GET /data?file=../../etc/passwd${RESET}"
EXPLOIT_RESULT=$(curl -s "${TARGET_URL}/data?file=../../etc/passwd")
echo "Exploit response: ${EXPLOIT_RESULT}"
if echo "$EXPLOIT_RESULT" | grep -q "SIMULATED"; then
  echo -e "${RED}✗ VULNERABLE: Target app returned response without blocking exploit${RESET}"
else
  echo -e "${GREEN}✓ BLOCKED: Exploit was prevented${RESET}"
fi
echo ""

echo -e "${BOLD}Step 4: Simulate OpenClaw IDS alert${RESET}"
echo -e "${YELLOW}🚨 [OPENCLAW] Suspicious request detected on /data endpoint${RESET}"
echo -e "${YELLOW}🚨 [OPENCLAW] Initiating ZeroWall defense cycle...${RESET}"
echo ""

echo -e "${BOLD}Step 5: Run ZeroWall defense cycle${RESET}"
cd "$(dirname "$0")/.."
python3 -m core.orchestrator.openclaw_cli defend \
  --endpoint "/data" \
  --payload-type "path-traversal"
echo ""

echo -e "${BOLD}Step 6: Deploy best variant${RESET}"
echo -e "→ Checking active version..."
curl -s ${TARGET_URL}/version | python3 -m json.tool
echo ""

echo -e "${BOLD}Step 7: Verify normal requests still work (post-deploy)${RESET}"
echo -e "→ GET /health ..."
curl -s ${TARGET_URL}/health | python3 -m json.tool
echo -e "→ GET /items/2 ..."
curl -s ${TARGET_URL}/items/2 | python3 -m json.tool
echo ""

echo -e "${BOLD}Step 8: Replay exploit against hardened version${RESET}"
echo -e "${CYAN}→ Simulated path traversal: GET /data?file=../../etc/passwd${RESET}"
POST_EXPLOIT=$(curl -s "${TARGET_URL}/data?file=../../etc/passwd")
echo "Post-defense response: ${POST_EXPLOIT}"
if echo "$POST_EXPLOIT" | grep -q "403\|Access denied\|not in allowlist"; then
  echo -e "${GREEN}✓ BLOCKED: Exploit now fails against hardened variant!${RESET}"
else
  echo -e "${YELLOW}⚠  Check deploy — candidate may need rebuild restart${RESET}"
fi
echo ""

echo -e "${BOLD}Step 9: Open Streamlit Dashboard${RESET}"
echo -e "${CYAN}Dashboard: http://localhost:8501${RESET}"
echo ""

echo -e "${GREEN}${BOLD}✅ ZeroWall Demo Complete!${RESET}"
echo -e "${CYAN}Evidence:${RESET}"
echo "  - Defense cycle log: above ↑"
echo "  - Benchmark results: artifacts/benchmark/benchmark_summary.json"
echo "  - Telemetry: telemetry_data/telemetry.jsonl"
echo "  - Dashboard: http://localhost:8501"
