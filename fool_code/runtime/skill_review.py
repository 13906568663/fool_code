"""Background skill review — fire-and-forget post-conversation analysis.

After a conversation with enough iterations (nudge threshold), this module
spins up a background LLM call to review what happened and decide whether
any reusable patterns should be saved as skills (or existing skills patched).

Modeled after Hermes's background-review mechanism but adapted to fool-code's
Skill Store and SkillManage infrastructure.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SKILL_REVIEW_PROMPT = """\
你是一个技能审查助手。你的任务是分析下面的对话，判断是否值得将某些方法/工作流保存为可复用的技能。

判断标准（满足任一即可）：
1. 对话中解决了一个复杂问题（涉及多个步骤或工具调用）
2. 对话中发现了一个非显而易见的工作流程或技巧
3. 对话中修复了一个棘手的 bug，修复方法值得记录
4. 对话中使用了某个现有技能，但发现它需要更新

请以 JSON 格式回复。如果不值得保存，返回：
{"action": "skip", "reason": "简短说明原因"}

如果值得创建新技能，返回：
{"action": "create", "name": "技能ID（英文短横线命名）", "content": "完整的 SKILL.md 内容（含 YAML frontmatter）"}

如果值得修补现有技能，返回：
{"action": "patch", "name": "已有技能ID", "old_string": "要替换的原文", "new_string": "替换后的新文本"}

