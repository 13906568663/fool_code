"""Status, settings, models, skills, permission, workspace routes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fool_code.api_types import (
    DiscoverModelsRequest,
    ModelProviderRowOut,
    ModelsResponse,
    PermissionDecisionRequest,
    PermissionModeResponse,
    SaveSettingsRequest,
    SetPermissionModeRequest,
    SettingsResponse,
    SkillInfo,
    SkillsResponse,
    StatusResponse,
    WorkspaceResponse,
    SetWorkspaceRequest,
)
from fool_code.runtime.config import (
    DEFAULT_MODEL,
    app_data_root,
    config_path,
    export_runtime_env,
    load_api_config_to_env,
    mask_key,
    read_api_config,
    read_config_root,
    sessions_path,
    skills_path,
    write_config_root,
)
from fool_code.runtime.permissions import PermissionMode
from fool_code.runtime.prompt import build_system_prompt
from fool_code.runtime.providers_config import (
    any_provider_has_key,
    default_provider_row,
    load_root_migrated,
    new_provider_id,
    provider_row_by_id,
    read_api_config_for_session,
    row_to_api_dict,
    save_model_providers,
)
from fool_code.providers.model_discovery import fetch_openai_compatible_models
from fool_code.state import AppState, read_saved_models
from fool_code.types import ModelInfo


def _settings_response(workspace_root: Path) -> SettingsResponse:
    root = load_root_migrated(workspace_root)
    api = root.get("api") or {}
    rows_out: list[ModelProviderRowOut] = []
    for p in root.get("modelProviders") or []:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        key = (p.get("apiKey") or "").strip()
        rows_out.append(
            ModelProviderRowOut(
                id=str(p["id"]),
                label=str(p.get("label") or p["id"]),
                provider=str(p.get("provider") or "openai"),
                api_key_masked=mask_key(key),
                base_url=str(p.get("baseUrl") or ""),
                model=str(p.get("model") or DEFAULT_MODEL),
                saved_models=read_saved_models(row_to_api_dict(p)),
            )
        )
    return SettingsResponse(
        provider=str(api.get("provider") or "openai"),
        api_key_masked=mask_key(str(api.get("apiKey") or "")),
        base_url=str(api.get("baseUrl") or ""),
        model=str(api.get("model") or DEFAULT_MODEL),
        config_path=str(config_path(workspace_root)),
        saved_models=read_saved_models(api),
        default_provider_id=str(root.get("defaultProviderId") or ""),
        model_providers=rows_out,
    )


def _parse_permission_mode(raw: Any) -> PermissionMode:
    try:
        return PermissionMode(str(raw).strip())
    except Exception:
        return PermissionMode.DANGER_FULL_ACCESS


def _permission_mode_response(mode: PermissionMode) -> PermissionModeResponse:
    return PermissionModeResponse(mode=mode.value)


def _apply_permission_mode(state: AppState, mode: PermissionMode) -> None:
    state.permission_policy.mode = mode
    state.permission_gate.policy.mode = mode


def create_settings_router(state: AppState, *, init_mcp) -> APIRouter:
    """Create settings router. `init_mcp` is the async MCP init callback from app.py."""
    router = APIRouter()

    @router.get("/api/status")
    async def get_status() -> StatusResponse:
        with state.lock:
            active_id = state.store.active_id if state.store else ""
        configured = any_provider_has_key(state.workspace_root)
        return StatusResponse(
            model=state.model, status="ready",
            active_session=active_id, configured=configured,
        )

    @router.post("/api/permission")
    async def handle_permission(req: PermissionDecisionRequest):
        state.permission_gate.submit_decision(req.decision)
        return {"ok": True}

    @router.post("/api/ask-user-answer")
    async def handle_ask_user_answer(req: dict):
        from fool_code.tools.misc import submit_ask_user_answer
        answers = req.get("answers", {})
        submit_ask_user_answer(answers)
        return {"ok": True}

    @router.get("/api/permission-mode")
    async def get_permission_mode() -> PermissionModeResponse:
        return _permission_mode_response(state.permission_policy.mode)

    @router.post("/api/permission-mode")
    async def set_permission_mode(req: SetPermissionModeRequest):
        mode_raw = (req.mode or "").strip()
        try:
            mode = PermissionMode(mode_raw)
        except ValueError:
            return JSONResponse(
                {"error": f"Unknown permission mode: {mode_raw}"}, status_code=400,
            )
        _apply_permission_mode(state, mode)
        root = read_config_root()
        root["permissionMode"] = mode.value
        write_config_root(root)
        return _permission_mode_response(mode)

    @router.get("/api/settings")
    async def get_settings() -> SettingsResponse:
        return _settings_response(state.workspace_root)

    @router.post("/api/settings")
    async def save_settings(req: SaveSettingsRequest) -> SettingsResponse:
        if req.model_providers is not None:
            raw: list[dict[str, Any]] = []
            for r in req.model_providers:
                rid = (r.id or "").strip() or new_provider_id()
                raw.append({
                    "id": rid,
                    "label": (r.label or "未命名").strip() or rid,
                    "provider": (r.provider or "openai").strip() or "openai",
                    "apiKey": r.api_key,
                    "baseUrl": r.base_url,
                    "model": (r.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                    "savedModels": list(dict.fromkeys(
                        str(x).strip() for x in (r.saved_models or []) if str(x).strip()
                    )),
                })
            dpid = (req.default_provider_id or "").strip()
            ids = {p["id"] for p in raw}
            if raw and dpid not in ids:
                dpid = raw[0]["id"]
            save_model_providers(state.workspace_root, raw, dpid)
        else:
            root = load_root_migrated(state.workspace_root)
            profs = [p for p in (root.get("modelProviders") or []) if isinstance(p, dict)]
            new_key = (req.api_key or "").strip()
            prev_api = root.get("api") if isinstance(root.get("api"), dict) else {}
            if not profs:
                final_key = new_key if new_key else (prev_api.get("apiKey", "") or "")
                if req.saved_models is None:
                    saved = read_saved_models(prev_api)
                else:
                    saved = list(dict.fromkeys(
                        str(x).strip() for x in (req.saved_models or []) if str(x).strip()
                    ))
                single_id = new_provider_id()
                save_model_providers(state.workspace_root, [{
                    "id": single_id, "label": "默认", "provider": req.provider,
                    "apiKey": final_key,
                    "baseUrl": (req.base_url or prev_api.get("baseUrl") or ""),
                    "model": (req.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                    "savedModels": saved,
                }], single_id)
            else:
                row = default_provider_row(root)
                pid = str(row["id"]) if row else str(profs[0].get("id") or "")
                updated: list[dict[str, Any]] = []
                for p in profs:
                    if str(p.get("id")) != pid:
                        updated.append(dict(p))
                        continue
                    fk = new_key if new_key else (p.get("apiKey", "") or "")
                    sm = p.get("savedModels", []) if req.saved_models is None else req.saved_models
                    saved_list = list(dict.fromkeys(
                        str(x).strip() for x in (sm or []) if str(x).strip()
                    ))
                    updated.append({
                        "id": pid, "label": str(p.get("label") or "默认"),
                        "provider": req.provider, "apiKey": fk,
                        "baseUrl": req.base_url if req.base_url else (p.get("baseUrl") or ""),
                        "model": (req.model or p.get("model") or DEFAULT_MODEL),
                        "savedModels": saved_list,
                    })
                dpid = str(root.get("defaultProviderId") or pid)
                save_model_providers(state.workspace_root, updated, dpid)

        load_api_config_to_env(state.workspace_root)
        api_after = read_api_config(state.workspace_root)
        if api_after:
            state.model = api_after.get("model", "") or DEFAULT_MODEL
        state.system_prompt = build_system_prompt(state.workspace_root)
        state.reload_hook_config()
        return _settings_response(state.workspace_root)

    @router.get("/api/models")
    async def get_models(provider: str = "openai") -> ModelsResponse:
        models = [
            ("qwen3.5-plus", "通义千问 3.5 Plus"), ("qwen-max", "通义千问 Max"),
            ("qwen-turbo", "通义千问 Turbo"), ("deepseek-chat", "DeepSeek Chat"),
            ("deepseek-reasoner", "DeepSeek Reasoner"), ("gpt-4o", "GPT-4o"),
            ("gpt-4o-mini", "GPT-4o Mini"), ("o3-mini", "o3-mini"),
        ]
        return ModelsResponse(
            models=[ModelInfo(id=id, name=name) for id, name in models], error=None,
        )

    @router.post("/api/models/discover")
    async def discover_models(req: DiscoverModelsRequest) -> ModelsResponse:
        root = load_root_migrated(state.workspace_root)
        api = read_api_config(state.workspace_root) or {}
        key = (req.api_key or "").strip()
        base = (req.base_url or "").strip()
        pid = (req.provider_id or "").strip()
        if pid:
            row = provider_row_by_id(root, pid)
            if row:
                rdict = row_to_api_dict(row)
                if not key:
                    key = (rdict.get("apiKey", "") or "").strip()
                if not base:
                    base = (rdict.get("baseUrl", "") or "").strip()
        if not key:
            key = (api.get("apiKey", "") or "").strip()
        if not base:
            base = (api.get("baseUrl", "") or "").strip()
        if not base:
            base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

        def _run() -> tuple[list[ModelInfo], str | None]:
            return fetch_openai_compatible_models(base, key)

        models, err = await asyncio.to_thread(_run)
        return ModelsResponse(models=models, error=err)

    @router.get("/api/skills")
    async def get_skills() -> SkillsResponse:
        from fool_code.tools.skill import discover_all_skills as _discover

        discovered = _discover()
        skills: list[SkillInfo] = []
        dirs: list[str] = []

        skill_dir = skills_path(state.workspace_root)
        if skill_dir.is_dir():
            dirs.append(str(skill_dir))

        for si in discovered:
            skills.append(SkillInfo(
                name=si.name,
                path=si.path,
                description=si.listing_description,
            ))
        return SkillsResponse(skills=skills, skill_dirs=dirs)

    @router.get("/api/workspace")
    async def get_workspace() -> WorkspaceResponse:
        wr = state.workspace_root
        return WorkspaceResponse(
            workspace_root=str(wr), app_data_root=str(app_data_root()),
            config_path=str(config_path()), sessions_path=str(sessions_path()),
            skills_path=str(skills_path()),
        )

    @router.post("/api/workspace")
    async def set_workspace(req: SetWorkspaceRequest) -> WorkspaceResponse:
        new_root = Path(req.workspace_root).expanduser()
        new_root.mkdir(parents=True, exist_ok=True)
        state.workspace_root = export_runtime_env(new_root)
        root = read_config_root()
        root["workspace_root"] = str(state.workspace_root)
        write_config_root(root)
        load_api_config_to_env()
        state.system_prompt = build_system_prompt(state.workspace_root)
        state.reload_hook_config()
        await init_mcp(state)
        return WorkspaceResponse(
            workspace_root=str(state.workspace_root), app_data_root=str(app_data_root()),
            config_path=str(config_path()), sessions_path=str(sessions_path()),
            skills_path=str(skills_path()),
        )

    @router.get("/api/computer-use/config")
    async def get_cu_config():
        from fool_code.computer_use.window_manager import get_self_window_pattern, get_hide_mode
        from fool_code.runtime.message_pipeline import _IMAGE_DETAIL
        return {
            "self_window_pattern": get_self_window_pattern(),
            "hide_mode": get_hide_mode(),
            "image_detail": _IMAGE_DETAIL,
        }

    @router.post("/api/computer-use/config")
    async def set_cu_config(req: dict):
        if "self_window_pattern" in req:
            from fool_code.computer_use.window_manager import set_self_window_pattern
            set_self_window_pattern(req["self_window_pattern"])
        if "hide_mode" in req:
            from fool_code.computer_use.window_manager import set_hide_mode
            mode = str(req["hide_mode"]).strip()
            if mode not in ("none", "hide", "affinity"):
                return JSONResponse(
                    {"error": f"Invalid hide_mode: {mode!r}. Must be none/hide/affinity."},
                    status_code=400,
                )
            set_hide_mode(mode)  # type: ignore[arg-type]
        if "image_detail" in req:
            from fool_code.runtime.message_pipeline import set_image_detail
            detail = str(req["image_detail"]).strip()
            if detail not in ("low", "high", "auto"):
                return JSONResponse(
                    {"error": f"Invalid detail: {detail!r}. Must be low/high/auto."},
                    status_code=400,
                )
            set_image_detail(detail)
        return {"ok": True}

    return router
