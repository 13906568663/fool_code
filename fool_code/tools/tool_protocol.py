"""Tool protocol — enriched tool abstraction with metadata, categories, and structured results.

Upgrades from plain Callable[[dict], str] to a ToolHandler protocol with:
  - ToolCategory: classification (read_only, edit, execution, meta, mcp)
  - ToolMeta: static metadata per tool (read-only, concurrency, defer, etc.)
  - ToolResult: structured return value with error state and metadata
  - ToolContext: runtime context passed to each tool invocation
  - ToolHandler: abstract base class for all tools
  - FunctionToolHandler: adapter wrapping legacy Callable[[dict], str] functions
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from fool_code.runtime.agent_types import AgentDefinition
    from fool_code.types import ToolDefinition


class ToolCategory(str, Enum):
    READ_ONLY = "read_only"
    EDIT = "edit"
    EXECUTION = "execution"
    META = "meta"
    MCP = "mcp"


@dataclass(frozen=True)
class ToolMeta:
    """Static metadata describing a tool's nature and constraints."""

    name: str
    category: ToolCategory
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    should_defer: bool = False
    requires_user_interaction: bool = False


@dataclass
class ToolResult:
    """Structured result from tool execution."""

    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)


@dataclass
class ToolContext:
    """Runtime context passed to each tool invocation."""

    workspace_root: str = ""
    mode: str = "normal"  # "normal" | "plan"
    agent_id: str | None = None
    run_subagent: Callable[..., str] | None = None
    on_progress: Callable[[str], None] | None = None
    send_ask_user: Callable[[str], None] | None = None
    on_tool_discovered: Callable[[str], None] | None = None


class ToolHandler(ABC):
    """Base class for all tools. Provides metadata, validation, and execution."""

    meta: ToolMeta
    definition: ToolDefinition

    def is_enabled(self) -> bool:
        """Whether this tool is currently available."""
        return True

    def validate_input(self, args: dict[str, Any]) -> str | None:
        """Return error message if input is invalid, None if valid."""
        return None

    @abstractmethod
    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute the tool and return a structured result."""
        ...


class FunctionToolHandler(ToolHandler):
    """Adapts a plain function into a ToolHandler.

    Supports two signatures:
      - fn(args: dict) -> str            (needs_context=False, default)
      - fn(args: dict, ctx: ToolContext) -> str  (needs_context=True)
    """

    def __init__(
        self,
        meta: ToolMeta,
        definition: ToolDefinition,
        fn: Callable[..., str],
        *,
        needs_context: bool = False,
    ) -> None:
        self.meta = meta
        self.definition = definition
        self._fn = fn
        self._needs_context = needs_context

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            if self._needs_context:
                output = self._fn(args, context)
            else:
                output = self._fn(args)
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(output=str(e), is_error=True)
