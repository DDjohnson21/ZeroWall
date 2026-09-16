"""Safely rotate entries in known lookup tables used by the demo target."""

import libcst as cst
from typing import Any, Dict

from core.models import TransformType
from core.transforms.base import BaseTransformer, register_transform


class _KnownMappingRotator(cst.CSTTransformer):
    TARGETS = {"SIMULATED_FILES", "SIMULATED_COMMANDS"}

    def __init__(self, seed: int):
        self.seed = seed

    def leave_Assign(
        self,
        original_node: cst.Assign,
        updated_node: cst.Assign,
    ) -> cst.Assign:
        if (
            len(original_node.targets) != 1
            or not isinstance(original_node.targets[0].target, cst.Name)
            or original_node.targets[0].target.value not in self.TARGETS
            or not isinstance(updated_node.value, cst.Dict)
        ):
            return updated_node

        elements = list(updated_node.value.elements)
        if len(elements) < 2:
            return updated_node
        rotation = (self.seed % (len(elements) - 1)) + 1
        rotated = elements[rotation:] + elements[:rotation]
        return updated_node.with_changes(
            value=updated_node.value.with_changes(elements=rotated)
        )


@register_transform
class ReorderBlocksTransformer(BaseTransformer):
    """Create structural diversity without reordering dependent statements."""

    name = TransformType.REORDER_BLOCKS

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        seed = int(params.get("seed", 2))
        tree = cst.parse_module(source_code)
        return tree.visit(_KnownMappingRotator(seed)).code

    def describe(self, params: Dict[str, Any]) -> str:
        return (
            "Rotated entries in independent in-memory lookup tables "
            f"(seed={int(params.get('seed', 2))})"
        )
