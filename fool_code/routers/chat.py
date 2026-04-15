"""Chat SSE endpoint, conversation mode, plan mode logic."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import threading
import uuid as _uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from fool_code.api_types import ChatRequest
from fool_code.events import WebEvent
from fool_code.providers.openai_compat import OpenAICompatProvider
from fool_code.runtime.config import DEFAULT_MODEL, sessions_path
from fool_code.runtime.content_store import ContentStore, extract_plan_summary
from fool_code.runtime.conversation import ConversationRuntime
from fool_code.runtime.providers_config import read_api_config_for_session
from fool_code.runtime.transcript import TranscriptStorage
from fool_code.state import AppState, ChatSession, chat_messages_from_session, extract_title, persist_session
from fool_code.types import ChatMessage, ContentBlock, ConversationMessage, DisplayBlock, MessageRole, Session

logger = logging.getLogger(__name__)

_IMAGE_REF_PATTERN = re.compile(
    r"@((?:[A-Za-z]:[\\/]|/)[^\s]+\.(?:jpg|jpeg|png|gif|webp|bmp))",
    re.IGNORECASE,
)

_DOC_REF_PATTERN = re.compile(
    r"@((?:[A-Za-z]:[\\/]|/)[^\s]+\.(?:docx?|xlsx?|csv|tsv|txt|md|log|json|xml|ya?ml|toml))",
    re.IGNORECASE,
)

_MEDIA_TYPE_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp",
}


def _extract_image_refs(
    message: str,
    content_store: ContentStore,
    send_event,
) -> tuple[str, list[ContentBlock]]:
    """Detect @/path/to/image.ext references in user text.

    Returns (text, image_blocks).  The original text is preserved so the
    frontend can also parse the ``@path`` references to render thumbnails.
    Each referenced image is read from disk, stored via ContentStore, and
    turned into a proper image ContentBlock so the LLM receives pixel data.
    """
    matches = list(_IMAGE_REF_PATTERN.finditer(message))
    if not matches:
        return message, []

    image_blocks: list[ContentBlock] = []

    for m in matches:
        raw_path = m.group(1).replace("\\", "/")
        p = Path(raw_path)
        if not p.is_file():
            logger.warning("Image ref path does not exist: %s", p)
            continue

        suffix = p.suffix.lower()
        media_type = _MEDIA_TYPE_MAP.get(suffix, "image/png")

        try:
            img_b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        except Exception as exc:
            logger.warning("Failed to read image %s: %s", p, exc)
            continue

        img_id = f"usr-{_uuid.uuid4().hex[:12]}"
        stored_path = content_store.store_image(img_id, img_b64, media_type)
        send_event(WebEvent.make_image_stored(img_id, stored_path))

        image_blocks.append(ContentBlock.image_block(
            external_path=stored_path, media_type=media_type, image_id=img_id,
        ))

    return message, image_blocks


def _extract_document_refs(
    message: str,
    session_id: str,
) -> tuple[str, list[ContentBlock]]:
    """Detect @/path/to/file.docx (and xlsx/csv/…) references in user text.

    For each match, looks for a pre-converted markdown in file-cache.
    If not found, does an on-the-fly conversion.  Returns the original text
    unchanged plus document ContentBlocks (type="document") so the LLM
    receives the content but the UI shows a clean file card instead.
    """
    from fool_code.runtime.file_converter import (
        file_cache_dir,
        get_converter,
        process_file,
    )

    matches = list(_DOC_REF_PATTERN.finditer(message))
    if not matches:
        return message, []

    doc_blocks: list[ContentBlock] = []
    cache_dir = file_cache_dir(session_id)

    for m in matches:
        raw_path = m.group(1).replace("\\", "/")
        p = Path(raw_path)

        if not p.is_file():
            if not Path(raw_path).is_file():
                logger.warning("Document ref path does not exist: %s", p)
                continue
            p = Path(raw_path)

        if get_converter(p) is None:
            continue

        result = None
        md_path_str: str | None = None

        for f in cache_dir.glob("file-*"):
            if f.name.endswith(p.suffix + ".md") and p.stem.replace(" ", "_") in f.name:
                md_path_str = str(f)
                break

        if md_path_str is None:
            result = process_file(str(p), session_id)
            if result is None:
                logger.warning("Failed to convert document: %s", p)
                continue
            md_path_str = result.markdown_path

        file_id = f"doc-{_uuid.uuid4().hex[:12]}"
        doc_blocks.append(ContentBlock.document_block(
            external_path=str(p),
            markdown_path=md_path_str,
            filename=p.name,
            file_id=file_id,
            category="spreadsheet" if p.suffix.lower() in {".xlsx", ".xls", ".csv", ".tsv"} else "document",
            size=p.stat().st_size if p.is_file() else 0,
        ))

    return message, doc_blocks


PLAN_SYSTEM_INJECTION = """\

