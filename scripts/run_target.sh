#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python apps/target-fastapi/managed_runner.py
