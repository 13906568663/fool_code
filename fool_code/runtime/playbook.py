"""Playbook experience documents — user-maintained categorized knowledge base.

Users organize experience documents (.md files) into category directories.
The system scans the directory structure, maintains a lightweight index,
and injects only the category summary into the system prompt. The AI
retrieves specific documents on demand via the Playbook tool.

Storage layout:
    ~/.fool-code/playbooks/
        _index.json
        <category-dir>/
            <doc>.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fool_code.runtime.config import app_data_root

logger = logging.getLogger(__name__)

PLAYBOOK_DIR_NAME = "playbooks"
INDEX_FILENAME = "_index.json"

DOCUMENT_TEMPLATE = """\
# {title}

## 场景
<!-- 什么情况下会用到这个经验 -->

## 步骤
1. ...
2. ...

## 注意事项
- ...

## 相关命令
```
...
```
"""


def playbooks_dir() -> Path:
    return app_data_root() / PLAYBOOK_DIR_NAME


def ensure_playbooks_dir() -> Path:
    d = playbooks_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Scanning & indexing
# ---------------------------------------------------------------------------

def scan_playbooks() -> list[dict[str, Any]]:
    """Scan the playbooks directory and return a list of categories.

    Each category dict: {"name", "description", "documents": [{"filename", "title"}]}
    """
    pdir = playbooks_dir()
    if not pdir.is_dir():
        return []

    index = _load_index()
    desc_map = {c["name"]: c.get("description", "") for c in index.get("categories", [])}

    categories: list[dict[str, Any]] = []
    for entry in sorted(pdir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        docs = _scan_category_docs(entry)
        categories.append({
            "name": entry.name,
            "description": desc_map.get(entry.name, ""),
            "documents": docs,
        })

    return categories


def _scan_category_docs(category_path: Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for md in sorted(category_path.glob("*.md")):
        title = _extract_title(md)
        docs.append({"filename": md.name, "title": title})
    return docs


def _extract_title(path: Path) -> str:
    """Extract the first H1 heading from a markdown file, or use the stem."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    except (OSError, UnicodeDecodeError):
        pass
    return path.stem


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

def _index_path() -> Path:
    return playbooks_dir() / INDEX_FILENAME


def _load_index() -> dict[str, Any]:
    p = _index_path()
    if not p.is_file():
        return {"categories": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"categories": []}


def rebuild_index() -> dict[str, Any]:
    """Rebuild _index.json from the current directory structure.

    Preserves existing category descriptions while adding new categories
    and removing stale ones.
    """
    categories = scan_playbooks()
    old_index = _load_index()
    old_desc = {c["name"]: c.get("description", "") for c in old_index.get("categories", [])}

    new_cats: list[dict[str, Any]] = []
    for cat in categories:
        new_cats.append({
            "name": cat["name"],
            "description": old_desc.get(cat["name"], cat.get("description", "")),
            "doc_count": len(cat["documents"]),
        })

    index = {"categories": new_cats}
    pdir = ensure_playbooks_dir()
    (pdir / INDEX_FILENAME).write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index


def save_category_description(category: str, description: str) -> None:
    """Update the description of a category in the index."""
    index = _load_index()
    cats = index.get("categories", [])
    found = False
    for c in cats:
        if c["name"] == category:
            c["description"] = description
            found = True
            break
    if not found:
        cats.append({"name": category, "description": description, "doc_count": 0})
    index["categories"] = cats
    pdir = ensure_playbooks_dir()
    (pdir / INDEX_FILENAME).write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Document read / write
# ---------------------------------------------------------------------------

def read_playbook(category: str, filename: str) -> str | None:
    path = playbooks_dir() / category / filename
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write_playbook(category: str, filename: str, content: str) -> Path:
    cat_dir = ensure_playbooks_dir() / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    path = cat_dir / filename
    path.write_text(content, encoding="utf-8")
    rebuild_index()
    return path


def delete_playbook(category: str, filename: str) -> bool:
    path = playbooks_dir() / category / filename
    if not path.is_file():
        return False
    path.unlink()
    if not any(path.parent.glob("*.md")):
        try:
            path.parent.rmdir()
        except OSError:
            pass
    rebuild_index()
    return True


def create_category(name: str, description: str = "") -> Path:
    cat_dir = ensure_playbooks_dir() / name
    cat_dir.mkdir(parents=True, exist_ok=True)
    if description:
        save_category_description(name, description)
    else:
        rebuild_index()
    return cat_dir


def delete_category(name: str) -> bool:
    import shutil
    cat_dir = playbooks_dir() / name
    if not cat_dir.is_dir():
        return False
    shutil.rmtree(cat_dir)
    rebuild_index()
    return True


def get_document_template(title: str = "新经验文档") -> str:
    return DOCUMENT_TEMPLATE.format(title=title)


# ---------------------------------------------------------------------------
# Prompt injection — lightweight category summary
# ---------------------------------------------------------------------------

def playbook_summary_for_prompt() -> str | None:
    """Generate a short summary of playbook categories for system prompt injection.

    Returns None if no playbooks exist.
    """
    categories = scan_playbooks()
    if not categories:
        return None

    lines = [
        "# 经验文档库",
        "用户维护了以下经验分类，需要时可用 Playbook 工具查阅具体文档：",
    ]
    for cat in categories:
        doc_count = len(cat["documents"])
        desc = cat["description"]
        if desc:
            lines.append(f"- {cat['name']}（{doc_count} 篇）：{desc}")
        else:
            doc_names = "、".join(d["title"] for d in cat["documents"][:3])
            if len(cat["documents"]) > 3:
                doc_names += " 等"
            lines.append(f"- {cat['name']}（{doc_count} 篇）：{doc_names}")

    return "\n".join(lines)
