"""
ZeroWall — Candidate Sandbox
============================
Runs a mutation candidate's *actual* source as a live, isolated FastAPI
server on an ephemeral port so the Exploit Agent can replay payloads against
the real hardened code — not the static production app.

This is what makes ZeroWall a real Moving Target Defense instead of a
simulation: a `swap_validators` candidate only "wins" if, when launched and
attacked, it genuinely returns 4xx for the exploit payloads while still
serving legitimate traffic.

SAFETY: each sandbox binds to 127.0.0.1 only, runs the same in-memory demo
app (no real FS/DB/network), and is torn down after the replay completes.
"""

from core.sandbox.runner import CandidateSandbox, sandbox_for_candidate

__all__ = ["CandidateSandbox", "sandbox_for_candidate"]
