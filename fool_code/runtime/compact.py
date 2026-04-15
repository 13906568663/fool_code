"""Session compaction — summarize old messages to reduce context length."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from fool_code.types import ContentBlock, ConversationMessage, MessageRole, Session

logger = logging.getLogger(__name__)

COMPACT_CONTINUATION_PREAMBLE = (
    "本次会话是从之前的对话延续的，之前的对话上下文已超出限制。"
    "以下摘要涵盖了对话早期的内容。\n\n"
)
COMPACT_RECENT_MESSAGES_NOTE = "最近的消息已原样保留。"
COMPACT_DIRECT_RESUME_INSTRUCTION = (
    "从上次中断的地方继续对话，不要向用户提出任何进一步的问题。"
    "直接继续——不要确认摘要，不要回顾之前的内容，也不要添加"
    "任何过渡性文字。"
)

# ---------------------------------------------------------------------------
# CC-style LLM summarization prompt
# ---------------------------------------------------------------------------

COMPACT_SYSTEM_PROMPT = (
    "重要：仅以纯文本回复，不要调用任何工具。\n\n"
    "- 不要使用任何工具调用。\n"
    "- 你已经拥有对话中所有需要的上下文信息。\n"
    "- 工具调用会被拒绝并浪费你唯一的回合——你将无法完成任务。\n"
    "- 你的整个回复必须是纯文本：先输出 <analysis> 块，再输出 <summary> 块。\n\n"
    "你是一个负责总结对话的 AI 助手。"
)

COMPACT_USER_PROMPT = """\
你的任务是为目前为止的对话创建一份详细的摘要，密切关注用户的明确请求和你之前的操作。
这份摘要应当全面捕获技术细节、代码模式和架构决策，这些对于在不丢失上下文的情况下继续开发工作至关重要。

在提供最终摘要之前，请将你的分析过程包裹在 <analysis> 标签中，以整理思路并确保涵盖所有必要的要点。在分析过程中：

1. 按时间顺序分析对话中的每条消息和每个部分。对于每个部分，彻底识别：
   - 用户的明确请求和意图
   - 你处理用户请求的方式
   - 关键决策、技术概念和代码模式
   - 具体细节，例如：
     - 文件名
     - 完整代码片段
     - 函数签名
     - 文件编辑
   - 你遇到的错误以及如何修复
   - 特别注意你收到的用户反馈，尤其是用户要求你以不同方式做事的情况。
2. 仔细检查技术准确性和完整性，确保每个必需的要素都被充分涵盖。

你的摘要应包含以下章节：

1. 主要请求和意图：详细捕获用户所有明确的请求和意图
2. 关键技术概念：列出讨论过的所有重要技术概念、技术栈和框架。
3. 文件和代码部分：列举检查、修改或创建的具体文件和代码部分。特别关注最近的消息，尽可能包含完整代码片段，并总结为什么这个文件的读取或编辑很重要。
4. 错误和修复：列出你遇到的所有错误以及修复方式。特别注意用户的具体反馈，尤其是用户要求你以不同方式做事的情况。
5. 问题解决：记录已解决的问题和正在进行的故障排查工作。
6. 所有用户消息：列出所有非工具结果的用户消息。这些对于理解用户的反馈和变化的意图至关重要。
7. 待处理任务：列出用户明确要求你处理的所有待完成任务。
8. 当前工作：详细描述在此摘要请求之前正在进行的确切工作，特别关注用户和助手最近的消息。尽可能包含文件名和代码片段。
9. 可选的下一步：列出与你最近工作相关的下一个步骤。重要提示：确保此步骤直接符合用户最近的明确请求以及你在此摘要请求之前正在处理的任务。

