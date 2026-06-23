"""
ZeroWall — Candidate Sandbox Runner
===================================
Launches a candidate's mutated source as a throwaway uvicorn server on a free
local port, waits until it is healthy, and tears it down afterwards.

Used by the Exploit Agent path in the defense loop so that exploit replay
hits the *candidate's* code rather than the static production app. Without
this, every candidate looks identical to the attacker and no hardened variant
can ever be shown to block an exploit.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TARGET_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "target-fastapi"


def _free_port() -> int:
    """Ask the OS for an unused TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CandidateSandbox:
    """
    A short-lived, isolated server running one candidate's mutated code.

    Usage:
        with CandidateSandbox(mutated_code) as sb:
            replay_exploits(sb.base_url)   # attack the *candidate*, not prod
    """

    def __init__(
        self,
        mutated_code: str,
        host: str = "127.0.0.1",
        startup_timeout_s: float = 20.0,
        app_dir: Path = TARGET_APP_DIR,
    ):
        self.mutated_code = mutated_code
        self.host = host
        self.port = _free_port()
        self.startup_timeout_s = startup_timeout_s
        self.app_dir = app_dir

        self._tmpdir: Optional[str] = None
        self._proc: Optional[subprocess.Popen] = None
        self.ready: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> "CandidateSandbox":
        """Write the mutated code to a temp dir and boot uvicorn against it."""
        self._tmpdir = tempfile.mkdtemp(prefix="zw_sandbox_")
        tmp_path = Path(self._tmpdir)
        (tmp_path / "main.py").write_text(self.mutated_code, encoding="utf-8")

        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=self._tmpdir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        self.ready = self._await_health()
        if not self.ready:
            logger.warning(
                "[CandidateSandbox] candidate server on :%s never became healthy",
                self.port,
            )
        return self

    def _await_health(self) -> bool:
        deadline = time.time() + self.startup_timeout_s
        url = f"{self.base_url}/health"
        while time.time() < deadline:
            # If the process died on startup, stop waiting.
            if self._proc is not None and self._proc.poll() is not None:
                err = b""
                if self._proc.stderr is not None:
                    with contextlib.suppress(Exception):
                        err = self._proc.stderr.read() or b""
                logger.warning(
                    "[CandidateSandbox] uvicorn exited early (code=%s): %s",
                    self._proc.returncode,
                    err.decode("utf-8", "replace")[-400:],
                )
                return False
            try:
                r = httpx.get(url, timeout=1.0)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.15)
        return False

    def stop(self) -> None:
        if self._proc is not None:
            with contextlib.suppress(Exception):
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    # ── context manager sugar ────────────────────────────────────────────────
    def __enter__(self) -> "CandidateSandbox":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


@contextlib.contextmanager
def sandbox_for_candidate(mutated_code: str, **kwargs):
    """Convenience context manager: yields a started CandidateSandbox."""
    sb = CandidateSandbox(mutated_code, **kwargs)
    try:
        yield sb.start()
    finally:
        sb.stop()
