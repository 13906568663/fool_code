"""ConversationRuntime — the core agent loop: LLM → tools → LLM → …

Features:
  - UsageTracker integration
  - HookRunner (pre/post tool hooks, stop hooks)
  - Auto-compaction when token threshold is exceeded
  - Fire-and-forget background memory extraction
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Callable

from fool_code.types import (
    ContentBlock,
    ConversationMessage,
    MessageRole,
    Session,
    TokenUsage,
)
from fool_code.events import WebEvent
from fool_code.runtime.compact import CompactionConfig, compact_session, compact_session_with_llm, should_compact
from fool_code.runtime.content_store import ContentStore
from fool_code.runtime.hooks import (
    HookConfig,
    HookRunner,
    StopHookOutcome,
    merge_hook_feedback,
)
from fool_code.runtime.permissions import (
    PermissionDecision,
    PermissionGate,
    PermissionMode,
    PermissionPolicy,
)
from fool_code.runtime.tool_result_storage import (
    ContentReplacementState,
    ToolResultPersister,
    enforce_message_budget,
    reconstruct_replacement_state,
)
from fool_code.runtime.message_pipeline import normalize_for_api
from fool_code.runtime.usage import UsageTracker
from fool_code.tools.tool_protocol import ToolContext, ToolResult

if TYPE_CHECKING:
    from fool_code.mcp.manager import McpServerManager
    from fool_code.providers.openai_compat import OpenAICompatProvider
    from fool_code.runtime.agent_types import AgentDefinition
    from fool_code.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background memory extraction — fire-and-forget with overlap protection
# ---------------------------------------------------------------------------

class _BackgroundMemoryExtractor:
    """Process-wide singleton that runs memory extraction in a daemon thread.

    - Overlap guard: if an extraction is running, stash context for a trailing run.
    - Drain: await all in-flight work before shutdown (soft timeout).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_progress = False
        self._pending: tuple[list[dict], Any] | None = None
        self._in_flight: threading.Event | None = None

    def fire(
        self,
        messages: list[dict],
        workspace_root: Any,
        send_event: Callable[[WebEvent], None],
    ) -> None:
        with self._lock:
            if self._in_progress:
                self._pending = (messages, workspace_root)
                logger.debug("Memory extraction in progress — stashing for trailing run")
                return
            self._in_progress = True
            done_event = threading.Event()
            self._in_flight = done_event

        def _worker() -> None:
            try:
                self._run_once(messages, workspace_root, send_event)
            finally:
                trailing = None
                with self._lock:
                    trailing = self._pending
                    self._pending = None
                    if trailing is not None:
                        pass
                    else:
                        self._in_progress = False
                        done_event.set()
                        self._in_flight = None

                if trailing is not None:
                    logger.debug("Running trailing memory extraction for stashed context")
                    try:
                        self._run_once(trailing[0], trailing[1], send_event)
                    finally:
                        with self._lock:
                            self._in_progress = False
                            done_event.set()
                            self._in_flight = None

        threading.Thread(target=_worker, daemon=True, name="memory-extract").start()

    def drain(self, timeout: float = 60.0) -> None:
        evt = self._in_flight
        if evt is not None:
            evt.wait(timeout=timeout)

    @staticmethod
    def _run_once(
        messages: list[dict],
        workspace_root: Any,
        send_event: Callable[[WebEvent], None],
    ) -> None:
        try:
            from fool_code.runtime.memory import extract_memories_from_turn
            send_event(WebEvent.make_background_status("memory_extract", "started"))
            updated = extract_memories_from_turn(messages, workspace_root)
            status = "saved" if updated else "no_update"
            send_event(WebEvent.make_background_status("memory_extract", status))
        except Exception as exc:
            logger.debug("Background memory extraction failed: %s", exc)
            send_event(WebEvent.make_background_status("memory_extract", "error"))


_bg_memory = _BackgroundMemoryExtractor()


# ---------------------------------------------------------------------------
# Background MAGMA episodic memory extraction — same fire-and-forget pattern
# ---------------------------------------------------------------------------