请基于目前的对话提供你的摘要，遵循上述结构并确保精确和全面。
请将分析输出在 <analysis> 标签中，将最终摘要输出在 <summary> 标签中。"""


@dataclass
class CompactionConfig:
    preserve_recent_messages: int = 4
    max_estimated_tokens: int = 100_000


@dataclass
class CompactionResult:
    summary: str = ""
    formatted_summary: str = ""
    compacted_session: Session = field(default_factory=Session)
    removed_message_count: int = 0
    boundary_msg: ConversationMessage | None = None
    summary_msg: ConversationMessage | None = None


def estimate_session_tokens(session: Session) -> int:
    return sum(_estimate_message_tokens(m) for m in session.messages)


def should_compact(session: Session, config: CompactionConfig) -> bool:
    msgs = get_messages_after_compact_boundary(session.messages)
    if len(msgs) <= config.preserve_recent_messages:
        return False
    return (
        sum(_estimate_message_tokens(m) for m in msgs)
        >= config.max_estimated_tokens
    )


def format_compact_summary(summary: str) -> str:
    without_analysis = _strip_tag_block(summary, "analysis")
    content = _extract_tag_block(without_analysis, "summary")
    if content is not None:
        formatted = without_analysis.replace(
            f"<summary>{content}</summary>",
            f"摘要：\n{content.strip()}",
        )
    else:
        formatted = without_analysis
    return _collapse_blank_lines(formatted).strip()


def get_compact_continuation_message(
    summary: str,
    suppress_follow_up: bool,
    recent_preserved: bool,
) -> str:
    base = COMPACT_CONTINUATION_PREAMBLE + format_compact_summary(summary)
    if recent_preserved:
        base += "\n\n" + COMPACT_RECENT_MESSAGES_NOTE
    if suppress_follow_up:
        base += "\n" + COMPACT_DIRECT_RESUME_INSTRUCTION
    return base


def compact_session(
    session: Session, config: CompactionConfig
) -> CompactionResult:
    if not should_compact(session, config):
        return CompactionResult(
            compacted_session=session.model_copy(deep=True),
        )

    post_boundary = get_messages_after_compact_boundary(session.messages)

    keep_count = config.preserve_recent_messages
    if len(post_boundary) <= keep_count:
        return CompactionResult(
            compacted_session=session.model_copy(deep=True),
        )

    removed = post_boundary[:-keep_count] if keep_count > 0 else post_boundary
    preserved = post_boundary[-keep_count:] if keep_count > 0 else []

    new_summary_text = _summarize_messages(removed)
    existing_summary = _extract_existing_compacted_summary_from_boundary(session)
    summary = _merge_compact_summaries(existing_summary, new_summary_text)
    formatted = format_compact_summary(summary)
    continuation = get_compact_continuation_message(
        summary, suppress_follow_up=True, recent_preserved=True
    )

    boundary_msg = ConversationMessage(
        role=MessageRole.system,
        blocks=[ContentBlock.text_block("compact_boundary")],
        is_compact_boundary=True,
    )
    summary_msg = ConversationMessage(
        role=MessageRole.user,
        blocks=[ContentBlock.text_block(continuation)],
        is_compact_summary=True,
        is_visible_in_transcript_only=True,
    )

    # Keep all original messages, then insert boundary + summary + preserved recent
    pre_boundary_msgs = session.messages[:len(session.messages) - len(post_boundary)]
    new_messages = pre_boundary_msgs + removed + [boundary_msg, summary_msg] + preserved

    return CompactionResult(
        summary=summary,
        formatted_summary=formatted,
        compacted_session=Session(
            version=session.version,
            messages=new_messages,
            chat_model=session.chat_model,
            chat_provider_id=session.chat_provider_id,
            plan_slug=session.plan_slug,
            plan_status=session.plan_status,
        ),
        removed_message_count=len(removed),
        boundary_msg=boundary_msg,
        summary_msg=summary_msg,
    )


def compact_session_with_llm(
    session: Session,
    provider: Any,
    config: CompactionConfig | None = None,
) -> CompactionResult:
    """Use LLM to generate a high-quality conversation summary.

    Falls back to rule-based ``compact_session()`` if the LLM call fails.
    """
    if config is None:
        config = CompactionConfig()

    if not should_compact(session, config):
        return CompactionResult(compacted_session=session.model_copy(deep=True))

    post_boundary = get_messages_after_compact_boundary(session.messages)

    keep_count = config.preserve_recent_messages
    if len(post_boundary) <= keep_count:
        return CompactionResult(compacted_session=session.model_copy(deep=True))

    removed = post_boundary[:-keep_count] if keep_count > 0 else post_boundary
    preserved = post_boundary[-keep_count:] if keep_count > 0 else []

    from fool_code.runtime.message_pipeline import normalize_for_api  # late import to avoid circular dependency

    api_messages = normalize_for_api(removed)
    api_messages.append({"role": "user", "content": COMPACT_USER_PROMPT})

    try:
        llm_response = provider.simple_chat(
            messages=api_messages,
            system=COMPACT_SYSTEM_PROMPT,
            max_tokens=16_000,
        )
    except Exception as exc:
        logger.warning("LLM compact failed (%s), falling back to rule-based", exc)
        return compact_session(session, config)

    if not llm_response or not llm_response.strip():
        logger.warning("LLM compact returned empty response, falling back to rule-based")
        return compact_session(session, config)

    existing_summary = _extract_existing_compacted_summary_from_boundary(session)
    merged = _merge_compact_summaries(existing_summary, llm_response) if existing_summary else llm_response

    formatted = format_compact_summary(merged)
    continuation = get_compact_continuation_message(
        merged, suppress_follow_up=True, recent_preserved=True,
    )

    boundary_msg = ConversationMessage(
        role=MessageRole.system,
        blocks=[ContentBlock.text_block("compact_boundary")],
        is_compact_boundary=True,
    )
    summary_msg = ConversationMessage(
        role=MessageRole.user,
        blocks=[ContentBlock.text_block(continuation)],
        is_compact_summary=True,
        is_visible_in_transcript_only=True,
    )

    pre_boundary_msgs = session.messages[: len(session.messages) - len(post_boundary)]
    new_messages = pre_boundary_msgs + removed + [boundary_msg, summary_msg] + preserved

    return CompactionResult(
        summary=merged,
        formatted_summary=formatted,
        compacted_session=Session(
            version=session.version,
            messages=new_messages,
            chat_model=session.chat_model,
            chat_provider_id=session.chat_provider_id,
            plan_slug=session.plan_slug,
            plan_status=session.plan_status,
        ),
        removed_message_count=len(removed),
        boundary_msg=boundary_msg,
        summary_msg=summary_msg,
    )


# ---- Public helpers ----

def get_messages_after_compact_boundary(
    messages: list[ConversationMessage],
) -> list[ConversationMessage]:
    """Return messages after the last compact_boundary (excluding boundary itself)."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].is_compact_boundary:
            return messages[i + 1:]
    return messages


