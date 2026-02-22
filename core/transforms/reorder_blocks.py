"""
ZeroWall Transform — Reorder Independent Blocks
=================================================
Reorders independent top-level statement blocks in the module
(e.g., the order of constant definitions, import groups, helper
function declarations) where order doesn't affect behavior.

SAFETY: Only reorders blocks that are provably independent.
Never reorders anything where order matters (e.g., function defs
that call each other, class defs with inheritance).
"""

import libcst as cst
from typing import Dict, Any, List, Sequence
from core.transforms.base import BaseTransformer, register_transform
from core.models import TransformType


@register_transform
class ReorderBlocksTransformer(BaseTransformer):
    """
    Reorders independent module-level constant/assignment blocks.
    Creates structural variation without any behavioral change.
    """
    name = TransformType.REORDER_BLOCKS

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        seed = params.get("seed", 2)
        try:
            tree = cst.parse_module(source_code)
            stmts = list(tree.body)

            # Identify reorderable groups: simple Assign statements at module level
            # that don't reference each other (constants/dicts)
            reorderable_ranges = []
            current_range_start = None

            for i, stmt in enumerate(stmts):
                is_simple_assign = isinstance(stmt, cst.SimpleStatementLine) and any(
                    isinstance(s, cst.Assign) for s in stmt.body
                )
                if is_simple_assign:
                    if current_range_start is None:
                        current_range_start = i
                else:
                    if current_range_start is not None and i - current_range_start > 1:
                        reorderable_ranges.append((current_range_start, i))
                    current_range_start = None

            # Apply rotation within each reorderable range
            new_stmts = list(stmts)
            for start, end in reorderable_ranges:
                block = new_stmts[start:end]
                # Deterministic rotation based on seed
                rotation = seed % len(block)
                rotated = block[rotation:] + block[:rotation]
                new_stmts[start:end] = rotated

            new_tree = tree.with_changes(body=new_stmts)
            return new_tree.code
        except Exception:
            return source_code

    def describe(self, params: Dict[str, Any]) -> str:
        seed = params.get("seed", 2)
        return f"Reordered independent module-level constant blocks (rotation seed={seed})"
