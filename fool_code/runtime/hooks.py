"""Hook system — pre/post tool-use hooks and stop hooks."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"


@dataclass
class HookRunResult:
    denied: bool = False
    messages: list[str] = field(default_factory=list)

    @staticmethod
    def allow(messages: list[str] | None = None) -> HookRunResult:
        return HookRunResult(denied=False, messages=messages or [])

    @property
    def is_denied(self) -> bool:
        return self.denied


class StopHookOutcome(Enum):
    ALLOW = "allow"
    BLOCKING = "blocking"
    PREVENT_CONTINUATION = "prevent_continuation"


@dataclass
class StopHookResult:
    outcome: StopHookOutcome
    message: str = ""


@dataclass
class HookConfig:
    pre_tool_use: list[str] = field(default_factory=list)
    post_tool_use: list[str] = field(default_factory=list)
    stop: list[str] = field(default_factory=list)
    stop_agent_prompt: str | None = None

    @staticmethod
    def from_settings(settings: dict[str, Any]) -> HookConfig:
        hooks = settings.get("hooks", {})
        if not isinstance(hooks, dict):
            return HookConfig()
        return HookConfig(
            pre_tool_use=hooks.get("PreToolUse", []),
            post_tool_use=hooks.get("PostToolUse", []),
            stop=hooks.get("Stop", []),
            stop_agent_prompt=hooks.get("StopAgent"),
        )


class HookRunner:
    def __init__(self, config: HookConfig | None = None) -> None:
        self.config = config or HookConfig()

    @property
    def has_stop_hooks(self) -> bool:
        return bool(self.config.stop)

    def run_stop_hooks(
        self, last_assistant_text: str, stop_hook_active: bool
    ) -> StopHookResult:
        commands = self.config.stop
        if not commands:
            return StopHookResult(outcome=StopHookOutcome.ALLOW)

        payload = json.dumps({
            "hook_event_name": "Stop",
            "stop_hook_active": stop_hook_active,
            "last_assistant_message": last_assistant_text,
        })

        for command in commands:
            try:
                result = _run_shell_hook(command, {
                    "HOOK_EVENT": "Stop",
                    "HOOK_STOP_ACTIVE": "1" if stop_hook_active else "0",
                }, payload)
            except Exception:
                continue

            stdout = result.stdout.strip()

            parsed = _try_parse_stop_json(stdout)
            if parsed is not None and parsed.get("prevent_continuation"):
                reason = parsed.get("reason", "Stop hook prevented continuation")
                return StopHookResult(
                    outcome=StopHookOutcome.PREVENT_CONTINUATION, message=reason
                )

            if result.returncode == 2:
                message = stdout or f"Stop hook `{command}` blocked: condition not met"
                return StopHookResult(
                    outcome=StopHookOutcome.BLOCKING, message=message
                )

        return StopHookResult(outcome=StopHookOutcome.ALLOW)

    def run_pre_tool_use(self, tool_name: str, tool_input: str) -> HookRunResult:
        return self._run_commands(
            HookEvent.PRE_TOOL_USE,
            self.config.pre_tool_use,
            tool_name, tool_input, None, False,
        )

    def run_post_tool_use(
        self,
        tool_name: str,
        tool_input: str,
        tool_output: str,
        is_error: bool,
    ) -> HookRunResult:
        return self._run_commands(
            HookEvent.POST_TOOL_USE,
            self.config.post_tool_use,
            tool_name, tool_input, tool_output, is_error,
        )

    def _run_commands(
        self,
        event: HookEvent,
        commands: list[str],
        tool_name: str,
        tool_input: str,
        tool_output: str | None,
        is_error: bool,
    ) -> HookRunResult:
        if not commands:
            return HookRunResult.allow()

        try:
            input_json = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            input_json = {"raw": tool_input}

        payload = json.dumps({
            "hook_event_name": event.value,
            "tool_name": tool_name,
            "tool_input": input_json,
            "tool_input_json": tool_input,
            "tool_output": tool_output,
            "tool_result_is_error": is_error,
        })

        messages: list[str] = []

        for command in commands:
            env = {
                "HOOK_EVENT": event.value,
                "HOOK_TOOL_NAME": tool_name,
                "HOOK_TOOL_INPUT": tool_input,
                "HOOK_TOOL_IS_ERROR": "1" if is_error else "0",
            }
            if tool_output is not None:
                env["HOOK_TOOL_OUTPUT"] = tool_output

            try:
                result = _run_shell_hook(command, env, payload)
            except Exception as exc:
                messages.append(
                    f"{event.value} hook `{command}` failed to start for `{tool_name}`: {exc}"
                )
                continue

            stdout = result.stdout.strip()

            if result.returncode == 0:
                if stdout:
                    messages.append(stdout)
            elif result.returncode == 2:
                message = stdout or f"{event.value} hook denied tool `{tool_name}`"
                messages.append(message)
                return HookRunResult(denied=True, messages=messages)
            else:
                stderr = result.stderr.strip()
                warn = f"Hook `{command}` exited with status {result.returncode}; allowing tool execution to continue"
                if stdout:
                    warn += f": {stdout}"
                elif stderr:
                    warn += f": {stderr}"
                messages.append(warn)

        return HookRunResult.allow(messages)


def merge_hook_feedback(
    hook_messages: list[str], output: str, denied: bool
) -> str:
    if not hook_messages:
        return output
    sections: list[str] = []
    if output.strip():
        sections.append(output)
    label = "Hook feedback (denied)" if denied else "Hook feedback"
    sections.append(f"{label}:\n" + "\n".join(hook_messages))
    return "\n\n".join(sections)


def _run_shell_hook(
    command: str, extra_env: dict[str, str], stdin_data: str
) -> subprocess.CompletedProcess:
    env = {**os.environ, **extra_env}
    if platform.system() == "Windows":
        args = ["cmd", "/C", command]
    else:
        args = ["sh", "-lc", command]
    return subprocess.run(
        args,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _try_parse_stop_json(stdout: str) -> dict | None:
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("continue") is False:
        return {
            "prevent_continuation": True,
            "reason": data.get("stopReason"),
        }
    return None
