from pathlib import Path

import pytest

from core.agents.verifier_agent import VerifierAgent
from core.models import CandidateResult, MutationPlan, TransformType
from core.transforms.base import apply_transform

import core.transforms.rename_identifiers
import core.transforms.reorder_blocks
import core.transforms.route_rotation
import core.transforms.split_helpers
import core.transforms.swap_validators


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "apps" / "target-fastapi" / "main.py").read_text()


@pytest.mark.parametrize("transform_type", list(TransformType))
def test_each_transform_changes_code_and_preserves_contract(transform_type):
    params = {"seed": 2, "strategy": "regex_guard"}
    mutated, _ = apply_transform(SOURCE, transform_type, params)
    assert mutated != SOURCE
    compile(mutated, "candidate.py", "exec")

    candidate = CandidateResult(
        candidate_id=transform_type.value,
        plan=MutationPlan(
            candidate_id=transform_type.value,
            transform_type=transform_type,
            transform_params=params,
            source_path="main.py",
        ),
        mutated_code=mutated,
    )
    result = VerifierAgent(run_bandit=False).verify_candidate(candidate)
    assert result.verifier_pass
    assert result.tests_passed == 28


def test_validator_strategies_are_distinct():
    outputs = {
        apply_transform(
            SOURCE,
            TransformType.SWAP_VALIDATORS,
            {"seed": index, "strategy": strategy},
        )[0]
        for index, strategy in enumerate(("allowlist", "strict_type", "regex_guard"))
    }
    assert len(outputs) == 3
