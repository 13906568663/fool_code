"""Domain models — Session, Message, Tool definitions, and shared lightweight types.

This module contains the core data structures used across the entire codebase.
HTTP API request/response models live in api_types.py.
SSE event types live in events.py.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------- Session / Message model ----------

class MessageRole(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class ContentBlock(BaseModel):
    type: str  # "text" | "image" | "tool_use" | "tool_result" | "plan_ref" | "document"
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: str | None = None
    tool_use_id: str | None = None
    tool_name: str | None = None
    output: str | None = None
    is_error: bool | None = None

    # --- External content reference (content externalization) ---
    external_path: str | None = None
    preview: str | None = None
    media_type: str | None = None
    original_size: int | None = None
    inline_data: str | None = None

    @staticmethod
    def text_block(text: str) -> ContentBlock:
        return ContentBlock(type="text", text=text)

    @staticmethod
    def tool_use_block(id: str, name: str, input: str) -> ContentBlock:
        return ContentBlock(type="tool_use", id=id, name=name, input=input)

    @staticmethod
    def tool_result_block(
        tool_use_id: str, tool_name: str, output: str, is_error: bool = False
    ) -> ContentBlock:
        return ContentBlock(
            type="tool_result",
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            output=output,
            is_error=is_error,
        )

    @staticmethod
    def image_block(
        external_path: str, media_type: str = "image/png", image_id: str | None = None,
    ) -> ContentBlock:
        label = f"[Image #{image_id}]" if image_id else "[Image]"
        return ContentBlock(
            type="image",
            external_path=external_path,
            media_type=media_type,
            preview=label,
            id=image_id,
        )

    @staticmethod
    def plan_ref_block(external_path: str, preview: str) -> ContentBlock:
        return ContentBlock(
            type="plan_ref",
            external_path=external_path,
            preview=preview,
        )

    @staticmethod
    def document_block(
        external_path: str,
        markdown_path: str,
        filename: str,
        file_id: str,
        category: str = "document",
        size: int = 0,
        meta: dict | None = None,
    ) -> ContentBlock:
        """A document attachment — markdown stored externally, not shown in chat."""
        return ContentBlock(
            type="document",
            id=file_id,
            name=filename,
            external_path=markdown_path,
            preview=filename,
            media_type=category,
            original_size=size,
        )

    @staticmethod
    def externalized_tool_result_block(
        tool_use_id: str,
        tool_name: str,
        replacement_text: str,
        external_path: str,
        preview: str,
        original_size: int,
        is_error: bool = False,
    ) -> ContentBlock:
        return ContentBlock(
            type="tool_result",
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            output=replacement_text,
            is_error=is_error,
            external_path=external_path,
            preview=preview,
            original_size=original_size,
        )


def _make_uuid() -> str:
    return str(_uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


class ConversationMessage(BaseModel):
    role: MessageRole
    blocks: list[ContentBlock]
    usage: TokenUsage | None = None

    # --- Message metadata (chain structure) ---
    uuid: str = Field(default_factory=_make_uuid)
    parent_uuid: str | None = None
    timestamp: str = Field(default_factory=_now_iso)

    # --- Visibility flags ---
    is_virtual: bool = False
    is_meta: bool = False
    is_visible_in_transcript_only: bool = False

    # --- Compaction flags ---
    is_compact_boundary: bool = False
    is_compact_summary: bool = False

    @staticmethod
    def user_text(text: str, parent_uuid: str | None = None) -> ConversationMessage:
        return ConversationMessage(
            role=MessageRole.user,
            blocks=[ContentBlock.text_block(text)],
            parent_uuid=parent_uuid,
        )

    @staticmethod
    def assistant_blocks(
        blocks: list[ContentBlock],
        usage: TokenUsage | None = None,
        parent_uuid: str | None = None,
    ) -> ConversationMessage:
        return ConversationMessage(
            role=MessageRole.assistant, blocks=blocks, usage=usage,
            parent_uuid=parent_uuid,
        )

    @staticmethod
    def tool_result(
        tool_use_id: str, tool_name: str, output: str, is_error: bool = False,
        parent_uuid: str | None = None,
    ) -> ConversationMessage:
        return ConversationMessage(
            role=MessageRole.tool,
            blocks=[
                ContentBlock.tool_result_block(tool_use_id, tool_name, output, is_error)
            ],
            parent_uuid=parent_uuid,
        )

    @staticmethod
    def meta_user(text: str, parent_uuid: str | None = None) -> ConversationMessage:
        return ConversationMessage(
            role=MessageRole.user,
            blocks=[ContentBlock.text_block(text)],
            is_meta=True,
            parent_uuid=parent_uuid,
        )


class Session(BaseModel):
    version: int = 2
    messages: list[ConversationMessage] = Field(default_factory=list)
    chat_model: str | None = None
    chat_provider_id: str | None = None
    plan_slug: str | None = None
    plan_status: str = "none"  # "none" | "drafted" | "executing" | "completed"


# ---------- Display layer types ----------

class DisplayBlock(BaseModel):
    """Structured block for frontend rendering — each type maps to a UI component."""
    type: str  # "text" | "image_ref" | "plan_summary" | "tool_call" | "tool_result" | "thinking"
    content: str | None = None
    meta: dict[str, Any] | None = None


class ChatMessage(BaseModel):
    """UI-layer message with structured blocks (replaces flat content: str)."""
    role: str
    blocks: list[DisplayBlock] = Field(default_factory=list)
    uuid: str | None = None
    timestamp: str | None = None
    is_plan: bool = False

    # Backward-compatible flat content for existing frontend code
    content: str = ""


# ---------- Shared lightweight types ----------

class SessionListItem(BaseModel):
    id: str
    title: str
    created_at: int
    message_count: int
    active: bool


class ModelInfo(BaseModel):
    id: str
    name: str


# ---------- Content replacement record (for prompt cache stability) ----------

class ContentReplacementRecord(BaseModel):
    kind: str = "tool-result"
    tool_use_id: str
    replacement: str


# ---------- Tool definition (OpenAI function calling format) ----------

class ToolParameter(BaseModel):
    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolFunction(BaseModel):
    name: str
    description: str
    parameters: ToolParameter


class ToolDefinition(BaseModel):
    type: str = "function"
    function: ToolFunction
