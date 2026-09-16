"""Extract a stable expression into a private helper function."""

import libcst as cst
from typing import Any, Dict

from core.models import TransformType
from core.transforms.base import BaseTransformer, register_transform


class _PublicContentCallExtractor(cst.CSTTransformer):
    def __init__(self, helper_name: str):
        self.helper_name = helper_name

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        func = original_node.func
        if not (
            isinstance(func, cst.Attribute)
            and isinstance(func.value, cst.Name)
            and func.value.value == "SIMULATED_FILES"
            and func.attr.value == "get"
            and original_node.args
            and isinstance(original_node.args[0].value, cst.SimpleString)
            and original_node.args[0].value.evaluated_value == "public.txt"
        ):
            return updated_node
        return cst.Call(func=cst.Name(self.helper_name))


@register_transform
class SplitHelpersTransformer(BaseTransformer):
    """Extract public-content lookup logic into a deterministic private helper."""

    name = TransformType.SPLIT_HELPERS

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        seed = int(params.get("seed", 3))
        helper_name = f"_zw_public_content_{seed}"
        tree = cst.parse_module(source_code)
        if helper_name in source_code:
            return source_code

        modified = tree.visit(_PublicContentCallExtractor(helper_name))
        helper = cst.parse_module(
            f"\n\ndef {helper_name}():\n"
            '    return SIMULATED_FILES.get("public.txt", "")\n'
        )
        return modified.with_changes(body=[*modified.body, *helper.body]).code

    def describe(self, params: Dict[str, Any]) -> str:
        return (
            "Extracted public-content lookup into a private helper "
            f"(seed={int(params.get('seed', 3))})"
        )
