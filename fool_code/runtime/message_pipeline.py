"""Message pipeline — normalize messages for different consumers.

Two main pipelines:
  1. normalize_for_api() → build LLM request messages (model view)
  2. normalize_for_display() → build UI-layer ChatMessages (display view)

Handles:
  - isVirtual: display-only, never sent to API
  - isMeta: system injection, not shown to user
  - isVisibleInTranscriptOnly: only in history review
  - Image blocks: resolve to multimodal content for API, ref for display
  - External tool results: preview+path for API, preview for display
  - Plan refs: full content for API, summary for display
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fool_code.runtime.content_store import ContentStore
from fool_code.types import (
    ChatMessage,
    ConversationMessage,
    DisplayBlock,
)
from fool_code.runtime.compact import get_messages_after_compact_boundary

logger = logging.getLogger(__name__)

_IMAGE_DETAIL: str = "auto"
_IMAGE_BASE_URL: str | None = None


def set_image_detail(detail: str) -> None:
    """Set the ``detail`` parameter for image_url blocks sent to the LLM.

    OpenAI vision tokens:
      - ``"low"``  → 85 tokens per image (512×512 downsample)
      - ``"high"`` → tile-based, ~1K+ tokens (full fidelity)
      - ``"auto"`` → API picks based on image size (default)

    When the API proxy doesn't support vision, images are tokenised as
    raw base64 text (~80K tokens/image) regardless of this setting.
    """
    global _IMAGE_DETAIL
    _IMAGE_DETAIL = detail
    logger.info("Image detail mode set to %r", detail)


def set_image_base_url(base_url: str | None) -> None:
    """Set the HTTP base URL for serving images externally.

    When set, ``normalize_for_api`` will use
    ``{base_url}/{session_id}/{filename}`` instead of embedding images as
    base64 data-URIs.  Pass ``None`` to revert to base64 mode.
    """
    global _IMAGE_BASE_URL
    _IMAGE_BASE_URL = base_url.rstrip("/") if base_url else None
    logger.info("Image base URL set to %r", _IMAGE_BASE_URL)


def _make_image_url_block(data_url: str) -> dict[str, Any]:
    """Build an ``image_url`` content block with the configured ``detail``."""
    block: dict[str, Any] = {"url": data_url}
    if _IMAGE_DETAIL != "auto":
        block["detail"] = _IMAGE_DETAIL
    return {"type": "image_url", "image_url": block}


def _external_path_to_url(external_path: str) -> str | None:
    """Convert a local image-cache path to an HTTP URL.

    Expected path shape:
        …/image-cache/{session_id}/{image_id}.{ext}
    Returns:
        {_IMAGE_BASE_URL}/{session_id}/{image_id}.{ext}
    """
    if not _IMAGE_BASE_URL:
        return None
    p = Path(external_path)
    try:
        session_id = p.parent.name
        filename = p.name
        return f"{_IMAGE_BASE_URL}/{session_id}/{filename}"
    except Exception:
        return None


def _resolve_image_block(
    external_path: str,
    media_type: str | None,
    content_store: ContentStore | None,
) -> dict[str, Any] | None:
    """Build an image_url block — prefer HTTP URL, fallback to base64."""
    url = _external_path_to_url(external_path)
    if url:
        return _make_image_url_block(url)
    if content_store:
        try:
            img_data = content_store.read_image_base64(external_path)
            return _make_image_url_block(
                f"data:{media_type or 'image/png'};base64,{img_data}",
            )
        except Exception:
            pass
    return None


# ------------------------------------------------------------------
# Model view: build dicts for the LLM API
# ------------------------------------------------------------------

def normalize_for_api(
    messages: list[ConversationMessage],
    content_store: ContentStore | None = None,
) -> list[dict[str, Any]]:
    """Build LLM request messages from domain messages.

    Filters:
      - Only messages after the last compact_boundary
      - Skip isVirtual (display-only)
      - Skip compact_boundary markers themselves
      - Resolve image blocks to multimodal content
      - Resolve plan_ref blocks to full plan text
      - Keep externalized tool results as-is (preview+path)
    """
    effective = get_messages_after_compact_boundary(messages)
    result: list[dict[str, Any]] = []

    for msg in effective:
        if msg.is_virtual:
            continue
        if msg.is_compact_boundary:
            continue

        if msg.role.value in ("user", "assistant", "system"):
            content_parts: list[Any] = []
            openai_tool_calls: list[dict] = []

            for block in msg.blocks:
                if block.type == "text" and block.text:
                    content_parts.append(block.text)

                elif block.type == "image" and block.external_path:
                    resolved = _resolve_image_block(
                        block.external_path, block.media_type, content_store,
                    )
                    if resolved:
                        content_parts.append(resolved)
                    else:
                        content_parts.append(block.preview or "[Image unavailable]")

                elif block.type == "plan_ref" and block.external_path and content_store:
                    try:
                        full_plan = content_store.read_content(block.external_path)
                        content_parts.append(full_plan)
                    except Exception:
                        content_parts.append(block.preview or "[Plan unavailable]")

                elif block.type == "document" and block.external_path:
                    try:
                        md_path = Path(block.external_path)
                        if md_path.is_file():
                            md_text = md_path.read_text(encoding="utf-8", errors="replace")
                            header = f"[Document: {block.name or 'file'}]\n"
                            content_parts.append(header + md_text)
                        else:
                            content_parts.append(f"[Document: {block.name} — file not available]")
                    except Exception:
                        content_parts.append(f"[Document: {block.name} — read error]")

                elif block.type == "tool_use":
                    openai_tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": block.input or "{}",
                        },
                    })

            role = msg.role.value
            if role == "system":
                role = "user"

            entry: dict[str, Any] = {"role": role}

            has_multimodal = any(isinstance(p, dict) for p in content_parts)
            if has_multimodal:
                api_content = []
                for p in content_parts:
                    if isinstance(p, str):
                        api_content.append({"type": "text", "text": p})
                    else:
                        api_content.append(p)
                entry["content"] = api_content
            elif content_parts:
                entry["content"] = "\n".join(str(p) for p in content_parts)

            if openai_tool_calls:
                entry["tool_calls"] = openai_tool_calls
                if "content" not in entry:
                    entry["content"] = None

            result.append(entry)

        elif msg.role.value == "tool":
            for block in msg.blocks:
                if block.type == "tool_result":
                    image_blocks = [
                        b for b in msg.blocks
                        if b.type == "image" and (b.inline_data or b.external_path)
                    ]
                    if image_blocks:
                        content_parts: list[Any] = [
                            {"type": "text", "text": block.output or ""},
                        ]
                        for ib in image_blocks:
                            if ib.external_path:
                                resolved = _resolve_image_block(
                                    ib.external_path, ib.media_type, content_store,
                                )
                                if resolved:
                                    content_parts.append(resolved)
                                    continue
                            if ib.inline_data:
                                content_parts.append(_make_image_url_block(
                                    f"data:{ib.media_type or 'image/jpeg'};base64,{ib.inline_data}",
                                ))
                        result.append({
                            "role": "tool",
                            "tool_call_id": block.tool_use_id,
                            "content": content_parts,
                        })
                    else:
                        result.append({
                            "role": "tool",
                            "tool_call_id": block.tool_use_id,
                            "content": block.output or "",
                        })

    _strip_images_for_compact(result)

    return result


IMAGE_TOKEN_ESTIMATE = 80_000


def _strip_images_for_compact(messages: list[dict[str, Any]]) -> None:
    """Image handling: keep ALL images in normal conversation.

    Images are only stripped during compaction (handled by compact.py).
    This function is a no-op placeholder that can be enabled for
    token-budget-based stripping if needed in the future.
    """


# ------------------------------------------------------------------
# Display view: build ChatMessages for the frontend
# ------------------------------------------------------------------

def normalize_for_display(
    messages: list[ConversationMessage],
    include_transcript_only: bool = False,
) -> list[ChatMessage]:
    """Build UI-layer ChatMessages with structured DisplayBlocks.

    Filters:
      - Skip isMeta (system injections)
      - Skip isVisibleInTranscriptOnly unless include_transcript_only=True
      - Merge tool_result blocks into the preceding assistant ChatMessage
    """
    result: list[ChatMessage] = []

    idx = 0
    while idx < len(messages):
        msg = messages[idx]
        idx += 1

        if msg.is_meta:
            continue
        if msg.is_visible_in_transcript_only and not include_transcript_only:
            continue
        if msg.role.value not in ("user", "assistant"):
            continue

        blocks: list[DisplayBlock] = []
        text_parts: list[str] = []
        has_plan_ref = False

        for b in msg.blocks:
            if b.type == "text" and b.text:
                blocks.append(DisplayBlock(type="text", content=b.text))
                text_parts.append(b.text)

            elif b.type == "image":
                blocks.append(DisplayBlock(
                    type="image_ref",
                    content=b.preview or "[Image]",
                    meta={"path": b.external_path, "media_type": b.media_type},
                ))

            elif b.type == "document":
                blocks.append(DisplayBlock(
                    type="document_ref",
                    content=b.name or b.preview or "[Document]",
                    meta={
                        "markdown_path": b.external_path,
                        "file_id": b.id,
                        "filename": b.name,
                        "category": b.media_type or "document",
                        "size": b.original_size or 0,
                    },
                ))

            elif b.type == "tool_use" and b.name:
                blocks.append(DisplayBlock(
                    type="tool_call",
                    content=b.name,
                    meta={"id": b.id, "input": b.input},
                ))

            elif b.type == "tool_result":
                display_content = b.preview if b.external_path else (b.output or "")
                blocks.append(DisplayBlock(
                    type="tool_result",
                    content=display_content,
                    meta={
                        "tool_name": b.tool_name,
                        "is_error": b.is_error,
                        "external_path": b.external_path,
                        "original_size": b.original_size,
                    },
                ))

            elif b.type == "plan_ref":
                has_plan_ref = True
                blocks.append(DisplayBlock(
                    type="plan_summary",
                    content=b.preview or "",
                    meta={"path": b.external_path},
                ))
                text_parts.append(b.preview or "")

        if msg.role.value == "assistant":
            while idx < len(messages):
                next_msg = messages[idx]
                if next_msg.is_meta:
                    idx += 1
                    continue
                if next_msg.role.value != "tool":
                    break
                for b in next_msg.blocks:
                    if b.type == "tool_result":
                        display_content = b.preview if b.external_path else (b.output or "")
                        blocks.append(DisplayBlock(
                            type="tool_result",
                            content=display_content,
                            meta={
                                "tool_use_id": b.tool_use_id,
                                "tool_name": b.tool_name,
                                "is_error": b.is_error,
                                "external_path": b.external_path,
                                "original_size": b.original_size,
                            },
                        ))
                idx += 1

        if not blocks:
            continue

        flat_content = "\n".join(text_parts)
        result.append(ChatMessage(
            role=msg.role.value,
            blocks=blocks,
            uuid=msg.uuid,
            timestamp=msg.timestamp,
            content=flat_content,
            is_plan=has_plan_ref,
        ))

    return result
