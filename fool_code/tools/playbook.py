"""Playbook tool — lets the AI browse and read user experience documents."""

from __future__ import annotations

import json
from typing import Any

from fool_code.runtime.playbook import (
    read_playbook,
    scan_playbooks,
)


def playbook_tool(args: dict[str, Any]) -> str:
    action = (args.get("action") or "").strip().lower()

    if action == "categories":
        return _list_categories()
    elif action == "list":
        category = (args.get("category") or "").strip()
        return _list_docs(category)
    elif action == "read":
        category = (args.get("category") or "").strip()
        filename = (args.get("filename") or "").strip()
        if not category or not filename:
            return json.dumps({"error": "category and filename are required for action='read'"})
        return _read_doc(category, filename)
    else:
        return json.dumps({
            "error": f"Unknown action: {action!r}. Use 'categories', 'list', or 'read'.",
        })


def _list_categories() -> str:
    categories = scan_playbooks()
    if not categories:
        return json.dumps({"categories": [], "message": "用户尚未创建经验文档"})
    result = []
    for cat in categories:
        result.append({
            "name": cat["name"],
            "description": cat.get("description", ""),
            "doc_count": len(cat["documents"]),
        })
    return json.dumps({"categories": result}, ensure_ascii=False)


def _list_docs(category: str) -> str:
    categories = scan_playbooks()
    if not categories:
        return json.dumps({"categories": [], "message": "用户尚未创建经验文档"})

    if not category:
        result = []
        for cat in categories:
            result.append({
                "name": cat["name"],
                "description": cat.get("description", ""),
                "documents": cat["documents"],
            })
        return json.dumps({"categories": result}, ensure_ascii=False)

    for cat in categories:
        if cat["name"] == category:
            return json.dumps({
                "category": cat["name"],
                "description": cat.get("description", ""),
                "documents": cat["documents"],
            }, ensure_ascii=False)

    return json.dumps({"error": f"分类 '{category}' 不存在"})


def _read_doc(category: str, filename: str) -> str:
    if not filename.endswith(".md"):
        filename += ".md"
    content = read_playbook(category, filename)
    if content is None:
        return json.dumps({"error": f"文档 '{category}/{filename}' 不存在"})
    return json.dumps({
        "category": category,
        "filename": filename,
        "content": content,
    }, ensure_ascii=False)
