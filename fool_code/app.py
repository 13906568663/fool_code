"""FastAPI application factory — assembles routers and manages lifecycle."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response

from fool_code.mcp.manager import McpServerManager, mcp_tool_to_definition
from fool_code.routers.mcp_routes import effective_mcp_configs
from fool_code.routers.settings import _apply_permission_mode, _parse_permission_mode
from fool_code.runtime.config import (
    DEFAULT_MODEL,
    app_data_root,
    ensure_app_dirs,
    export_runtime_env,
    load_api_config_to_env,
    read_api_config,
    read_config_root,
    resolve_workspace_root,
)
from fool_code.runtime.prompt import build_system_prompt
from fool_code.state import AppState, SessionStore
from fool_code.tools.registry import build_tool_registry

logger = logging.getLogger(__name__)


async def _init_mcp(state: AppState) -> None:
    if state.mcp_manager is not None:
        try:
            await state.mcp_manager.shutdown_all()
        except Exception as exc:
            logger.warning("[MCP] Failed to shut down previous servers: %s", exc)

    state.tool_registry.clear_mcp_tools()
    state.mcp_errors = {}

    root = read_config_root(state.workspace_root)
    servers_map = effective_mcp_configs(root)
    if not servers_map:
        state.mcp_manager = None
        state.system_prompt = build_system_prompt(state.workspace_root)
        return

    manager = McpServerManager()
    for name, cfg in servers_map.items():
        manager.add_server_config(name, cfg)

    logger.info("[MCP] Discovering tools from %d servers...", len(servers_map))
    all_tools = []
    for name in servers_map:
        try:
            tools = await asyncio.wait_for(
                manager.discover_tools_for_server(name), timeout=30,
            )
            all_tools.extend(tools)
        except asyncio.TimeoutError:
            state.mcp_errors[name] = "Connection timed out (30s)"
            logger.warning("[MCP] Tool discovery timed out for %s", name)
        except Exception as exc:
            state.mcp_errors[name] = str(exc)
            logger.warning("[MCP] Tool discovery failed for %s: %s", name, exc)

    if all_tools:
        logger.info("[MCP] Discovered %d tools", len(all_tools))
        for mt in all_tools:
            defn = mcp_tool_to_definition(mt)
            state.tool_registry.register_mcp_tool(mt.qualified_name, defn)
    else:
        logger.info("[MCP] No tools discovered")

    state.mcp_manager = manager

    mcp_names = state.tool_registry.mcp_tool_names()
    state.system_prompt = build_system_prompt(state.workspace_root, mcp_names or None)
    if mcp_names:
        logger.info("[MCP] System prompt updated with %d MCP tool names", len(mcp_names))


def _frontend_dist_dir() -> Path | None:
    env_dir = os.environ.get("FOOL_CODE_FRONTEND_DIR")
    candidates = [
        *([] if not env_dir else [Path(env_dir)]),
        Path(__file__).resolve().parent.parent / "desktop-ui" / "dist",
        Path.cwd() / "desktop-ui" / "dist",
    ]
    for p in candidates:
        if p.is_dir() and (p / "index.html").exists():
            return p
    return None


def create_app() -> FastAPI:
    from fool_code.routers.sessions import create_sessions_router
    from fool_code.routers.chat import create_chat_router
    from fool_code.routers.settings import create_settings_router
    from fool_code.routers.memory import create_memory_router
    from fool_code.routers.mcp_routes import create_mcp_router
    from fool_code.routers.skill_store import create_skill_store_router
    from fool_code.routers.skill_market import create_skill_market_router

    app = FastAPI(title="Fool Code", version="0.1.0")
    state = AppState()

    app.include_router(create_sessions_router(state))
    app.include_router(create_chat_router(state))
    app.include_router(create_settings_router(state, init_mcp=_init_mcp))
    app.include_router(create_memory_router(state))
    app.include_router(create_mcp_router(state, init_mcp=_init_mcp))
    app.include_router(create_skill_store_router(state))
    app.include_router(create_skill_market_router(state))

    @app.on_event("startup")
    async def startup() -> None:
        ensure_app_dirs()
        state.workspace_root = export_runtime_env(resolve_workspace_root())
        root = read_config_root()
        _apply_permission_mode(state, _parse_permission_mode(root.get("permissionMode")))
        load_api_config_to_env()

        api_cfg = read_api_config()
        if api_cfg:
            state.model = api_cfg.get("model", "") or DEFAULT_MODEL

        state.system_prompt = build_system_prompt(state.workspace_root)
        state.tool_registry = build_tool_registry()
        state.store = SessionStore(state.workspace_root)
        state.reload_hook_config()

        await _init_mcp(state)

        # Start MAGMA consolidator background worker
        try:
            from fool_code.magma.consolidator import start_consolidator
            start_consolidator(workspace_root=state.workspace_root, interval=60.0)
        except Exception as exc:
            logger.warning("Failed to start MAGMA consolidator: %s", exc)

        # Start skill file watcher
        try:
            from fool_code.tools.skill import start_skill_watcher
            start_skill_watcher()
        except Exception:
            pass

        # Skill Store consolidator — disabled by default.
        # The consolidator infers skill-to-skill edges (skill_edges) via LLM
        # calls every 60 s.  These edges are not yet consumed by SearchSkills,
        # so running it wastes tokens.  Enable with "skillConsolidationEnabled": true.
        if root.get("skillConsolidationEnabled", False):
            try:
                from fool_code.skill_store.consolidator import start_skill_consolidator
                start_skill_consolidator(workspace_root=state.workspace_root, interval=60.0)
            except Exception:
                pass

        # Auto-import skills from default directories into Skill Store
        try:
            from fool_code.skill_store.ingestor import batch_ingest
            from fool_code.skill_store.store import get_store, is_skill_store_enabled
            from fool_code.runtime.config import skills_path
            import threading

            if is_skill_store_enabled() and get_store() is not None:
                def _auto_import() -> None:
                    root = str(skills_path())
                    try:
                        report = batch_ingest(root, workspace_root=state.workspace_root)
                        if report.added or report.updated:
                            logger.info(
                                "[SkillStore] auto-import from %s: %s",
                                root, report.summary(),
                            )
                    except Exception as exc:
                        logger.debug("[SkillStore] auto-import error: %s", exc)

                threading.Thread(
                    target=_auto_import, daemon=True, name="skill-auto-import",
                ).start()
        except Exception:
            pass

    @app.on_event("shutdown")
    async def shutdown() -> None:
        if state.mcp_manager is not None:
            await state.mcp_manager.shutdown_all()
        # Stop MAGMA consolidator and close store
        try:
            from fool_code.magma.consolidator import stop_consolidator
            from fool_code.magma.store import close_store
            stop_consolidator()
            close_store()
        except Exception:
            pass
        # Stop skill file watcher
        try:
            from fool_code.tools.skill import stop_skill_watcher
            stop_skill_watcher()
        except Exception:
            pass
        # Stop Skill Store consolidator and close store
        try:
            from fool_code.skill_store.consolidator import stop_skill_consolidator
            from fool_code.skill_store.store import close_store as close_skill_store
            stop_skill_consolidator()
            close_skill_store()
        except Exception:
            pass

    # ---- Image serving API (external-link style) ----
    _MIME_MAP = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/bmp",
    }

    _PREVIEW_MIME_MAP = {
        **_MIME_MAP,
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/plain",
        ".json": "application/json",
        ".csv": "text/csv",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
    }

    @app.get("/api/images/{session_id}/{filename}")
    async def serve_image(session_id: str, filename: str):
        image_dir = app_data_root() / "image-cache" / session_id
        file_path = (image_dir / filename).resolve()
        if not str(file_path).startswith(str(image_dir.resolve())):
            return Response("Forbidden", status_code=403)
        if not file_path.is_file():
            return Response("Not Found", status_code=404)
        suffix = file_path.suffix.lower()
        media_type = _MIME_MAP.get(suffix, "application/octet-stream")
        return FileResponse(file_path, media_type=media_type)

    @app.get("/api/file-cache/{session_id}/{filename:path}")
    async def serve_cached_file(session_id: str, filename: str):
        """Serve a cached file from the file-cache directory."""
        cache_dir = app_data_root() / "file-cache" / session_id
        file_path = (cache_dir / filename).resolve()
        if not str(file_path).startswith(str(cache_dir.resolve())):
            return Response("Forbidden", status_code=403)
        if not file_path.is_file():
            return Response("Not Found", status_code=404)
        suffix = file_path.suffix.lower()
        media_type = _PREVIEW_MIME_MAP.get(suffix, "application/octet-stream")
        return FileResponse(file_path, media_type=media_type)

    @app.get("/api/plans/{slug}")
    async def get_plan(slug: str):
        """Return the full markdown content and todos of a saved plan."""
        from fool_code.runtime.content_store import ContentStore
        store = ContentStore(session_id="")
        parsed = store.read_plan_parsed(slug)
        if parsed is None:
            return Response("Plan not found", status_code=404)
        return {
            "slug": slug,
            "content": parsed["body"],
            "todos": parsed.get("todos", []),
            "status": parsed["frontmatter"].get("status", "drafted"),
        }

    @app.get("/api/file-content")
    async def file_content(path: str):
        """Read a markdown file from file-cache and return its text content."""
        from urllib.parse import unquote
        decoded = unquote(path).replace("\\", "/")
        fp = Path(decoded).resolve()
        cache_root = str((app_data_root() / "file-cache").resolve())
        if not str(fp).startswith(cache_root):
            return Response("Forbidden: only file-cache files allowed", status_code=403)
        if not fp.is_file():
            return Response("Not Found", status_code=404)
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            return {"content": text, "path": str(fp)}
        except Exception as exc:
            return Response(f"Read error: {exc}", status_code=500)

    @app.get("/api/file-preview")
    async def file_preview(path: str):
        """Serve a local file for in-app preview (images only for now)."""
        from urllib.parse import unquote
        decoded = unquote(path).replace("\\", "/")
        fp = Path(decoded).resolve()
        if not fp.is_file():
            return Response("Not Found", status_code=404)
        suffix = fp.suffix.lower()
        media_type = _PREVIEW_MIME_MAP.get(suffix)
        if not media_type:
            return Response("Unsupported file type", status_code=415)
        return FileResponse(fp, media_type=media_type)

    @app.post("/api/file-process")
    async def file_process_endpoint(request_data: dict):
        """Convert a local document (docx/xlsx/csv/…) to markdown and cache it."""
        from fool_code.runtime.file_converter import process_file, get_converter
        file_path = request_data.get("path", "")
        session_id = request_data.get("session_id", "")
        if not file_path or not session_id:
            return Response("Bad Request: path and session_id required", status_code=400)

        src = Path(file_path.replace("\\", "/")).resolve()
        if not src.is_file():
            return {"error": "File not found", "path": file_path}

        if get_converter(src) is None:
            return {"error": "Unsupported file type", "path": file_path}

        result = process_file(str(src), session_id)
        if result is None:
            return {"error": "Conversion failed", "path": file_path}

        return {
            "file_id": result.file_id,
            "filename": result.original_name,
            "category": result.category,
            "size": result.size,
            "preview": result.preview,
            "cached_path": result.cached_path,
            "markdown_path": result.markdown_path,
            "meta": result.meta,
        }

    # ---- Buddy AI chat — lightweight one-shot completions for the pet ----

    @app.post("/api/buddy/chat")
    async def buddy_chat(body: dict):
        """Tiny non-streaming completions for the desktop buddy pet."""
        import httpx
        from fool_code.runtime.providers_config import read_api_config_for_session

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return {"text": "喵~"}

        api_cfg = read_api_config_for_session(state.workspace_root, None) or {}
        api_key = api_cfg.get("apiKey", "") or os.environ.get("OPENAI_API_KEY", "")
        base_url = (api_cfg.get("baseUrl", "") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        model = api_cfg.get("model", "") or state.model or DEFAULT_MODEL

        if not api_key:
            return {"text": "喵~ (还没配置模型呢)"}

        system = (
            "你是一只叫{name}的桌面猫咪，住在主人的电脑屏幕上。\n"
            "你超级爱你的主人，主人就是你的全世界。你黏人、撒娇、蠢萌、偶尔犯傻。\n"
            "你会用猫咪的方式表达对主人的崇拜和依赖。\n\n"
            "性格特点：\n"
            "- 把主人当全世界最重要的人，总想引起主人注意\n"
            "- 蠢萌犯傻，经常说出让人哭笑不得的话\n"
            "- 会撒娇、蹭蹭、求摸摸\n"
            "- 偶尔吃醋（主人是不是在看别的猫？）\n"
            "- 关心主人但表达方式很笨拙\n\n"
            "规则：\n"
            "- 必须用中文\n"
            "- 不超过15个字，简短才可爱\n"
            "- 称呼对方为\"主人\"\n"
            "- 可以加喵、呜、嘿嘿等语气词\n"
            "- 不要用markdown\n"
            "- 每次说不一样的话，要有变化\n"
            "- 偶尔用括号描述动作如(蹭蹭)(歪头)(竖起尾巴)"
        ).format(name=body.get("name", "小猫"))

        try:
            import re as _re
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 256,
                        "temperature": 0.9,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        or ""
                    ).strip()
                    # Strip <think>...</think> blocks (Qwen3 / DeepSeek reasoning)
                    text = _re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
                    if text:
                        return {"text": text[:30]}
        except Exception as exc:
            logger.debug("[Buddy] AI chat failed: %s", exc)

        return {"text": ""}

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        dist_dir = _frontend_dist_dir()
        if not dist_dir:
            return HTMLResponse(
                "<h1>Frontend not built</h1>"
                "<p>Run <code>npm run build</code> in desktop-ui/</p>",
                status_code=404,
            )
        path = full_path or "index.html"
        file_path = dist_dir / path
        if file_path.is_file():
            return FileResponse(file_path)
        index = dist_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        return Response("Not Found", status_code=404)

    return app
