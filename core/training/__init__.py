"""
ZeroWall — Training & Continuous Learning
==========================================
The closed-loop learning subsystem that makes the Mutation Planner smarter
under sustained attack.

Pipeline:
    DefenseCycle outcome
        → feedback.cycle_to_example()        (label = what actually worked)
        → FeedbackRecorder (append SFT JSONL)
        → dataset_builder.build_dataset()    (RAPIDS cuDF aggregation)
        → nemo/finetune_mutation_planner.py  (SFT + LoRA on DGX Spark)
        → nemo/export_to_triton.py           (serve the new planner)

Everything here runs CPU-side with a pandas fallback so the loop is
demonstrable off-DGX; the actual fine-tuning step requires DGX Spark.
"""

from core.training.schema import (
    RankedTransformPlan,
    TransformChoice,
    PlannerValidationError,
    validate_plan,
)

__all__ = [
    "RankedTransformPlan",
    "TransformChoice",
    "PlannerValidationError",
    "validate_plan",
]
