"""Tool registry — maps tool names to ToolHandler instances and OpenAI function schemas.

Architecture upgrade: tools are now first-class ToolHandler objects carrying
metadata (ToolMeta), structured results (ToolResult), and execution context
(ToolContext). Legacy Callable[[dict], str] functions are wrapped via
FunctionToolHandler for backward compatibility.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from fool_code.tools.tool_protocol import (
    FunctionToolHandler,
    ToolCategory,
    ToolContext,
    ToolHandler,
    ToolMeta,
    ToolResult,
)
from fool_code.types import ToolDefinition, ToolFunction, ToolParameter


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._mcp_tool_names: set[str] = set()
        self._cached_full: list[dict] | None = None
        self._cached_core: list[dict] | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_handler(self, handler: ToolHandler) -> None:
        """Register a full ToolHandler (preferred)."""
        self._handlers[handler.meta.name] = handler
        self._definitions[handler.meta.name] = handler.definition
        self._invalidate_cache()

    def register(
        self,
        name: str,
        handler_fn: Any,
        definition: ToolDefinition,
        *,
        meta: ToolMeta | None = None,
        needs_context: bool = False,
    ) -> None:
        """Legacy compat: wrap a plain function as FunctionToolHandler."""
        if meta is None:
            meta = ToolMeta(name=name, category=ToolCategory.META)
        wrapped = FunctionToolHandler(
            meta=meta, definition=definition, fn=handler_fn, needs_context=needs_context,
        )
        self.register_handler(wrapped)

    def register_mcp_tool(self, name: str, definition: ToolDefinition) -> None:
        self._mcp_tool_names.add(name)
        self._definitions[name] = definition
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_handler(self, name: str) -> ToolHandler | None:
        return self._handlers.get(name)

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._mcp_tool_names

    def mcp_tool_names(self) -> list[str]:
        return sorted(self._mcp_tool_names)

    def is_tool_read_only(self, tool_name: str, args: dict[str, Any] | None = None) -> bool:
        handler = self._handlers.get(tool_name)
        if handler:
            if args and hasattr(handler, "is_read_only_for"):
                return handler.is_read_only_for(args)
            return handler.meta.is_read_only
        from fool_code.runtime.permissions import TOOL_PERMISSION_MAP, PermissionMode
        perm = TOOL_PERMISSION_MAP.get(tool_name)
        return perm == PermissionMode.READ_ONLY if perm else False

    def handlers_by_category(self, category: ToolCategory) -> list[ToolHandler]:
        return [h for h in self._handlers.values() if h.meta.category == category]

    def enabled_handlers(self) -> list[ToolHandler]:
        return [h for h in self._handlers.values() if h.is_enabled()]

    # ------------------------------------------------------------------
    # Definitions (for LLM API)
    # ------------------------------------------------------------------

    def definitions(self) -> list[dict]:
        """Full tool list — used by sub-agents and internal queries."""
        if self._cached_full is not None:
            return self._cached_full
        defs = self._build_full_defs()
        self._cached_full = defs
        return defs

    def definitions_filtered(self, discovered: set[str] | None = None) -> list[dict]:
        """Core tools + discovered deferred tools — for main LLM calls.

        ``discovered`` is the per-session set of tool names that have been
        activated via ToolSearch.  Deferred built-in tools and all MCP tools
        are excluded unless their name appears in this set.

        When *discovered* is ``None`` or empty, only core (non-deferred)
        built-in tools are returned — typically ~15 tools instead of ~50,
        saving thousands of tokens per LLM round-trip.
        """
        if not discovered:
            if self._cached_core is not None:
                return self._cached_core
            defs = self._build_core_defs()
            self._cached_core = defs
            return defs

        # With a non-empty discovered set we must build on the fly because
        # the set is per-session and changes independently of the registry.
        return self._build_filtered_defs(discovered)

    def _build_full_defs(self) -> list[dict]:
        defs = []
        for handler in self._handlers.values():
            if handler.is_enabled():
                defs.append(handler.definition.model_dump())
        for name in sorted(self._mcp_tool_names):
            defn = self._definitions.get(name)
            if defn:
                defs.append(defn.model_dump())
        return defs

    def _build_core_defs(self) -> list[dict]:
        """Only non-deferred built-in tools (no MCP)."""
        defs = []
        for handler in self._handlers.values():
            if not handler.is_enabled():
                continue
            if handler.meta.should_defer:
                continue
            defs.append(handler.definition.model_dump())
        return defs

    def _build_filtered_defs(self, discovered: set[str]) -> list[dict]:
        """Core tools + deferred tools present in *discovered*."""
        defs = []
        for handler in self._handlers.values():
            if not handler.is_enabled():
                continue
            if handler.meta.should_defer and handler.meta.name not in discovered:
                continue
            defs.append(handler.definition.model_dump())
        for name in sorted(self._mcp_tool_names):
            if name not in discovered:
                continue
            defn = self._definitions.get(name)
            if defn:
                defs.append(defn.model_dump())
        return defs

    def tool_names(self) -> list[str]:
        names = [h.meta.name for h in self._handlers.values() if h.is_enabled()]
        names.extend(sorted(self._mcp_tool_names))
        return names

    def deferred_tool_names(self) -> list[str]:
        """Names of all deferred tools (built-in + MCP) for prompt injection."""
        names: list[str] = []
        for handler in self._handlers.values():
            if handler.is_enabled() and handler.meta.should_defer:
                names.append(handler.meta.name)
        names.extend(sorted(self._mcp_tool_names))
        return sorted(names)

    def _invalidate_cache(self) -> None:
        self._cached_full = None
        self._cached_core = None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self, tool_name: str, raw_input: str, context: ToolContext | None = None,
    ) -> ToolResult:
        if self.is_mcp_tool(tool_name):
            return ToolResult(
                output=f"MCP tool '{tool_name}' must be executed via McpServerManager",
                is_error=True,
            )

        handler = self._handlers.get(tool_name)
        if handler is None:
            return ToolResult(output=f"Unknown tool: {tool_name}", is_error=True)

        try:
            args = json.loads(raw_input) if raw_input else {}
        except json.JSONDecodeError:
            args = {"raw": raw_input}

        ctx = context or ToolContext()

        error = handler.validate_input(args)
        if error:
            return ToolResult(output=error, is_error=True)

        return handler.execute(args, ctx)

    # ------------------------------------------------------------------
    # MCP management
    # ------------------------------------------------------------------

    def unregister_mcp_server(self, server_name: str) -> None:
        prefix = f"mcp__{server_name}__"
        to_remove = [n for n in self._mcp_tool_names if n.startswith(prefix)]
        for name in to_remove:
            self._mcp_tool_names.discard(name)
            self._definitions.pop(name, None)
        if to_remove:
            self._invalidate_cache()

    def clear_mcp_tools(self) -> None:
        for name in list(self._mcp_tool_names):
            self._definitions.pop(name, None)
        self._mcp_tool_names.clear()
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Filtering (for sub-agents)
    # ------------------------------------------------------------------

    def filter_tools(
        self,
        *,
        exclude: list[str] | None = None,
        include_only: list[str] | None = None,
    ) -> ToolRegistry:
        """Create a filtered copy of this registry for sub-agent use."""
        exclude_set = set(exclude) if exclude else set()
        include_set = set(include_only) if include_only else None

        new_registry = ToolRegistry()

        for name, handler in self._handlers.items():
            if name in exclude_set:
                continue
            if include_set is not None and name not in include_set:
                continue
            new_registry.register_handler(handler)

        for name in self._mcp_tool_names:
            if name in exclude_set:
                continue
            if include_set is not None and name not in include_set:
                continue
            defn = self._definitions.get(name)
            if defn:
                new_registry.register_mcp_tool(name, defn)

        return new_registry


# ======================================================================
# Schema helpers
# ======================================================================

def _td(name: str, description: str, props: dict, required: list[str]) -> ToolDefinition:
    return ToolDefinition(
        function=ToolFunction(
            name=name,
            description=description,
            parameters=ToolParameter(properties=props, required=required),
        )
    )


def _meta(
    name: str,
    category: ToolCategory,
    *,
    read_only: bool = False,
    concurrent: bool = False,
    defer: bool = False,
    user_interaction: bool = False,
) -> ToolMeta:
    return ToolMeta(
        name=name,
        category=category,
        is_read_only=read_only,
        is_concurrency_safe=concurrent,
        should_defer=defer,
        requires_user_interaction=user_interaction,
    )


# ======================================================================
# ToolSearch handler (needs registry reference)
# ======================================================================

class _ToolSearchHandler(ToolHandler):
    def __init__(self, meta: ToolMeta, definition: ToolDefinition) -> None:
        self.meta = meta
        self.definition = definition
        self._registry: ToolRegistry | None = None

    def set_registry(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        from fool_code.tools.misc import tool_search
        names = self._registry.tool_names() if self._registry else []
        try:
            output = tool_search(args, all_tool_names=names)
            if context.on_tool_discovered:
                matches = json.loads(output).get("matches", [])
                for name in matches:
                    context.on_tool_discovered(name)
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(output=str(e), is_error=True)


# ======================================================================
# Dynamic read-only detection for shell tools
# ======================================================================

_READ_ONLY_COMMAND_PREFIXES = (
    "ls", "dir", "cat", "type", "head", "tail", "less", "more",
    "pwd", "cd", "echo", "print", "which", "where", "where.exe",
    "whoami", "hostname", "uname", "date", "uptime",
    "git status", "git log", "git diff", "git show", "git branch",
    "git remote", "git tag", "git stash list",
    "find", "locate", "wc", "sort", "uniq", "grep", "rg", "ag",
    "file", "stat", "df", "du", "free", "top", "ps", "env", "set",
    "docker ps", "docker images", "docker logs", "docker inspect",
    "kubectl get", "kubectl describe", "kubectl logs",
    "systemctl status", "journalctl", "service",
    "pip list", "pip show", "npm list", "npm ls", "node -v",
    "python --version", "java -version",
    "netstat", "ss", "ping", "traceroute", "nslookup", "dig", "curl",
    "kafka-consumer-groups.sh --describe", "kafka-topics.sh --list",
    "kafka-topics.sh --describe",
)


def _is_read_only_command(args: dict[str, Any]) -> bool:
    cmd = (args.get("command") or "").strip().lstrip("sudo ")
    if not cmd:
        return False
    cmd_lower = cmd.lower()
    return any(cmd_lower.startswith(p) for p in _READ_ONLY_COMMAND_PREFIXES)


def _attach_shell_read_only_check(registry: "ToolRegistry", name: str) -> None:
    handler = registry.get_handler(name)
    if handler:
        handler.is_read_only_for = _is_read_only_command  # type: ignore[attr-defined]


# ======================================================================
# Build the default registry
# ======================================================================

def build_tool_registry() -> ToolRegistry:
    """Create a registry with all built-in tools wrapped as ToolHandlers."""
    from fool_code.tools.bash import execute_bash
    from fool_code.tools.file_ops import read_file, write_file, edit_file
    from fool_code.tools.search import glob_search, grep_search
    from fool_code.tools.web import web_fetch, web_search
    from fool_code.tools.todo import TodoWriteHandler
    from fool_code.tools.skill import skill_load, skill_search, skill_manage
    from fool_code.tools.notebook import notebook_edit
    from fool_code.tools.misc import (
        sleep_tool,
        send_user_message,
        config_tool,
        structured_output,
        repl_tool,
        powershell_tool,
        agent_tool,
        ask_user_question,
    )
    from fool_code.tools.playbook import playbook_tool
    from fool_code.tools.plan_mode import SuggestPlanModeHandler

    registry = ToolRegistry()

    is_windows = sys.platform == "win32"

    # --- bash ---
    registry.register(
        "bash",
        execute_bash,
        _td(
            "bash",
            "Execute a shell command via PowerShell. Supports pipes, variables, and all Windows/PowerShell commands. "
            "Working directory persists across calls (cd is tracked). Default timeout: 30 minutes."
            if is_windows
            else "Execute a shell command in the current workspace via bash. "
            "Working directory persists across calls (cd is tracked). Default timeout: 30 minutes.",
            {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "minimum": 1},
                "description": {"type": "string"},
                "run_in_background": {"type": "boolean"},
            },
            ["command"],
        ),
        meta=_meta("bash", ToolCategory.EXECUTION),
        needs_context=True,
    )
    _attach_shell_read_only_check(registry, "bash")

    # --- read_file ---
    registry.register(
        "read_file",
        read_file,
        _td(
            "read_file",
            "读取工作区中的文本文件。拒绝已知的二进制类型"
            "（如图片、PDF、Office文档、压缩包、可执行文件）；请使用其他工具或先导出为纯文本。",
            {
                "path": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1},
            },
            ["path"],
        ),
        meta=_meta("read_file", ToolCategory.READ_ONLY, read_only=True, concurrent=True),
    )

    # --- write_file ---
    registry.register(
        "write_file",
        write_file,
        _td(
            "write_file",
            "在工作区中写入文本文件。"
            "重要：调用 write_file 之前必须先对目标文件调用 read_file。"
            "如果文件已存在且你在本次对话中尚未读取过它，write_file 将会失败。"
            "务必先读取，再写入。",
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            ["path", "content"],
        ),
        meta=_meta("write_file", ToolCategory.EDIT),
    )

    # --- edit_file ---
    registry.register(
        "edit_file",
        edit_file,
        _td(
            "edit_file",
            "替换工作区文件中的文本内容。"
            "重要：调用 edit_file 之前必须先对目标文件调用 read_file。"
            "如果你在本次对话中尚未读取过该文件，edit_file 将会失败。"
            "不要批量发送多个 edit_file 去修改尚未读取的文件——"
            "先逐个读取文件，再逐个编辑。",
            {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            ["path", "old_string", "new_string"],
        ),
        meta=_meta("edit_file", ToolCategory.EDIT),
    )

    # --- glob_search ---
    registry.register(
        "glob_search",
        glob_search,
        _td(
            "glob_search",
            "Find files by glob pattern.",
            {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            ["pattern"],
        ),
        meta=_meta("glob_search", ToolCategory.READ_ONLY, read_only=True, concurrent=True),
    )

    # --- grep_search ---
    registry.register(
        "grep_search",
        grep_search,
        _td(
            "grep_search",
            "Search file contents with a regex pattern.",
            {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string"},
                "output_mode": {"type": "string"},
                "-B": {"type": "integer", "minimum": 0},
                "-A": {"type": "integer", "minimum": 0},
                "-C": {"type": "integer", "minimum": 0},
                "-i": {"type": "boolean"},
                "type": {"type": "string"},
                "head_limit": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0},
                "multiline": {"type": "boolean"},
            },
            ["pattern"],
        ),
        meta=_meta("grep_search", ToolCategory.READ_ONLY, read_only=True, concurrent=True),
    )

    # --- WebFetch ---
    registry.register(
        "WebFetch",
        web_fetch,
        _td(
            "WebFetch",
            "Fetch a URL, convert it into readable text, and answer a prompt about it.",
            {
                "url": {"type": "string", "format": "uri"},
                "prompt": {"type": "string"},
            },
            ["url", "prompt"],
        ),
        meta=_meta("WebFetch", ToolCategory.READ_ONLY, read_only=True, concurrent=True, defer=True),
    )

    # --- WebSearch ---
    registry.register(
        "WebSearch",
        web_search,
        _td(
            "WebSearch",
            "Search the web for current information and return cited results.",
            {
                "query": {"type": "string", "minLength": 2},
                "allowed_domains": {"type": "array", "items": {"type": "string"}},
                "blocked_domains": {"type": "array", "items": {"type": "string"}},
            },
            ["query"],
        ),
        meta=_meta("WebSearch", ToolCategory.READ_ONLY, read_only=True, concurrent=True, defer=True),
    )

    # --- TodoWrite ---
    registry.register_handler(TodoWriteHandler())

    # --- Skill ---
    registry.register(
        "Skill",
        skill_load,
        _td(
            "Skill",
            "Execute a skill within the main conversation. Skills provide specialized "
            "capabilities and domain knowledge. Use SearchSkills to find available skills first, "
            "then use this tool to invoke them by name.",
            {
                "skill": {"type": "string", "description": "The skill name, e.g. 'excel-xlsx', 'commit'"},
                "args": {"type": "string", "description": "Optional arguments for the skill"},
            },
            ["skill"],
        ),
        meta=_meta("Skill", ToolCategory.META, read_only=True, concurrent=True),
        needs_context=True,
    )

    # --- SearchSkills ---
    registry.register(
        "SearchSkills",
        skill_search,
        _td(
            "SearchSkills",
            "搜索技能库，返回与查询匹配的技能列表。"
            "传入 query='all' 返回所有技能的基本信息（ID、名称、分类）。"
            "传入具体描述则按相关度返回匹配的技能（仅返回高相关度结果）。"
            "找到合适的技能后，用 Skill 工具加载其完整文档。",
            {
                "query": {"type": "string", "description": "传 'all' 列出全部技能；或传自然语言搜索词如 '处理Excel文件'"},
            },
            ["query"],
        ),
        meta=_meta("SearchSkills", ToolCategory.META, read_only=True, concurrent=True),
        needs_context=True,
    )

    # --- SkillManage ---
    registry.register(
        "SkillManage",
        skill_manage,
        _td(
            "SkillManage",
            "创建、修补或删除用户技能。\n\n"
            "何时创建（action='create'）：\n"
            "- 完成了涉及 5 次以上工具调用的复杂任务\n"
            "- 修复了不直觉的 bug 或发现了可复用的工作流程\n"
            "- 用户明确要求保存当前方法为技能\n\n"
            "何时修补（action='patch'）：\n"
            "- 使用技能时发现其内容过时或有误\n"
            "- 环境/依赖变更导致技能步骤需要更新\n\n"
            "何时删除（action='delete'）：\n"
            "- 技能内容已被合并到其他技能中\n"
            "- 技能不再有用\n\n"
            "content 必须是完整的 SKILL.md 格式（YAML frontmatter + 正文）。"
            "frontmatter 至少包含 name 和 description 字段。",
            {
                "action": {
                    "type": "string",
                    "enum": ["create", "patch", "delete"],
                    "description": "操作类型",
                },
                "name": {
                    "type": "string",
                    "description": "技能 ID（目录名），如 'excel-handler'",
                },
                "content": {
                    "type": "string",
                    "description": "（create 时必填）完整的 SKILL.md 内容，含 YAML frontmatter",
                },
                "old_string": {
                    "type": "string",
                    "description": "（patch 时必填）要替换的原文",
                },
                "new_string": {
                    "type": "string",
                    "description": "（patch 时必填）替换后的新文本",
                },
                "category": {
                    "type": "string",
                    "description": "（可选）技能分类子目录，如 'database'、'devops'",
                },
            },
            ["action", "name"],
        ),
        meta=_meta("SkillManage", ToolCategory.EDIT),
    )

    # --- Agent ---
    registry.register(
        "Agent",
        agent_tool,
        _td(
            "Agent",
            "启动一个新的代理来自主处理复杂的多步骤任务。\n\n"
            "Agent 工具会启动专门的代理（子进程），自主处理复杂任务。"
            "每种代理类型都有特定的能力和可用工具。\n\n"
            "可用的代理类型：\n"
            "- explore：快速只读代理，专门用于探索代码库。"
            "用于快速查找文件模式、搜索代码关键词或回答关于代码库的问题。"
            "指定期望的彻底程度：\"quick\"、\"medium\" 或 \"very thorough\"。\n"
            "- plan：软件架构师代理，用于设计实现方案。"
            "返回逐步方案，识别关键文件，并考虑架构权衡。只读。\n"
            "- general-purpose：通用代理，用于研究复杂问题、搜索代码和执行"
            "多步骤任务。当你搜索关键词或文件但不确定前几次尝试能否找到时使用。\n"
            "- verification：在报告完成之前验证已完成的工作。"
            "在非平凡任务（3个以上文件编辑、API 变更、基础设施工作）后使用。\n\n"
            "何时不要使用 Agent 工具：\n"
            "- 如果你想读取一个特定文件路径，直接使用 read_file\n"
            "- 如果你在搜索特定的类定义如 \"class Foo\"，直接使用 Glob 或 Grep\n"
            "- 如果你在 2-3 个已知文件中搜索代码，直接使用 read_file\n"
            "- 其他不需要多步骤调查的简单任务\n\n"
            "使用说明：\n"
            "- 始终附带一个简短的描述（3-5 个词）概括任务\n"
            "- 尽可能同时启动多个代理以最大化效率；"
            "方法是在一次回复中多次调用 Agent\n"
            "- 代理完成后会向你返回结果。结果对用户不可见。"
            "你必须为用户总结结果。\n"
            "- 明确告诉代理你期望它写代码还是只做研究"
            "（搜索、读文件），因为它不了解用户的意图\n\n"
            "## 如何编写 prompt\n\n"
            "像给一个刚走进房间的聪明同事做简报一样——"
            "他没有看过这次对话，不知道你试过什么，不理解为什么这个任务重要。\n"
            "- 解释你试图完成什么以及为什么\n"
            "- 描述你已经了解到的或排除的内容\n"
            "- 提供足够的周边问题上下文，让代理能做出判断，"
            "而不是仅仅遵循狭隘的指令\n"
            "- 如果你需要简短的回复，明确说明（\"200 字以内报告\"）\n\n"
            "简短的命令式 prompt 会产生肤浅、泛泛的工作。\n\n"
            "**不要委托理解。** 不要写 \"根据你的发现，修复这个 bug\" "
            "或 \"根据研究，实现它\"。这些说法把综合理解推给了代理。"
            "写能证明你理解了的 prompt：包含文件路径、行号、具体要改什么。",
            {
                "description": {"type": "string", "description": "任务的简短描述（3-5 个词）"},
                "prompt": {"type": "string", "description": "代理要执行的任务"},
                "subagent_type": {"type": "string", "description": "要使用的专用代理类型（explore、plan、general-purpose、verification）"},
                "name": {"type": "string", "description": "可选的代理名称"},
                "model": {"type": "string", "description": "可选的模型覆盖（sonnet、opus、haiku）"},
            },
            ["description", "prompt"],
        ),
        meta=_meta("Agent", ToolCategory.META),
        needs_context=True,
    )

    # --- Playbook ---
    registry.register(
        "Playbook",
        playbook_tool,
        _td(
            "Playbook",
            "查阅用户的经验文档库。action='categories' 查看分类概览，"
            "action='list' 查看分类下的文档列表，action='read' 读取具体文档。",
            {
                "action": {
                    "type": "string",
                    "enum": ["categories", "list", "read"],
                },
                "category": {"type": "string"},
                "filename": {"type": "string"},
            },
            ["action"],
        ),
        meta=_meta("Playbook", ToolCategory.META, read_only=True, concurrent=True, defer=True),
    )

    # --- ToolSearch ---
    ts_handler = _ToolSearchHandler(
        meta=_meta("ToolSearch", ToolCategory.META, read_only=True, concurrent=True),
        definition=_td(
            "ToolSearch",
            "Fetch full schema definitions for deferred tools so they can be called. "
            "Not all tools are loaded by default — some specialized tools (web, MCP, "
            "notebook, computer-use, etc.) are deferred to save tokens. Until fetched "
            "via this tool, only their names are known and they cannot be invoked.\n\n"
            "Query forms:\n"
            '- "select:WebSearch,WebFetch" — fetch exact tools by name\n'
            '- "notebook jupyter" — keyword search, returns up to max_results matches\n'
            '- "mcp ssh" — find MCP tools by keyword',
            {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1},
            },
            ["query"],
        ),
    )
    registry.register_handler(ts_handler)
    ts_handler.set_registry(registry)

    # --- NotebookEdit ---
    registry.register(
        "NotebookEdit",
        notebook_edit,
        _td(
            "NotebookEdit",
            "Replace, insert, or delete a cell in a Jupyter notebook.",
            {
                "notebook_path": {"type": "string"},
                "cell_id": {"type": "string"},
                "new_source": {"type": "string"},
                "cell_type": {"type": "string", "enum": ["code", "markdown"]},
                "edit_mode": {"type": "string", "enum": ["replace", "insert", "delete"]},
            },
            ["notebook_path"],
        ),
        meta=_meta("NotebookEdit", ToolCategory.EDIT, defer=True),
    )

    # --- Sleep ---
    registry.register(
        "Sleep",
        sleep_tool,
        _td(
            "Sleep",
            "Wait for a specified duration without holding a shell process.",
            {
                "duration_ms": {"type": "integer", "minimum": 0},
            },
            ["duration_ms"],
        ),
        meta=_meta("Sleep", ToolCategory.META, read_only=True, concurrent=True),
    )

    # --- SendUserMessage ---
    registry.register(
        "SendUserMessage",
        send_user_message,
        _td(
            "SendUserMessage",
            "Send a message to the user.",
            {
                "message": {"type": "string"},
                "attachments": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["normal", "proactive"]},
            },
            ["message", "status"],
        ),
        meta=_meta("SendUserMessage", ToolCategory.META, read_only=True, concurrent=True),
    )

    # --- Brief (alias for SendUserMessage) ---
    registry.register(
        "Brief",
        send_user_message,
        _td(
            "Brief",
            "Send a brief message to the user (alias for SendUserMessage).",
            {
                "message": {"type": "string"},
                "attachments": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["normal", "proactive"]},
            },
            ["message", "status"],
        ),
        meta=_meta("Brief", ToolCategory.META, read_only=True, concurrent=True),
    )

    # --- Config ---
    registry.register(
        "Config",
        config_tool,
        _td(
            "Config",
            "Get or set Fool Code settings.",
            {
                "setting": {"type": "string"},
                "value": {"type": ["string", "boolean", "number"]},
            },
            ["setting"],
        ),
        meta=_meta("Config", ToolCategory.META, defer=True),
    )

    # --- StructuredOutput ---
    registry.register(
        "StructuredOutput",
        structured_output,
        ToolDefinition(
            function=ToolFunction(
                name="StructuredOutput",
                description="Return structured output in the requested format.",
                parameters=ToolParameter(properties={}, required=[]),
            )
        ),
        meta=_meta("StructuredOutput", ToolCategory.META, read_only=True, concurrent=True, defer=True),
    )

    # --- REPL ---
    registry.register(
        "REPL",
        repl_tool,
        _td(
            "REPL",
            "Execute code in a REPL-like subprocess.",
            {
                "code": {"type": "string"},
                "language": {"type": "string"},
                "timeout_ms": {"type": "integer", "minimum": 1},
            },
            ["code", "language"],
        ),
        meta=_meta("REPL", ToolCategory.EXECUTION, defer=True),
    )

    # --- PowerShell ---
    registry.register(
        "PowerShell",
        powershell_tool,
        _td(
            "PowerShell",
            "Execute a PowerShell command. Preferred over bash on Windows for better Unicode support and richer scripting."
            if is_windows
            else "Execute a PowerShell command with optional timeout.",
            {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "minimum": 1},
                "description": {"type": "string"},
                "run_in_background": {"type": "boolean"},
            },
            ["command"],
        ),
        meta=_meta("PowerShell", ToolCategory.EXECUTION),
    )
    _attach_shell_read_only_check(registry, "PowerShell")

    # --- SuggestPlanMode ---
    registry.register_handler(SuggestPlanModeHandler())

    # --- AskUserQuestion ---
    registry.register(
        "AskUserQuestion",
        ask_user_question,
        _td(
            "AskUserQuestion",
            "Present structured multiple-choice questions to the user and wait for their answers. "
            "Use when you need clarification, want to offer choices between approaches, "
            "or need user input before proceeding. Each question has 2-4 options.",
            {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                    "required": ["label"],
                                },
                                "minItems": 2,
                                "maxItems": 4,
                            },
                        },
                        "required": ["question", "options"],
                    },
                    "minItems": 1,
                    "maxItems": 4,
                },
            },
            ["questions"],
        ),
        meta=_meta("AskUserQuestion", ToolCategory.READ_ONLY, read_only=True),
        needs_context=True,
    )

    # --- Computer Use (Windows, optional — remove this block to uninstall) ---
    if is_windows:
        try:
            from fool_code.computer_use import register_computer_use
            register_computer_use(registry)
        except Exception:
            pass

    # --- MemoryQuery (MAGMA episodic memory) ---
    from fool_code.tools.memory_query import memory_query_tool
    registry.register(
        "MemoryQuery",
        memory_query_tool,
        _td(
            "MemoryQuery",
            "查询用户的历史活动记录（情景记忆）。当用户问「我最近做了什么」「上个月干了什么」「之前讨论过XXX吗」等与过往活动相关的问题时，调用此工具。"
            "传入自然语言查询，返回匹配的历史活动摘要。支持时间表达（如「上周」「3月」「去年夏天」）和语义搜索。",
            {
                "query": {
                    "type": "string",
                    "description": "自然语言查询，例如「最近一周我做了什么」「上个月讨论过的项目」",
                },
            },
            ["query"],
        ),
        meta=_meta("MemoryQuery", ToolCategory.READ_ONLY, read_only=True, concurrent=True),
        needs_context=True,
    )

    # --- Initialize bundled skills ---
    from fool_code.tools.skill import init_bundled_skills
    init_bundled_skills()

    return registry