class _BackgroundMagmaExtractor:
    """Extracts episodic events from conversations and ingests into the MAGMA
    multi-graph store.  Runs in a daemon thread with overlap protection."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_progress = False
        self._pending: tuple[list[dict], str, Any] | None = None

    def fire(
        self,
        messages: list[dict],
        session_id: str,
        workspace_root: Any,
        send_event: Callable[[WebEvent], None],
    ) -> None:
        with self._lock:
            if self._in_progress:
                self._pending = (messages, session_id, workspace_root)
                return
            self._in_progress = True

        def _worker() -> None:
            try:
                self._run_once(messages, session_id, workspace_root, send_event)
            finally:
                trailing = None
                with self._lock:
                    trailing = self._pending
                    self._pending = None
                    if trailing is None:
                        self._in_progress = False
                if trailing is not None:
                    try:
                        self._run_once(trailing[0], trailing[1], trailing[2], send_event)
                    finally:
                        with self._lock:
                            self._in_progress = False

        threading.Thread(target=_worker, daemon=True, name="magma-extract").start()

    @staticmethod
    def _run_once(
        messages: list[dict],
        session_id: str,
        workspace_root: Any,
        send_event: Callable[[WebEvent], None],
    ) -> None:
        try:
            from fool_code.magma.extractor import extract_and_ingest
            send_event(WebEvent.make_background_status("magma_extract", "started"))
            count = extract_and_ingest(messages, session_id, workspace_root)
            status = f"saved_{count}" if count > 0 else "no_events"
            send_event(WebEvent.make_background_status("magma_extract", status))
        except Exception as exc:
            logger.debug("Background MAGMA extraction failed: %s", exc)
            send_event(WebEvent.make_background_status("magma_extract", "error"))


_bg_magma = _BackgroundMagmaExtractor()


# ---------------------------------------------------------------------------
# Background skill review — post-conversation analysis
# ---------------------------------------------------------------------------

from fool_code.runtime.skill_review import BackgroundSkillReviewer

_bg_skill_review = BackgroundSkillReviewer()


class ConversationRuntime:
    def __init__(
        self,
        session: Session,
        provider: OpenAICompatProvider,
        tool_registry: ToolRegistry,
        system_prompt: list[str],
        permission_gate: PermissionGate,
        event_callback: Callable[[WebEvent], None],
        mcp_manager: McpServerManager | None = None,
        hook_config: HookConfig | None = None,
        auto_compact_threshold: int | None = None,
        main_loop: asyncio.AbstractEventLoop | None = None,
        workspace_root: Any = None,
        agent_id: str | None = None,
        content_store: ContentStore | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt
        self.permission_gate = permission_gate
        self.send_event = event_callback
        self.mcp_manager = mcp_manager
        self.main_loop = main_loop
        self.max_iterations = 50
        self.usage_tracker = UsageTracker.from_session(session)
        self.hook_runner = HookRunner(hook_config)
        self.auto_compact_threshold = auto_compact_threshold
        self.auto_compacted = False
        self.auto_compact_removed = 0
        self.workspace_root = workspace_root
        self.agent_id = agent_id
        self.session_id: str | None = None
        self._mode = "normal"  # "normal" | "plan"
        self._cancelled = threading.Event()
        self._discovered_deferred: set[str] = set()
        self._skip_tool_filtering = False
        self._iters_since_skill = 0
        self._skill_nudge_interval = 10
        self._rebuild_discovered_from_history()

        self.content_store = content_store
        self.tool_result_persister = (
            ToolResultPersister(content_store) if content_store else None
        )
        self.content_replacement_state = reconstruct_replacement_state(
            session.messages, [],
        ) if session.messages else ContentReplacementState()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def set_mode(self, new_mode: str) -> None:
        old = self._mode
        self._mode = new_mode
        if old != new_mode:
            self.send_event(WebEvent.make_mode_change(new_mode))

    def _refresh_skill_prompt_section(self) -> None:
        """Re-build the skill listing in the system prompt after SkillManage changes."""
        try:
            from fool_code.tools.skill import build_skill_prompt_section
            new_section = build_skill_prompt_section()
            if new_section is None:
                return
            for i, part in enumerate(self.system_prompt):
                if "技能库" in part or "Skill Store" in part:
                    self.system_prompt[i] = new_section
                    return
            self.system_prompt.append(new_section)
        except Exception as exc:
            logger.debug("[SKILLS] Failed to refresh skill prompt section: %s", exc)

    def run_turn(self, user_input: str) -> None:
        self.session.messages.append(ConversationMessage.user_text(user_input))
        self._run_agent_loop()

    def run_turn_with_message(self, user_msg: ConversationMessage) -> None:
        """Run a turn where the user message is already appended to session."""
        self._run_agent_loop()

    def _run_agent_loop(self) -> None:
        stop_hook_active = False
        _llm_retries = 0
        _MAX_LLM_RETRIES = 2
        _consecutive_tool_errors = 0
        _MAX_CONSECUTIVE_TOOL_ERRORS = 3

        logger.info("[AGENT] agent loop started, %d messages in session", len(self.session.messages))

        self._auto_compact_before_loop()

        try:
            self._agent_loop_iterations()
        except Exception as exc:
            logger.error("[AGENT] FATAL: agent loop crashed: %s", exc, exc_info=True)
            self.send_event(WebEvent.make_error(
                f"处理过程中发生内部错误: {type(exc).__name__}: {exc}\n"
                "已有的对话内容已保存，请重新发送消息继续。"
            ))

        logger.info("[AGENT] agent loop ended, session now has %d messages", len(self.session.messages))

        # Fire-and-forget: memory extraction runs in a background thread so the
        # user can continue immediately.
        built_messages = self._build_messages()
        _bg_memory.fire(built_messages, self.workspace_root, self.send_event)

        # MAGMA episodic memory: extract events and ingest into multi-graph store
        magma_sid = self.session_id or self.agent_id or "default"
        _bg_magma.fire(built_messages, magma_sid, self.workspace_root, self.send_event)

        # Background skill review: if enough iterations passed without SkillManage
        if (self._skill_nudge_interval > 0
                and self._iters_since_skill >= self._skill_nudge_interval):
            self._iters_since_skill = 0
            _bg_skill_review.fire(built_messages, self.workspace_root, self.send_event)

        usage_lines = self.usage_tracker.summary_lines("usage")
        for line in usage_lines:
            logger.info(line)

    def _agent_loop_iterations(self) -> None:
        stop_hook_active = False
        _llm_retries = 0
        _MAX_LLM_RETRIES = 2
        _consecutive_tool_errors = 0
        _MAX_CONSECUTIVE_TOOL_ERRORS = 3
        _compact_failures = 0

        for iteration in range(self.max_iterations):
            if self.is_cancelled:
                logger.info("[AGENT] cancelled by user at iteration %d", iteration)
                break

            if iteration > 0:
                _compact_failures = self._auto_compact_mid_loop(_compact_failures)

            result = self._call_llm()
            if result is None:
                has_pending_tool_results = (
                    self.session.messages
                    and self.session.messages[-1].role.value == "tool"
                )
                if has_pending_tool_results and _llm_retries < _MAX_LLM_RETRIES:
                    _llm_retries += 1
                    logger.warning(
                        "LLM call returned None after tool result at iteration %d "
                        "(retry %d/%d)",
                        iteration, _llm_retries, _MAX_LLM_RETRIES,
                    )
                    time.sleep(1.0 * _llm_retries)
                    continue

                logger.warning(
                    "LLM call returned None at iteration %d — ending loop", iteration
                )
                if has_pending_tool_results:
                    self.send_event(WebEvent.make_error(
                        "模型调用失败，工具已执行但未能获得后续响应。"
                        "请重新发送消息以继续。"
                    ))
                break

            _llm_retries = 0

            if self.is_cancelled:
                break

            assistant_msg, tool_calls, usage = result
            if usage:
                self.usage_tracker.record(usage)
            self.session.messages.append(assistant_msg)

            text_preview = _extract_assistant_text(assistant_msg)[:120]
            tc_names = [tc["name"] for tc in tool_calls] if tool_calls else []
            logger.info(
                "[AGENT] iter=%d | text=%r | tool_calls=%s",
                iteration, text_preview, tc_names or "(none)",
            )

            self._iters_since_skill += 1
            if any(tc["name"] == "SkillManage" for tc in tool_calls):
                self._iters_since_skill = 0
                self._refresh_skill_prompt_section()

            if not tool_calls:
                last_text = _extract_assistant_text(assistant_msg)

                if self.hook_runner.has_stop_hooks and not stop_hook_active:
                    self.send_event(WebEvent.make_hook_start("stop"))
                    hook_result = self.hook_runner.run_stop_hooks(
                        last_text, stop_hook_active
                    )
                    if hook_result.outcome == StopHookOutcome.BLOCKING:
                        self.send_event(
                            WebEvent.make_hook_end("stop", hook_result.message, error=True)
                        )
                        feedback = ConversationMessage.user_text(
                            f"[Stop hook feedback]: {hook_result.message}\n\n"
                            "Please address the above issue before completing."
                        )
                        self.session.messages.append(feedback)
                        stop_hook_active = True
                        continue
                    elif hook_result.outcome == StopHookOutcome.PREVENT_CONTINUATION:
                        self.send_event(WebEvent.make_hook_end("stop", "prevented"))
                        break
                    else:
                        self.send_event(WebEvent.make_hook_end("stop"))

                break

            batches = self._batch_tool_calls(tool_calls)
            _batch_failed_files: set[str] = set()
            for batch in batches:
                if self.is_cancelled:
                    break

                # Fast-skip: if this batch has a single edit/write on a file
                # that already failed "must read first" in this turn, skip it
                # and record the error directly instead of re-executing.
                if len(batch) == 1 and batch[0]["name"] in ("edit_file", "write_file"):
                    try:
                        _args = json.loads(batch[0].get("input", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        _args = {}
                    _fpath = _args.get("file_path") or _args.get("path", "")
                    if _fpath and _fpath in _batch_failed_files:
                        _skip_msg = (
                            f"已跳过：{_fpath} 在本轮中已因未先读取而失败。"
                            f"请先对该文件调用 read_file，然后再重试。"
                        )
                        self._record_tool_error(batch[0], _skip_msg)
                        continue

                if len(batch) == 1 or not all(
                    self.tool_registry.is_tool_read_only(tc["name"]) for tc in batch
                ):
                    for tc in batch:
                        if self.is_cancelled:
                            break
                        self._process_single_tool(tc)
                else:
                    self._process_parallel_tools(batch)

                # 追踪本轮中因"必须先读取"而失败的文件
                for msg in reversed(self.session.messages):
                    if msg.role != MessageRole.tool:
                        break
                    for b in msg.blocks:
                        out = getattr(b, "output", "")
                        if getattr(b, "is_error", False) and "必须先读取" in out:
                            try:
                                _args2 = json.loads(batch[0].get("input", "{}"))
                                _p2 = _args2.get("file_path") or _args2.get("path", "")
                                if _p2:
                                    _batch_failed_files.add(_p2)
                            except Exception:
                                pass

                # Check consecutive errors after EACH batch, not just at the end
                _consecutive_tool_errors = self._count_trailing_tool_errors()
                if _consecutive_tool_errors >= _MAX_CONSECUTIVE_TOOL_ERRORS:
                    logger.warning(
                        "Detected %d consecutive tool errors — breaking batch loop early",
                        _consecutive_tool_errors,
                    )
                    break

            _consecutive_tool_errors = self._count_trailing_tool_errors()
            if _consecutive_tool_errors >= _MAX_CONSECUTIVE_TOOL_ERRORS:
                logger.warning(
                    "Detected %d consecutive tool errors — injecting strategy hint",
                    _consecutive_tool_errors,
                )
                hint = ConversationMessage.user_text(
                    f"[System] 最近 {_consecutive_tool_errors} 次工具调用全部失败。"
                    "请立即停止重试相同或类似的命令。"
                    "请改用完全不同的方法，或直接用文字告诉用户当前遇到的限制和已获取的信息。"
                )
                self.session.messages.append(hint)
                self.send_event(WebEvent.make_error(
                    f"连续 {_consecutive_tool_errors} 次工具调用失败，已提醒模型更换策略。"
                ))

    # ------------------------------------------------------------------
    # Tool call batching and parallel execution
    # ------------------------------------------------------------------

    def _batch_tool_calls(self, tool_calls: list[dict]) -> list[list[dict]]:
        """Split tool calls into batches: consecutive read-only tools form one
        parallel batch; each non-read-only tool is its own sequential batch."""
        batches: list[list[dict]] = []
        current_ro: list[dict] = []

        from fool_code.runtime.permissions import TOOL_PERMISSION_MAP, PermissionMode

        registry = self.tool_registry

        def _is_likely_read_only(name: str, tc: dict) -> bool:
            try:
                args = json.loads(tc.get("input", "{}")) if tc.get("input") else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            handler = registry.get_handler(name)
            if handler and hasattr(handler, "is_read_only_for"):
                return handler.is_read_only_for(args)
            if handler:
                return handler.meta.is_read_only
            perm = TOOL_PERMISSION_MAP.get(name)
            return perm == PermissionMode.READ_ONLY if perm else False

        for tc in tool_calls:
            if _is_likely_read_only(tc["name"], tc):
                current_ro.append(tc)
            else:
                if current_ro:
                    batches.append(current_ro)
                    current_ro = []
                batches.append([tc])

        if current_ro:
            batches.append(current_ro)

        return batches if batches else [[tc] for tc in tool_calls]

    def _process_single_tool(self, tc: dict) -> None:
        """Process one tool call: plan gate, permission, hooks, execute, record."""
        tool_use_id = tc["id"]
        tool_name = tc["name"]
        tool_input = tc["input"]

        try:
            self._process_single_tool_inner(tool_use_id, tool_name, tool_input)
        except Exception as exc:
            logger.error(
                "[AGENT] FATAL: unhandled error processing tool %s: %s",
                tool_name, exc, exc_info=True,
            )
            try:
                self.send_event(WebEvent.make_tool_end(
                    tool_name,
                    f"内部错误: {type(exc).__name__}: {exc}",
                    error=True,
                ))
                fallback_msg = ConversationMessage.tool_result(
                    tool_use_id, tool_name,
                    f"工具执行时发生内部错误 ({type(exc).__name__}): {exc}。请换一种方式完成任务，或告知用户当前遇到的问题。",
                    is_error=True,
                )
                self.session.messages.append(fallback_msg)
            except Exception:
                pass

    def _process_single_tool_inner(
        self, tool_use_id: str, tool_name: str, tool_input: str,
    ) -> None:

        if self._mode == "plan" and tool_name != "SuggestPlanMode":
            if not self.tool_registry.is_tool_read_only(tool_name):
                result_msg = ConversationMessage.tool_result(
                    tool_use_id, tool_name,
                    "当前处于计划模式(Plan Mode)。此工具需要写入权限，在计划模式下不可用。"
                    "请用文本描述你的执行计划，用户审阅后会决定是否执行。",
                    is_error=True,
                )
                self.session.messages.append(result_msg)
                self.send_event(WebEvent.make_tool_end(tool_name, "Blocked: plan mode", error=True))
                return

        decision = self.permission_gate.request_permission(
            tool_name, _truncate(tool_input),
            lambda tn, ti: self.send_event(WebEvent.make_permission_request(tn, ti)),
        )
        if decision == PermissionDecision.DENY:
            result_msg = ConversationMessage.tool_result(
                tool_use_id, tool_name, "用户拒绝了该操作", is_error=True,
            )
            self.session.messages.append(result_msg)
            return

        pre_hook = self.hook_runner.run_pre_tool_use(tool_name, tool_input)
        if pre_hook.is_denied:
            deny_msg = f"PreToolUse hook denied tool `{tool_name}`"
            output = "\n".join(pre_hook.messages) if pre_hook.messages else deny_msg
            result_msg = ConversationMessage.tool_result(
                tool_use_id, tool_name, output, is_error=True,
            )
            self.session.messages.append(result_msg)
            return

        self.send_event(WebEvent.make_tool_start(tool_name, _truncate(tool_input)))
        logger.info("[AGENT] executing tool: %s (input: %s)", tool_name, _truncate(tool_input, 200))

        tool_result: ToolResult | None = None
        try:
            tool_result = self._execute_tool(tool_name, tool_input)
            output = tool_result.output
            is_error = tool_result.is_error
            if tool_result.metadata.get("set_mode"):
                self.set_mode(tool_result.metadata["set_mode"])
            if tool_result.metadata.get("suggest_plan_mode"):
                reason = tool_result.metadata.get("reason", "")
                self.send_event(WebEvent.make_plan_mode_suggest(reason))
            if tool_result.metadata.get("todo_update"):
                self.send_event(WebEvent.make_todo_update(
                    json.dumps(tool_result.metadata["todo_update"], ensure_ascii=False)
                ))
                plan_slug = self.session.plan_slug if hasattr(self.session, "plan_slug") else None
                if plan_slug:
                    try:
                        self.content_store.update_plan_todos(
                            plan_slug, tool_result.metadata["todo_update"]
                        )
                    except Exception as exc:
                        logger.warning("Failed to sync todos to plan file: %s", exc)
            self._maybe_discover_skills_for_tool(tool_name, tool_input)
        except Exception as exc:
            output = str(exc)
            is_error = True
            logger.error("[AGENT] tool %s raised exception: %s", tool_name, exc, exc_info=True)

        output = merge_hook_feedback(pre_hook.messages, output, False)

        post_hook = self.hook_runner.run_post_tool_use(tool_name, tool_input, output, is_error)
        if post_hook.is_denied:
            is_error = True
        output = merge_hook_feedback(post_hook.messages, output, post_hook.is_denied)

        self.send_event(WebEvent.make_tool_end(tool_name, _truncate(output), error=is_error))

        if self.tool_result_persister:
            result_block = self.tool_result_persister.maybe_persist(
                tool_use_id, tool_name, output, is_error,
            )
            result_msg = ConversationMessage(
                role=MessageRole.tool,
                blocks=[result_block],
            )
        else:
            result_msg = ConversationMessage.tool_result(
                tool_use_id, tool_name, output, is_error=is_error,
            )

        if tool_result is not None and tool_result.images and self.content_store:
            import uuid as _uuid
            for img_b64 in tool_result.images:
                img_id = f"cu-{_uuid.uuid4().hex[:12]}"
                path = self.content_store.store_image(img_id, img_b64, "image/jpeg")
                result_msg.blocks.append(ContentBlock(
                    type="image", external_path=path, media_type="image/jpeg",
                    preview="[Screenshot]", id=img_id,
                ))
        elif tool_result is not None and tool_result.images:
            for img_b64 in tool_result.images:
                result_msg.blocks.append(ContentBlock(
                    type="image", inline_data=img_b64, media_type="image/jpeg",
                    preview="[Screenshot]",
                ))

        self.session.messages.append(result_msg)

    def _process_parallel_tools(self, batch: list[dict]) -> None:
        """Execute a batch of read-only tools in parallel using threads."""
        for tc in batch:
            self.send_event(WebEvent.make_tool_start(tc["name"], _truncate(tc["input"])))

        results: dict[str, tuple[str, bool]] = {}

        def _run_one(tc: dict) -> tuple[str, str, bool]:
            tool_name = tc["name"]
            tool_input = tc["input"]
            try:
                tool_result = self._execute_tool(tool_name, tool_input)
                return tc["id"], tool_result.output, tool_result.is_error
            except Exception as exc:
                return tc["id"], str(exc), True

        with ThreadPoolExecutor(max_workers=min(len(batch), 8)) as pool:
            futures = {pool.submit(_run_one, tc): tc for tc in batch}
            for future in as_completed(futures):
                tc_id, output, is_error = future.result()
                results[tc_id] = (output, is_error)

        for tc in batch:
            tool_use_id = tc["id"]
            tool_name = tc["name"]
            output, is_error = results.get(tool_use_id, ("(no result)", True))

            post_hook = self.hook_runner.run_post_tool_use(tool_name, tc["input"], output, is_error)
            if post_hook.is_denied:
                is_error = True
            output = merge_hook_feedback(post_hook.messages, output, post_hook.is_denied)

            self.send_event(WebEvent.make_tool_end(tool_name, _truncate(output), error=is_error))

            if self.tool_result_persister:
                result_block = self.tool_result_persister.maybe_persist(
                    tool_use_id, tool_name, output, is_error,
                )
                result_msg = ConversationMessage(
                    role=MessageRole.tool,
                    blocks=[result_block],
                )
            else:
                result_msg = ConversationMessage.tool_result(
                    tool_use_id, tool_name, output, is_error=is_error,
                )
            self.session.messages.append(result_msg)

    def _auto_compact_before_loop(self) -> None:
        """Check token threshold and run LLM-powered compaction before the agent loop starts."""
        config = CompactionConfig()
        if not should_compact(self.session, config):
            return

        # Flush pending MAGMA extraction so pre-compact messages are ingested
        try:
            built = self._build_messages()
            magma_sid = self.session_id or self.agent_id or "default"
            from fool_code.magma.extractor import extract_and_ingest
            extract_and_ingest(built, magma_sid, self.workspace_root)
        except Exception as exc:
            logger.debug("Pre-compact MAGMA flush failed: %s", exc)

        logger.info("[COMPACT] Auto-compact triggered (threshold %d tokens)", config.max_estimated_tokens)
        self.send_event(WebEvent.make_compact_start())

        try:
            result = compact_session_with_llm(self.session, self.provider, config)
        except Exception as exc:
            logger.warning("[COMPACT] LLM compact failed (%s), trying rule-based fallback", exc)
            try:
                result = compact_session(self.session, config)
            except Exception as exc2:
                logger.error("[COMPACT] Rule-based compact also failed: %s", exc2)
                self.send_event(WebEvent.make_compact_end())
                return

        if result.removed_message_count > 0:
            self.session = result.compacted_session
            self.auto_compacted = True
            self.auto_compact_removed = result.removed_message_count
            logger.info(
                "[COMPACT] Auto-compacted session: removed %d messages, summary length %d chars",
                result.removed_message_count,
                len(result.formatted_summary),
            )

        self.send_event(WebEvent.make_compact_end(result.formatted_summary[:200] if result.formatted_summary else ""))

    _MAX_CONSECUTIVE_COMPACT_FAILURES = 3

    def _auto_compact_mid_loop(self, consecutive_failures: int) -> int:
        """Check token threshold mid-loop and compact if needed.

        Returns the updated consecutive_failures count.  Skipped inside
        sub-agents to avoid nested compaction, and circuit-breakers after
        ``_MAX_CONSECUTIVE_COMPACT_FAILURES`` consecutive failures so a
        session that is irrecoverably over the limit does not waste API
        calls on doomed compaction attempts every iteration.
        """
        if self.agent_id and self.agent_id.startswith("subagent-"):
            return consecutive_failures
        if consecutive_failures >= self._MAX_CONSECUTIVE_COMPACT_FAILURES:
            return consecutive_failures

        config = CompactionConfig()
        if not should_compact(self.session, config):
            return consecutive_failures

        logger.info("[COMPACT] Mid-loop auto-compact triggered (threshold %d tokens)", config.max_estimated_tokens)
        self.send_event(WebEvent.make_compact_start())

        try:
            result = compact_session_with_llm(self.session, self.provider, config)
        except Exception as exc:
            logger.warning("[COMPACT] Mid-loop LLM compact failed (%s), trying rule-based fallback", exc)
            try:
                result = compact_session(self.session, config)
            except Exception as exc2:
                logger.error("[COMPACT] Mid-loop rule-based compact also failed: %s", exc2)
                self.send_event(WebEvent.make_compact_end())
                return consecutive_failures + 1

        if result.removed_message_count > 0:
            self.session = result.compacted_session
            self.auto_compacted = True
            self.auto_compact_removed += result.removed_message_count
            logger.info(
                "[COMPACT] Mid-loop compacted: removed %d messages, summary length %d chars",
                result.removed_message_count,
                len(result.formatted_summary),
            )

        self.send_event(WebEvent.make_compact_end(result.formatted_summary[:200] if result.formatted_summary else ""))
        return 0

    def _count_trailing_tool_errors(self) -> int:
        """Count how many consecutive tool results at the tail are errors."""
        count = 0
        for msg in reversed(self.session.messages):
            if msg.role != MessageRole.tool:
                break
            is_error = any(
                getattr(b, "is_error", False)
                or (hasattr(b, "output") and _looks_like_error(getattr(b, "output", "")))
                for b in msg.blocks
            )
            if is_error:
                count += 1
            else:
                break
        return count

    def _record_tool_error(self, tc: dict, error_msg: str) -> None:
        """Record a tool error message into the session without actually executing the tool."""
        result_msg = ConversationMessage.tool_result(
            tc["id"], tc["name"], error_msg, is_error=True,
        )
        self.session.messages.append(result_msg)
        self.send_event(WebEvent.make_tool_end(tc["name"], error_msg, error=True))

    def _on_tool_discovered(self, name: str) -> None:
        """Callback from ToolSearch: mark a tool as discovered for this session."""
        self._discovered_deferred.add(name)
        logger.info("[AGENT] tool discovered via ToolSearch: %s (total discovered: %s)", name, sorted(self._discovered_deferred))

    def _rebuild_discovered_from_history(self) -> None:
        """Reconstruct the discovered-deferred set from existing message history.

        This ensures that tools discovered via ToolSearch in previous turns
        remain available when a new ConversationRuntime is created for the
        same session (each HTTP request creates a fresh runtime instance).
        """
        for msg in self.session.messages:
            if msg.role != MessageRole.assistant:
                continue
            for block in msg.blocks:
                if block.type != "tool_use" or not block.name:
                    continue
                name = block.name
                handler = self.tool_registry.get_handler(name)
                if handler and handler.meta.should_defer:
                    self._discovered_deferred.add(name)
                elif self.tool_registry.is_mcp_tool(name):
                    self._discovered_deferred.add(name)
        if self._discovered_deferred:
            logger.info(
                "Rebuilt discovered-deferred set from history: %s",
                sorted(self._discovered_deferred),
            )

    def _execute_tool(self, tool_name: str, raw_input: str) -> ToolResult:
        if self.tool_registry.is_mcp_tool(tool_name) and self.mcp_manager:
            return self._execute_mcp_tool(tool_name, raw_input)

        def _progress_callback(content: str) -> None:
            self.send_event(WebEvent.make_tool_progress(tool_name, content))

        def _ask_user_callback(questions_json: str) -> None:
            self.send_event(WebEvent.make_ask_user(tool_name, questions_json))

        context = ToolContext(
            workspace_root=str(self.workspace_root or ""),
            mode=self._mode,
            agent_id=self.agent_id,
            run_subagent=self._run_subagent,
            on_progress=_progress_callback,
            send_ask_user=_ask_user_callback,
            on_tool_discovered=self._on_tool_discovered,
        )
        return self.tool_registry.execute(tool_name, raw_input, context)

    def _maybe_discover_skills_for_tool(self, tool_name: str, raw_input: str) -> None:
        """After file-touching tools, discover new skill directories dynamically."""
        if tool_name not in ("read_file", "write_file", "edit_file"):
            return
        try:
            args = json.loads(raw_input) if raw_input else {}
        except (json.JSONDecodeError, TypeError):
            return
        file_path = args.get("path", "")
        if not file_path:
            return

        cwd = str(self.workspace_root or "")
        if not cwd:
            return

        from fool_code.tools.skill import (
            discover_skills_for_paths,
            add_dynamic_skill_directories,
            activate_conditional_skills,
        )

        new_dirs = discover_skills_for_paths([file_path], cwd)
        if new_dirs:
            count = add_dynamic_skill_directories(new_dirs)
            if count > 0:
                logger.info(
                    "[SKILLS] Dynamically discovered %d skills from %d dirs",
                    count, len(new_dirs),
                )

        activated = activate_conditional_skills([file_path], cwd)
        if activated:
            logger.info(
                "[SKILLS] Activated conditional skills: %s", activated,
            )

    def _execute_mcp_tool(self, tool_name: str, raw_input: str) -> ToolResult:
        try:
            arguments: dict[str, Any] | None = (
                json.loads(raw_input) if raw_input else None
            )
        except json.JSONDecodeError:
            arguments = None

        coro = self.mcp_manager.call_tool(tool_name, arguments)

        if self.main_loop and self.main_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self.main_loop)
            result = future.result(timeout=600)
        else:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(coro)
            finally:
                loop.close()

        texts = [c.text for c in result.content if c.text]
        output = "\n".join(texts) if texts else "(empty result)"
        return ToolResult(output=output, is_error=bool(result.isError))

    # ------------------------------------------------------------------
    # Sub-agent loop
    # ------------------------------------------------------------------

    def _run_subagent(self, agent_def: AgentDefinition, prompt: str) -> str:
        """Run a sub-agent with its own tool loop (real multi-turn)."""
        from fool_code.runtime.agent_types import AgentDefinition
        from fool_code.runtime.subagent import create_role_provider

        agent_id = f"subagent-{id(agent_def)}-{int(__import__('time').time_ns())}"

        always_exclude = ["Agent", "SuggestPlanMode"]
        exclude_list = list(set(always_exclude + list(agent_def.disallowed_tools)))
        sub_registry = self.tool_registry.filter_tools(exclude=exclude_list)

        sub_provider = None
        if agent_def.model_role:
            sub_provider = create_role_provider(agent_def.model_role)
        if sub_provider is None:
            sub_provider = self.provider

        if agent_def.system_prompt:
            sub_system = [agent_def.system_prompt]
            if agent_def.critical_reminder:
                sub_system.append(agent_def.critical_reminder)
        else:
            sub_system = list(self.system_prompt)

        sub_session = Session()

        self.send_event(WebEvent.make_subagent_start(agent_id, agent_def.agent_type))

        sub_runtime = ConversationRuntime(
            session=sub_session,
            provider=sub_provider,
            tool_registry=sub_registry,
            system_prompt=sub_system,
            permission_gate=self.permission_gate,
            event_callback=self.send_event,
            mcp_manager=self.mcp_manager,
            main_loop=self.main_loop,
            workspace_root=self.workspace_root,
            agent_id=agent_id,
        )
        sub_runtime.max_iterations = agent_def.max_turns
        sub_runtime._skip_tool_filtering = True

        try:
            sub_runtime.run_turn(prompt)
            status = "completed"
        except Exception as exc:
            logger.warning("Sub-agent %s failed: %s", agent_id, exc)
            status = "error"

        self.send_event(WebEvent.make_subagent_end(agent_id, status))

        output_parts: list[str] = []
        for msg in sub_session.messages:
            if msg.role == MessageRole.assistant:
                for block in msg.blocks:
                    if block.type == "text" and block.text:
                        output_parts.append(block.text)

        return "\n\n".join(output_parts) if output_parts else "(sub-agent produced no output)"

    def _call_llm(
    self,
    ) -> tuple[ConversationMessage, list[dict], TokenUsage | None] | None:
        messages = self._build_messages()
        tools = (
            self.tool_registry.definitions()
            if self._skip_tool_filtering
            else self.tool_registry.definitions_filtered(self._discovered_deferred)
        )
        system = "\n\n".join(self.system_prompt) if self.system_prompt else None

        tool_names = [t["function"]["name"] for t in tools if "function" in t]
        mcp_names = [n for n in tool_names if n.startswith("mcp__")]
        logger.info(
            "LLM call: %d messages, %d tools (%d MCP: %s)",
            len(messages), len(tools), len(mcp_names),
            ", ".join(mcp_names) if mcp_names else "none",
        )

        try:
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            usage: TokenUsage | None = None

            for chunk in self.provider.stream_chat(messages, tools, system):
                if self.is_cancelled:
                    break
                kind = chunk.get("type")
                if kind == "text_delta":
                    delta = chunk["content"]
                    text_parts.append(delta)
                    self.send_event(WebEvent.make_text(delta))
                elif kind == "thinking_delta":
                    self.send_event(WebEvent.make_thinking(chunk["content"]))
                elif kind == "tool_call":
                    tool_calls.append(chunk)
                elif kind == "usage":
                    usage = TokenUsage(
                        input_tokens=chunk.get("input_tokens", 0),
                        output_tokens=chunk.get("output_tokens", 0),
                        cache_creation_input_tokens=chunk.get(
                            "cache_creation_input_tokens", 0
                        ),
                        cache_read_input_tokens=chunk.get(
                            "cache_read_input_tokens", 0
                        ),
                    )
                elif kind == "error":
                    self.send_event(WebEvent.make_error(chunk["message"]))
                    return None

            blocks: list[ContentBlock] = []
            full_text = "".join(text_parts)
            if full_text.strip():
                blocks.append(ContentBlock.text_block(full_text))
            for tc in tool_calls:
                blocks.append(
                    ContentBlock.tool_use_block(tc["id"], tc["name"], tc["input"])
                )

            if not blocks:
                logger.warning(
                    "LLM returned empty response (no text, no tool calls). "
                    "raw text=%r, tool_calls=%d",
                    full_text[:200] if full_text else "(empty)",
                    len(tool_calls),
                )
                return None

            assistant_msg = ConversationMessage.assistant_blocks(blocks, usage)
            return assistant_msg, tool_calls, usage

        except Exception as exc:
            self.send_event(WebEvent.make_error(f"LLM 调用失败: {exc}"))
            return None

    def _build_messages(self) -> list[dict]:
        if self.content_store:
            self.session.messages, _ = enforce_message_budget(
                self.session.messages,
                self.content_replacement_state,
                self.content_store,
            )

        return normalize_for_api(self.session.messages, self.content_store)


def _extract_assistant_text(message: ConversationMessage) -> str:
    parts: list[str] = []
    for b in message.blocks:
        if b.type == "text" and b.text:
            parts.append(b.text)
    return "\n".join(parts)


def _truncate(s: str, max_len: int = 4000) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "\n... (输出已截断)"


def _looks_like_error(output: str) -> bool:
    """Heuristic: check if a tool output looks like a command error."""
    if not output:
        return False
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            rc = data.get("returnCodeInterpretation", "")
            if rc and "exit_code:" in rc and ":0" not in rc:
                return True
            stderr = data.get("stderr", "")
            if stderr and "not recognized" in stderr:
                return True
    except (json.JSONDecodeError, TypeError):
        pass
    return False


def drain_background_memory(timeout: float = 60.0) -> None:
    """Wait for any in-flight background memory extraction to complete.

    Call during graceful shutdown.
    """
    _bg_memory.drain(timeout)
