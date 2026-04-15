"""File operation tools — read_file, write_file, edit_file.

Includes protections:
  - Token/size limit for read_file (prevent context blowup)
  - Read-file-state tracking + dedup (unchanged reads short-circuit)
  - Write/Edit require prior read of the target file
  - mtime race-condition check before Write/Edit
  - Edit: file size cap, .ipynb interception, quote normalization
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fool_code.runtime.config import active_workspace_root

logger = logging.getLogger(__name__)

# Max content for a single read_file call (~50K tokens at ~4 chars/token)
MAX_READ_CHARS = 200_000

# Max file size for edit_file (1 GiB)
MAX_EDIT_FILE_SIZE = 1 * 1024 * 1024 * 1024

_BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".tif",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".m4v", ".mpeg", ".mpg",
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma", ".aiff", ".opus",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".xz", ".z", ".tgz", ".iso",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".obj", ".lib", ".app",
    ".msi", ".deb", ".rpm",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".pyc", ".pyo", ".class", ".jar", ".war", ".ear", ".node", ".wasm", ".rlib",
    ".sqlite", ".sqlite3", ".db", ".mdb", ".idx",
    ".psd", ".ai", ".eps", ".sketch", ".fig", ".xd", ".blend", ".3ds", ".max",
    ".swf", ".fla",
    ".lockb", ".dat", ".data",
})

# Extensions handled specially (not blocked as binary)
_PDF_EXTENSIONS = frozenset({".pdf"})
_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif",
})

# ---------------------------------------------------------------------------
# Read-file state tracking
# ---------------------------------------------------------------------------

@dataclass
class _ReadRecord:
    mtime: float
    offset: int | None
    limit: int | None
    is_partial: bool
    read_at: float = field(default_factory=time.monotonic)


_state_lock = threading.Lock()
_read_state: dict[str, _ReadRecord] = {}


def _record_read(path: Path, mtime: float, offset: int | None, limit: int | None, is_partial: bool) -> None:
    key = str(path)
    with _state_lock:
        _read_state[key] = _ReadRecord(
            mtime=mtime, offset=offset, limit=limit, is_partial=is_partial,
        )


def _get_read_record(path: Path) -> _ReadRecord | None:
    with _state_lock:
        return _read_state.get(str(path))


def _update_read_after_write(path: Path) -> None:
    """After a successful write/edit, update the read record so subsequent
    reads don't return stale ``file_unchanged``."""
    key = str(path)
    with _state_lock:
        _read_state.pop(key, None)


def reset_read_state() -> None:
    """Clear all read state (useful for session reset)."""
    with _state_lock:
        _read_state.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _binary_extension_reject_message(path: Path) -> str:
    ext = path.suffix.lower()
    return (
        "此工具无法读取二进制文件。"
        f"该文件似乎是 {ext or '(无扩展名)'} 类型的二进制文件。"
        "请使用合适的工具或先将其转换/导出为纯文本。"
    )