# ---- Internal helpers ----

def _compacted_summary_prefix_len(session: Session) -> int:
    return 1 if _extract_existing_compacted_summary(session) is not None else 0


def _extract_existing_compacted_summary_from_boundary(
    session: Session,
) -> str | None:
    """Extract summary text from the summary message following the last boundary."""
    for i in range(len(session.messages) - 1, -1, -1):
        if session.messages[i].is_compact_boundary:
            for j in range(i + 1, len(session.messages)):
                if session.messages[j].is_compact_summary:
                    text = _first_text_block(session.messages[j])
                    if text and text.startswith(COMPACT_CONTINUATION_PREAMBLE):
                        rest = text[len(COMPACT_CONTINUATION_PREAMBLE):]
                        for sentinel in [
                            f"\n\n{COMPACT_RECENT_MESSAGES_NOTE}",
                            f"\n{COMPACT_DIRECT_RESUME_INSTRUCTION}",
                        ]:
                            idx = rest.find(sentinel)
                            if idx != -1:
                                rest = rest[:idx]
                        return rest.strip()
                break
    return _extract_existing_compacted_summary(session)


def _extract_existing_compacted_summary(session: Session) -> str | None:
    if not session.messages:
        return None
    msg = session.messages[0]
    if msg.role != MessageRole.system:
        return None
    text = _first_text_block(msg)
    if text is None:
        return None
    if not text.startswith(COMPACT_CONTINUATION_PREAMBLE):
        return None
    rest = text[len(COMPACT_CONTINUATION_PREAMBLE):]
    for sentinel in [
        f"\n\n{COMPACT_RECENT_MESSAGES_NOTE}",
        f"\n{COMPACT_DIRECT_RESUME_INSTRUCTION}",
    ]:
        idx = rest.find(sentinel)
        if idx != -1:
            rest = rest[:idx]
    return rest.strip()


