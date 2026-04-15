"""Tool result storage — auto-externalize large tool outputs.

  - Per-tool persistence threshold
  - Per-message aggregate budget enforcement
  - ContentReplacementState for prompt cache stability across turns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fool_code.runtime.content_store import ContentStore, PERSISTED_OUTPUT_TAG
from fool_code.types import ContentBlock, ContentReplacementRecord, ConversationMessage

logger = logging.getLogger(__name__)

DEFAULT_PERSIST_THRESHOLD = 50_000  # 50KB per tool result
PER_MESSAGE_BUDGET = 200_000       # 200KB aggregate per message


@dataclass
class ContentReplacementState:
    """Tracks which tool results have been replaced to preserve prompt cache."""
    seen_ids: set[str] = field(default_factory=set)
    replacements: dict[str, str] = field(default_factory=dict)

    def clone(self) -> ContentReplacementState:
        return ContentReplacementState(
            seen_ids=set(self.seen_ids),
            replacements=dict(self.replacements),
        )


class ToolResultPersister:
    """Decides whether to externalize tool results, and applies replacements."""

    def __init__(self, content_store: ContentStore) -> None:
        self.store = content_store

    def maybe_persist(
        self,
        tool_use_id: str,
        tool_name: str,
        output: str,
        is_error: bool = False,
        threshold: int = DEFAULT_PERSIST_THRESHOLD,
    ) -> ContentBlock:
        """If output exceeds threshold, write to disk and return externalized block.
        Otherwise return a normal tool_result block."""
        if len(output) <= threshold:
            return ContentBlock.tool_result_block(
                tool_use_id, tool_name, output, is_error,
            )

        file_path, preview, has_more = self.store.persist_tool_result(
            tool_use_id, output,
        )
        replacement = self.store.build_replacement_message(
            file_path, preview, len(output), has_more,
        )

        logger.info(
            "Externalized tool result %s (%s → %s)",
            tool_name,
            _fmt(len(output)),
            _fmt(len(replacement)),
        )

        return ContentBlock.externalized_tool_result_block(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            replacement_text=replacement,
            external_path=file_path,
            preview=preview,
            original_size=len(output),
            is_error=is_error,
        )


def enforce_message_budget(
    messages: list[ConversationMessage],
    state: ContentReplacementState,
    store: ContentStore,
    budget: int = PER_MESSAGE_BUDGET,
) -> tuple[list[ConversationMessage], list[ContentReplacementRecord]]:
    """Enforce per-message aggregate budget on tool result sizes.

    Walks through messages. For each group of tool results that would
    appear in a single API-level user message:
      1. Re-apply cached replacements (seen before)
      2. Check if fresh results push the group over budget
      3. Replace largest fresh results if over budget

    Returns (possibly-modified messages, newly-created replacement records).
    """
    replacement_map: dict[str, str] = {}
    to_persist: list[tuple[str, str, int]] = []  # (tool_use_id, content, size)
    newly_replaced: list[ContentReplacementRecord] = []

    groups = _collect_tool_result_groups(messages)

    for group in groups:
        must_reapply = []
        frozen = []
        fresh = []

        for tid, content, size in group:
            if tid in state.replacements:
                must_reapply.append((tid, state.replacements[tid]))
            elif tid in state.seen_ids:
                frozen.append((tid, content, size))
            else:
                fresh.append((tid, content, size))

        for tid, repl in must_reapply:
            replacement_map[tid] = repl

        frozen_size = sum(s for _, _, s in frozen)
        fresh_size = sum(s for _, _, s in fresh)

        if frozen_size + fresh_size <= budget:
            for tid, _, _ in fresh:
                state.seen_ids.add(tid)
            continue

        sorted_fresh = sorted(fresh, key=lambda x: x[2], reverse=True)
        remaining = frozen_size + fresh_size
        selected_ids: set[str] = set()

        for tid, content, size in sorted_fresh:
            if remaining <= budget:
                break
            selected_ids.add(tid)
            remaining -= size
            to_persist.append((tid, content, size))

        for tid, _, _ in fresh:
            if tid not in selected_ids:
                state.seen_ids.add(tid)

    for tid, content, size in to_persist:
        file_path, preview, has_more = store.persist_tool_result(tid, content)
        repl = store.build_replacement_message(file_path, preview, size, has_more)
        replacement_map[tid] = repl
        state.seen_ids.add(tid)
        state.replacements[tid] = repl
        newly_replaced.append(ContentReplacementRecord(
            tool_use_id=tid,
            replacement=repl,
        ))

    if not replacement_map:
        return messages, []

    result = _apply_replacements(messages, replacement_map)
    return result, newly_replaced


def reconstruct_replacement_state(
    messages: list[ConversationMessage],
    records: list[ContentReplacementRecord],
) -> ContentReplacementState:
    """Rebuild replacement state from persisted records (for resume)."""
    state = ContentReplacementState()
    candidate_ids = set()
    for msg in messages:
        if msg.role.value != "tool":
            continue
        for b in msg.blocks:
            if b.type == "tool_result" and b.tool_use_id:
                if not (b.output and b.output.startswith(PERSISTED_OUTPUT_TAG)):
                    candidate_ids.add(b.tool_use_id)

    for cid in candidate_ids:
        state.seen_ids.add(cid)

    for r in records:
        if r.kind == "tool-result" and r.tool_use_id in candidate_ids:
            state.replacements[r.tool_use_id] = r.replacement

    return state


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _collect_tool_result_groups(
    messages: list[ConversationMessage],
) -> list[list[tuple[str, str, int]]]:
    """Group tool result blocks by API-level user message boundary."""
    groups: list[list[tuple[str, str, int]]] = []
    current: list[tuple[str, str, int]] = []

    for msg in messages:
        if msg.role.value == "tool":
            for b in msg.blocks:
                if b.type == "tool_result" and b.tool_use_id and b.output:
                    if b.output.startswith(PERSISTED_OUTPUT_TAG):
                        continue
                    current.append((b.tool_use_id, b.output, len(b.output)))
        elif msg.role.value == "assistant":
            if current:
                groups.append(current)
                current = []

    if current:
        groups.append(current)
    return groups


def _apply_replacements(
    messages: list[ConversationMessage],
    replacement_map: dict[str, str],
) -> list[ConversationMessage]:
    result = []
    for msg in messages:
        if msg.role.value != "tool":
            result.append(msg)
            continue
        needs_replace = any(
            b.type == "tool_result" and b.tool_use_id in replacement_map
            for b in msg.blocks
        )
        if not needs_replace:
            result.append(msg)
            continue
        new_blocks = []
        for b in msg.blocks:
            if b.type == "tool_result" and b.tool_use_id in replacement_map:
                new_blocks.append(b.model_copy(update={
                    "output": replacement_map[b.tool_use_id],
                }))
            else:
                new_blocks.append(b)
        result.append(msg.model_copy(update={"blocks": new_blocks}))
    return result


def _fmt(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    return f"{size / 1024:.1f}KB"