注意：
- name 使用英文小写+短横线，如 "docker-compose-debug"
- SKILL.md frontmatter 必须包含 name 和 description
- 只在真正有价值时才创建技能，不要为琐碎的操作创建
- 每次只返回一个操作（最重要的那个）
"""

_MAX_CONVERSATION_CHARS = 6000


def _summarize_conversation(messages: list[dict]) -> str:
    """Extract a compact conversation summary for the review LLM."""
    parts: list[str] = []
    total = 0

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts)

        if not content or not isinstance(content, str):
            continue

        if role in ("user", "assistant"):
            snippet = content[:500]
            label = "用户" if role == "user" else "助手"
            line = f"[{label}] {snippet}"
        elif role == "tool":
            snippet = content[:200]
            line = f"[工具结果] {snippet}"
        else:
            continue

        if total + len(line) > _MAX_CONVERSATION_CHARS:
            remaining = _MAX_CONVERSATION_CHARS - total
            if remaining > 50:
                parts.append(line[:remaining] + "…")
            break

        parts.append(line)
        total += len(line)

    return "\n\n".join(parts)


def _parse_review_response(text: str) -> dict[str, Any] | None:
    """Extract JSON from the LLM review response.

    Uses a progressive strategy to handle nested braces in content fields:
    1. Try markdown code fence extraction (```json ... ```)
    2. Try balanced-brace extraction (find the outermost { ... })
    3. Fall back to greedy regex with progressive truncation
    """
    # Strategy 1: markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 2: balanced brace matching from the first {
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # Strategy 3: greedy regex with progressive truncation
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        candidate = json_match.group()
        for _ in range(5):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                last_brace = candidate.rfind("}", 0, len(candidate) - 1)
                if last_brace <= 0:
                    break
                candidate = candidate[:last_brace + 1]

    return None


def _execute_review_action(action: dict[str, Any]) -> None:
    """Execute the create/patch action from the review response."""
    from fool_code.tools.skill import skill_manage

    act = action.get("action", "")
    if act == "skip":
        logger.debug("[SKILL-REVIEW] LLM decided to skip: %s", action.get("reason", ""))
        return

    if act == "create":
        result_json = skill_manage({
            "action": "create",
            "name": action.get("name", ""),
            "content": action.get("content", ""),
            "category": action.get("category", ""),
        })
        result = json.loads(result_json)
        if result.get("success"):
            logger.info("[SKILL-REVIEW] Created skill: %s", action.get("name"))
        else:
            logger.debug("[SKILL-REVIEW] Create failed: %s", result.get("error"))

    elif act == "patch":
        result_json = skill_manage({
            "action": "patch",
            "name": action.get("name", ""),
            "old_string": action.get("old_string", ""),
            "new_string": action.get("new_string", ""),
        })
        result = json.loads(result_json)
        if result.get("success"):
            logger.info("[SKILL-REVIEW] Patched skill: %s", action.get("name"))
        else:
            logger.debug("[SKILL-REVIEW] Patch failed: %s", result.get("error"))

    else:
        logger.debug("[SKILL-REVIEW] Unknown action: %s", act)


class BackgroundSkillReviewer:
    """Fire-and-forget background skill review with stash queue.

    Follows the same overlap-guard pattern as _BackgroundMemoryExtractor:
    if a review is already running, the latest request is stashed and
    executed as a trailing run once the current one finishes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_progress = False
        self._pending: tuple[list[dict], Any, Callable | None] | None = None
        self._in_flight: threading.Event | None = None

    def fire(
        self,
        messages: list[dict],
        workspace_root: Any,
        send_event: Callable | None = None,
    ) -> None:
        with self._lock:
            if self._in_progress:
                self._pending = (messages, workspace_root, send_event)
                logger.debug("[SKILL-REVIEW] Already in progress — stashing for trailing run")
                return
            self._in_progress = True
            done_event = threading.Event()
            self._in_flight = done_event

        def _worker() -> None:
            try:
                self._run_once(messages, workspace_root, send_event)
            except Exception as exc:
                logger.debug("[SKILL-REVIEW] Background review failed: %s", exc)
            finally:
                trailing = None
                with self._lock:
                    trailing = self._pending
                    self._pending = None
                    if trailing is None:
                        self._in_progress = False
                        done_event.set()
                        self._in_flight = None

                if trailing is not None:
                    logger.debug("[SKILL-REVIEW] Running trailing review for stashed context")
                    try:
                        self._run_once(trailing[0], trailing[1], trailing[2])
                    except Exception as exc:
                        logger.debug("[SKILL-REVIEW] Trailing review failed: %s", exc)
                    finally:
                        with self._lock:
                            self._in_progress = False
                            done_event.set()
                            self._in_flight = None

        threading.Thread(target=_worker, daemon=True, name="skill-review").start()

    def drain(self, timeout: float = 30.0) -> None:
        """Wait for in-flight review to finish (used during shutdown)."""
        evt = self._in_flight
        if evt is not None:
            evt.wait(timeout=timeout)

    @staticmethod
    def _run_once(
        messages: list[dict],
        workspace_root: Any,
        send_event: Callable | None = None,
    ) -> None:
        from fool_code.events import WebEvent

        if send_event:
            send_event(WebEvent.make_background_status("skill_review", "started"))

        summary = _summarize_conversation(messages)
        if len(summary.strip()) < 100:
            logger.debug("[SKILL-REVIEW] Conversation too short, skipping review")
            if send_event:
                send_event(WebEvent.make_background_status("skill_review", "skipped"))
            return

        try:
            from fool_code.runtime.subagent import create_role_provider
            provider = create_role_provider("memory", workspace_root)
        except Exception:
            provider = None

        if provider is None:
            logger.debug("[SKILL-REVIEW] No LLM provider available for review")
            if send_event:
                send_event(WebEvent.make_background_status("skill_review", "no_provider"))
            return

        review_messages = [
            {"role": "user", "content": f"{_SKILL_REVIEW_PROMPT}\n\n---\n\n以下是对话内容：\n\n{summary}"},
        ]

        try:
            response_parts: list[str] = []
            for chunk in provider.stream_chat(review_messages, tools=[], system=None):
                if chunk.get("type") == "text_delta":
                    response_parts.append(chunk["content"])

            response_text = "".join(response_parts)
        except Exception as exc:
            logger.debug("[SKILL-REVIEW] LLM call failed: %s", exc)
            if send_event:
                send_event(WebEvent.make_background_status("skill_review", "error"))
            return

        action = _parse_review_response(response_text)
        if action is None:
            logger.debug("[SKILL-REVIEW] Could not parse LLM response")
            if send_event:
                send_event(WebEvent.make_background_status("skill_review", "parse_error"))
            return

        _execute_review_action(action)

        status = action.get("action", "skip")
        if send_event:
            send_event(WebEvent.make_background_status("skill_review", status))