# 当前处于计划模式 (Plan Mode)

你现在处于**计划模式**。在此模式下：

1. **不要执行任何写入操作**（文件修改、命令执行等会被系统阻止）。
2. **使用只读工具**（read_file、grep_search、glob_search 等）来了解代码现状。
3. **你的任务是制定一个详细的执行计划**。

## 重要：先询问再规划

在制定计划之前，如果你发现以下任何情况，**必须**先调用 `AskUserQuestion` 工具向用户提出 1-3 个关键问题：

- 任务有多种可选方案且影响显著（如技术选型、架构方向）
- 需求存在歧义或缺少关键信息
- 需要确认改动范围、优先级或约束条件
- 你不确定用户的偏好

`AskUserQuestion` 的用法示例：
```json
{
  "questions": [
    {
      "question": "你希望使用哪种认证方案？",
      "options": [
        {"label": "JWT Token", "description": "无状态，适合分布式场景"},
        {"label": "Session Cookie", "description": "传统方案，适合单体应用"},
        {"label": "OAuth 2.0", "description": "支持第三方登录"}
      ]
    }
  ]
}
```

收到用户的回答后，再根据用户偏好输出完整计划。如果任务非常明确无需询问，可以直接输出计划。

## 输出格式要求

计划将被保存为带有结构化元数据的文件。每个 `## ` 二级标题会自动成为一个可追踪的任务步骤，执行时在前端显示进度。

**格式**：
```
# 计划标题

简要说明整体思路（1-2 句话）

## 修改 src/auth.py — 添加 JWT 验证

- 在 `login()` 函数中添加 token 生成逻辑
- 新增 `verify_token()` 辅助函数

## 创建 src/middleware.py — 请求验证中间件

- 拦截所有 `/api/` 路由
- 校验 Authorization header
```

**关键规则**：
- 使用 `# ` 一级标题作为计划名称
- 每个独立操作步骤用 `## ` 二级标题，标题简洁唯一
- 不要在标题前加数字序号（系统自动编号追踪）
- 详细内容放在标题下方
- 不要在输出计划的同时调用 SuggestPlanMode（你已经在计划模式了）
- 如果有风险或注意事项，在最后一个步骤中列出

用户看完你的计划后，会决定是否执行、修改或放弃。"""


PLAN_REFINE_INJECTION = """\

# 计划修改模式

用户已经看过你之前制定的计划，现在提出了修改意见。请：

1. 仔细阅读用户的反馈
2. 基于反馈，输出**修订后的完整计划**（不是增量补丁）
3. 在修订计划中体现用户要求的所有改动
4. 保持 `## ` 二级标题格式，每个步骤一个标题
5. 如果用户的反馈不够清晰，可以先用 `AskUserQuestion` 澄清再修改

之前的计划内容：
"""


EXECUTION_SYSTEM_INJECTION_PREFIX = """\

# 执行模式 — 按照计划实施

用户已审阅并批准了你之前制定的计划。你现在的任务是**按计划逐步执行**。

## 极其重要：你必须连续执行所有步骤！

- **不要在完成一个步骤后停下来等待用户确认**，你必须在本次对话中一口气完成计划中的所有步骤。
- 每完成一个步骤立即开始下一个步骤，中间不要输出"是否继续"之类的确认语句。
- 只有在全部步骤都执行完毕后，才输出最终总结。
- 如果某个步骤执行失败，记录错误后继续执行后续步骤，最后在总结中汇报失败的步骤。

## 关于任务进度

