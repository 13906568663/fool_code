"""Session CRUD, switch, compaction routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fool_code.api_types import (
    SessionDetailResponse,
    SessionsResponse,
    SetSessionModelRequest,
    SetSessionProviderRequest,
    ProviderSummary,
)
from fool_code.runtime.compact import CompactionConfig, compact_session
from fool_code.runtime.config import DEFAULT_MODEL, sessions_path
from fool_code.runtime.content_store import ContentStore
from fool_code.runtime.providers_config import (
    load_root_migrated,
    provider_summaries,
    read_api_config_for_session,
)
from fool_code.state import (
    AppState,
    ChatSession,
    chat_messages_from_session,
    persist_session,
    read_saved_models,
    session_effective_model,
)


def create_sessions_router(state: AppState) -> APIRouter:
    router = APIRouter()

    def _load_plan_todos(slug: str | None) -> list[dict]:
        if not slug:
            return []
        try:
            store = ContentStore(session_id="")
            parsed = store.read_plan_parsed(slug)
            if parsed:
                return parsed.get("todos", [])
        except Exception:
            pass
        return []

    @router.get("/api/sessions")
    async def list_sessions() -> SessionsResponse:
        with state.lock:
            return SessionsResponse(
                sessions=state.store.sorted_sessions(),
                active_id=state.store.active_id,
            )

    @router.post("/api/sessions/new")
    async def new_session() -> SessionsResponse:
        with state.lock:
            cs = ChatSession()
            persist_session(cs, state.workspace_root)
            state.store.sessions[cs.id] = cs
            state.store.active_id = cs.id
            state.last_plan_text = ""
            state.conversation_mode = "normal"
            return SessionsResponse(
                sessions=state.store.sorted_sessions(),
                active_id=state.store.active_id,
            )

    @router.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> SessionDetailResponse:
        with state.lock:
            cs = state.store.sessions.get(session_id)
        if cs:
            root = load_root_migrated(state.workspace_root)
            api = read_api_config_for_session(
                state.workspace_root, cs.session.chat_provider_id
            ) or {}
            default_model = (api.get("model", "") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
            saved = read_saved_models(api)
            eff = session_effective_model(cs, state.workspace_root)
            provs = [
                ProviderSummary(id=s["id"], label=s["label"])
                for s in provider_summaries(root)
            ]
            return SessionDetailResponse(
                id=cs.id,
                title=cs.title,
                messages=cs.messages,
                chat_model=cs.session.chat_model,
                chat_provider_id=cs.session.chat_provider_id,
                default_provider_id=str(root.get("defaultProviderId") or ""),
                providers=provs,
                default_model=default_model,
                saved_models=saved,
                effective_model=eff,
                plan_slug=cs.session.plan_slug,
                plan_status=cs.session.plan_status,
                plan_todos=_load_plan_todos(cs.session.plan_slug),
            )
        return SessionDetailResponse(
            id=session_id, title="未找到", messages=[], effective_model="",
        )

    @router.post("/api/sessions/{session_id}/model")
    async def set_session_model(session_id: str, req: SetSessionModelRequest) -> dict[str, Any]:
        with state.lock:
            cs = state.store.sessions.get(session_id)
            if not cs:
                return JSONResponse({"error": "Session not found"}, status_code=404)
            m = (req.model or "").strip()
            cs.session.chat_model = m if m else None
            persist_session(cs, state.workspace_root)
            eff = session_effective_model(cs, state.workspace_root)
            cm = cs.session.chat_model
        return {"ok": True, "effective_model": eff, "chat_model": cm}

    @router.post("/api/sessions/{session_id}/provider")
    async def set_session_provider(
        session_id: str, req: SetSessionProviderRequest,
    ) -> dict[str, Any]:
        with state.lock:
            cs = state.store.sessions.get(session_id)
            if not cs:
                return JSONResponse({"error": "Session not found"}, status_code=404)
            pid = (req.provider_id or "").strip()
            cs.session.chat_provider_id = pid if pid else None
            persist_session(cs, state.workspace_root)
            eff = session_effective_model(cs, state.workspace_root)
            cpid = cs.session.chat_provider_id
        return {"ok": True, "effective_model": eff, "chat_provider_id": cpid}

    @router.post("/api/sessions/{session_id}/switch")
    async def switch_session(session_id: str) -> SessionsResponse:
        with state.lock:
            if session_id in state.store.sessions:
                state.store.active_id = session_id
                cs = state.store.sessions[session_id]
                slug = cs.session.plan_slug
                if slug:
                    store = ContentStore(session_id=session_id)
                    plan_text = store.read_plan(slug)
                    state.last_plan_text = plan_text or ""
                else:
                    state.last_plan_text = ""
                # Restore conversation mode from plan_status
                ps = cs.session.plan_status
                if ps == "drafted":
                    state.conversation_mode = "normal"
                elif ps in ("executing", "completed", "none"):
                    state.conversation_mode = "normal"
            return SessionsResponse(
                sessions=state.store.sorted_sessions(),
                active_id=state.store.active_id,
            )

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> SessionsResponse:
        with state.lock:
            if len(state.store.sessions) > 1:
                state.store.sessions.pop(session_id, None)
                # Delete both JSONL transcript and legacy JSON snapshot
                for suffix in (".jsonl", ".json"):
                    p = sessions_path(state.workspace_root) / f"{session_id}{suffix}"
                    p.unlink(missing_ok=True)
                if state.store.active_id == session_id:
                    state.store.active_id = next(iter(state.store.sessions))
            return SessionsResponse(
                sessions=state.store.sorted_sessions(),
                active_id=state.store.active_id,
            )

    @router.post("/api/sessions/{session_id}/compact")
    async def compact_session_endpoint(session_id: str):
        with state.lock:
            cs = state.store.sessions.get(session_id)
        if not cs:
            return JSONResponse({"error": "Session not found"}, status_code=404)

        result = compact_session(cs.session, CompactionConfig())
        if result.removed_message_count == 0:
            return {"compacted": False, "message": "Session does not need compaction"}

        with state.lock:
            cs.session = result.compacted_session
            cs.messages = chat_messages_from_session(cs.session)
            persist_session(cs, state.workspace_root)

        return {
            "compacted": True,
            "removed_messages": result.removed_message_count,
            "summary": result.formatted_summary[:200],
        }

    return router
