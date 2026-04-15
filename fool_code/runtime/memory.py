"""Dynamic user memory system — user profile and collaboration preferences."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fool_code.runtime.config import app_data_root, read_config_root

logger = logging.getLogger(__name__)

MAX_MEMORY_INJECT_CHARS = 2_000
MAX_MEMORY_PER_TYPE_CHARS = 1_200

MEMORY_TYPES: dict[str, dict[str, str]] = {
    "user": {
        "filename": "user.md",
        "title": "基本信息",
        "description": "记录用户的角色、技术背景、工作目标、知识水平等",
        "template": (
            "# 用户画像\n\n"
            "<!-- 在这里记录你的角色、技术背景、工作目标等，AI 会据此调整回答方式 -->\n\n"
        ),
    },
    "feedback": {
        "filename": "feedback.md",
        "title": "协作偏好",
        "description": "记录用户对 AI 的协作风格偏好",
        "template": (
            "# 协作偏好\n\n"
            "<!-- 在这里记录你希望 AI 遵守的协作方式，例如：\n"
            "  - 回答风格偏好（简洁/详细）\n"
            "  - 代码风格偏好\n"
            "  - 不希望 AI 做的事\n"
            "-->\n\n"
        ),
    },
}


def memory_dir() -> Path:
    return app_data_root() / "memory"


def ensure_memory_dir() -> Path:
    d = memory_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_memory_enabled() -> bool:
    root = read_config_root()
    return bool(root.get("autoMemoryEnabled", True))


def read_memory(memory_type: str) -> str | None:
    spec = MEMORY_TYPES.get(memory_type)
    if spec is None:
        return None
    path = memory_dir() / spec["filename"]
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
        return content if content else None
    except (OSError, UnicodeDecodeError):
        return None


def write_memory(memory_type: str, content: str) -> bool:
    spec = MEMORY_TYPES.get(memory_type)
    if spec is None:
        return False
    d = ensure_memory_dir()
    path = d / spec["filename"]
    path.write_text(content, encoding="utf-8")
    logger.info("Memory written: %s (%d chars)", memory_type, len(content))
    return True


def memory_has_content(memory_type: str) -> bool:
    content = read_memory(memory_type)
    if content is None:
        return False
    stripped = _strip_template_comments(content)
    return bool(stripped.strip())


def memory_preview(memory_type: str, max_chars: int = 100) -> str:
    content = read_memory(memory_type)
    if not content:
        return ""
    stripped = _strip_template_comments(content)
    if not stripped.strip():
        return ""
    flat = " ".join(stripped.split())
    if len(flat) <= max_chars:
        return flat
    return flat[:max_chars] + "…"


def load_all_memory() -> str | None:
    if not is_memory_enabled():
        return None

    sections: list[str] = []
    remaining = MAX_MEMORY_INJECT_CHARS

    for mem_type, spec in MEMORY_TYPES.items():
        if remaining <= 0:
            break
        content = read_memory(mem_type)
        if not content:
            continue
        stripped = _strip_template_comments(content)
        if not stripped.strip():
            continue

        if len(stripped) > remaining:
            stripped = stripped[:remaining] + "\n\n[truncated]"
        remaining -= len(stripped)

        sections.append(f"## {spec['title']}\n\n{stripped.strip()}")

    if not sections:
        return None

    return "# 用户画像\n\n" + "\n\n".join(sections)


def list_memory_types() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for mem_type, spec in MEMORY_TYPES.items():
        result.append({
            "type": mem_type,
            "title": spec["title"],
            "description": spec["description"],
            "has_content": memory_has_content(mem_type),
            "preview": memory_preview(mem_type),
        })
    return result


def get_memory_template(memory_type: str) -> str:
    spec = MEMORY_TYPES.get(memory_type)
    if spec is None:
        return ""
    return spec["template"]


def _strip_template_comments(content: str) -> str:
    """Remove HTML comments from content for checking if there's real user input."""
    import re
    return re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Memory compression — merge & deduplicate when a memory type grows too large
# ---------------------------------------------------------------------------

COMPRESS_SYSTEM_PROMPT = """\
你是一个记忆压缩专家。你的任务是将一份长期记忆笔记压缩合并成更精炼的版本。

规则：
- 合并语义重复和相似的条目（同一件事只保留一条）
- 如果后面的内容和前面矛盾，以后面的为准（更新覆盖旧信息）
- 保留所有重要的、不重复的信息，不丢失关键偏好
- 保持 "- " 开头的列表格式
- 压缩后总长度控制在原文的 40-60%
- 只输出压缩后的正文内容，不要加标题行、不要加解释说明"""

COMPRESS_USER_TEMPLATE = """\
以下是「{title}」的当前全部内容（{char_count} 字符），请压缩合并为更精炼的版本：

---
{content}
---

请输出压缩后的版本（只输出列表内容，不要加标题）："""


