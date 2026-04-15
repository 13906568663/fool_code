"""SSE event types — WebEvent pushed to the frontend during conversation."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel


WebEventType = Literal[
    "text", "thinking", "tool_start", "tool_end", "error", "permission_request", "done",
    "hook_start", "hook_end", "background_status",
    "mode_change", "subagent_start", "subagent_end",
    "plan_mode_suggest", "tool_progress", "todo_update",
    "image_stored", "document_attached", "content_replaced", "plan_updated",
    "ask_user",
    "compact_start", "compact_end",
]


class WebEvent(BaseModel):
    type: WebEventType
    content: str | None = None
    name: str | None = None
    input: str | None = None
    output: str | None = None
    error: bool | None = None
    tool_name: str | None = None
    status: str | None = None

    @classmethod
    def make_text(cls, content: str) -> WebEvent:
        return cls(type="text", content=content)

    @classmethod
    def make_thinking(cls, content: str) -> WebEvent:
        return cls(type="thinking", content=content)

    @classmethod
    def make_tool_start(cls, name: str, input: str) -> WebEvent:
        return cls(type="tool_start", name=name, input=input)

    @classmethod
    def make_tool_end(cls, name: str, output: str, error: bool = False) -> WebEvent:
        return cls(type="tool_end", name=name, output=output, error=error)

    @classmethod
    def make_error(cls, content: str) -> WebEvent:
        return cls(type="error", content=content)

    @classmethod
    def make_permission_request(cls, tool_name: str, input: str) -> WebEvent:
        return cls(type="permission_request", tool_name=tool_name, input=input)

    @classmethod
    def make_done(cls) -> WebEvent:
        return cls(type="done")

    @classmethod
    def make_hook_start(cls, name: str) -> WebEvent:
        return cls(type="hook_start", name=name)

    @classmethod
    def make_hook_end(cls, name: str, output: str = "", error: bool = False) -> WebEvent:
        return cls(type="hook_end", name=name, output=output, error=error)

    @classmethod
    def make_background_status(cls, name: str, status: str) -> WebEvent:
        return cls(type="background_status", name=name, status=status)

    @classmethod
    def make_mode_change(cls, mode: str) -> WebEvent:
        return cls(type="mode_change", content=mode)

    @classmethod
    def make_subagent_start(cls, name: str, agent_type: str) -> WebEvent:
        return cls(type="subagent_start", name=name, content=agent_type)

    @classmethod
    def make_subagent_end(cls, name: str, status: str) -> WebEvent:
        return cls(type="subagent_end", name=name, status=status)

    @classmethod
    def make_plan_mode_suggest(cls, reason: str) -> WebEvent:
        return cls(type="plan_mode_suggest", content=reason)

    @classmethod
    def make_tool_progress(cls, tool_name: str, content: str) -> WebEvent:
        return cls(type="tool_progress", name=tool_name, content=content)

    @classmethod
    def make_todo_update(cls, todos_json: str) -> WebEvent:
        return cls(type="todo_update", content=todos_json)

    @classmethod
    def make_image_stored(cls, image_id: str, path: str) -> WebEvent:
        return cls(type="image_stored", name=image_id, content=path)

    @classmethod
    def make_content_replaced(cls, tool_use_id: str, original_size: int) -> WebEvent:
        return cls(type="content_replaced", name=tool_use_id, content=str(original_size))

    @classmethod
    def make_document_attached(
        cls, file_id: str, filename: str, category: str, size: int,
        cached_path: str = "", markdown_path: str = "",
    ) -> WebEvent:
        return cls(
            type="document_attached",
            name=file_id,
            content=json.dumps(
                {
                    "filename": filename, "category": category, "size": size,
                    "file_id": file_id,
                    "cached_path": cached_path, "markdown_path": markdown_path,
                },
                ensure_ascii=False,
            ),
        )

    @classmethod
    def make_plan_updated(cls, slug: str, path: str) -> WebEvent:
        return cls(type="plan_updated", name=slug, content=path)

    @classmethod
    def make_ask_user(cls, tool_use_id: str, questions_json: str) -> WebEvent:
        return cls(type="ask_user", name=tool_use_id, content=questions_json)

    @classmethod
    def make_compact_start(cls) -> WebEvent:
        return cls(type="compact_start", content="正在整理上下文...")

    @classmethod
    def make_compact_end(cls, summary_preview: str = "") -> WebEvent:
        return cls(type="compact_end", content=summary_preview)