def _summarize_messages(messages: list[ConversationMessage]) -> str:
    user_count = sum(1 for m in messages if m.role == MessageRole.user)
    assistant_count = sum(1 for m in messages if m.role == MessageRole.assistant)
    tool_count = sum(1 for m in messages if m.role == MessageRole.tool)

    tool_names: list[str] = []
    for m in messages:
        for b in m.blocks:
            if b.type == "tool_use" and b.name:
                tool_names.append(b.name)
            elif b.type == "tool_result" and b.tool_name:
                tool_names.append(b.tool_name)
    tool_names = sorted(set(tool_names))

    lines = [
        "<summary>",
        "对话摘要：",
        f"- 范围：已压缩 {len(messages)} 条历史消息 "
        f"(用户={user_count}, 助手={assistant_count}, 工具={tool_count})。",
    ]
    if tool_names:
        lines.append(f"- 涉及工具：{', '.join(tool_names)}。")

    recent_user = _collect_recent_role_summaries(messages, MessageRole.user, 3)
    if recent_user:
        lines.append("- 最近的用户请求：")
        lines.extend(f"  - {r}" for r in recent_user)

    pending = _infer_pending_work(messages)
    if pending:
        lines.append("- 待处理工作：")
        lines.extend(f"  - {p}" for p in pending)

    key_files = _collect_key_files(messages)
    if key_files:
        lines.append(f"- 关键文件引用：{', '.join(key_files)}。")

    current = _infer_current_work(messages)
    if current:
        lines.append(f"- 当前工作：{current}")

    lines.append("- 关键时间线：")
    for m in messages:
        role = m.role.value
        content = " | ".join(_summarize_block(b) for b in m.blocks)
        lines.append(f"  - {role}: {content}")

    lines.append("</summary>")
    return "\n".join(lines)


def _merge_compact_summaries(existing: str | None, new_summary: str) -> str:
    if existing is None:
        return new_summary

    prev_highlights = _extract_summary_highlights(existing)
    new_formatted = format_compact_summary(new_summary)
    new_highlights = _extract_summary_highlights(new_formatted)
    new_timeline = _extract_summary_timeline(new_formatted)

    lines = ["<summary>", "对话摘要："]
    if prev_highlights:
        lines.append("- 之前压缩的上下文：")
        lines.extend(f"  {h}" for h in prev_highlights)
    if new_highlights:
        lines.append("- 新压缩的上下文：")
        lines.extend(f"  {h}" for h in new_highlights)
    if new_timeline:
        lines.append("- 关键时间线：")
        lines.extend(f"  {t}" for t in new_timeline)
    lines.append("</summary>")
    return "\n".join(lines)


def _summarize_block(block: ContentBlock) -> str:
    if block.type == "text":
        raw = block.text or ""
    elif block.type == "tool_use":
        raw = f"工具调用 {block.name}({block.input})"
    elif block.type == "tool_result":
        err = "错误 " if block.is_error else ""
        raw = f"工具结果 {block.tool_name}: {err}{block.output or ''}"
    elif block.type == "image":
        raw = "[图片]"
    else:
        raw = ""
    return _truncate_summary(raw, 160)


def _collect_recent_role_summaries(
    messages: list[ConversationMessage], role: MessageRole, limit: int
) -> list[str]:
    results: list[str] = []
    for m in reversed(messages):
        if m.role != role:
            continue
        text = _first_text_block(m)
        if text:
            results.append(_truncate_summary(text, 160))
        if len(results) >= limit:
            break
    results.reverse()
    return results


