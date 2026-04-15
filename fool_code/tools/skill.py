"""Skill tool — load, discover, and manage SKILL.md definitions.

Includes:
- Structured YAML frontmatter parsing (name, description, when_to_use, etc.)
- Multi-source skill discovery (app, user home, workspace, legacy)
- Dynamic skill directory discovery from file paths
- Conditional skill activation via paths matching
- Token-budget-aware skill listing for system prompt injection
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fool_code.runtime.config import skills_path

logger = logging.getLogger(__name__)

MAX_LISTING_DESC_CHARS = 250
SKILL_BUDGET_CONTEXT_PERCENT = 0.01
CHARS_PER_TOKEN = 4
DEFAULT_CHAR_BUDGET = 8_000


# ======================================================================
# Frontmatter parser
# ======================================================================

_FRONTMATTER_RE = re.compile(
    r"\A\s*---[ \t]*\r?\n(.*?\r?\n)---[ \t]*\r?\n",
    re.DOTALL,
)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from SKILL.md content.

    Returns (frontmatter_dict, body_content).
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content

    raw_yaml = m.group(1)
    body = content[m.end():]
    fm: dict[str, Any] = {}

    for line in raw_yaml.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace("-", "_")
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if value.lower() in ("true", "yes"):
            fm[key] = True
        elif value.lower() in ("false", "no"):
            fm[key] = False
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            fm[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
        else:
            fm[key] = value

    return fm, body


# ======================================================================
# SkillInfo dataclass
# ======================================================================

@dataclass
class SkillInfo:
    name: str
    description: str
    when_to_use: str | None = None
    version: str | None = None
    path: str = ""
    source: str = "user"
    loaded_from: str = "skills"
    allowed_tools: list[str] = field(default_factory=list)
    argument_hint: str | None = None
    model: str | None = None
    user_invocable: bool = True
    disable_model_invocation: bool = False
    context: str | None = None  # "fork" | None
    agent: str | None = None
    paths: list[str] | None = None  # conditional activation patterns
    effort: str | None = None
    content_length: int = 0
    display_name: str | None = None

    @property
    def listing_description(self) -> str:
        desc = self.description
        if self.when_to_use:
            desc = f"{desc} - {self.when_to_use}"
        if len(desc) > MAX_LISTING_DESC_CHARS:
            return desc[:MAX_LISTING_DESC_CHARS - 1] + "…"
        return desc


# ======================================================================
# Skill discovery — directories
# ======================================================================

def _all_skill_search_dirs() -> list[Path]:
    """Return skill directories to search.

    Only one source: ~/.fool-code/skills/ (global user skills)
    """
    app_skills = skills_path()
    if app_skills.is_dir():
        return [app_skills]
    return []


def _load_skill_from_dir(skill_dir: Path, source: str = "user") -> SkillInfo | None:
    """Load a single skill from a directory containing SKILL.md."""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    fm, body = parse_frontmatter(content)
    skill_name = fm.get("slug") or fm.get("name") or skill_dir.name

    description = fm.get("description", "")
    if not description:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped[:200]
                break

    paths_raw = fm.get("paths")
    paths = None
    if isinstance(paths_raw, list):
        paths = [p for p in paths_raw if p and p != "**"]
        if not paths:
            paths = None
    elif isinstance(paths_raw, str) and paths_raw != "**":
        paths = [paths_raw]

    return SkillInfo(
        name=str(skill_name),
        display_name=fm.get("name") if fm.get("slug") else None,
        description=str(description),
        when_to_use=fm.get("when_to_use") or fm.get("changelog"),
        version=fm.get("version"),
        path=str(skill_dir),
        source=source,
        loaded_from="skills",
        allowed_tools=fm.get("allowed_tools", []),
        argument_hint=fm.get("argument_hint"),
        model=fm.get("model"),
        user_invocable=fm.get("user_invocable", True),
        disable_model_invocation=fm.get("disable_model_invocation", False),
        context=fm.get("context"),
        agent=fm.get("agent"),
        paths=paths,
        effort=fm.get("effort"),
        content_length=len(content),
    )


def discover_all_skills() -> list[SkillInfo]:
    """Scan all skill directories and return all available skills."""
    skills: list[SkillInfo] = []
    seen_names: set[str] = set()

    for bs in get_bundled_skills():
        if bs.name.lower() not in seen_names:
            skills.append(bs)
            seen_names.add(bs.name.lower())

    for root in _all_skill_search_dirs():
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue

        for entry in entries:
            if not entry.is_dir():
                continue
            info = _load_skill_from_dir(entry)
            if info is None:
                continue
            if info.name.lower() in seen_names:
                continue
            seen_names.add(info.name.lower())
            skills.append(info)

    return skills


# ======================================================================
# Dynamic skill discovery from file paths (P2)
# ======================================================================

_dynamic_skill_dirs: set[str] = set()
_dynamic_skills: dict[str, SkillInfo] = {}
_conditional_skills: dict[str, SkillInfo] = {}
_activated_conditional: set[str] = set()


def discover_skills_for_paths(file_paths: list[str], cwd: str) -> list[str]:
    """Walk up from file paths to cwd, discovering new .fool-code/skills/ dirs.

    Returns list of newly discovered skill directory paths.
    """
    resolved_cwd = cwd.rstrip("/\\")
    new_dirs: list[str] = []
    sep = os.sep

    for fp in file_paths:
        current = os.path.dirname(fp)
        while current.startswith(resolved_cwd + sep) and current != resolved_cwd:
            skill_dir = os.path.join(current, ".fool-code", "skills")
            if skill_dir not in _dynamic_skill_dirs:
                _dynamic_skill_dirs.add(skill_dir)
                if os.path.isdir(skill_dir):
                    new_dirs.append(skill_dir)
            current = os.path.dirname(current)

    return sorted(new_dirs, key=lambda d: -d.count(sep))


def add_dynamic_skill_directories(dirs: list[str]) -> int:
    """Load skills from dynamically discovered directories."""
    count = 0
    for d in dirs:
        root = Path(d)
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            info = _load_skill_from_dir(entry, source="project")
            if info is None:
                continue
            _dynamic_skills[info.name] = info
            count += 1
    return count


def get_dynamic_skills() -> list[SkillInfo]:
    return list(_dynamic_skills.values())


def activate_conditional_skills(file_paths: list[str], cwd: str) -> list[str]:
    """Activate conditional skills whose paths patterns match the given files."""
    if not _conditional_skills:
        return []

    import fnmatch
    activated: list[str] = []

    for name, skill in list(_conditional_skills.items()):
        if not skill.paths:
            continue
        for fp in file_paths:
            rel = os.path.relpath(fp, cwd)
            if rel.startswith("..") or os.path.isabs(rel):
                continue
            for pattern in skill.paths:
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, pattern + "/**"):
                    _dynamic_skills[name] = skill
                    del _conditional_skills[name]
                    _activated_conditional.add(name)
                    activated.append(name)
                    break
            if name in activated:
                break

    return activated


def clear_skill_caches() -> None:
    _dynamic_skill_dirs.clear()
    _dynamic_skills.clear()
    _conditional_skills.clear()
    _activated_conditional.clear()


# ======================================================================
# Skill listing for system prompt (P0 + P2 budget)
# ======================================================================

def format_skill_listing(
    skills: list[SkillInfo],
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> str:
    """Format skill listing within a character budget for system prompt injection."""
    if not skills:
        return ""

    full_entries = [f"- {s.name}: {s.listing_description}" for s in skills]
    full_total = sum(len(e) for e in full_entries) + len(full_entries) - 1

    if full_total <= char_budget:
        return "\n".join(full_entries)

    name_overhead = sum(len(s.name) + 4 for s in skills) + len(skills) - 1
    available = char_budget - name_overhead
    max_desc = max(20, available // len(skills))

    result: list[str] = []
    for s in skills:
        desc = s.listing_description
        if len(desc) > max_desc:
            desc = desc[:max_desc - 1] + "…"
        if max_desc < 20:
            result.append(f"- {s.name}")
        else:
            result.append(f"- {s.name}: {desc}")
    return "\n".join(result)


def build_skill_prompt_section() -> str | None:
    """Build the skill section for system prompt injection.

    Includes:
    - How to search/load skills
    - Self-improvement guidance (when to create/patch/delete)
    - Top-N existing skill listing so the LLM is aware of available skills
    """
    from fool_code.skill_store.store import is_skill_store_enabled
    if not is_skill_store_enabled():
        return None

    parts = [
        "# 技能库（Skill Store）",
        "",
    ]

    skill_list, total_count, was_truncated = _build_skill_listing_for_prompt()
    if skill_list:
        # Hermes-style: tell the LLM to scan the list before replying
        parts.append(
            "回复前先浏览下方技能列表。如果有匹配的技能，用 Skill(skill=\"ID\") 加载完整文档并按文档执行。"
        )
        if was_truncated:
            parts.append(
                f'当前仅列出 {len(skill_list.splitlines())} / {total_count} 个技能。'
                ' 更多请用 SearchSkills(query="关键词") 搜索。'
            )
        parts.append("用户输入 `/<技能名>` 是调用技能的简写。")
        parts.append("\n## 已有技能")
        parts.append(skill_list)
    else:
        parts.append("你拥有一个技能库。通过 SearchSkills 工具使用它：")
        parts.append('- 查看全部技能：SearchSkills(query="all")')
        parts.append('- 搜索特定技能：SearchSkills(query="处理Excel文件")')
        parts.append('找到技能后，用 Skill(skill="技能ID") 加载完整文档并按文档执行。')
        parts.append("用户输入 `/<技能名>` 是调用技能的简写。")

    parts.append(_SKILLS_GUIDANCE)

    return "\n".join(parts)


def _build_skill_listing_for_prompt() -> tuple[str, int, bool]:
    """Return a compact bullet list of existing skills for system prompt.

    Tries the Skill Store first; falls back to file-system discovery.

    Returns (listing_text, total_count, was_truncated):
      - listing_text may be empty if no skills exist
      - total_count is the full number of skills found
      - was_truncated is True when the listing was cut short
    """
    items: list[tuple[str, str]] = []

    try:
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is not None:
            raw = store.list_skills()
            skills = json.loads(raw) if isinstance(raw, str) else raw
            for s in skills:
                sid = s.get("id", "")
                desc = s.get("description", s.get("display_name", sid))
                items.append((sid, str(desc)[:60]))
    except Exception:
        pass

    if not items:
        try:
            all_skills = discover_all_skills()
            for s in all_skills:
                items.append((s.name, (s.description or "")[:60]))
        except Exception:
            return "", 0, False

    total_count = len(items)
    if total_count == 0:
        return "", 0, False

    # Adaptive limit: full list when <= 50, top-N when > 50
    if total_count <= _SKILL_LIST_FULL_LIMIT:
        display_items = items
        was_truncated = False
    else:
        display_items = items[:_SKILL_LIST_TRUNCATED_LIMIT]
        was_truncated = True

    lines: list[str] = []
    total_chars = 0
    for sid, desc in display_items:
        line = f"- {sid}: {desc}" if desc else f"- {sid}"
        if total_chars + len(line) > _SKILL_LIST_CHAR_BUDGET:
            was_truncated = True
            break
        lines.append(line)
        total_chars += len(line) + 1

    return "\n".join(lines), total_count, was_truncated


# ======================================================================
# Skill management — create / patch / delete  (called by LLM via SkillManage)
# ======================================================================

_SKILLS_GUIDANCE = (
    "\n\n## 技能自我改进\n"
    "完成复杂任务后（5次以上工具调用）、修复了棘手的错误、或发现了非显而易见的工作流程时，"
    "用 SkillManage(action='create') 将方法保存为技能，以便下次复用。\n"
    "使用技能时发现它过时、不完整或有误，"
    "立即用 SkillManage(action='patch') 修补——不要等人要求。\n"
    "不再需要的技能，用 SkillManage(action='delete') 删除。"
)

_SKILL_LIST_FULL_LIMIT = 50       # list all skills when total <= this
_SKILL_LIST_TRUNCATED_LIMIT = 20  # when total > FULL_LIMIT, show top N
_SKILL_LIST_CHAR_BUDGET = 4000    # max chars for the skill listing block


def _validate_skill_content(content: str) -> str | None:
    """Validate SKILL.md content has proper frontmatter with name + description.

    Returns an error message or None if valid.
    """
    fm, body = parse_frontmatter(content)
    if not fm:
        return "SKILL.md 必须以 YAML frontmatter 开头（--- ... ---）"
    if not fm.get("name"):
        return "frontmatter 中必须包含 'name' 字段"
    if not fm.get("description"):
        return "frontmatter 中必须包含 'description' 字段"
    if not body.strip():
        return "SKILL.md frontmatter 之后必须有正文内容（操作步骤、说明等）"
    return None


def _auto_ingest_skill(skill_dir: Path) -> bool:
    """Best-effort: ingest/update a skill in the Skill Store after disk write.

    Returns True on success, False if ingest failed (caller may want to warn).
    """
    try:
        from fool_code.skill_store.ingestor import ingest_single
        result = ingest_single(skill_dir)
        if result is None:
            logger.warning("[SKILLS] Auto-ingest returned None for %s", skill_dir)
            return False
        return True
    except Exception as exc:
        logger.warning("[SKILLS] Auto-ingest to Skill Store failed: %s", exc)
        return False


def _remove_from_store(skill_id: str) -> None:
    """Best-effort: remove a skill from the Skill Store index."""
    try:
        from fool_code.skill_store.store import get_store, is_skill_store_enabled
        if not is_skill_store_enabled():
            return
        store = get_store()
        if store is None:
            return
        if hasattr(store, "delete_skill"):
            store.delete_skill(skill_id)
        elif hasattr(store, "remove_skill"):
            store.remove_skill(skill_id)
    except Exception as exc:
        logger.debug("Remove from Skill Store failed: %s", exc)


def skill_manage(args: dict[str, Any], context: Any = None) -> str:
    """Create, patch, or delete a user skill.

    Actions:
      create — write a new SKILL.md with validated frontmatter
      patch  — find-and-replace within an existing SKILL.md
      delete — remove a skill directory entirely
    """
    action = (args.get("action") or "").strip().lower()
    name = (args.get("name") or "").strip()

    if not action:
        return json.dumps({"success": False, "error": "action 不能为空"}, ensure_ascii=False)
    if not name:
        return json.dumps({"success": False, "error": "name 不能为空"}, ensure_ascii=False)

    if action == "create":
        return _skill_create(name, args)
    elif action == "patch":
        return _skill_patch(name, args)
    elif action == "delete":
        return _skill_delete(name)
    else:
        return json.dumps(
            {"success": False, "error": f"未知 action: {action}，支持 create/patch/delete"},
            ensure_ascii=False,
        )


def _skill_create(name: str, args: dict[str, Any]) -> str:
    content = (args.get("content") or "").lstrip()

    if not content:
        return json.dumps({"success": False, "error": "content 不能为空"}, ensure_ascii=False)

    err = _validate_skill_content(content)
    if err:
        return json.dumps({"success": False, "error": err}, ensure_ascii=False)

    fm, _ = parse_frontmatter(content)
    fm_name = fm.get("name", "")
    if fm_name and fm_name != name:
        return json.dumps({
            "success": False,
            "error": f"frontmatter name '{fm_name}' 与参数 name '{name}' 不一致，请统一",
        }, ensure_ascii=False)

    # Flat directory layout: skills/<name>/SKILL.md
    # category is stored only in frontmatter metadata for the Skill Store index
    base = skills_path()
    base.mkdir(parents=True, exist_ok=True)
    skill_dir = base / name

    if (skill_dir / "SKILL.md").exists():
        return json.dumps(
            {"success": False, "error": f"技能 '{name}' 已存在，请用 action='patch' 修改"},
            ensure_ascii=False,
        )

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")

    ingest_ok = _auto_ingest_skill(skill_dir)
    clear_skill_caches()

    logger.info("[SKILLS] Created skill: %s at %s", name, skill_dir)
    result: dict[str, Any] = {
        "success": True,
        "action": "create",
        "name": name,
        "path": str(skill_dir),
        "message": f"技能 '{name}' 创建成功",
    }
    if not ingest_ok:
        result["warning"] = "技能文件已保存，但自动索引失败。SearchSkills 可能暂时搜不到，可稍后手动重建索引。"
    return json.dumps(result, ensure_ascii=False)


def _skill_patch(name: str, args: dict[str, Any]) -> str:
    old_string = args.get("old_string")
    new_string = args.get("new_string")

    if old_string is None:
        return json.dumps({"success": False, "error": "old_string 不能为空"}, ensure_ascii=False)
    if new_string is None:
        return json.dumps({"success": False, "error": "new_string 不能为空（删除文本请传空字符串）"}, ensure_ascii=False)

    try:
        skill_path = _resolve_skill_path(name)
    except ValueError:
        return json.dumps({"success": False, "error": f"未找到技能: {name}"}, ensure_ascii=False)

    content = skill_path.read_text(encoding="utf-8")

    if old_string not in content:
        return json.dumps({
            "success": False,
            "error": "old_string 未在 SKILL.md 中找到，请确认内容完全匹配",
        }, ensure_ascii=False)

    new_content = content.replace(old_string, new_string, 1)

    err = _validate_skill_content(new_content)
    if err:
        return json.dumps({"success": False, "error": f"修改后内容无效: {err}"}, ensure_ascii=False)

    skill_path.write_text(new_content, encoding="utf-8")

    ingest_ok = _auto_ingest_skill(skill_path.parent)
    clear_skill_caches()

    logger.info("[SKILLS] Patched skill: %s", name)
    result: dict[str, Any] = {
        "success": True,
        "action": "patch",
        "name": name,
        "path": str(skill_path),
        "message": f"技能 '{name}' 修补成功",
    }
    if not ingest_ok:
        result["warning"] = "技能文件已更新，但自动索引失败。SearchSkills 可能暂时搜不到最新内容。"
    return json.dumps(result, ensure_ascii=False)


def _skill_delete(name: str) -> str:
    import shutil

    try:
        skill_path = _resolve_skill_path(name)
    except ValueError:
        return json.dumps({"success": False, "error": f"未找到技能: {name}"}, ensure_ascii=False)

    skill_dir = skill_path.parent
    _remove_from_store(name)

    try:
        shutil.rmtree(skill_dir)
    except OSError as exc:
        return json.dumps({"success": False, "error": f"删除失败: {exc}"}, ensure_ascii=False)

    clear_skill_caches()

    logger.info("[SKILLS] Deleted skill: %s at %s", name, skill_dir)
    return json.dumps({
        "success": True,
        "action": "delete",
        "name": name,
        "message": f"技能 '{name}' 已删除",
    }, ensure_ascii=False)


# ======================================================================
# Skill search tool handler (called by LLM via SearchSkills tool)
# ======================================================================

_CATALOG_LIMIT = 20


def _list_all_skills_catalog() -> str:
    """Return a compact catalog of all skills (id + name + category only)."""
    from fool_code.skill_store.store import get_store

    store = get_store()
    if store is None:
        return json.dumps({"skills": [], "total": 0}, ensure_ascii=False)

    try:
        raw = store.list_skills()
        skills = json.loads(raw)
    except Exception:
        return json.dumps({"skills": [], "total": 0}, ensure_ascii=False)

    total = len(skills)
    catalog = [
        {"id": s.get("id", ""), "name": s.get("display_name", s.get("id", "")), "category": s.get("category", "")}
        for s in skills[:_CATALOG_LIMIT]
    ]

    result: dict[str, Any] = {"skills": catalog, "total": total}
    if total > _CATALOG_LIMIT:
        result["message"] = f"仅显示前 {_CATALOG_LIMIT} 个，共 {total} 个技能。请用具体关键词搜索更多。"
    return json.dumps(result, ensure_ascii=False, indent=2)


def skill_search(args: dict[str, Any], context: Any = None) -> str:
    """Search the skill store and return brief summaries."""
    query = args.get("query", "").strip()
    if not query:
        raise ValueError("query must not be empty")

    if query.lower() == "all":
        return _list_all_skills_catalog()

    workspace_root = None
    if context and hasattr(context, "workspace_root"):
        workspace_root = context.workspace_root

    has_embedding = False
    try:
        from fool_code.skill_store.retriever import retrieve_skills_brief
        results, has_embedding = retrieve_skills_brief(query, top_k=5, workspace_root=workspace_root)
    except Exception:
        results = []

    # Dynamic threshold: when embeddings are available all 3 RRF signals
    # contribute; without embeddings only keyword + heat are active so we
    # lower the bar to avoid filtering out everything.
    if has_embedding:
        ref_max = 3.0 / 61.0   # vector + keyword + heat
        threshold = 0.9 * ref_max
    else:
        ref_max = 2.0 / 61.0   # keyword + heat only
        threshold = 0.7 * ref_max

    filtered = [r for r in results if r.get("_score", 0) >= threshold]

    if not filtered:
        return json.dumps({"results": [], "message": "未找到高相关度的技能"}, ensure_ascii=False)

    return json.dumps({"results": filtered}, ensure_ascii=False, indent=2)


# ======================================================================
# Skill tool handler (called by LLM via Skill tool)
# ======================================================================

def skill_load(args: dict[str, Any], context: Any = None) -> str:
    skill = args.get("skill", "").strip().lstrip("/").lstrip("$")
    if not skill:
        raise ValueError("skill must not be empty")

    bundled_prompt = get_bundled_skill_prompt(skill)
    if bundled_prompt is not None:
        _record_skill_usage(skill, context)
        return json.dumps({
            "skill": skill,
            "status": "inline",
            "name": skill,
            "source": "bundled",
            "prompt": bundled_prompt,
        }, indent=2, ensure_ascii=False)

    skill_path = _resolve_skill_path(skill)
    content = skill_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    description = fm.get("description", "")
    if not description:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped[:200]
                break

    base_dir = str(skill_path.parent)
    final_content = f"Base directory for this skill: {base_dir}\n\n{body}"

    skill_args = args.get("args", "")
    if skill_args:
        final_content = final_content.replace("$ARGUMENTS", skill_args)

    execution_context = fm.get("context")
    allowed_tools = fm.get("allowed_tools", [])
    model_override = fm.get("model")

    run_subagent = getattr(context, "run_subagent", None) if context else None

    _record_skill_usage(skill, context)

    if execution_context == "fork" and run_subagent is not None:
        from fool_code.runtime.agent_types import AgentDefinition
        fork_agent = AgentDefinition(
            agent_type="skill-fork",
            when_to_use="",
            system_prompt=(
                "You are executing a skill. Follow the skill instructions below "
                "and complete the task. Report your findings concisely."
            ),
            disallowed_tools=["Agent", "SuggestPlanMode"],
            background=False,
            model_role=model_override or "",
            max_turns=10,
            color="green",
        )
        result_text = run_subagent(fork_agent, final_content)
        return json.dumps({
            "skill": skill,
            "status": "forked",
            "result": result_text,
            "commandName": fm.get("name") or fm.get("slug") or skill,
        }, indent=2, ensure_ascii=False)

    return json.dumps({
        "skill": skill,
        "path": str(skill_path),
        "base_dir": base_dir,
        "args": skill_args or None,
        "name": fm.get("name") or fm.get("slug") or skill,
        "description": description,
        "when_to_use": fm.get("when_to_use"),
        "version": fm.get("version"),
        "allowed_tools": allowed_tools,
        "model": model_override,
        "context": execution_context,
        "prompt": final_content,
    }, indent=2, ensure_ascii=False)


def _record_skill_usage(skill_name: str, context: Any = None) -> None:
    """Fire-and-forget: record skill usage in the Skill Store for heat ranking."""
    try:
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return
        session_id = ""
        if context and hasattr(context, "session_id"):
            session_id = str(context.session_id)
        store.record_usage(skill_name, session_id, "")
    except Exception:
        pass


def _resolve_skill_path(skill: str) -> Path:
    # Check dynamic skills first
    if skill in _dynamic_skills:
        p = Path(_dynamic_skills[skill].path) / "SKILL.md"
        if p.exists():
            return p

    for root in _all_skill_search_dirs():
        direct = root / skill / "SKILL.md"
        if direct.exists():
            return direct

        if root.is_dir():
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                path = entry / "SKILL.md"
                if path.exists() and entry.name.lower() == skill.lower():
                    return path

    raise ValueError(f"unknown skill: {skill}")


# ======================================================================
# Bundled skills — ship with the application
# ======================================================================

_bundled_skills: list[SkillInfo] = []


def register_bundled_skill(
    name: str,
    description: str,
    prompt_content: str,
    *,
    when_to_use: str | None = None,
    allowed_tools: list[str] | None = None,
    user_invocable: bool = True,
    context: str | None = None,
    model: str | None = None,
) -> None:
    """Register a bundled skill that ships with the application.

    Bundled skills are always available and don't need SKILL.md files on disk.
    """
    info = SkillInfo(
        name=name,
        description=description,
        when_to_use=when_to_use,
        source="bundled",
        loaded_from="bundled",
        allowed_tools=allowed_tools or [],
        user_invocable=user_invocable,
        context=context,
        model=model,
        content_length=len(prompt_content),
    )
    _bundled_skills.append(info)
    _bundled_skill_prompts[name] = prompt_content


_bundled_skill_prompts: dict[str, str] = {}


def get_bundled_skills() -> list[SkillInfo]:
    return list(_bundled_skills)


def get_bundled_skill_prompt(name: str) -> str | None:
    return _bundled_skill_prompts.get(name)


def init_bundled_skills() -> None:
    """Register all built-in skills. Called at startup."""
    pass


# ======================================================================
# Skill file watcher — hot-reload on disk changes
# ======================================================================

import threading
import time

_watcher_thread: threading.Thread | None = None
_watcher_stop = threading.Event()
_skill_snapshot: dict[str, float] = {}
_on_skills_changed_callbacks: list[Any] = []

_WATCH_INTERVAL_S = 2.0


def _snapshot_skill_dirs() -> dict[str, float]:
    """Build a {filepath: mtime} snapshot of all SKILL.md files in watched dirs."""
    snap: dict[str, float] = {}
    for root in _all_skill_search_dirs():
        if not root.is_dir():
            continue
        try:
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                skill_file = entry / "SKILL.md"
                if skill_file.exists():
                    try:
                        snap[str(skill_file)] = skill_file.stat().st_mtime
                    except OSError:
                        pass
        except OSError:
            continue
    return snap


def _watcher_loop() -> None:
    """Background thread: poll skill directories for changes."""
    global _skill_snapshot
    _skill_snapshot = _snapshot_skill_dirs()

    while not _watcher_stop.is_set():
        _watcher_stop.wait(_WATCH_INTERVAL_S)
        if _watcher_stop.is_set():
            break

        new_snap = _snapshot_skill_dirs()
        if new_snap != _skill_snapshot:
            added = set(new_snap) - set(_skill_snapshot)
            removed = set(_skill_snapshot) - set(new_snap)
            modified = {
                k for k in set(new_snap) & set(_skill_snapshot)
                if new_snap[k] != _skill_snapshot[k]
            }

            if added or removed or modified:
                logger.info(
                    "[SKILLS] File change detected — added=%d removed=%d modified=%d, refreshing",
                    len(added), len(removed), len(modified),
                )
                clear_skill_caches()
                for cb in _on_skills_changed_callbacks:
                    try:
                        cb()
                    except Exception:
                        logger.debug("[SKILLS] Callback error", exc_info=True)

            _skill_snapshot = new_snap


def start_skill_watcher() -> None:
    """Start the background skill file watcher thread."""
    global _watcher_thread
    if _watcher_thread is not None and _watcher_thread.is_alive():
        return
    _watcher_stop.clear()
    _watcher_thread = threading.Thread(
        target=_watcher_loop, name="skill-watcher", daemon=True,
    )
    _watcher_thread.start()
    logger.info("[SKILLS] File watcher started (poll interval: %.1fs)", _WATCH_INTERVAL_S)


def stop_skill_watcher() -> None:
    """Stop the background skill file watcher thread."""
    global _watcher_thread
    _watcher_stop.set()
    if _watcher_thread is not None:
        _watcher_thread.join(timeout=5)
        _watcher_thread = None
    logger.info("[SKILLS] File watcher stopped")


def on_skills_changed(callback: Any) -> None:
    """Register a callback to be called when skill files change on disk."""
    _on_skills_changed_callbacks.append(callback)

