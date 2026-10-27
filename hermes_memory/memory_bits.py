# From Hermes Agent by Nous Research, tools/memory_tool.py at commit 1ae3c55e4bb16f495ebf0536a5672782d903e15e
# https://github.com/NousResearch/hermes-agent, MIT License, see LICENSE in this folder.
# Copied by sync_hermes.py; only the imports are changed, see UPSTREAM.json. Don't edit by hand.

"""The piece of Hermes Agent's memory tool (tools/memory_tool.py) its store (memory_store.py) calls back into:
the check that one write names one store, USER.md or MEMORY.md, and that the store is switched on."""

from typing import Any

from .memory_store import FAILURE_CLASS, MemoryStore


# --- tools/memory_tool.py ---

def _memory_target_error(
    store: MemoryStore, target: str | None, operations: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Validate one explicit store before writing, staging, or replaying a batch."""
    if target is None:
        FAILURE_CLASS.set("invalid_args")
        return {"success": False, "error": (
            "Missing required target. Retry with target='memory' or target='user' at the top level. "
            "For a batch, remove target from every operation; use separate calls for different stores. "
            "Nothing was written or staged.")}
    if not isinstance(target, str) or target not in {"memory", "user"}:
        from .tool_bits import _bound_error_text
        FAILURE_CLASS.set("invalid_args")
        return {"success": False,
                "error": _bound_error_text(f"Invalid memory target '{target}'. Use 'memory' or 'user'.")}
    if isinstance(operations, list):
        for index, op in enumerate(operations, 1):
            # A nested target equal to the call's (or null) is redundant, not wrong; only a
            # different one asks for two stores in one call, which a batch cannot do.
            if isinstance(op, dict) and op.get("target") not in (None, target):
                FAILURE_CLASS.set("invalid_args")
                return {"success": False, "error": (
                    f"Operation {index} names a different target than the one at the top level. "
                    "One call writes one store: retry with separate calls for different stores. "
                    "Nothing was written or staged.")}
    if store.target_enabled(target):
        return None
    label = "USER.md" if target == "user" else "MEMORY.md"
    FAILURE_CLASS.set("disabled")
    return {"success": False, "error": f"Built-in {label} writes are disabled in memory config.", "target": target}
