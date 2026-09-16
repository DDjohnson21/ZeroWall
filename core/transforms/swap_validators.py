"""Deterministic, strategy-specific hardening for the demo attack surfaces."""

import textwrap
from typing import Any, Dict

import libcst as cst

from core.models import TransformType
from core.transforms.base import BaseTransformer, register_transform


_SNIPPETS = {
    "allowlist": {
        "read_file": """
            allowed_files = {"report.txt", "config.txt", "public.txt", "readme.txt"}
            if file not in allowed_files:
                raise HTTPException(status_code=403, detail="Access denied: file not in allowlist")
            return {"file": file, "content": SIMULATED_FILES[file]}
        """,
        "run_command": """
            body = await request.json()
            cmd = body.get("cmd", "")
            if cmd not in SIMULATED_COMMANDS:
                raise HTTPException(status_code=400, detail="Command not in allowlist")
            return {"cmd": cmd, "output": SIMULATED_COMMANDS[cmd], "status": "success"}
        """,
        "search_items": """
            import re as _re
            if not _re.fullmatch(r"[a-zA-Z0-9 _-]+", q):
                raise HTTPException(status_code=400, detail="Invalid search query")
            safe_results = [
                {"id": 1, "name": "Gadget Alpha"},
                {"id": 2, "name": "Widget Beta"},
            ]
            return {"query": q, "results": safe_results, "note": "[SIMULATED] Parameterized in-memory query"}
        """,
    },
    "strict_type": {
        "read_file": """
            if not isinstance(file, str) or len(file) > 64:
                raise HTTPException(status_code=400, detail="Invalid filename")
            try:
                content = SIMULATED_FILES[file]
            except KeyError:
                raise HTTPException(status_code=403, detail="Access denied")
            return {"file": file, "content": content}
        """,
        "run_command": """
            body = await request.json()
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="Invalid request body")
            cmd = body.get("cmd")
            try:
                result = SIMULATED_COMMANDS[cmd]
            except (KeyError, TypeError):
                raise HTTPException(status_code=400, detail="Unknown command")
            return {"cmd": cmd, "output": result, "status": "success"}
        """,
        "search_items": """
            allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-")
            if len(q) > 80 or any(char not in allowed for char in q):
                raise HTTPException(status_code=400, detail="Invalid search query")
            safe_results = [
                {"id": 1, "name": "Gadget Alpha"},
                {"id": 2, "name": "Widget Beta"},
            ]
            return {"query": q, "results": safe_results, "note": "[SIMULATED] Validated in-memory query"}
        """,
    },
    "regex_guard": {
        "read_file": """
            import re as _re
            if not _re.fullmatch(r"[a-zA-Z0-9_-]+[.]txt", file) or file not in SIMULATED_FILES:
                raise HTTPException(status_code=403, detail="Filename rejected by guard")
            return {"file": file, "content": SIMULATED_FILES[file]}
        """,
        "run_command": """
            import re as _re
            body = await request.json()
            cmd = str(body.get("cmd", ""))
            if not _re.fullmatch(r"[a-z]+", cmd) or cmd not in SIMULATED_COMMANDS:
                raise HTTPException(status_code=400, detail="Command rejected by guard")
            return {"cmd": cmd, "output": SIMULATED_COMMANDS[cmd], "status": "success"}
        """,
        "search_items": """
            import re as _re
            if _re.search(r"[^a-zA-Z0-9 _-]", q):
                raise HTTPException(status_code=400, detail="Search rejected by guard")
            safe_results = [
                {"id": 1, "name": "Gadget Alpha"},
                {"id": 2, "name": "Widget Beta"},
            ]
            return {"query": q, "results": safe_results, "note": "[SIMULATED] Guarded in-memory query"}
        """,
    },
}


class _ValidatorSwapper(cst.CSTTransformer):
    def __init__(self, strategy: str):
        self.snippets = _SNIPPETS[strategy]

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        matched = next(
            (name for name in self.snippets if original_node.name.value.startswith(name)),
            None,
        )
        if matched is None:
            return updated_node

        body = textwrap.dedent(self.snippets[matched]).strip("\n")
        parsed = cst.parse_module(
            "async def _temporary():\n" + textwrap.indent(body, "    ") + "\n"
        )
        statements = parsed.body[0].body.body
        return updated_node.with_changes(
            body=updated_node.body.with_changes(body=statements)
        )


@register_transform
class SwapValidatorsTransformer(BaseTransformer):
    """Replace vulnerable handlers with one of three audited guard strategies."""

    name = TransformType.SWAP_VALIDATORS

    def apply(self, source_code: str, params: Dict[str, Any]) -> str:
        strategy = str(params.get("strategy", "allowlist"))
        if strategy not in _SNIPPETS:
            raise ValueError(f"Unknown validator strategy: {strategy}")
        tree = cst.parse_module(source_code)
        return tree.visit(_ValidatorSwapper(strategy)).code

    def describe(self, params: Dict[str, Any]) -> str:
        strategy = str(params.get("strategy", "allowlist"))
        return (
            f"Applied audited {strategy} guards to /data, /run, and /search"
        )
