"""TodoWrite tool — structured task list management.

Upgraded to a full ToolHandler (matching SuggestPlanModeHandler pattern)
so that the todo list is passed via ToolResult.metadata instead of
requiring conversation.py to parse the string output.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fool_code.runtime.config import active_workspace_root
from fool_code.tools.tool_protocol import (
    ToolCategory,
    ToolContext,
    ToolHandler,
    ToolMeta,
    ToolResult,
)
from fool_code.types import ToolDefinition, ToolFunction, ToolParameter


def _todo_store_path() -> Path:
    env = os.environ.get("FOOL_CODE_TODO_STORE")
    if env:
        return Path(env)
    return active_workspace_root() / ".fool-code-todos.json"


class TodoWriteHandler(ToolHandler):
    """Manage the structured task list for the current session.

    Returns metadata["todo_update"] with the new todo list so the runtime
    can push a ``todo_update`` SSE event without parsing strings.
    """

    meta = ToolMeta(
        name="TodoWrite",
        category=ToolCategory.META,
        is_read_only=False,
        is_concurrency_safe=True,
    )

    definition = ToolDefinition(
        function=ToolFunction(
            name="TodoWrite",
            description="Update the structured task list for the current session.",
            parameters=ToolParameter(
                properties={
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "activeForm": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["content", "activeForm", "status"],
                        },
                    }
                },
                required=["todos"],
            ),
        )
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        todos = args.get("todos", [])
        if not todos:
            return ToolResult(output="todos must not be empty", is_error=True)

        for t in todos:
            if not t.get("content", "").strip():
                return ToolResult(output="todo content must not be empty", is_error=True)
            if not t.get("activeForm", "").strip():
                return ToolResult(output="todo activeForm must not be empty", is_error=True)

        store = _todo_store_path()
        old_todos: list[dict] = []
        if store.exists():
            try:
                old_todos = json.loads(store.read_text(encoding="utf-8"))
            except Exception:
                old_todos = []

        all_done = all(t.get("status") == "completed" for t in todos)
        persisted = [] if all_done else todos

        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(
            json.dumps(persisted, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        nudge = (
            all_done
            and len(todos) >= 3
            and not any("verif" in t.get("content", "").lower() for t in todos)
        )

        output = json.dumps(
            {
                "old_todos": old_todos,
                "new_todos": todos,
                "verification_nudge_needed": nudge or None,
            },
            indent=2,
            ensure_ascii=False,
        )

        if nudge:
            output += (
                "\n\nNOTE: You just closed out 3+ tasks and none of them was a "
                'verification step. Before writing your final summary, spawn the '
                'verification agent (subagent_type="verification"). You cannot '
                "self-assign PARTIAL by listing caveats in your summary — only "
                "the verifier issues a verdict."
            )

        return ToolResult(
            output=output,
            metadata={"todo_update": todos},
        )
