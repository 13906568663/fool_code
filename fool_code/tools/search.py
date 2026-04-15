"""Search tools — glob_search and grep_search.

grep_search calls ripgrep (rg) as a subprocess instead of Python re + os.walk
for a large performance gain. Falls back to Python if rg is not installed.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fool_code.runtime.config import active_workspace_root

logger = logging.getLogger(__name__)

_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "target", "dist", "build", ".next", ".cache", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

# VCS directories excluded from ripgrep search
_VCS_DIRS_TO_EXCLUDE = [".git", ".svn", ".hg", ".bzr", ".jj", ".sl"]

# Default cap on returned lines/files when head_limit is omitted
_DEFAULT_HEAD_LIMIT = 250

_TYPE_EXTENSION_MAP: dict[str, set[str]] = {
    "py": {".py", ".pyi"},
    "js": {".js", ".jsx", ".mjs", ".cjs"},
    "ts": {".ts", ".tsx", ".mts", ".cts"},
    "rust": {".rs"},
    "go": {".go"},
    "java": {".java"},
    "c": {".c", ".h"},
    "cpp": {".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".h"},
    "rb": {".rb"},
    "php": {".php"},
    "css": {".css", ".scss", ".sass", ".less"},
    "html": {".html", ".htm"},
    "json": {".json"},
    "yaml": {".yaml", ".yml"},
    "toml": {".toml"},
    "md": {".md", ".markdown"},
    "sh": {".sh", ".bash", ".zsh"},
    "sql": {".sql"},
    "xml": {".xml"},
}

# ---------------------------------------------------------------------------
# ripgrep detection (cached per-process)
# ---------------------------------------------------------------------------

_rg_path: str | None = None
_rg_checked = False


def _find_rg() -> str | None:
    global _rg_path, _rg_checked
    if _rg_checked:
        return _rg_path
    _rg_checked = True
    _rg_path = shutil.which("rg")
    if _rg_path:
        logger.info("ripgrep found: %s", _rg_path)
    else:
        logger.warning(
            "ripgrep (rg) not found — grep_search will use Python fallback (much slower)"
        )
    return _rg_path


# ---------------------------------------------------------------------------
# glob_search
# ---------------------------------------------------------------------------

def glob_search(args: dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        raise ValueError("pattern is required")

    base_path = _resolve_search_base(args.get("path", "."))
    if not base_path.exists():
        raise ValueError(f"Path does not exist: {base_path}")

    started = time.monotonic()
    matches: list[str] = []

    try:
        all_hits = sorted(base_path.glob(pattern), key=_mtime_key, reverse=True)
        for p in all_hits:
            if not p.is_file():
                continue
            if _should_skip(p):
                continue
            matches.append(str(p))
            if len(matches) >= 100:
                break
    except Exception as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    truncated = len(matches) >= 100
    duration_ms = int((time.monotonic() - started) * 1000)

    return json.dumps({
        "durationMs": duration_ms,
        "numFiles": len(matches),
        "filenames": matches,
        "truncated": truncated,
    }, ensure_ascii=False, indent=2)


def _mtime_key(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# grep_search — dispatches to ripgrep or Python fallback
# ---------------------------------------------------------------------------

def grep_search(args: dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    if not pattern:
        raise ValueError("pattern is required")

    rg = _find_rg()
    if rg:
        return _grep_ripgrep(args, rg)
    return _grep_python_fallback(args)


# ---------------------------------------------------------------------------
# ripgrep implementation
# ---------------------------------------------------------------------------

def _grep_ripgrep(args: dict[str, Any], rg_path: str) -> str:
    pattern: str = args["pattern"]
    base_path = _resolve_search_base(args.get("path", "."))
    case_insensitive = args.get("-i", False)
    multiline = args.get("multiline", False)
    glob_filter = args.get("glob") or args.get("include")
    file_type = args.get("type")
    output_mode = args.get("output_mode", "files_with_matches")
    before = args.get("-B", 0)
    after = args.get("-A", 0)
    ctx = args.get("-C") or args.get("context", 0)
    head_limit = args.get("head_limit")
    offset = args.get("offset", 0) or 0

    if ctx:
        before = before or ctx
        after = after or ctx

    # --- build rg arguments ---
    rg_args: list[str] = ["--hidden", "--no-config"]

    for d in _VCS_DIRS_TO_EXCLUDE:
        rg_args.extend(["--glob", f"!{d}"])

    # Prevent base64 / minified mega-lines from cluttering output
    rg_args.extend(["--max-columns", "500"])

    if multiline:
        rg_args.extend(["-U", "--multiline-dotall"])

    if case_insensitive:
        rg_args.append("-i")

    if output_mode == "files_with_matches":
        rg_args.append("-l")
    elif output_mode == "count":
        rg_args.append("-c")

    if output_mode == "content":
        rg_args.append("-n")

    if output_mode == "content":
        if ctx:
            rg_args.extend(["-C", str(ctx)])
        else:
            if before:
                rg_args.extend(["-B", str(before)])
            if after:
                rg_args.extend(["-A", str(after)])

    if pattern.startswith("-"):
        rg_args.extend(["-e", pattern])
    else:
        rg_args.append(pattern)

    if file_type:
        rg_args.extend(["--type", file_type])

    if glob_filter:
        for part in glob_filter.split():
            if "{" in part and "}" in part:
                rg_args.extend(["--glob", part])
            else:
                for sub in part.split(","):
                    if sub:
                        rg_args.extend(["--glob", sub])

    rg_args.append(str(base_path))

    # --- execute ripgrep ---
    is_windows = sys.platform == "win32"
    try:
        proc = subprocess.run(
            [rg_path, *rg_args],
            capture_output=True,
            timeout=30,
            creationflags=0x08000000 if is_windows else 0,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({
            "error": (
                "Ripgrep search timed out after 30 seconds. "
                "Try a more specific path or pattern."
            ),
        }, indent=2)
    except FileNotFoundError:
        global _rg_path, _rg_checked
        _rg_path = None
        _rg_checked = False
        return _grep_python_fallback(args)

    # exit code 1 = no matches (normal for ripgrep)
    stdout_text = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode not in (0, 1):
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        if stderr_text:
            return json.dumps({"error": f"ripgrep error: {stderr_text}"}, indent=2)

    lines = (
        [l.rstrip("\r") for l in stdout_text.strip().split("\n") if l.strip()]
        if stdout_text.strip()
        else []
    )

    workspace_root = str(active_workspace_root())

    # --- format output by mode ---
    if output_mode == "content":
        lines, applied_limit, applied_offset = _apply_limit(
            lines, head_limit, offset,
        )
        rel_lines = [_relativize_content_line(l, workspace_root) for l in lines]
        return json.dumps({
            "mode": output_mode,
            "numFiles": 0,
            "filenames": [],
            "numLines": len(rel_lines),
            "content": "\n".join(rel_lines),
            "appliedLimit": applied_limit,
            "appliedOffset": applied_offset,
        }, ensure_ascii=False, indent=2)

    if output_mode == "count":
        lines, applied_limit, applied_offset = _apply_limit(
            lines, head_limit, offset,
        )
        total_matches = 0
        file_count = 0
        rel_lines: list[str] = []
        for line in lines:
            ci = line.rfind(":")
            if ci > 0:
                fp = line[:ci]
                cnt_str = line[ci + 1 :]
                try:
                    total_matches += int(cnt_str)
                    file_count += 1
                except ValueError:
                    pass
                rel_lines.append(_to_relative(fp, workspace_root) + ":" + cnt_str)
            else:
                rel_lines.append(line)

        return json.dumps({
            "mode": output_mode,
            "numFiles": file_count,
            "filenames": [],
            "numMatches": total_matches,
            "content": "\n".join(rel_lines),
            "appliedLimit": applied_limit,
            "appliedOffset": applied_offset,
        }, ensure_ascii=False, indent=2)

    # --- files_with_matches (default) — sort by mtime ---
    sorted_files = sorted(
        lines, key=lambda f: _safe_mtime(f), reverse=True,
    )
    sorted_files, applied_limit, applied_offset = _apply_limit(
        sorted_files, head_limit, offset,
    )
    rel_files = [_to_relative(f, workspace_root) for f in sorted_files]

    return json.dumps({
        "mode": output_mode,
        "numFiles": len(rel_files),
        "filenames": rel_files,
        "appliedLimit": applied_limit,
        "appliedOffset": applied_offset,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Python fallback (original implementation, used when rg is not installed)
# ---------------------------------------------------------------------------

def _grep_python_fallback(args: dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    base_path = _resolve_search_base(args.get("path", "."))
    case_insensitive = args.get("-i", False)
    multiline = args.get("multiline", False)
    glob_filter = args.get("glob") or args.get("include")
    file_type = args.get("type")
    output_mode = args.get("output_mode", "files_with_matches")
    before = args.get("-B", 0)
    after = args.get("-A", 0)
    context = args.get("-C") or args.get("context", 0)
    head_limit = args.get("head_limit")
    offset = args.get("offset", 0) or 0

    if context:
        before = before or context
        after = after or context

    flags = re.IGNORECASE if case_insensitive else 0
    if multiline:
        flags |= re.DOTALL

    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        return json.dumps({"error": f"Invalid regex: {exc}"}, indent=2)

    files = _collect_search_files(base_path)
    filenames: list[str] = []
    content_lines: list[str] = []
    total_matches = 0

    for file_path in files:
        if not _matches_filters(file_path, glob_filter, file_type):
            continue

        try:
            file_text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if output_mode == "count":
            count = len(regex.findall(file_text))
            if count > 0:
                filenames.append(str(file_path))
                total_matches += count
            continue

        lines = file_text.splitlines()

        if multiline:
            # True multiline: search entire file text, map match positions to lines
            matched_indices: list[int] = []
            for m in regex.finditer(file_text):
                line_no = file_text[:m.start()].count("\n")
                if line_no not in matched_indices:
                    matched_indices.append(line_no)
                    total_matches += 1
        else:
            matched_indices = []
            for idx, line in enumerate(lines):
                if regex.search(line):
                    total_matches += 1
                    matched_indices.append(idx)

        if not matched_indices:
            continue

        filenames.append(str(file_path))

        if output_mode == "content":
            for idx in matched_indices:
                start = max(0, idx - before)
                end = min(len(lines), idx + after + 1)
                for cur in range(start, end):
                    prefix = f"{file_path}:{cur + 1}:"
                    content_lines.append(f"{prefix}{lines[cur]}")

    if output_mode == "content":
        content_lines, applied_limit, applied_offset = _apply_limit(
            content_lines, head_limit, offset,
        )
        return json.dumps({
            "mode": output_mode,
            "numFiles": len(filenames),
            "filenames": filenames,
            "numLines": len(content_lines),
            "content": "\n".join(content_lines),
            "appliedLimit": applied_limit,
            "appliedOffset": applied_offset,
        }, ensure_ascii=False, indent=2)

    if output_mode == "count":
        filenames, applied_limit, applied_offset = _apply_limit(
            filenames, head_limit, offset,
        )
        return json.dumps({
            "mode": output_mode,
            "numFiles": len(filenames),
            "filenames": filenames,
            "numMatches": total_matches,
            "appliedLimit": applied_limit,
            "appliedOffset": applied_offset,
        }, ensure_ascii=False, indent=2)

    # files_with_matches (default)
    filenames, applied_limit, applied_offset = _apply_limit(
        filenames, head_limit, offset,
    )
    return json.dumps({
        "mode": output_mode,
        "numFiles": len(filenames),
        "filenames": filenames,
        "appliedLimit": applied_limit,
        "appliedOffset": applied_offset,
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _to_relative(path_str: str, workspace_root: str) -> str:
    """Convert absolute path to relative path to save tokens."""
    try:
        rel = os.path.relpath(path_str, workspace_root)
        if rel.startswith(".."):
            return path_str
        return rel
    except ValueError:
        return path_str


def _relativize_content_line(line: str, workspace_root: str) -> str:
    """Relativize path prefix in a content-mode line like '/abs/path:10:code'."""
    colon_idx = line.find(":")
    if colon_idx > 0:
        fp = line[:colon_idx]
        rest = line[colon_idx:]
        return _to_relative(fp, workspace_root) + rest
    return line


def _safe_mtime(path_str: str) -> float:
    try:
        return os.path.getmtime(path_str)
    except OSError:
        return 0.0


def _collect_search_files(base: Path) -> list[Path]:
    if base.is_file():
        return [base]

    files: list[Path] = []
    for root_str, dirs, file_names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in file_names:
            files.append(Path(root_str) / fn)
    return files


def _matches_filters(path: Path, glob_filter: str | None, file_type: str | None) -> bool:
    if glob_filter:
        path_str = str(path)
        name = path.name
        if not fnmatch.fnmatch(name, glob_filter) and not fnmatch.fnmatch(path_str, glob_filter):
            return False

    if file_type:
        exts = _TYPE_EXTENSION_MAP.get(file_type)
        if exts:
            if path.suffix.lower() not in exts:
                return False
        else:
            if path.suffix.lower().lstrip(".") != file_type.lower():
                return False

    return True


def _apply_limit(
    items: list, limit: int | None, offset: int,
) -> tuple[list, int | None, int | None]:
    if offset:
        items = items[offset:]
    explicit_limit = limit if limit is not None else _DEFAULT_HEAD_LIMIT
    if explicit_limit == 0:
        return items, None, offset if offset else None

    truncated = len(items) > explicit_limit
    items = items[:explicit_limit]
    return (
        items,
        explicit_limit if truncated else None,
        offset if offset else None,
    )


def _should_skip(path: Path) -> bool:
    return any(part in _SKIP_DIRS for part in path.parts)


def _resolve_search_base(raw_path: str) -> Path:
    base = Path(raw_path or ".")
    if base.is_absolute():
        return base.resolve()
    return (active_workspace_root() / base).resolve()
