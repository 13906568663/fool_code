"""Phase 1-2: Scan skill directories and parse SKILL.md files."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from fool_code.skill_store.schemas import ParsedSkill

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(
    r"\A\s*---[ \t]*\r?\n(.*?\r?\n)---[ \t]*\r?\n",
    re.DOTALL,
)

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _sanitize_id(raw: str) -> str:
    """Turn an arbitrary name into a URL-safe kebab-case ID."""
    s = raw.lower().strip()
    s = re.sub(r"[/\\]+", "-", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff\-]", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s or "unnamed-skill"


def scan_skill_dir(root: str | Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    results = []
    try:
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if skill_md.exists():
                results.append(entry)
    except OSError:
        pass
    return results


def parse_skill_md(skill_dir: Path) -> ParsedSkill | None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    fm, body = _parse_frontmatter(content)

    name = fm.get("name", "")
    if not name:
        name = skill_dir.name
    name = _sanitize_id(str(name).strip())

    description = fm.get("description", "")
    if not description:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped[:200]
                break

    if not description:
        return None

    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    display_name = title_match.group(1).strip() if title_match else name.replace("-", " ").title()

    body_no_title = re.sub(r"^#.*\n", "", body, count=1).strip()
    body_summary = body_no_title[:200]

    body_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    trigger_terms = fm.get("trigger_terms", [])
    if isinstance(trigger_terms, str):
        trigger_terms = [t.strip() for t in trigger_terms.split(",") if t.strip()]
    elif not isinstance(trigger_terms, list):
        trigger_terms = []

    category = fm.get("category")
    if isinstance(category, str):
        category = category.strip() or None
    else:
        category = None

    scripts_dir = skill_dir / "scripts"
    has_scripts = scripts_dir.is_dir()
    script_langs: list[str] = []
    if has_scripts:
        try:
            for f in scripts_dir.iterdir():
                if f.is_file() and f.suffix:
                    lang = f.suffix.lstrip(".")
                    if lang not in script_langs:
                        script_langs.append(lang)
        except OSError:
            pass

    references = re.findall(r"\[.*?\]\((\w+\.md)\)", body)

    return ParsedSkill(
        id=name,
        display_name=display_name,
        description=str(description),
        category=category,
        trigger_terms=[str(t) for t in trigger_terms],
        body_text=body,
        body_summary=body_summary,
        body_path=str(skill_file),
        body_hash=body_hash,
        has_scripts=has_scripts,
        script_langs=script_langs,
        references=references,
    )


def validate_skill(parsed: ParsedSkill) -> tuple[bool, str]:
    if not parsed.id:
        return False, "name is empty"
    if len(parsed.id) > 64:
        return False, f"name too long ({len(parsed.id)} > 64)"
    if not parsed.description:
        return False, "description is empty"
    if len(parsed.description) > 1024:
        return False, f"description too long ({len(parsed.description)} > 1024)"
    if not parsed.body_text.strip():
        return False, "SKILL.md body is empty"
    line_count = parsed.body_text.count("\n") + 1
    if line_count > 1000:
        return False, f"body too long ({line_count} lines > 1000)"
    return True, ""


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content

    raw_yaml = m.group(1)
    body = content[m.end():]
    fm: dict[str, Any] = {}

    current_key = ""
    for line in raw_yaml.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith("  - ") or line.startswith("  -\t"):
            val = line.strip().lstrip("-").strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            if current_key and current_key in fm and isinstance(fm[current_key], list):
                fm[current_key].append(val)
            continue

        if ":" not in stripped:
            if current_key and isinstance(fm.get(current_key), str):
                fm[current_key] = fm[current_key] + " " + stripped
            continue

        key, _, value = stripped.partition(":")
        key = key.strip().lower().replace("-", "_")
        value = value.strip()

        if value == "":
            fm[key] = []
            current_key = key
            continue

        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]

        if value.startswith(">") or value.startswith("|"):
            fm[key] = ""
            current_key = key
            continue

        if value.lower() in ("true", "yes"):
            fm[key] = True
        elif value.lower() in ("false", "no"):
            fm[key] = False
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            fm[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
        else:
            fm[key] = value

        current_key = key

    return fm, body