def _is_binary_extension_path(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in _BINARY_EXTENSIONS or ext in _PDF_EXTENSIONS or ext in _IMAGE_EXTENSIONS


def _resolve(file_path: str) -> Path:
    p = Path(file_path)
    if p.is_absolute():
        return p.resolve()
    return (active_workspace_root() / p).resolve()


def _resolve_allow_missing(file_path: str) -> Path:
    p = Path(file_path)
    if p.is_absolute():
        candidate = p
    else:
        candidate = active_workspace_root() / p

    try:
        return candidate.resolve()
    except OSError:
        pass

    parent = candidate.parent
    try:
        resolved_parent = parent.resolve()
    except OSError:
        resolved_parent = parent
    return resolved_parent / candidate.name


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _normalize_quotes(s: str) -> str:
    """Normalize curly/smart quotes to straight quotes."""
    return (
        s
        .replace("\u2018", "'").replace("\u2019", "'")
        .replace("\u201c", '"').replace("\u201d", '"')
    )


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

def read_file(args: dict[str, Any]) -> str:
    file_path = args.get("file_path") or args.get("path", "")
    if not file_path:
        raise ValueError("path 参数是必填的")

    path = _resolve(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件未找到：{path}")
    if not path.is_file():
        raise ValueError(f"不是文件：{path}")
    if _is_binary_extension_path(path):
        ext = path.suffix.lower()
        if ext in _PDF_EXTENSIONS:
            return _read_pdf(path)
        if ext in _IMAGE_EXTENSIONS:
            return _read_image_stub(path)
        raise ValueError(_binary_extension_reject_message(path))

    offset = args.get("offset")
    limit = args.get("limit")
    current_mtime = _safe_mtime(path)

    # --- Dedup check ---
    prev = _get_read_record(path)
    if prev is not None:
        same_range = (prev.offset == (int(offset) if offset is not None else None)
                      and prev.limit == (int(limit) if limit is not None else None))
        if same_range and abs(current_mtime - prev.mtime) < 0.001:
            return json.dumps({
                "type": "file_unchanged",
                "file": {
                    "filePath": str(path),
                    "message": "文件自上次读取以来没有变化。",
                },
            }, ensure_ascii=False, indent=2)

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)

    start_index = int(offset) if offset is not None else 0
    start_index = min(start_index, total_lines)
    if limit is not None:
        end_index = min(start_index + int(limit), total_lines)
    else:
        end_index = total_lines

    selected = lines[start_index:end_index]
    content = "\n".join(selected)
    is_partial = (start_index > 0) or (end_index < total_lines)

    # --- Token limit check ---
    if len(content) > MAX_READ_CHARS:
        truncated_content = content[:MAX_READ_CHARS]
        approx_tokens = len(content) // 4
        _record_read(path, current_mtime, start_index if start_index else None,
                     int(limit) if limit is not None else None, True)
        return json.dumps({
            "type": "text",
            "file": {
                "filePath": str(path),
                "content": truncated_content,
                "numLines": len(selected),
                "startLine": start_index + 1,
                "totalLines": total_lines,
                "truncatedAt": MAX_READ_CHARS,
                "warning": (
                    f"文件内容已在 {MAX_READ_CHARS:,} 字符处截断"
                    f"（约 {approx_tokens:,} tokens）。请使用 offset/limit 参数"
                    "读取指定区段。"
                ),
            },
        }, ensure_ascii=False, indent=2)

    _record_read(
        path, current_mtime,
        start_index if start_index else None,
        int(limit) if limit is not None else None,
        is_partial,
    )

    return json.dumps({
        "type": "text",
        "file": {
            "filePath": str(path),
            "content": content,
            "numLines": len(selected),
            "startLine": start_index + 1,
            "totalLines": total_lines,
        },
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

def write_file(args: dict[str, Any]) -> str:
    file_path = args.get("file_path") or args.get("path", "")
    content = args.get("content", "")
    if not file_path:
        raise ValueError("path 参数是必填的")

    path = _resolve_allow_missing(file_path)
    original_file: str | None = None
    kind = "create"

    if path.exists():
        # --- Must-read-before-write check ---
        prev = _get_read_record(path)
        if prev is None:
            raise ValueError(
                f"写入前必须先读取 {path}。"
                "请先使用 read_file 查看当前内容。"
            )
        # --- mtime race check ---
        current_mtime = _safe_mtime(path)
        if current_mtime - prev.mtime > 0.5:
            raise ValueError(
                f"文件 {path} 在你上次读取之后被修改过"
                f"（读取时 mtime={prev.mtime:.3f}，当前={current_mtime:.3f}）。"
                "请重新读取文件后再写入。"
            )
        # --- Partial-view warning ---
        if prev.is_partial:
            logger.warning(
                "Writing to %s which was only partially read (offset=%s, limit=%s). "
                "Full-file overwrites after partial reads may lose content.",
                path, prev.offset, prev.limit,
            )

        original_file = path.read_text(encoding="utf-8", errors="replace")
        kind = "update"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _update_read_after_write(path)

    return json.dumps({
        "type": kind,
        "filePath": str(path),
        "content": content,
        "structuredPatch": _make_patch(original_file or "", content),
        "originalFile": original_file,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# edit_file
# ---------------------------------------------------------------------------

def edit_file(args: dict[str, Any]) -> str:
    file_path = args.get("file_path") or args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    replace_all = args.get("replace_all", False)

    if not file_path:
        raise ValueError("path 参数是必填的")
    if not old_string:
        raise ValueError("old_string 参数是必填的")
    if old_string == new_string:
        raise ValueError("old_string 和 new_string 必须不同")

    path = _resolve(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件未找到：{path}")

    # --- .ipynb interception ---
    if path.suffix.lower() == ".ipynb":
        raise ValueError(
            f"{path.name} 是 Jupyter notebook 文件。"
            "请使用 NotebookEdit 工具，而不是 edit_file。"
        )

    # --- File size limit ---
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0
    if file_size > MAX_EDIT_FILE_SIZE:
        raise ValueError(
            f"文件 {path} 太大（{file_size / (1024**3):.1f} GiB）。"
            f"edit_file 最大支持 1 GiB 的文件。"
        )

    # --- Must-read-before-edit check ---
    prev = _get_read_record(path)
    if prev is None:
        raise ValueError(
            f"编辑前必须先读取 {path}。"
            "请先使用 read_file 查看当前内容。"
        )

    # --- mtime race check ---
    current_mtime = _safe_mtime(path)
    if current_mtime - prev.mtime > 0.5:
        raise ValueError(
            f"文件 {path} 在你上次读取之后被修改过"
            f"（读取时 mtime={prev.mtime:.3f}，当前={current_mtime:.3f}）。"
            "请重新读取文件后再编辑。"
        )

    original_file = path.read_text(encoding="utf-8")

    # --- Quote normalization ---
    if old_string not in original_file:
        normalized_old = _normalize_quotes(old_string)
        if normalized_old != old_string and normalized_old in original_file:
            old_string = normalized_old
        else:
            raise ValueError(
                f"old_string 在 {path} 中未找到。请确保内容完全匹配。"
            )

    if replace_all:
        updated = original_file.replace(old_string, new_string)
    else:
        count = original_file.count(old_string)
        if count > 1:
            raise ValueError(
                f"old_string 在 {path} 中出现了 {count} 次。"
                "请提供更多上下文使其唯一，或设置 replace_all=true。"
            )
        updated = original_file.replace(old_string, new_string, 1)

    path.write_text(updated, encoding="utf-8")
    _update_read_after_write(path)

    return json.dumps({
        "filePath": str(path),
        "oldString": old_string,
        "newString": new_string,
        "originalFile": original_file,
        "structuredPatch": _make_patch(original_file, updated),
        "replaceAll": replace_all,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# PDF reading (best-effort with optional PyPDF2)
# ---------------------------------------------------------------------------

def _read_pdf(path: Path) -> str:
    try:
        import PyPDF2
    except ImportError:
        try:
            import pypdf as PyPDF2  # type: ignore[no-redef]
        except ImportError:
            raise ValueError(
                f"无法读取 PDF 文件 {path.name}：PyPDF2 和 pypdf 均未安装。"
                "请执行：pip install pypdf"
            )

    try:
        reader = PyPDF2.PdfReader(str(path))
        pages_text: list[str] = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages_text.append(f"--- Page {i + 1} ---\n{text}")

        if not pages_text:
            return json.dumps({
                "type": "text",
                "file": {
                    "filePath": str(path),
                    "content": "（PDF 中无可提取的文本——可能是扫描件/图片格式）",
                    "numLines": 0,
                    "startLine": 1,
                    "totalLines": 0,
                },
            }, ensure_ascii=False, indent=2)

        content = "\n\n".join(pages_text)
        if len(content) > MAX_READ_CHARS:
            content = content[:MAX_READ_CHARS]
            content += f"\n\n...（PDF 文本已在 {MAX_READ_CHARS:,} 字符处截断）"

        lines = content.splitlines()
        return json.dumps({
            "type": "text",
            "file": {
                "filePath": str(path),
                "content": content,
                "numLines": len(lines),
                "startLine": 1,
                "totalLines": len(lines),
                "totalPages": len(reader.pages),
            },
        }, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise ValueError(f"读取 PDF 失败 {path.name}：{exc}")


# ---------------------------------------------------------------------------
# Image reading stub (image compression + token budget — simplified)
# ---------------------------------------------------------------------------

def _read_image_stub(path: Path) -> str:
    """Return image metadata. Actual image content is not extracted as text;
    the model should use other tools or the user can attach images directly."""
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    size_kb = size / 1024
    return json.dumps({
        "type": "image",
        "file": {
            "filePath": str(path),
            "content": (
                f"图片文件：{path.name}（{size_kb:.1f} KB）。"
                "图片内容无法提取为文本。"
                "如果需要分析此图片，请让用户直接在对话中发送。"
            ),
            "numLines": 0,
            "startLine": 1,
            "totalLines": 0,
        },
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------

def _make_patch(original: str, updated: str, context: int = 3) -> list[dict]:
    """Generate structured hunks using difflib, with *context* surrounding lines."""
    import difflib

    old_lines = original.splitlines()
    new_lines = updated.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    hunks: list[dict] = []

    for group in matcher.get_grouped_opcodes(context):
        old_start = group[0][1] + 1
        old_count = group[-1][2] - group[0][1]
        new_start = group[0][3] + 1
        new_count = group[-1][4] - group[0][3]

        lines: list[str] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for ln in old_lines[i1:i2]:
                    lines.append(f" {ln}")
            elif tag == "replace":
                for ln in old_lines[i1:i2]:
                    lines.append(f"-{ln}")
                for ln in new_lines[j1:j2]:
                    lines.append(f"+{ln}")
            elif tag == "delete":
                for ln in old_lines[i1:i2]:
                    lines.append(f"-{ln}")
            elif tag == "insert":
                for ln in new_lines[j1:j2]:
                    lines.append(f"+{ln}")

        hunks.append({
            "oldStart": old_start,
            "oldLines": old_count,
            "newStart": new_start,
            "newLines": new_count,
            "lines": lines,
        })

    return hunks
