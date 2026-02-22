#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ZeroWall — Seed Known Attack Payloads
# Seeds the target app with all known exploit payloads.
# Outputs response headers to show X-ZeroWall-Alert injection.
# DISCLAIMER: Targets local demo app ONLY. Zero real harm.
# ─────────────────────────────────────────────────────────────────────────────

TARGET_URL="${TARGET_URL:-http://localhost:8000}"

echo "🎯 Seeding attack payloads against ${TARGET_URL}"
echo "──────────────────────────────────────────────"

echo ""
echo "1. Simulated Path Traversal"
echo "   GET /data?file=../../etc/passwd"
curl -si "${TARGET_URL}/data?file=../../etc/passwd" | grep -E "HTTP|X-ZeroWall|content"
echo ""

echo "2. Simulated Command Injection"
echo "   POST /run {cmd: 'rm -rf /'}"
curl -si -X POST "${TARGET_URL}/run" -H "Content-Type: application/json" -d '{"cmd":"rm -rf /"}' | grep -E "HTTP|X-ZeroWall|status"
echo ""

echo "3. Simulated SQL Injection"
echo "   GET /search?q=' OR 1=1 --"
curl -si "${TARGET_URL}/search?q=%27+OR+1%3D1+--" | grep -E "HTTP|X-ZeroWall|query"
echo ""

echo "4. Config File Access"
echo "   GET /data?file=../../config/secrets.yaml"
curl -si "${TARGET_URL}/data?file=../../config/secrets.yaml" | grep -E "HTTP|X-ZeroWall|content"
echo ""

echo "5. Shell Escape Probe"
echo "   POST /run {cmd: '; ls -la'}"
curl -si -X POST "${TARGET_URL}/run" -H "Content-Type: application/json" -d '{"cmd":"; ls -la"}' | grep -E "HTTP|X-ZeroWall|status"
echo ""

echo "──────────────────────────────────────────────"
echo "✅ All payloads seeded. Check X-ZeroWall-Alert headers above."
echo "   Run: python -m core.orchestrator.openclaw_cli simulate-alert"
