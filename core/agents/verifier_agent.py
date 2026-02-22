"""
ZeroWall — Verifier Agent
==========================
Runs pytest test suite and optional bandit static analysis against
each mutation candidate to verify behavioral correctness.

PIPELINE:
1. Write mutated code to a temp file
2. Run pytest against the temp module
3. Run bandit for security issues (optional)
4. Return pass/fail matrix
"""

import os
import time
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from core.models import CandidateResult, CandidateStatus
from core.transforms.base import apply_transform

logger = logging.getLogger(__name__)

# Path to the test suite in the target app
TARGET_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "target-fastapi"


class VerifierAgent:
    """
    Runs tests and static analysis against mutation candidates.
    """

    def __init__(
        self,
        test_dir: Path = TARGET_APP_DIR,
        run_bandit: bool = True,
        timeout_s: int = 30,
    ):
        self.test_dir = test_dir
        self.run_bandit = run_bandit
        self.timeout_s = timeout_s

    def verify_candidate(self, candidate: CandidateResult) -> CandidateResult:
        """
        Apply the mutation and run tests against the mutated code.
        Updates candidate in-place with verifier results.
        """
        logger.info(f"[VerifierAgent] Verifying {candidate.candidate_id}")
        t_start = time.time()

        if not candidate.mutated_code:
            logger.warning(f"[VerifierAgent] No mutated code for {candidate.candidate_id}")
            candidate.verifier_pass = False
            candidate.status = CandidateStatus.TESTS_FAIL
            return candidate

        # Write mutated code to a temp directory alongside test files
        with tempfile.TemporaryDirectory(prefix="zw_verify_") as tmpdir:
            tmp_path = Path(tmpdir)

            # Copy test file and requirements
            shutil.copy(self.test_dir / "test_app.py", tmp_path / "test_app.py")

            # Write mutated main.py
            (tmp_path / "main.py").write_text(candidate.mutated_code, encoding="utf-8")

            # Run pytest
            passed, failed, errors = self._run_pytest(tmp_path)
            candidate.tests_passed = passed
            candidate.tests_failed = failed
            candidate.tests_errors = errors
            candidate.verifier_pass = (failed == 0 and errors == 0)

            # Run bandit
            if self.run_bandit:
                issues = self._run_bandit(tmp_path / "main.py")
                candidate.bandit_issues = issues
            else:
                candidate.bandit_issues = 0

        elapsed_s = time.time() - t_start
        candidate.eval_end_time = time.time()
        candidate.eval_latency_s = elapsed_s

        if candidate.verifier_pass:
            candidate.status = CandidateStatus.TESTS_PASS
        else:
            candidate.status = CandidateStatus.TESTS_FAIL

        logger.info(
            f"[VerifierAgent] {candidate.candidate_id}: "
            f"pass={candidate.verifier_pass} "
            f"tests={candidate.tests_passed}✓ {candidate.tests_failed}✗ "
            f"bandit_issues={candidate.bandit_issues} "
            f"in {elapsed_s:.2f}s"
        )
        return candidate

    def _run_pytest(self, work_dir: Path) -> tuple[int, int, int]:
        """Run pytest in the given directory. Returns (passed, failed, errors)."""
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "test_app.py", "-v", "--tb=no", "-q",
                 "--no-header"],
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
            output = result.stdout + result.stderr
            passed = self._parse_pytest_count(output, "passed")
            failed = self._parse_pytest_count(output, "failed")
            errors = self._parse_pytest_count(output, "error")
            return passed, failed, errors
        except subprocess.TimeoutExpired:
            logger.error(f"[VerifierAgent] pytest timed out")
            return 0, 0, 1
        except Exception as e:
            logger.error(f"[VerifierAgent] pytest error: {e}")
            return 0, 0, 1

    def _parse_pytest_count(self, output: str, keyword: str) -> int:
        """Parse pytest output for passed/failed/error counts."""
        import re
        pattern = rf"(\d+)\s+{keyword}"
        match = re.search(pattern, output)
        return int(match.group(1)) if match else 0

    def _run_bandit(self, source_file: Path) -> int:
        """Run bandit and return number of issues found. 0 = clean."""
        try:
            result = subprocess.run(
                ["python", "-m", "bandit", str(source_file), "-q", "-ll"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if "No issues identified" in result.stdout:
                return 0
            import re
            match = re.search(r"Total issues \(by severity\):.*?High: (\d+)", result.stdout, re.DOTALL)
            if match:
                return int(match.group(1))
            return 0 if result.returncode == 0 else 1
        except Exception as e:
            logger.warning(f"[VerifierAgent] bandit error: {e}")
            return 0
