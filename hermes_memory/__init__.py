"""Hermes Agent's built-in memory, for Hey Jev: MEMORY.md (her notes) and USER.md (who you are), small and bounded,
read into every request she makes.

memory_store.py and threat_patterns.py are Hermes Agent's own code (MIT, see LICENSE), changed only where marked.
memory_tool() below is Hermes' tools/memory_tool.py entry point at the same commit, without the parts that need the
rest of Hermes: the write-approval gate, background-review rules and metrics. Since 1ae3c55e (26 October) Hermes'
tool offers 'patch', which changes one span inside an entry and keeps the rest, and turns 'replace' away. Here
'replace' (the whole entry) stays too: her planner's memory step and her learning review still ask for it, and the
store still does it.
"""
import json
from typing import Any, Dict, List, Optional

from ._compat import get_hermes_home, get_memory_dir, set_home, set_memory_dir
from .memory_store import ENTRY_DELIMITER, MEMORY_BLOCK_HEADERS, PATCH_DROP_HINT, MemoryStore

__all__ = ["ENTRY_DELIMITER", "MEMORY_BLOCK_HEADERS", "MemoryStore", "get_hermes_home", "get_memory_dir", "set_home",
           "set_memory_dir",
           "memory_tool", "store", "USER_CHAR_LIMIT", "MEMORY_CHAR_LIMIT"]

# Hey Jev: USER.md was full at Hermes' 1,375 letters by 22 October, and everything new she learned about you was
# dropped ("not kept: Memory at 1,357/1,375 chars"), while MEMORY.md used 53 of its 2,200. The room goes where she
# writes: the same 3,575 letters in all, so her prompt stays within its budget (tests/test_learning.py)
USER_CHAR_LIMIT, MEMORY_CHAR_LIMIT = 2000, 1575


def store() -> MemoryStore:
    """Her memory, with Hey Jev's limits: use this, not MemoryStore(), so every reader and writer agrees on them."""
    return MemoryStore(memory_char_limit=MEMORY_CHAR_LIMIT, user_char_limit=USER_CHAR_LIMIT)

_STORE_ACTIONS = {
    "add": lambda store, target, content, old_text: store.add(target, content),
    "patch": lambda store, target, content, old_text: store.patch(target, old_text, content),
    "replace": lambda store, target, content, old_text: store.replace(target, old_text, content),
    "remove": lambda store, target, content, old_text: store.remove(target, old_text),
}


def _error(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


def memory_tool(store: MemoryStore, action: Optional[str] = None, target: str = "memory",
                content: Optional[str] = None, old_text: Optional[str] = None, new_text: Optional[str] = None,
                operations: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One change (action add / patch / replace / remove, with content and old_text) or a batch (operations),
    applied atomically against the size limit. Returns Hermes' result dict: success, and error or usage."""
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
        return _error("Missing required parameter: provide 'action' (add/patch/replace/remove) "
                      "or 'operations' (batch list). Got neither.")
    if action not in _STORE_ACTIONS:
        return _error(f"Unknown action '{action}'. Use: add, patch, replace, remove")
    if action == "add" and not content:
        return _error("Content is required for 'add' action.")
    if action in ("patch", "replace", "remove") and not old_text:
        return {"success": False, "error": f"'{action}' needs old_text -- a short unique substring of the entry to "
                                           f"{action}.", "current_entries": store._entries_for(target)}
    if action == "patch" and not content:
        return _error(f"content (the new text for the old_text span) is required for 'patch' action. "
                      f"{PATCH_DROP_HINT}")
    if action == "replace" and not content:
        return _error("content is required for 'replace' action.")
    return _STORE_ACTIONS[action](store, target, content, old_text)


def as_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
