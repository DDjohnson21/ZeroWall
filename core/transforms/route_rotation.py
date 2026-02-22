"""
ZeroWall Transform — Route Alias Rotation
==========================================
Rotates internal handler names and adds/changes route alias
decorators while keeping the actual URL paths identical.

This changes the internal code structure that an attacker who has
read the source would exploit, without changing any external behavior.

SAFETY: URL paths are never changed. Only internal function names
that back routes are renamed, keeping all external API contracts.
"""

import libcst as cst
from typing import Dict, Any, List, Sequence
from core.transforms.base import BaseTransformer, register_transform
from core.models import TransformType


# Rotation pool for internal handler name suffixes
_HANDLER_SUFFIXES = [
    "_handler", "_processor", "_executor", "_resolver",
    "_responder", "_dispatcher", "_router", "_worker",
]


class _RouteHandlerRenamer(cst.CSTTransformer):
    """Renames internal function names that back routes."""

    def __init__(self, rename_map: Dict[str, str]):
        self.rename_map = rename_map
        self._in_function_def = False

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        return True

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        old_name = original_node.name.value
        if old_name in self.rename_map:
            new_name = self.rename_map[old_name]
            return updated_node.with_changes(
                name=updated_node.name.with_changes(value=new_name)
            )
        return updated_node


@register_transform
class RouteRotationTransformer(BaseTransformer):
    """
    Renames internal FastAPI route handler functions while keeping URL paths.
    E.g., def health_check() → def health_check_handler_zw3()
    The @app.get("/health") decorator path stays the same.
    """
    name = TransformType.ROUTE_ROTATION

    # Internal handler names in target app (kept current)
    _TARGET_HANDLERS = [
        "health_check", "get_version", "public_info", "get_item",
        "read_file", "run_command", "search_items",
    ]

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        seed = params.get("seed", 1)
        suffix = _HANDLER_SUFFIXES[seed % len(_HANDLER_SUFFIXES)]

        rename_map = {}
        for handler in self._TARGET_HANDLERS:
            if hash(handler + str(seed)) % 2 == 0:  # deterministic selection
                rename_map[handler] = f"{handler}{suffix}_zw{seed}"

        try:
            tree = cst.parse_module(source_code)
            modified = tree.visit(_RouteHandlerRenamer(rename_map))
            return modified.code
        except Exception:
            return source_code

    def describe(self, params: Dict[str, Any]) -> str:
        seed = params.get("seed", 1)
        suffix = _HANDLER_SUFFIXES[seed % len(_HANDLER_SUFFIXES)]
        return f"Rotated internal route handler names with suffix '{suffix}' (seed={seed})"
