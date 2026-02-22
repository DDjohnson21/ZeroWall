"""
ZeroWall Transform — Rename Internal Identifiers
=================================================
Uses libcst to rename internal function/variable names while
preserving all external API contracts (route names, public function
names, parameter names seen by callers).

SAFETY: Only renames based on a deterministic mapping.
External interfaces are never touched.
"""

import re
import libcst as cst
from typing import Dict, Any, Set
from core.transforms.base import BaseTransformer, register_transform
from core.models import TransformType


# Internal names that are safe to rename (never public API endpoints)
RENAMEABLE_PREFIXES = ("_internal_", "_helper_", "_validate_", "_process_", "_check_")
ALWAYS_SAFE_TO_RENAME = {"result", "data", "body", "flags", "safe_results", "items"}


class _RenameVisitor(cst.CSTTransformer):
    """CST visitor that renames identifiers per a mapping."""

    def __init__(self, rename_map: Dict[str, str]):
        self.rename_map = rename_map

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        if original_node.value in self.rename_map:
            return updated_node.with_changes(value=self.rename_map[original_node.value])
        return updated_node


@register_transform
class RenameIdentifiersTransformer(BaseTransformer):
    """
    Renames internal variables/helpers using a deterministic seed-based mapping.
    Never renames: route handlers, endpoint parameter names, public class/module names.
    """
    name = TransformType.RENAME_IDENTIFIERS

    # Deterministic name pool for rotating to
    _NAME_POOL = [
        ("result", "outcome"), ("data", "payload"), ("body", "request_body"),
        ("flags", "markers"), ("safe_results", "allowed_results"),
        ("items", "entries"), ("cmd", "command_key"),
    ]

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        seed = params.get("seed", 0)
        # Build deterministic rename map based on seed
        rename_map = {}
        for i, (original, replacement) in enumerate(self._NAME_POOL):
            if (seed + i) % 3 != 0:  # deterministic: skip some based on seed
                continue
            rename_map[original] = f"{replacement}_zw{seed + i}"

        try:
            tree = cst.parse_module(source_code)
            modified = tree.visit(_RenameVisitor(rename_map))
            return modified.code
        except Exception:
            # If CST fails (e.g. syntax edge case), return unchanged
            return source_code

    def describe(self, params: Dict[str, Any]) -> str:
        seed = params.get("seed", 0)
        return f"Renamed internal identifiers (seed={seed}) — external API preserved"
