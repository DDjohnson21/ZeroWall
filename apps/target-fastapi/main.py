"""
ZeroWall Demo Target App — Intentionally Vulnerable FastAPI Service
====================================================================
DISCLAIMER: This application contains SIMULATED vulnerabilities for
demonstration purposes only. It does NOT expose real system resources,
execute real OS commands, or perform any harmful operations.
All "vulnerabilities" are sandboxed, fictional, and safe.

This app is the attack surface that ZeroWall defends.
"""

import os
import hashlib
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse
import uvicorn

# ─── Version tracking (updated by ZeroWall deploy controller) ─────────────
APP_VERSION = os.environ.get("APP_VERSION", "v1.0.0-ORIGINAL")
DEPLOY_HASH = os.environ.get("DEPLOY_HASH", "aabbcc001122")
START_TIME = time.time()

# ─── Simulated in-memory data store (no real FS or DB access) ─────────────
SIMULATED_FILES = {
    "report.txt": "Q4 revenue report: $4.2M — CONFIDENTIAL",
    "config.txt": "DB_HOST=localhost DB_PORT=5432 DB_USER=admin",
    "public.txt": "Welcome to the public info page!",
    "readme.txt": "This is a demo application for ZeroWall.",
}

SIMULATED_COMMANDS = {
    "hello": "Hello from the server!",
    "date": "Sat Feb 21 22:00:00 UTC 2026",
    "uptime": "up 3 days, 4:22, load average: 0.01 0.01 0.00",
    "whoami": "demouser",
}

app = FastAPI(
    title="ZeroWall Demo Target",
    description="Intentionally vulnerable demo app — ZeroWall hackathon target",
    version=APP_VERSION,
)


# ─── SAFE ENDPOINTS ─────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Always-safe health check. ZeroWall verifies this keeps working."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "deploy_hash": DEPLOY_HASH,
        "uptime_seconds": round(time.time() - START_TIME, 2),
    }


@app.get("/version")
def get_version():
    """Returns current deployed version info."""
    return {
        "app_version": APP_VERSION,
        "deploy_hash": DEPLOY_HASH,
        "zerowall_managed": True,
    }


@app.get("/public")
def public_info():
    """Publicly accessible info — always safe."""
    return {
        "message": "Welcome to the ZeroWall Demo App",
        "content": SIMULATED_FILES.get("public.txt", ""),
    }


@app.get("/items/{item_id}")
def get_item(item_id: int, q: Optional[str] = None):
    """Normal item lookup endpoint — used to verify functional correctness."""
    items = {
        1: {"name": "Gadget Alpha", "price": 29.99},
        2: {"name": "Widget Beta", "price": 49.99},
        3: {"name": "Doohickey Gamma", "price": 9.99},
    }
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    result = items[item_id]
    if q:
        result["query"] = q
    return result


# ─── VULNERABLE ENDPOINTS ────────────────────────────────────────────────────
# These simulate real vulnerability PATTERNS without any real harm.
# They are the attack surface ZeroWall mutates and hardens.

@app.get("/data")
def read_file(file: str = Query(..., description="Filename to read")):
    """
    SIMULATED PATH TRAVERSAL VULNERABILITY (v1 — unpatched)
    =========================================================
    In v1, the 'file' param is used directly with no sanitization.
    An attacker can pass '../../etc/passwd' style paths.

    NOTE: This ONLY accesses a simulated in-memory dict, never the real FS.
    The vulnerability is in the LOGIC PATTERN: missing input validation.
    ZeroWall will mutate this to add strict whitelisting.
    """
    # VULNERABLE: no sanitization — this is the attack surface
    # In a real app this would be: open(f"/data/{file}").read()
    # Here we simulate it safely with an in-memory dict lookup
    # but we purposely mirror the vulnerable pattern (no whitelist check)
    if file in SIMULATED_FILES:
        return {"file": file, "content": SIMULATED_FILES[file]}
    # Simulate what would be an info leak — reveals file existence
    return {"file": file, "content": f"[SIMULATED] File '{file}' not found on server"}


@app.post("/run")
async def run_command(request: Request):
    """
    SIMULATED COMMAND INJECTION VULNERABILITY (v1 — unpatched)
    ===========================================================
    In v1, the 'cmd' field is passed directly without allowlist validation.
    An attacker can pass arbitrary strings to probe server behavior.

    NOTE: This ONLY ever echoes from a safe in-memory dict, never executes
    real OS commands. No subprocess, no os.system, no eval.
    The vulnerability is in the missing input validation PATTERN.
    ZeroWall will mutate this to enforce strict allowlisting.
    """
    body = await request.json()
    cmd = body.get("cmd", "")

    # VULNERABLE: accepts any cmd string, no allowlist — attack surface
    # In a real app this could be: subprocess.run(cmd, shell=True)
    # Here we safely simulate the pattern with a dict lookup
    result = SIMULATED_COMMANDS.get(cmd)
    if result:
        return {"cmd": cmd, "output": result, "status": "success"}
    else:
        # Simulates info disclosure: reveals what was attempted
        return {
            "cmd": cmd,
            "output": f"[SIMULATED] Unknown command: '{cmd}'",
            "status": "unknown",
            "hint": "Try: hello, date, uptime, whoami",
        }


@app.get("/search")
def search_items(q: str = Query(..., min_length=1)):
    """
    SIMULATED SQL INJECTION PROBE SURFACE (v1 — unpatched)
    =======================================================
    No real DB. Simulates missing input sanitization pattern.
    ZeroWall mutation: add parameterization + sanitization.
    """
    # VULNERABLE: raw query value echoed back without sanitization
    # Simulates what a real unsanitized DB query would expose
    safe_results = [
        {"id": 1, "name": "Gadget Alpha"},
        {"id": 2, "name": "Widget Beta"},
    ]
    return {
        "query": q,  # VULNERABLE: raw input reflected
        "results": safe_results,
        "note": "[SIMULATED] Query executed against in-memory store",
    }


# ─── Attack Detection Hook ──────────────────────────────────────────────────

@app.middleware("http")
async def detect_suspicious_requests(request: Request, call_next):
    """
    Lightweight middleware to flag suspicious request patterns.
    In real deployment, this feeds ZeroWall's IDS webhook.
    """
    suspicious_patterns = [
        "../", "etc/passwd", "cmd=", "SELECT ", "DROP ", "<script",
        "' OR ", "| ls", "; rm", "eval(", "exec(",
    ]
    path_and_query = str(request.url)
    body_bytes = b""

    # Check URL for suspicious patterns
    flags = [p for p in suspicious_patterns if p.lower() in path_and_query.lower()]

    response = await call_next(request)

    if flags:
        # In production, this would fire a webhook to ZeroWall/OpenClaw
        response.headers["X-ZeroWall-Alert"] = "SUSPICIOUS"
        response.headers["X-ZeroWall-Flags"] = ",".join(flags)

    return response


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=False,
    )
