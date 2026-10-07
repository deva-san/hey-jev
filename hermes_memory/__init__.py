"""Hermes Agent's built-in memory, for Hey Jev: MEMORY.md (her notes) and USER.md (who you are), small and bounded,
read into every request she makes.

memory_store.py and threat_patterns.py are Hermes Agent's own code (MIT, see LICENSE), changed only where marked.
memory_tool() below is Hermes' tools/memory_tool.py entry point at the same commit, without the parts that need the
rest of Hermes: the write-approval gate, background-review rules and metrics.
"""
import json
from typing import Any, Dict, List, Optional

from .memory_store import ENTRY_DELIMITER, MEMORY_BLOCK_HEADERS, MemoryStore, get_memory_dir, set_memory_dir

__all__ = ["ENTRY_DELIMITER", "MEMORY_BLOCK_HEADERS", "MemoryStore", "get_memory_dir", "set_memory_dir",
           "memory_tool"]

_STORE_ACTIONS = {
    "add": lambda store, target, content, old_text: store.add(target, content),
    "replace": lambda store, target, content, old_text: store.replace(target, old_text, content),
    "remove": lambda store, target, content, old_text: store.remove(target, old_text),
}


def _error(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


def memory_tool(store: MemoryStore, action: Optional[str] = None, target: str = "memory",
                content: Optional[str] = None, old_text: Optional[str] = None, new_text: Optional[str] = None,
                operations: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One change (action add / replace / remove, with content and old_text) or a batch (operations), applied
    atomically against the size limit. Returns Hermes' result dict: success, and error or usage."""
    if content is None and new_text is not None:
        content = new_text
    target = "memory" if target is None else target
    if target not in ("memory", "user"):
        return _error(f"Invalid memory target '{target}'. Use 'memory' or 'user'.")
    if operations:
        if not isinstance(operations, list):
            return _error("operations must be a list of {action, content?, old_text?} objects.")
        return store.apply_batch(target, operations)
    if not action:
        return _error("Missing required parameter: provide 'action' (add/replace/remove) "
                      "or 'operations' (batch list). Got neither.")
    if action not in _STORE_ACTIONS:
        return _error(f"Unknown action '{action}'. Use: add, replace, remove")
    if action == "add" and not content:
        return _error("Content is required for 'add' action.")
    if action in ("replace", "remove") and not old_text:
        return {"success": False, "error": f"'{action}' needs old_text -- a short unique substring of the entry to "
                                           f"{action}.", "current_entries": store._entries_for(target)}
    if action == "replace" and not content:
        return _error("content is required for 'replace' action.")
    return _STORE_ACTIONS[action](store, target, content, old_text)


def as_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
