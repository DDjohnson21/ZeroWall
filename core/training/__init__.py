"""
ZeroWall — Training & Continuous Learning
==========================================
The closed-loop learning subsystem that makes the Mutation Planner smarter
under sustained attack.

Pipeline (all implemented):
    DefenseCycle outcome
        → feedback.cycle_to_examples()       (label = what actually worked)
        → FeedbackRecorder (append JSONL)     core/training/feedback.py
        → selfplay.run_selfplay()             generate data under attack
        → dataset_builder.build_dataset()    (RAPIDS cuDF / pandas aggregation)
        → train.py                            (PyTorch SFT on DGX Spark GPU)
        → planner_policy.LearnedPlanner       (host-side numpy serving)
        → MutationAgent cascade tier 1        (the planner gets used)

Data generation, aggregation, and serving run CPU-side (numpy/pandas) so the
loop is demonstrable off-GPU; the training step uses the DGX Spark GB10 GPU
(falls back to CPU if torch has no CUDA).
"""

from core.training.schema import (
    RankedTransformPlan,
    TransformChoice,
    PlannerValidationError,
    validate_plan,
)
from core.training.features import encode_context, FEATURE_DIM, LABEL_DIM, TRANSFORMS
from core.training.feedback import FeedbackRecorder, cycle_to_examples
from core.training.dataset_builder import build_dataset, PlannerDataset
from core.training.planner_policy import LearnedPlanner

__all__ = [
    "RankedTransformPlan",
    "TransformChoice",
    "PlannerValidationError",
    "validate_plan",
    "encode_context",
    "FEATURE_DIM",
    "LABEL_DIM",
    "TRANSFORMS",
    "FeedbackRecorder",
    "cycle_to_examples",
    "build_dataset",
    "PlannerDataset",
    "LearnedPlanner",
]
