"""Miscellaneous tools — Sleep, Config, REPL, PowerShell, SendUserMessage, StructuredOutput, ToolSearch."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fool_code.runtime.config import active_workspace_root, app_data_root


# ---------------------------------------------------------------------------
# Sleep
# ---------------------------------------------------------------------------

def sleep_tool(args: dict[str, Any]) -> str:
    duration_ms = args.get("duration_ms", 0)
    time.sleep(duration_ms / 1000.0)
    return json.dumps({"duration_ms": duration_ms, "message": f"Slept for {duration_ms}ms"})


# ---------------------------------------------------------------------------
# SendUserMessage / Brief
# ---------------------------------------------------------------------------

def send_user_message(args: dict[str, Any]) -> str:
    message = args.get("message", "").strip()
    if not message:
        raise ValueError("message must not be empty")

    attachments_raw = args.get("attachments")
    resolved_attachments: list[dict] | None = None
    if attachments_raw:
        resolved_attachments = [_resolve_attachment(p) for p in attachments_raw]

    return json.dumps({
        "message": message,
        "attachments": resolved_attachments,
        "sent_at": _iso8601_now(),
    }, indent=2, ensure_ascii=False)


def _resolve_attachment(path_str: str) -> dict:
    p = Path(path_str)
    if not p.is_absolute():
        p = active_workspace_root() / p
    p = p.resolve()
    meta = p.stat()
    ext = p.suffix.lower().lstrip(".")
    return {
        "path": str(p),
        "size": meta.st_size,
        "is_image": ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"),
    }


# ---------------------------------------------------------------------------
# StructuredOutput
# ---------------------------------------------------------------------------

def structured_output(args: dict[str, Any]) -> str:
    return json.dumps({
        "data": "Structured output provided successfully",
        "structured_output": args,
    }, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_SETTINGS: dict[str, dict] = {
    "theme": {"scope": "global", "kind": "string", "path": ["theme"]},
    "editorMode": {"scope": "global", "kind": "string", "path": ["editorMode"], "options": ["default", "vim", "emacs"]},
    "verbose": {"scope": "global", "kind": "bool", "path": ["verbose"]},
    "preferredNotifChannel": {"scope": "global", "kind": "string", "path": ["preferredNotifChannel"]},
    "autoCompactEnabled": {"scope": "global", "kind": "bool", "path": ["autoCompactEnabled"]},
    "autoMemoryEnabled": {"scope": "settings", "kind": "bool", "path": ["autoMemoryEnabled"]},
    "autoDreamEnabled": {"scope": "settings", "kind": "bool", "path": ["autoDreamEnabled"]},
    "fileCheckpointingEnabled": {"scope": "global", "kind": "bool", "path": ["fileCheckpointingEnabled"]},
    "showTurnDuration": {"scope": "global", "kind": "bool", "path": ["showTurnDuration"]},
    "terminalProgressBarEnabled": {"scope": "global", "kind": "bool", "path": ["terminalProgressBarEnabled"]},
    "todoFeatureEnabled": {"scope": "global", "kind": "bool", "path": ["todoFeatureEnabled"]},
    "model": {"scope": "settings", "kind": "string", "path": ["model"]},
    "alwaysThinkingEnabled": {"scope": "settings", "kind": "bool", "path": ["alwaysThinkingEnabled"]},
    "permissions.defaultMode": {"scope": "settings", "kind": "string", "path": ["permissions", "defaultMode"], "options": ["default", "plan", "acceptEdits", "dontAsk", "auto"]},
    "language": {"scope": "settings", "kind": "string", "path": ["language"]},
    "teammateMode": {"scope": "global", "kind": "string", "path": ["teammateMode"], "options": ["tmux", "in-process", "auto"]},
}


def config_tool(args: dict[str, Any]) -> str:
    setting = args.get("setting", "").strip()
    if not setting:
        raise ValueError("setting must not be empty")

    spec = _CONFIG_SETTINGS.get(setting)
    if spec is None:
        return json.dumps({"success": False, "error": f'Unknown setting: "{setting}"'}, indent=2)

    path = _config_file_for_scope(spec["scope"])
    doc = _read_json_object(path)

    value = args.get("value")
    if value is not None:
        normalized = _normalize_config_value(spec, value)
        previous = _get_nested(doc, spec["path"])
        _set_nested(doc, spec["path"], normalized)
        _write_json_object(path, doc)
        return json.dumps({
            "success": True,
            "operation": "set",
            "setting": setting,
            "value": normalized,
            "previous_value": previous,
            "new_value": normalized,
        }, indent=2, ensure_ascii=False)
    else:
        return json.dumps({
            "success": True,
            "operation": "get",
            "setting": setting,
            "value": _get_nested(doc, spec["path"]),
        }, indent=2, ensure_ascii=False)


def _config_file_for_scope(scope: str) -> Path:
    if scope == "global":
        config_home = os.environ.get("FOOL_CODE_CONFIG_HOME")
        if config_home:
            return Path(config_home) / "settings.json"
        return app_data_root() / "settings.json"
    else:
        return active_workspace_root() / ".fool-code" / "settings.local.json"


def _read_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text)


def _write_json_object(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_nested(data: dict, keys: list[str]) -> Any:
    current: Any = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


def _set_nested(data: dict, keys: list[str], value: Any) -> None:
    for k in keys[:-1]:
        if k not in data or not isinstance(data[k], dict):
            data[k] = {}
        data = data[k]
    data[keys[-1]] = value


def _normalize_config_value(spec: dict, value: Any) -> Any:
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(value, bool):
            normalized = value
        elif isinstance(value, str):
            if value.strip().lower() == "true":
                normalized = True
            elif value.strip().lower() == "false":
                normalized = False
            else:
                raise ValueError("setting requires true or false")
        else:
            raise ValueError("setting requires true or false")
    else:
        normalized = str(value) if not isinstance(value, str) else value

    options = spec.get("options")
    if options and isinstance(normalized, str) and normalized not in options:
        raise ValueError(f'Invalid value "{normalized}". Options: {", ".join(options)}')
    return normalized


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def repl_tool(args: dict[str, Any]) -> str:
    code = args.get("code", "").strip()
    language = args.get("language", "").strip()
    if not code:
        raise ValueError("code must not be empty")
    if not language:
        raise ValueError("language is required")

    program, cmd_args = _resolve_repl_runtime(language)
    started = time.monotonic()
    result = subprocess.run(
        [program, *cmd_args, code],
        capture_output=True,
        timeout=args.get("timeout_ms", 30000) / 1000.0,
        cwd=str(active_workspace_root()),
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    return json.dumps({
        "language": language,
        "stdout": result.stdout.decode("utf-8", errors="replace"),
        "stderr": result.stderr.decode("utf-8", errors="replace"),
        "exit_code": result.returncode,
        "duration_ms": duration_ms,
    }, indent=2, ensure_ascii=False)


def _resolve_repl_runtime(language: str) -> tuple[str, list[str]]:
    lang = language.lower().strip()
    if lang in ("python", "py"):
        prog = _detect_command(["python3", "python"])
        if not prog:
            raise ValueError("python runtime not found")
        return (prog, ["-c"])
    elif lang in ("javascript", "js", "node"):
        prog = _detect_command(["node"])
        if not prog:
            raise ValueError("node runtime not found")
        return (prog, ["-e"])
    elif lang in ("sh", "shell", "bash"):
        prog = _detect_command(["bash", "sh"])
        if not prog:
            raise ValueError("shell runtime not found")
        return (prog, ["-lc"])
    else:
        raise ValueError(f"unsupported REPL language: {lang}")


def _detect_command(candidates: list[str]) -> str | None:
    for cmd in candidates:
        if shutil.which(cmd):
            return cmd
    return None


# ---------------------------------------------------------------------------
# PowerShell — delegates to bash tool (which uses PowerShell on Windows)
# ---------------------------------------------------------------------------

def powershell_tool(args: dict[str, Any]) -> str:
    from fool_code.tools.bash import execute_bash
    return execute_bash(args)


# ---------------------------------------------------------------------------
# ToolSearch
# ---------------------------------------------------------------------------

def tool_search(args: dict[str, Any], all_tool_names: list[str] | None = None) -> str:
    query = args.get("query", "").strip()
    max_results = max(1, args.get("max_results", 5))

    if all_tool_names is None:
        all_tool_names = []

    lowered = query.lower()

    if lowered.startswith("select:"):
        selection = lowered[len("select:"):]
        wanted = [t.strip() for t in selection.split(",") if t.strip()]
        matches = []
        for w in wanted:
            canon_w = _canonical(w)
            for name in all_tool_names:
                if _canonical(name) == canon_w:
                    matches.append(name)
                    break
        return json.dumps({
            "matches": matches[:max_results],
            "query": query,
            "total_tools": len(all_tool_names),
        }, indent=2)

    terms = lowered.split()
    scored: list[tuple[int, str]] = []
    for name in all_tool_names:
        canon = _canonical(name)
        score = 0
        for term in terms:
            canon_term = _canonical(term)
            if term in name.lower():
                score += 2
            if name.lower() == term:
                score += 8
            if canon == canon_term:
                score += 12
            if canon_term in canon:
                score += 4
        if score > 0 or not query:
            scored.append((score, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    matches = [name for _, name in scored[:max_results]]

    return json.dumps({
        "matches": matches,
        "query": query,
        "total_tools": len(all_tool_names),
    }, indent=2)


def _canonical(value: str) -> str:
    c = "".join(ch for ch in value if ch.isalnum()).lower()
    if c.endswith("tool"):
        c = c[:-4]
    return c


# ---------------------------------------------------------------------------
# Agent (sub-agent launch — runs real LLM for verification, stub for others)
# ---------------------------------------------------------------------------


def agent_tool(args: dict[str, Any], context: Any = None) -> str:
    from fool_code.tools.tool_protocol import ToolContext

    description = args.get("description", "").strip()
    prompt = args.get("prompt", "").strip()
    if not description:
        raise ValueError("description must not be empty")
    if not prompt:
        raise ValueError("prompt must not be empty")

    agent_id = f"agent-{int(time.time_ns())}"
    subagent_type = _normalize_subagent_type(args.get("subagent_type"))
    name = _slugify(args.get("name") or description)
    created_at = _iso8601_now()
    model = (args.get("model") or "").strip() or "default"

    from fool_code.runtime.agent_types import get_agent_definition
    agent_def = get_agent_definition(subagent_type)

    store_dir = _agent_store_dir()
    store_dir.mkdir(parents=True, exist_ok=True)

    output_file = store_dir / f"{agent_id}.md"
    manifest_file = store_dir / f"{agent_id}.json"

    # Real sub-agent loop via context.run_subagent (multi-turn with tools)
    llm_result = None
    ctx = context if isinstance(context, ToolContext) else None
    if ctx and ctx.run_subagent:
        try:
            llm_result = ctx.run_subagent(agent_def, prompt)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Sub-agent loop failed (%s): %s", subagent_type, exc
            )
            llm_result = None

    # Fallback: single LLM call (no tool loop)
    if llm_result is None and agent_def.model_role and agent_def.system_prompt:
        llm_result = _run_subagent_llm(agent_def, prompt)

    output_contents = (
        f"# Agent Task\n\n"
        f"- id: {agent_id}\n"
        f"- name: {name}\n"
        f"- description: {description}\n"
        f"- subagent_type: {subagent_type}\n"
        f"- created_at: {created_at}\n\n"
        f"## Prompt\n\n{prompt}\n"
    )
    if llm_result:
        output_contents += f"\n## Agent Result\n\n{llm_result}\n"

    output_file.write_text(output_contents, encoding="utf-8")

    status = "completed" if llm_result else "running"
    manifest = {
        "agent_id": agent_id,
        "name": name,
        "description": description,
        "subagent_type": subagent_type,
        "model": model,
        "status": status,
        "output_file": str(output_file),
        "manifest_file": str(manifest_file),
        "created_at": created_at,
        "started_at": created_at,
        "completed_at": _iso8601_now() if llm_result else None,
        "error": None,
    }
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if llm_result:
        manifest["agent_output"] = llm_result
    return json.dumps(manifest, indent=2, ensure_ascii=False)


def _run_subagent_llm(agent_def, prompt: str) -> str | None:
    """Run a sub-agent LLM call using the agent definition's model role and system prompt."""
    try:
        from fool_code.runtime.subagent import create_role_provider
        provider = create_role_provider(agent_def.model_role)
        if provider is None:
            return None
        result = provider.simple_chat(
            [{"role": "user", "content": prompt}],
            system=agent_def.system_prompt,
            max_tokens=2048,
        )
        provider.close()
        return result if result.strip() else None
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Sub-agent LLM call failed (%s): %s", agent_def.agent_type, exc)
        return None