def _maybe_compress_memory(mem_type: str, workspace_root=None) -> bool:
    """Compress a memory type if it exceeds the per-type threshold.

    Uses the memory-role LLM to merge duplicates and produce a concise version.
    Returns True if compression was performed.
    """
    content = read_memory(mem_type)
    if not content:
        return False

    stripped = _strip_template_comments(content)
    if len(stripped.strip()) <= MAX_MEMORY_PER_TYPE_CHARS:
        return False

    from fool_code.runtime.subagent import create_role_provider

    provider = create_role_provider("memory", workspace_root)
    if provider is None:
        logger.debug("Memory compression skipped: no provider for 'memory' role")
        return False

    spec = MEMORY_TYPES[mem_type]
    prompt = COMPRESS_USER_TEMPLATE.format(
        title=spec["title"],
        char_count=len(stripped),
        content=stripped.strip(),
    )

    try:
        result = provider.simple_chat(
            [{"role": "user", "content": prompt}],
            system=COMPRESS_SYSTEM_PROMPT,
            max_tokens=1024,
        )
        provider.close()
    except Exception as exc:
        logger.warning("Memory compression LLM call failed (%s): %s", mem_type, exc)
        return False

    if not result or not result.strip():
        logger.debug("Memory compression returned empty result for %s", mem_type)
        return False

    compressed_body = result.strip()
    if len(compressed_body) >= len(stripped.strip()):
        logger.debug("Memory compression did not reduce size for %s, skipping", mem_type)
        return False

    compressed = f"# {spec['title']}\n\n{compressed_body}\n"
    before_len = len(stripped.strip())
    after_len = len(compressed_body)
    write_memory(mem_type, compressed)
    logger.info(
        "Memory compressed: %s (%d -> %d chars, %.0f%% reduction)",
        mem_type, before_len, after_len,
        (1 - after_len / before_len) * 100 if before_len else 0,
    )
    return True


# ---------------------------------------------------------------------------
# Auto-extraction — runs after each conversation turn
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
你是一个记忆提取子代理。你的任务是分析用户和 AI 助手的最近对话，从中提取值得长期记住的信息。

你需要输出一个 JSON 对象，包含两个字段：
- "user": 关于用户画像的新发现（角色、技术背景、工作目标、知识水平等）。如果没有新发现则为 null。
- "feedback": 关于协作偏好的新发现（回答风格、代码风格、交互方式等通用偏好）。如果没有新发现则为 null。

规则：
- 只提取对话中**明确体现**的信息，不要推测
- 不要重复已有记忆中已经存在的信息
- 每条内容简洁明了，用 "- " 开头的列表格式
- 如果这轮对话没有值得记忆的新信息，两个字段都返回 null
- 不要记录具体的代码实现细节或一次性的技术问题
- 不要记录具体的操作步骤（如鼠标坐标、文件路径、命令输出）
- 不要记录单次对话中的临时事件（如某次测试的具体过程）
- user 字段重点关注：用户是谁、用什么技术栈、做什么类型的工作
- feedback 字段重点关注：用户反复表达的通用偏好，而非某次操作的细节

只输出 JSON，不要输出其他内容。"""

EXTRACTION_USER_TEMPLATE = """\
## 已有记忆

### 用户画像
{existing_user}

### 协作偏好
{existing_feedback}

## 最近对话

{recent_messages}

请分析以上对话，提取值得记忆的新信息。输出 JSON 格式：
{{"user": "...", "feedback": "..."}}"""


def extract_memories_from_turn(
    messages: list[dict],
    workspace_root=None,
) -> bool:
    """Analyze recent messages and extract memories using the memory-role model.

    Returns True if any memory was updated.
    """
    from fool_code.runtime.subagent import create_role_provider

    if not is_memory_enabled():
        return False

    provider = create_role_provider("memory", workspace_root)
    if provider is None:
        logger.info("Memory extraction skipped: no provider available")
        return False

    recent = _format_recent_messages(messages, max_messages=8)
    if not recent.strip():
        return False

    existing_user = read_memory("user") or "(空)"
    existing_feedback = read_memory("feedback") or "(空)"

    user_prompt = EXTRACTION_USER_TEMPLATE.format(
        existing_user=existing_user,
        existing_feedback=existing_feedback,
        recent_messages=recent,
    )

    try:
        result = provider.simple_chat(
            [{"role": "user", "content": user_prompt}],
            system=EXTRACTION_SYSTEM_PROMPT,
            max_tokens=1024,
        )
        provider.close()
    except Exception as exc:
        logger.warning("Memory extraction LLM call failed: %s", exc)
        return False

    return _apply_extraction_result(result, workspace_root)


def _format_recent_messages(messages: list[dict], max_messages: int = 8) -> str:
    """Format the most recent conversation messages for the extraction prompt."""
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if not content or role not in ("user", "assistant"):
            continue
        if isinstance(content, list):
            text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = "\n".join(text_parts)
        if len(content) > 500:
            content = content[:500] + "…"
        label = "用户" if role == "user" else "助手"
        lines.append(f"**{label}**: {content}")
    return "\n\n".join(lines)


def _apply_extraction_result(raw_result: str, workspace_root=None) -> bool:
    """Parse LLM extraction result and merge into memory files."""
    import re

    raw_result = raw_result.strip()
    json_match = re.search(r"\{.*\}", raw_result, re.DOTALL)
    if not json_match:
        logger.debug("Memory extraction: no JSON found in response")
        return False

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.debug("Memory extraction: invalid JSON in response")
        return False

    updated = False

    for mem_type in ("user", "feedback"):
        new_content = data.get(mem_type)
        if not new_content or not isinstance(new_content, str) or not new_content.strip():
            continue

        existing = read_memory(mem_type) or ""
        stripped_existing = _strip_template_comments(existing)

        if new_content.strip() in stripped_existing:
            continue

        if stripped_existing.strip():
            merged = existing.rstrip() + "\n\n" + new_content.strip() + "\n"
        else:
            spec = MEMORY_TYPES[mem_type]
            merged = f"# {spec['title']}\n\n{new_content.strip()}\n"

        write_memory(mem_type, merged)
        updated = True
        logger.info("Memory auto-extracted: %s (+%d chars)", mem_type, len(new_content))

    if updated:
        for mem_type in ("user", "feedback"):
            try:
                _maybe_compress_memory(mem_type, workspace_root)
            except Exception as exc:
                logger.debug("Memory compression check failed for %s: %s", mem_type, exc)

    return updated
