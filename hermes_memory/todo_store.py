# From Hermes Agent by Nous Research, tools/todo_tool.py at commit 1ae3c55e4bb16f495ebf0536a5672782d903e15e
# https://github.com/NousResearch/hermes-agent, MIT License, see LICENSE in this folder.
# Copied by sync_hermes.py; only the imports are changed, see UPSTREAM.json. Don't edit by hand.

"""Hermes Agent's checklist for the agent's own work on a job of several parts (tools/todo_tool.py): TodoStore,
its schema (which allows one item in progress at a time) and the tool's entry point. Without the
tool-registry entry and the transcript helpers, which need the rest of Hermes."""

import json
from typing import Any, Dict, List, Optional

from .tool_bits import tool_error


# --- tools/todo_tool.py ---

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


MAX_TODO_CONTENT_CHARS = 4000


MAX_TODO_ITEMS = 256


MAX_TODO_RESULT_CHARS = 512_000


_TRUNCATION_MARKER = "… [truncated]"


TODO_INJECTION_HEADER = "[Your active task list was preserved across context compression]"


_STATUS_MARKERS = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]", "cancelled": "[~]"}


_ACTIVE_STATUSES = {"pending", "in_progress"}


class TodoStore:
    """In-memory todo list, one per AIAgent. List position is priority; items are
    ``{id, content, status, parent?}`` — ``parent`` nests a subtask."""

    def __init__(self):
        self._items: list[dict[str, str]] = []
        self._revision = 0

    def _fresh_items(self, todos: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Validate, dedupe and order a whole new list (replace / restore)."""
        return self._normalize_order([self._validate(t) for t in self._dedupe_by_id(todos)])

    def write(self, todos: list[dict[str, Any]], merge: bool = False) -> list[dict[str, str]]:
        """Replace the list (default) or merge by id; returns the full list after writing.
        Raises ValueError (leaving the list untouched) if any item is invalid."""
        before = self.read()
        try:
            if merge:
                self._merge(todos)
            else:
                self._items = self._fresh_items(todos)
        except ValueError:
            self._items = before  # rejected write must not leave a partial list behind
            raise
        del self._items[MAX_TODO_ITEMS:]  # keep the priority head; replays can't grow unbounded
        self._sanitize_parents(self._items)
        if self._items != before:
            self._revision += 1
        return self.read()

    def _merge(self, todos: list[dict[str, Any]]) -> None:
        """Update existing items only in the fields provided; append new ones (validated)."""
        existing = {item["id"]: item for item in self._items}
        for t in self._dedupe_by_id(todos):
            item_id = str(t.get("id", "")).strip()
            if not item_id:
                continue  # can't merge without an id
            cur = existing.get(item_id)
            if cur is None:
                validated = self._validate(t)
                existing[validated["id"]] = validated
                self._items.append(validated)
                continue
            if t.get("content"):
                cur["content"] = self._cap_content(str(t["content"]).strip())
            if t.get("status") and str(t["status"]).strip().lower() in VALID_STATUSES:
                cur["status"] = str(t["status"]).strip().lower()
            if "parent" in t:
                parent = str(t["parent"] or "").strip()
                if parent:
                    cur["parent"] = parent
                else:
                    cur.pop("parent", None)
        # Rebuild preserving original order for existing items (first occurrence wins).
        rebuilt = {item["id"]: existing.get(item["id"], item) for item in self._items}
        self._items = self._normalize_order(list(rebuilt.values()))

    def read(self) -> list[dict[str, str]]:
        return [item.copy() for item in self._items]

    def has_items(self) -> bool:
        return bool(self._items)

    def snapshot(self) -> dict[str, Any]:
        """Full state clients can reconcile atomically."""
        return {"todos": self.read(), "revision": self._revision}

    def restore(self, todos: list[dict[str, Any]], *, revision: Any = 0) -> list[dict[str, str]]:
        """Restore a trusted snapshot without manufacturing a new revision."""
        self._items = self._fresh_items(todos)[:MAX_TODO_ITEMS]
        try:
            self._revision = max(0, int(revision or 0))
        except (TypeError, ValueError):
            self._revision = 0
        return self.read()

    def format_for_injection(self) -> Optional[str]:
        """Render the list for post-compression injection, or None if nothing active. Only
        pending/in_progress items are injected — finished ones make the model re-do work after
        compression. A parent is kept (with its real status marker) when any descendant is
        active so subtasks keep context."""
        if not self._items:
            return None
        children: dict[str, list[dict[str, str]]] = {}
        for item in self._items:
            if item.get("parent"):
                children.setdefault(item["parent"], []).append(item)

        def render(item: dict[str, str], depth: int, out: list[str]) -> bool:
            kid_lines: list[str] = []
            has_active_kid = False
            for kid in children.get(item["id"], []):
                has_active_kid |= render(kid, depth + 1, kid_lines)
            keep = item["status"] in _ACTIVE_STATUSES or has_active_kid
            if keep:
                marker = _STATUS_MARKERS.get(item["status"], "[?]")
                out.append(f"{'  ' * depth}- {marker} {item['id']}. "
                           f"{item['content']} ({item['status']})")
                out.extend(kid_lines)
            return keep

        lines = [TODO_INJECTION_HEADER]
        for item in self._items:
            if not item.get("parent"):
                render(item, 0, lines)
        return "\n".join(lines) if len(lines) > 1 else None

    @staticmethod
    def _cap_content(content: str) -> str:
        """Truncate to MAX_TODO_CONTENT_CHARS keeping the head (the actionable part) + marker."""
        if len(content) > MAX_TODO_CONTENT_CHARS:
            return content[:MAX_TODO_CONTENT_CHARS - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
        return content

    @staticmethod
    def _validate(item: dict[str, Any]) -> dict[str, str]:
        """Normalize one item to ``{id, content, status, parent?}`` (placeholders when missing)."""
        if not isinstance(item, dict):
            return {"id": "?", "content": "(invalid item)", "status": "pending"}
        item_id = str(item.get("id", "")).strip() or "?"
        content = str(item.get("content", "")).strip()
        if not content:
            raise ValueError(
                f"Todo item '{item_id}' has empty or missing content. "
                "Each item must have a non-empty description."
            )
        status = str(item.get("status", "pending")).strip().lower()
        result = {"id": item_id,
                  "content": TodoStore._cap_content(content),
                  "status": status if status in VALID_STATUSES else "pending"}
        parent = str(item.get("parent") or "").strip()
        if parent and parent != item_id:
            result["parent"] = parent
        return result

    @staticmethod
    def _sanitize_parents(items: list[dict[str, str]]) -> None:
        """Drop dangling parent refs and break cycles in place (such items become roots)."""
        by_id = {item["id"]: item for item in items}
        for item in items:
            if item.get("parent") and item["parent"] not in by_id:
                item.pop("parent", None)
        for item in items:
            seen, node = {item["id"]}, item
            while node.get("parent"):
                if node["parent"] in seen:
                    item.pop("parent", None)
                    break
                seen.add(node["parent"])
                node = by_id[node["parent"]]

    @staticmethod
    def _dedupe_by_id(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse duplicate ids, keeping the last occurrence in its position."""
        last_index: dict[str, int] = {}
        for i, item in enumerate(todos):  # non-dicts get a synthetic key; _validate handles them
            key = str(item.get("id", "")).strip() if isinstance(item, dict) else f"__invalid_{i}"
            last_index[key or "?"] = i
        return [todos[i] for i in sorted(last_index.values())]

    @staticmethod
    def _normalize_order(items: list[dict[str, str]]) -> list[dict[str, str]]:
        """Lift the in_progress step ahead of any earlier pending placeholder. Nested lists
        keep authored order — reordering would tear a subtask from its siblings."""
        statuses = [item["status"] for item in items]
        if any(item.get("parent") for item in items) or "in_progress" not in statuses:
            return items
        active_index = statuses.index("in_progress")
        if "pending" not in statuses[:active_index]:
            return items
        normalized = items.copy()
        normalized.insert(statuses.index("pending"), normalized.pop(active_index))
        return normalized


def todo_tool(todos: Optional[list[dict[str, Any]]] = None, merge: bool = False,
              store: Optional[TodoStore] = None) -> str:
    """Write ``todos`` (replace, or ``merge`` by id) or read when None -> list + summary JSON."""
    if store is None:
        return tool_error("TodoStore not initialized")
    if todos is None:
        items = store.read()
    else:
        if not isinstance(todos, list):
            return tool_error(f"todos must be a list, got {type(todos).__name__}")
        try:
            items = store.write(todos, merge)
        except ValueError as e:
            return tool_error(str(e))
    summary = {"total": len(items)}
    for status in ("pending", "in_progress", "completed", "cancelled"):
        summary[status] = sum(1 for i in items if i["status"] == status)
    return json.dumps({"todos": items, "revision": store.snapshot()["revision"],
                       "summary": summary}, ensure_ascii=False)


def check_todo_requirements() -> bool:
    """Todo tool has no external requirements -- always available."""
    return True


TODO_SCHEMA = {
    "name": "todo_list",
    "description": (
        # See #95681.
        "Track a task list for multi-step work (3+ steps). Use for complex tasks "
        "with 3+ steps or when the user provides multiple tasks. "
        "For 'all N items' tasks, enumerate every instance as its own checklist "
        "item so none are silently dropped. "
        "Call with no parameters to read the current list.\n"
        "List order is priority. Only ONE item in_progress at a time. "
        "Break large phases into subtasks via parent. "
        "Mark an item completed only after the work is verified done, never "
        "based on intent. If something fails, cancel it and add a revised "
        "item. Always returns the full current list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Task items to write.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string"
                        },
                        "content": {
                            "type": "string",
                            "description": "Task description"
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"]
                        },
                        "parent": {
                            "type": "string",
                            "description": "Optional id of another item, making this a nested subtask. Omit for top-level."
                        }
                    },
                    "required": ["id", "content", "status"]
                }
            },
            "merge": {
                "type": "boolean",
                "description": (
                    "true: update existing items by id, add new ones. "
                    "false (default): replace the entire list with a fresh plan."
                ),
                "default": False
            }
        },
        "required": []
    }
}


TODO_LEGACY_ALIASES = ("todo",)


TODO_TOOL_NAMES = frozenset((TODO_SCHEMA["name"], *TODO_LEGACY_ALIASES))


def is_todo_tool_name(name: Any) -> bool:
    """True for the Todo tool's current name or a legacy alias (an already-unwrapped dispatch name)."""
    return isinstance(name, str) and name in TODO_TOOL_NAMES