下方任务列表中标注了每个步骤的当前状态：
- `[completed]` — 已完成，**不要重复执行**
- `[in_progress]` — 正在执行中，从此步骤继续
- `[pending]` — 尚未开始

如果所有步骤都已标记为 `[completed]`，说明计划已全部完成，无需再执行任何步骤。

## 执行流程

1. **第一步：调用 TodoWrite 工具**，根据下面的任务列表创建 todo。
   - **content 必须与下方任务列表的步骤标题完全一致**（系统通过标题匹配来追踪进度）。
   - 已完成的步骤 status 设为 `completed`，当前要执行的步骤设为 `in_progress`，其余设为 `pending`。
2. **然后立即开始执行**第一个未完成的步骤。
   - 执行每个步骤时，先输出 `## 步骤标题` 作为分隔，方便用户追踪进度。
   - 完成后调用 TodoWrite 标记为 `completed` 并将下一步标记为 `in_progress`。
3. **继续执行**下一个步骤，重复此过程直到所有步骤完成。
4. 执行完所有步骤后，给出简要总结。

"""


def _build_effective_prompt(state: AppState, user_query: str = "") -> list[str]:
    base = list(state.system_prompt)

    if state.conversation_mode == "plan":
        base.append(PLAN_SYSTEM_INJECTION)
        if state.last_plan_text:
            base.append(PLAN_REFINE_INJECTION + state.last_plan_text)
    elif state.last_plan_text:
        plan_body = state.last_plan_text
        _, headings = _parse_plan_headings_from_text(plan_body)

        live_todos = _read_live_plan_todos(state)
        todo_map = {t.get("content", "").strip().lower(): t.get("status", "pending") for t in live_todos} if live_todos else {}

        task_list = ""
        if headings:
            all_completed = todo_map and all(s == "completed" for s in todo_map.values())
            if all_completed:
                task_list = "## 计划已全部执行完成\n\n所有步骤都已完成。如果用户有后续要求，直接正常对话回应即可。\n\n## 已完成的步骤\n\n"
                for i, h in enumerate(headings, 1):
                    task_list += f"{i}. [completed] {h}\n"
                task_list += "\n"
            else:
                task_list = "## 任务列表（当前进度）\n\n"
                for i, h in enumerate(headings, 1):
                    status = _match_heading_status(h, todo_map) if todo_map else "pending"
                    task_list += f"{i}. [{status}] {h}\n"
                task_list += "\n## 完整计划详情\n\n"
        else:
            task_list = "## 待执行的计划\n\n"
        base.append(EXECUTION_SYSTEM_INJECTION_PREFIX + task_list + plan_body)

    deferred = state.tool_registry.deferred_tool_names()
    if deferred:
        base.append(
            "# Available Deferred Tools\n"
            "The following tools are available but NOT loaded by default. "
            "To use any of them, first call `ToolSearch` with "
            '`"select:ToolName"` to load its schema, then call it normally.\n\n'
            + "\n".join(f"- `{n}`" for n in deferred)
        )

    return base


def _read_live_plan_todos(state: AppState) -> list[dict]:
    """Read the latest todos from the active plan file's frontmatter."""
    try:
        with state.lock:
            cs = state.store.active_session()
            slug = cs.session.plan_slug if cs else None
        if not slug:
            return []
        store = ContentStore(session_id="")
        parsed = store.read_plan_parsed(slug)
        if parsed:
            return parsed.get("todos", [])
    except Exception:
        pass
    return []


def _match_heading_status(heading: str, todo_map: dict[str, str]) -> str:
    """Match a heading to a todo status using fuzzy matching."""
    h_lower = heading.strip().lower()
    if h_lower in todo_map:
        return todo_map[h_lower]
    for key, status in todo_map.items():
        if h_lower in key or key in h_lower:
            return status
    return "pending"


def _parse_plan_headings_from_text(markdown: str) -> tuple[str, list[str]]:
    """Extract (title, h2_headings) from plan markdown, stripping frontmatter."""
    body = markdown
    if body.startswith("---"):
        from fool_code.runtime.content_store import _split_frontmatter
        _, body = _split_frontmatter(body)
    title = ""
    headings: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## ") and not title:
            title = stripped[2:].strip()
        elif stripped.startswith("## "):
            h = stripped[3:].strip().rstrip(" \u2014-")
            if h:
                headings.append(h)
    return title, headings


