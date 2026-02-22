"""
ZeroWall Transform — Swap Validators
======================================
Swaps the implementation of input sanitization/validation logic
with equivalent but structurally different patterns.

Example transformations:
- Adds an explicit allowlist check before the existing lookup
- Swaps a dict.get() pattern with an explicit 'in' check + lookup
- Adds a length/type guard

SAFETY: All swapped validators produce identical behavior for
legitimate inputs. The key difference is structural — moving target.
This is the primary HARDENING transform for the vulnerable endpoints.
"""

import libcst as cst
from typing import Dict, Any, Sequence
from core.transforms.base import BaseTransformer, register_transform
from core.models import TransformType


# Hardened version of the /data endpoint body (safe allowlist version)
_DATA_ENDPOINT_HARDENED = '''
    ALLOWED_FILES = {"report.txt", "config.txt", "public.txt", "readme.txt"}
    if file not in ALLOWED_FILES:
        raise HTTPException(status_code=403, detail="Access denied: file not in allowlist")
    if file in SIMULATED_FILES:
        return {"file": file, "content": SIMULATED_FILES[file]}
    return {"file": file, "content": f"[SIMULATED] File not found"}
'''

_RUN_ENDPOINT_HARDENED = '''
    ALLOWED_COMMANDS = {"hello", "date", "uptime", "whoami"}
    if cmd not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=400, detail="Command not in allowlist")
    result = SIMULATED_COMMANDS.get(cmd)
    return {"cmd": cmd, "output": result, "status": "success"}
'''

_SEARCH_ENDPOINT_HARDENED = '''
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9 _-]+$', q):
        raise HTTPException(status_code=400, detail="Invalid search query")
    safe_results = [
        {"id": 1, "name": "Gadget Alpha"},
        {"id": 2, "name": "Widget Beta"},
    ]
    return {
        "query": q,
        "results": safe_results,
        "note": "[SIMULATED] Query executed against in-memory store",
    }
'''


class _ValidatorSwapper(cst.CSTTransformer):
    """Swaps function bodies of vulnerable endpoints with hardened versions."""

    VULNERABLE_FUNCTIONS = {
        "read_file": _DATA_ENDPOINT_HARDENED,
        "run_command": _RUN_ENDPOINT_HARDENED,
        "search_items": _SEARCH_ENDPOINT_HARDENED,
    }

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        func_name = original_node.name.value

        # Also match renamed variants (e.g. read_file_handler_zw3)
        matched_name = None
        for vuln_name in self.VULNERABLE_FUNCTIONS:
            if func_name.startswith(vuln_name):
                matched_name = vuln_name
                break

        if matched_name is None:
            return updated_node

        hardened_body = self.VULNERABLE_FUNCTIONS[matched_name]
        try:
            # Parse the hardened body as a module, extract statements
            wrapped = f"async def _tmp():\n"
            for line in hardened_body.strip().split("\n"):
                wrapped += f"    {line}\n"
            parsed = cst.parse_module(wrapped)
            new_body_stmts = parsed.body[0].body.body  # type: ignore

            new_body = updated_node.body.with_changes(body=new_body_stmts)
            return updated_node.with_changes(body=new_body)
        except Exception:
            return updated_node


@register_transform
class SwapValidatorsTransformer(BaseTransformer):
    """
    Swaps vulnerable input validation logic with hardened allowlist-based equivalents.
    This is the PRIMARY security hardening transform in ZeroWall.
    """
    name = TransformType.SWAP_VALIDATORS

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        strategy = params.get("strategy", "allowlist")
        try:
            tree = cst.parse_module(source_code)
            modified = tree.visit(_ValidatorSwapper())
            return modified.code
        except Exception:
            return source_code

    def describe(self, params: Dict[str, Any]) -> str:
        strategy = params.get("strategy", "allowlist")
        return f"Swapped vulnerable validators with hardened {strategy} pattern in /data, /run, /search endpoints"