def _agent_store_dir() -> Path:
    env = os.environ.get("FOOL_CODE_AGENT_STORE")
    if env:
        return Path(env)
    return app_data_root() / "agents"


def _slugify(text: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:32]


def _normalize_subagent_type(raw: str | None) -> str:
    if not raw or not raw.strip():
        return "general-purpose"
    canon = _canonical(raw.strip())
    mapping = {
        "general": "general-purpose",
        "generalpurpose": "general-purpose",
        "explore": "explore",
        "explorer": "explore",
        "plan": "plan",
        "planner": "plan",
        "verification": "verification",
        "verify": "verification",
        "verifier": "verification",
        "memory": "memory",
    }
    return mapping.get(canon, raw.strip())


def _iso8601_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# AskUserQuestion
# ---------------------------------------------------------------------------

import threading

_ask_user_lock = threading.Lock()
_ask_user_event = threading.Event()
_ask_user_answers: dict[str, str] = {}


def ask_user_question(args: dict[str, Any], context: Any = None) -> str:
    """Present structured questions to the user and wait for answers.

    Uses the same blocking-event pattern as PermissionGate: the tool sends
    an ``ask_user`` SSE event to the frontend, then blocks until the user
    submits their answers via the ``/api/ask-user-answer`` endpoint.
    """
    questions = args.get("questions", [])
    if not questions:
        raise ValueError("questions is required (list of question objects)")

    for q in questions:
        if not q.get("question"):
            raise ValueError("Each question must have a 'question' field")
        opts = q.get("options", [])
        if len(opts) < 2:
            raise ValueError("Each question must have at least 2 options")

    payload = json.dumps({"questions": questions}, ensure_ascii=False)

    if context and hasattr(context, "send_ask_user"):
        context.send_ask_user(payload)
    else:
        return json.dumps({
            "error": "AskUserQuestion is not supported in this context (no UI).",
        }, ensure_ascii=False)

    _ask_user_event.clear()
    if _ask_user_event.wait(timeout=300):
        with _ask_user_lock:
            answers = dict(_ask_user_answers)
    else:
        return json.dumps({
            "questions": questions,
            "answers": {},
            "timeout": True,
            "message": "User did not respond within 5 minutes.",
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "questions": questions,
        "answers": answers,
    }, ensure_ascii=False, indent=2)


def submit_ask_user_answer(answers: dict[str, str]) -> None:
    """Called by the API endpoint when the user submits their answers."""
    with _ask_user_lock:
        _ask_user_answers.clear()
        _ask_user_answers.update(answers)
    _ask_user_event.set()