def _extract_assistant_text(session: Session) -> str:
    texts: list[str] = []
    for msg in session.messages:
        if msg.role == MessageRole.assistant:
            for block in msg.blocks:
                if block.type == "text" and block.text:
                    texts.append(block.text)
    return texts[-1] if texts else ""


def _save_plan_document(
    state: AppState, plan_text: str, content_store: ContentStore, send_event,
) -> tuple[str, str]:
    """Save plan with frontmatter to external file and return (file_path, compact_summary)."""
    with state.lock:
        cs = state.store.active_session()
        slug = content_store.get_or_create_plan_slug(cs.session.plan_slug)
        cs.session.plan_slug = slug

    path = content_store.write_plan_with_frontmatter(slug, plan_text)
    summary = extract_plan_summary(plan_text)
    send_event(WebEvent.make_plan_updated(slug, path))

    sess_dir = sessions_path(state.workspace_root)
    transcript = TranscriptStorage(cs.id, sess_dir)
    transcript.append_plan_slug(slug)

    logger.info("Plan saved to %s (slug=%s)", path, slug)
    return path, summary


def _run_chat(
    state: AppState,
    message: str,
    send_event,
    *,
    main_loop: asyncio.AbstractEventLoop | None = None,
    request_model: str | None = None,
    images: list | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    is_plan_execution = (
        state.conversation_mode == "normal"
        and bool(state.last_plan_text)
    )

    with state.lock:
        cs = state.store.active_session()
        cs.messages.append(ChatMessage(
            role="user",
            blocks=[DisplayBlock(type="text", content=message)],
            content=message,
        ))
        if len(cs.messages) == 1:
            cs.title = extract_title(message)
        session = cs.session.model_copy(deep=True)
        active_id = cs.id
        session_chat = (cs.session.chat_model or "").strip()
        chat_provider_id = cs.session.chat_provider_id

    api_cfg = read_api_config_for_session(
        state.workspace_root, chat_provider_id
    ) or {}
    api_key = api_cfg.get("apiKey", "") or os.environ.get("OPENAI_API_KEY", "")
    base_url = (
        api_cfg.get("baseUrl", "")
        or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    rm = (request_model or "").strip()
    cfg_model = (api_cfg.get("model", "") or state.model or DEFAULT_MODEL).strip()
    model = rm or session_chat or cfg_model or DEFAULT_MODEL

    if not api_key:
        send_event(WebEvent.make_error("API Key 未配置，请在设置中配置"))
        return

    provider = OpenAICompatProvider(api_key=api_key, base_url=base_url, model=model)

    content_store = ContentStore(session_id=active_id)

    # Store images and build image content blocks
    image_blocks: list[ContentBlock] = []
    if images:
        for idx, img in enumerate(images):
            path = content_store.store_image(img.id, img.data, img.media_type)
            image_blocks.append(ContentBlock.image_block(
                external_path=path, media_type=img.media_type, image_id=img.id,
            ))
            send_event(WebEvent.make_image_stored(img.id, path))

    # Detect @/path/to/image.ext in message text and resolve to image blocks
    cleaned_message, ref_image_blocks = _extract_image_refs(
        message, content_store, send_event,
    )
    image_blocks.extend(ref_image_blocks)

    # Detect @/path/to/file.docx (xlsx/csv/…) and convert to text blocks
    cleaned_message, doc_blocks = _extract_document_refs(
        cleaned_message, active_id,
    )

    # Update the user ChatMessage with image/document display blocks
    _extra_display: list[DisplayBlock] = []
    for ib in image_blocks:
        _extra_display.append(DisplayBlock(
            type="image_ref",
            content=ib.preview or "[Image]",
            meta={"path": ib.external_path, "media_type": ib.media_type},
        ))
    for db in doc_blocks:
        md_path = db.external_path or ""
        cached_path = md_path[:-3] if md_path.endswith(".md") else md_path
        _extra_display.append(DisplayBlock(
            type="document_ref",
            content=db.name or db.preview or "[Document]",
            meta={
                "markdown_path": md_path,
                "cached_path": cached_path,
                "file_id": db.id,
                "filename": db.name,
                "category": db.media_type or "document",
                "size": db.original_size or 0,
            },
        ))
        send_event(WebEvent.make_document_attached(
            db.id or "", db.name or "",
            db.media_type or "document", db.original_size or 0,
            cached_path=cached_path,
            markdown_path=md_path,
        ))
    if _extra_display:
        with state.lock:
            if cs.messages and cs.messages[-1].role == "user":
                cs.messages[-1].blocks.extend(_extra_display)

    # Build user message with text + images + documents
    user_blocks: list[ContentBlock] = [ContentBlock.text_block(cleaned_message)]
    user_blocks.extend(image_blocks)
    user_blocks.extend(doc_blocks)
    user_msg = ConversationMessage(
        role=MessageRole.user,
        blocks=user_blocks,
    )
    session.messages.append(user_msg)

    # Inject MAGMA episodic context into system prompt (per-query retrieval)
    effective_prompt = _build_effective_prompt(state, user_query=message)
    try:
        from fool_code.magma.retriever import retrieve_context as _magma_retrieve
        magma_ctx = _magma_retrieve(message, workspace_root=state.workspace_root)
        if magma_ctx and magma_ctx.text:
            from fool_code.runtime.prompt import SystemPromptBuilder
            builder = SystemPromptBuilder()
            builder.with_episodic_context(magma_ctx.text)
            ep_sections = builder.build()
            for sec in ep_sections:
                if "近期活动记录" in sec:
                    effective_prompt.append(sec)
                    break
    except Exception as exc:
        logger.debug("MAGMA episodic context retrieval failed: %s", exc)

    runtime = ConversationRuntime(
        session=session,
        provider=provider,
        tool_registry=state.tool_registry,
        system_prompt=effective_prompt,
        permission_gate=state.permission_gate,
        event_callback=send_event,
        mcp_manager=state.mcp_manager,
        hook_config=state.hook_config,
        auto_compact_threshold=None,
        main_loop=main_loop,
        workspace_root=state.workspace_root,
        content_store=content_store,
    )

    runtime.session_id = active_id

    if state.conversation_mode == "plan":
        runtime._mode = "plan"
        send_event(WebEvent.make_mode_change("plan"))

    if cancel_event is not None:
        runtime._cancelled = cancel_event

    if is_plan_execution:
        runtime.session.plan_status = "executing"
        with state.lock:
            cs_exec = state.store.sessions.get(active_id)
            if cs_exec:
                cs_exec.session.plan_status = "executing"
        sess_dir = sessions_path(state.workspace_root)
        TranscriptStorage(active_id, sess_dir).append_plan_status("executing")
        slug = runtime.session.plan_slug
        if slug:
            content_store.update_plan_status(slug, "executing")

    try:
        runtime.run_turn_with_message(user_msg)

        logger.info("[CHAT] runtime.run_turn finished, session has %d messages", len(runtime.session.messages))

        if is_plan_execution:
            runtime.session.plan_status = "completed"
            with state.lock:
                cs_exec = state.store.sessions.get(active_id)
                if cs_exec:
                    cs_exec.session.plan_status = "completed"
            sess_dir = sessions_path(state.workspace_root)
            TranscriptStorage(active_id, sess_dir).append_plan_status("completed")
            slug = runtime.session.plan_slug
            if slug:
                content_store.update_plan_status(slug, "completed")

        try:
            assistant_text = _extract_assistant_text(runtime.session)
        except Exception as exc:
            logger.warning("Failed to extract assistant text: %s", exc)
            assistant_text = ""

        plan_path_str = ""
        plan_summary = ""

        if state.conversation_mode == "plan" and assistant_text.strip():
            plan_path_str, plan_summary = _save_plan_document(
                state, assistant_text, content_store, send_event,
            )
            state.last_plan_text = assistant_text
            with state.lock:
                saved_slug = state.store.active_session().session.plan_slug
            runtime.session.plan_slug = saved_slug

            for msg in reversed(runtime.session.messages):
                if msg.role == MessageRole.assistant:
                    msg.blocks = [
                        ContentBlock.plan_ref_block(
                            external_path=plan_path_str, preview=plan_summary,
                        )
                    ]
                    break

            runtime.session.plan_status = "drafted"
            sess_dir = sessions_path(state.workspace_root)
            TranscriptStorage(active_id, sess_dir).append_plan_status("drafted")
    except Exception as exc:
        logger.error("[CHAT] runtime error: %s", exc, exc_info=True)
        send_event(WebEvent.make_error(
            f"处理消息时发生错误: {type(exc).__name__}: {exc}"
        ))
    finally:
        # ALWAYS persist session — even after crashes, so messages are never lost
        try:
            with state.lock:
                cs = state.store.sessions.get(active_id)
                if cs:
                    cs.session = runtime.session
                    cs.messages = chat_messages_from_session(runtime.session)
                    persist_session(cs, state.workspace_root)
                    logger.info("[CHAT] session persisted: %d internal msgs, %d chat msgs", len(runtime.session.messages), len(cs.messages))
                else:
                    logger.error("[CHAT] !!! active session %s not found in store during persist!", active_id)
        except Exception as exc:
            logger.error("[CHAT] !!! Failed to persist session %s: %s", active_id, exc, exc_info=True)

    provider.close()


def create_chat_router(state: AppState) -> APIRouter:
    router = APIRouter()
    _active_cancel: dict[str, threading.Event] = {}

    @router.post("/api/chat")
    async def handle_chat(req: ChatRequest):
        queue: asyncio.Queue[WebEvent | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()
        cancel_event = threading.Event()

        with state.lock:
            cs = state.store.active_session()
            session_id = cs.id if cs else "default"
        _active_cancel[session_id] = cancel_event

        def send_event(evt: WebEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, evt)

        def chat_worker() -> None:
            logger.info("[CHAT] >>> chat_worker started, session=%s, msg=%r", session_id, req.message[:80])
            try:
                _run_chat(
                    state, req.message, send_event,
                    main_loop=loop, request_model=req.model,
                    images=req.images,
                    cancel_event=cancel_event,
                )
                logger.info("[CHAT] <<< _run_chat completed normally")
            except Exception as exc:
                logger.error("[CHAT] !!! _run_chat raised exception: %s", exc, exc_info=True)
                if not cancel_event.is_set():
                    send_event(WebEvent.make_error(str(exc)))
            finally:
                _active_cancel.pop(session_id, None)
                send_event(WebEvent.make_done())
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=chat_worker, daemon=True).start()

        async def event_generator():
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    data = event.model_dump_json(exclude_none=True)
                    yield {"data": data}
            except asyncio.CancelledError:
                cancel_event.set()
                logger.info("SSE connection closed by client, cancelling runtime")

        return EventSourceResponse(event_generator())

    @router.post("/api/chat/stop")
    async def stop_chat():
        cancelled = False
        for sid, evt in list(_active_cancel.items()):
            evt.set()
            cancelled = True
        return {"cancelled": cancelled}

    @router.get("/api/conversation-mode")
    async def get_conversation_mode():
        return {"mode": state.conversation_mode}

    @router.post("/api/conversation-mode")
    async def set_conversation_mode(req: dict):
        new_mode = (req.get("mode") or "normal").strip()
        if new_mode not in ("normal", "plan"):
            return JSONResponse({"error": f"Unknown mode: {new_mode}"}, status_code=400)
        old_mode = state.conversation_mode
        state.conversation_mode = new_mode
        if new_mode == "plan" and old_mode != "plan":
            state.last_plan_text = ""
        return {"mode": state.conversation_mode}

    @router.post("/api/plan/discard")
    async def discard_plan():
        with state.lock:
            cs = state.store.active_session()
            slug = cs.session.plan_slug
            if slug:
                store = ContentStore(session_id=cs.id)
                store.update_plan_status(slug, "discarded")
            cs.session.plan_slug = None
            cs.session.plan_status = "none"
            state.last_plan_text = ""
            state.conversation_mode = "normal"
        persist_session(cs, state.workspace_root)
        sess_dir = sessions_path(state.workspace_root)
        TranscriptStorage(cs.id, sess_dir).append_plan_status("none")
        return {"ok": True}

    return router