def _infer_pending_work(messages: list[ConversationMessage]) -> list[str]:
    results: list[str] = []
    for m in reversed(messages):
        text = _first_text_block(m)
        if text is None:
            continue
        low = text.lower()
        if any(kw in low for kw in ("todo", "next", "pending", "follow up", "remaining")):
            results.append(_truncate_summary(text, 160))
        if len(results) >= 3:
            break
    results.reverse()
    return results


def _collect_key_files(messages: list[ConversationMessage]) -> list[str]:
    candidates: set[str] = set()
    for m in messages:
        for b in m.blocks:
            for field_val in (b.text, b.input, b.output):
                if field_val:
                    candidates.update(_extract_file_candidates(field_val))
    return sorted(candidates)[:8]


_INTERESTING_EXTS = frozenset(("rs", "ts", "tsx", "js", "json", "md", "py", "toml"))


def _extract_file_candidates(content: str) -> list[str]:
    result: list[str] = []
    for token in content.split():
        candidate = token.strip(",.;:)('\"` ")
        if "/" not in candidate:
            continue
        ext = candidate.rsplit(".", 1)[-1].lower() if "." in candidate else ""
        if ext in _INTERESTING_EXTS:
            result.append(candidate)
    return result


def _infer_current_work(messages: list[ConversationMessage]) -> str | None:
    for m in reversed(messages):
        text = _first_text_block(m)
        if text and text.strip():
            return _truncate_summary(text, 200)
    return None


def _first_text_block(message: ConversationMessage) -> str | None:
    for b in message.blocks:
        if b.type == "text" and b.text and b.text.strip():
            return b.text
    return None


IMAGE_TOKEN_ESTIMATE = 80_000


def _estimate_message_tokens(message: ConversationMessage) -> int:
    total = 0
    for b in message.blocks:
        if b.type == "text":
            total += len(b.text or "") // 4 + 1
        elif b.type == "tool_use":
            total += (len(b.name or "") + len(b.input or "")) // 4 + 1
        elif b.type == "tool_result":
            total += (len(b.tool_name or "") + len(b.output or "")) // 4 + 1
        elif b.type == "image":
            total += IMAGE_TOKEN_ESTIMATE
    return total


def _truncate_summary(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\u2026"


def _extract_tag_block(content: str, tag: str) -> str | None:
    start = f"<{tag}>"
    end = f"</{tag}>"
    si = content.find(start)
    if si == -1:
        return None
    after = si + len(start)
    ei = content.find(end, after)
    if ei == -1:
        return None
    return content[after:ei]


def _strip_tag_block(content: str, tag: str) -> str:
    start = f"<{tag}>"
    end = f"</{tag}>"
    si = content.find(start)
    ei = content.find(end)
    if si == -1 or ei == -1:
        return content
    return content[:si] + content[ei + len(end):]


def _collapse_blank_lines(content: str) -> str:
    result: list[str] = []
    last_blank = False
    for line in content.splitlines():
        is_blank = not line.strip()
        if is_blank and last_blank:
            continue
        result.append(line)
        last_blank = is_blank
    return "\n".join(result)


def _extract_summary_highlights(summary: str) -> list[str]:
    lines: list[str] = []
    in_timeline = False
    for line in format_compact_summary(summary).splitlines():
        trimmed = line.rstrip()
        if not trimmed or trimmed in (
            "Summary:", "Conversation summary:",
            "摘要：", "对话摘要：",
        ):
            continue
        if trimmed in ("- Key timeline:", "- 关键时间线："):
            in_timeline = True
            continue
        if in_timeline:
            continue
        lines.append(trimmed)
    return lines


def _extract_summary_timeline(summary: str) -> list[str]:
    lines: list[str] = []
    in_timeline = False
    for line in format_compact_summary(summary).splitlines():
        trimmed = line.rstrip()
        if trimmed in ("- Key timeline:", "- 关键时间线："):
            in_timeline = True
            continue
        if not in_timeline:
            continue
        if not trimmed:
            break
        lines.append(trimmed)
    return lines
