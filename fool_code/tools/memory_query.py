"""MemoryQuery tool — lets the LLM query MAGMA episodic memory on demand."""

from __future__ import annotations

import logging
from typing import Any

from fool_code.tools.tool_protocol import ToolContext

logger = logging.getLogger(__name__)


def memory_query_tool(args: dict[str, Any], ctx: ToolContext) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "请提供查询内容。"

    try:
        from fool_code.magma.retriever import retrieve_context

        result = retrieve_context(query, ctx.workspace_root)
    except Exception as exc:
        logger.warning("MemoryQuery failed: %s", exc)
        return f"记忆查询失败: {exc}"

    if not result or not result.text.strip():
        return f"未找到与「{query}」相关的历史活动记录。"

    return (
        f"找到 {result.node_count} 条相关记录 "
        f"(约 {result.token_estimate} tokens):\n\n"
        + result.text
    )
