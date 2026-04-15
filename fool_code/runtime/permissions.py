"""Permission system — 5-level mode + per-tool authorization, matching Rust PermissionPolicy."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable


class PermissionMode(str, Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"
    DEFAULT = "default"
    DONT_ASK = "dont-ask"


# Per-tool required permission level (matches Rust mvp_tool_specs)
TOOL_PERMISSION_MAP: dict[str, PermissionMode] = {
    "bash": PermissionMode.DANGER_FULL_ACCESS,
    "read_file": PermissionMode.READ_ONLY,
    "write_file": PermissionMode.WORKSPACE_WRITE,
    "edit_file": PermissionMode.WORKSPACE_WRITE,
    "glob_search": PermissionMode.READ_ONLY,
    "grep_search": PermissionMode.READ_ONLY,
    "WebFetch": PermissionMode.READ_ONLY,
    "WebSearch": PermissionMode.READ_ONLY,
    "TodoWrite": PermissionMode.WORKSPACE_WRITE,
    "Skill": PermissionMode.READ_ONLY,
    "SearchSkills": PermissionMode.READ_ONLY,
    "SkillManage": PermissionMode.WORKSPACE_WRITE,
    "Agent": PermissionMode.DANGER_FULL_ACCESS,
    "ToolSearch": PermissionMode.READ_ONLY,
    "NotebookEdit": PermissionMode.WORKSPACE_WRITE,
    "Sleep": PermissionMode.READ_ONLY,
    "SendUserMessage": PermissionMode.READ_ONLY,
    "Brief": PermissionMode.READ_ONLY,
    "Config": PermissionMode.WORKSPACE_WRITE,
    "StructuredOutput": PermissionMode.READ_ONLY,
    "REPL": PermissionMode.DANGER_FULL_ACCESS,
    "PowerShell": PermissionMode.DANGER_FULL_ACCESS,
    "Playbook": PermissionMode.READ_ONLY,
    "SuggestPlanMode": PermissionMode.READ_ONLY,
    "AskUserQuestion": PermissionMode.READ_ONLY,
    # --- Computer Use ---
    "computer_screenshot": PermissionMode.READ_ONLY,
    "computer_screenshot_region": PermissionMode.READ_ONLY,
    "computer_cursor_position": PermissionMode.READ_ONLY,
    "computer_click": PermissionMode.DANGER_FULL_ACCESS,
    "computer_type": PermissionMode.DANGER_FULL_ACCESS,
    "computer_key": PermissionMode.DANGER_FULL_ACCESS,
    "computer_scroll": PermissionMode.DANGER_FULL_ACCESS,
    "computer_drag": PermissionMode.DANGER_FULL_ACCESS,
    "computer_wait": PermissionMode.READ_ONLY,
    "mcp__browser__get_browser_state": PermissionMode.READ_ONLY,
    "mcp__browser__list_tabs": PermissionMode.READ_ONLY,
    "mcp__browser__get_cookies": PermissionMode.READ_ONLY,
    # "mcp__browser__take_screenshot": PermissionMode.READ_ONLY,
    "mcp__browser__wait": PermissionMode.READ_ONLY,
    "mcp__browser__wait_for_page_stable": PermissionMode.READ_ONLY,
    "mcp__browser__click_element": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__input_text": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__select_option": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__scroll": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__navigate": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__open_tab": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__close_tab": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__switch_tab": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__set_cookie": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__remove_cookie": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__clear_cookies": PermissionMode.WORKSPACE_WRITE,
    "mcp__browser__execute_javascript": PermissionMode.DANGER_FULL_ACCESS,
}

_PERMISSION_RANK = {
    PermissionMode.READ_ONLY: 0,
    PermissionMode.WORKSPACE_WRITE: 1,
    PermissionMode.DANGER_FULL_ACCESS: 2,
}


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALWAYS = "always"


class PermissionPolicy:
    """Determines whether a given tool call is auto-allowed or needs user approval."""

    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT) -> None:
        self.mode = mode
        self._tool_overrides: dict[str, PermissionMode] = {}

    def with_tool_requirement(self, tool_name: str, required: PermissionMode) -> "PermissionPolicy":
        self._tool_overrides[tool_name] = required
        return self

    def is_auto_allowed(self, tool_name: str) -> bool:
        if self.mode == PermissionMode.DANGER_FULL_ACCESS or self.mode == PermissionMode.DONT_ASK:
            return True

        required = self._tool_overrides.get(tool_name, TOOL_PERMISSION_MAP.get(tool_name))
        if required is None:
            return False

        if self.mode == PermissionMode.READ_ONLY:
            return required == PermissionMode.READ_ONLY
        if self.mode == PermissionMode.WORKSPACE_WRITE:
            return _PERMISSION_RANK.get(required, 99) <= _PERMISSION_RANK[PermissionMode.WORKSPACE_WRITE]
        # DEFAULT mode: prompt for workspace-write and above
        return required == PermissionMode.READ_ONLY


class PermissionGate:
    """Manages permission prompting for a chat session."""

    def __init__(self, policy: PermissionPolicy | None = None) -> None:
        self._decision_event = threading.Event()
        self._decision: str = "deny"
        self._lock = threading.Lock()
        self._always_allowed: set[str] = set()
        self.policy = policy or PermissionPolicy(PermissionMode.DANGER_FULL_ACCESS)

    def request_permission(
        self,
        tool_name: str,
        tool_input: str,
        send_event: Callable,
        mode: PermissionMode | None = None,
    ) -> PermissionDecision:
        if tool_name in self._always_allowed:
            return PermissionDecision.ALLOW

        if self.policy.is_auto_allowed(tool_name):
            return PermissionDecision.ALLOW

        self._decision_event.clear()
        send_event(tool_name, tool_input)

        if self._decision_event.wait(timeout=300):
            with self._lock:
                raw = self._decision
        else:
            raw = "deny"

        if raw == "allow":
            return PermissionDecision.ALLOW
        if raw == "always":
            self._always_allowed.add(tool_name)
            return PermissionDecision.ALWAYS
        return PermissionDecision.DENY

    def submit_decision(self, decision: str) -> None:
        with self._lock:
            self._decision = decision
        self._decision_event.set()
