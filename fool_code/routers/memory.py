"""Memory, model roles, and playbook routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fool_code.api_types import (
    CreatePlaybookCategoryRequest,
    MemoryContentResponse,
    MemoryListResponse,
    MemoryTypeInfo,
    ModelRoleConfig,
    ModelRolesResponse,
    PlaybookCategoryInfo,
    PlaybookContentResponse,
    PlaybookDocInfo,
    PlaybooksResponse,
    SaveMemoryRequest,
    SaveModelRolesRequest,
    SavePlaybookRequest,
)
from fool_code.runtime.config import read_config_root, write_config_root
from fool_code.runtime.prompt import build_system_prompt
from fool_code.state import AppState


def create_memory_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/memory")
    async def list_memory() -> MemoryListResponse:
        from fool_code.runtime.memory import (
            is_memory_enabled,
            list_memory_types,
            memory_dir as get_memory_dir,
        )
        types_raw = list_memory_types()
        types = [MemoryTypeInfo(**t) for t in types_raw]
        return MemoryListResponse(
            types=types, enabled=is_memory_enabled(),
            memory_dir=str(get_memory_dir()),
        )

    @router.post("/api/memory/toggle")
    async def toggle_memory(req: Request):
        body = await req.json()
        enabled = bool(body.get("enabled", True))
        root = read_config_root()
        root["autoMemoryEnabled"] = enabled
        write_config_root(root)
        state.system_prompt = build_system_prompt(state.workspace_root)
        return {"ok": True, "enabled": enabled}

    @router.get("/api/model-roles")
    async def get_model_roles() -> ModelRolesResponse:
        from fool_code.runtime.subagent import read_model_roles
        roles = read_model_roles(state.workspace_root)
        v = roles.get("verification", {})
        m = roles.get("memory", {})
        return ModelRolesResponse(
            verification=ModelRoleConfig(
                provider_id=v.get("providerId", ""),
                model=v.get("model", ""), enabled=v.get("enabled", False),
            ),
            memory=ModelRoleConfig(
                provider_id=m.get("providerId", ""),
                model=m.get("model", ""), enabled=m.get("enabled", True),
            ),
        )

    @router.post("/api/model-roles")
    async def save_model_roles_endpoint(req: SaveModelRolesRequest):
        from fool_code.runtime.subagent import read_model_roles, save_model_roles
        roles = read_model_roles(state.workspace_root)
        if req.verification is not None:
            roles["verification"] = {
                "providerId": req.verification.provider_id,
                "model": req.verification.model,
                "enabled": req.verification.enabled,
            }
        if req.memory is not None:
            roles["memory"] = {
                "providerId": req.memory.provider_id,
                "model": req.memory.model,
                "enabled": req.memory.enabled,
            }
        save_model_roles(state.workspace_root, roles)
        return {"ok": True}

    @router.get("/api/memory/{memory_type}")
    async def get_memory(memory_type: str) -> MemoryContentResponse:
        from fool_code.runtime.memory import MEMORY_TYPES, get_memory_template, read_memory
        spec = MEMORY_TYPES.get(memory_type)
        if spec is None:
            return JSONResponse(
                {"error": f"Unknown memory type: {memory_type}"}, status_code=400,
            )
        content = read_memory(memory_type) or ""
        return MemoryContentResponse(
            type=memory_type, title=spec["title"], content=content,
            template=get_memory_template(memory_type),
        )

    @router.post("/api/memory/{memory_type}")
    async def save_memory(memory_type: str, req: SaveMemoryRequest):
        from fool_code.runtime.memory import MEMORY_TYPES, write_memory
        if memory_type not in MEMORY_TYPES:
            return JSONResponse(
                {"error": f"Unknown memory type: {memory_type}"}, status_code=400,
            )
        write_memory(memory_type, req.content)
        state.system_prompt = build_system_prompt(state.workspace_root)
        return {"ok": True, "type": memory_type}

    # ------ Playbooks ------

    @router.get("/api/playbooks")
    async def list_playbooks() -> PlaybooksResponse:
        from fool_code.runtime.playbook import playbooks_dir, scan_playbooks
        cats_raw = scan_playbooks()
        cats = [
            PlaybookCategoryInfo(
                name=c["name"], description=c.get("description", ""),
                documents=[
                    PlaybookDocInfo(filename=d["filename"], title=d["title"])
                    for d in c["documents"]
                ],
            )
            for c in cats_raw
        ]
        return PlaybooksResponse(categories=cats, playbooks_dir=str(playbooks_dir()))

    @router.post("/api/playbooks/category")
    async def create_playbook_category(req: CreatePlaybookCategoryRequest):
        from fool_code.runtime.playbook import create_category
        name = req.name.strip()
        if not name:
            return JSONResponse({"error": "Category name is required"}, status_code=400)
        path = create_category(name, req.description)
        state.system_prompt = build_system_prompt(state.workspace_root)
        return {"ok": True, "path": str(path)}

    @router.delete("/api/playbooks/category/{category}")
    async def delete_playbook_category(category: str):
        from fool_code.runtime.playbook import delete_category
        if delete_category(category):
            state.system_prompt = build_system_prompt(state.workspace_root)
            return {"ok": True}
        return JSONResponse({"error": "Category not found"}, status_code=404)

    @router.get("/api/playbooks/{category}/{filename}")
    async def get_playbook(category: str, filename: str) -> PlaybookContentResponse:
        from fool_code.runtime.playbook import get_document_template, read_playbook
        content = read_playbook(category, filename)
        if content is None:
            return JSONResponse(
                {"error": f"Document '{category}/{filename}' not found"}, status_code=404,
            )
        return PlaybookContentResponse(
            category=category, filename=filename, content=content,
            template=get_document_template(),
        )

    @router.post("/api/playbooks/{category}/{filename}")
    async def save_playbook(category: str, filename: str, req: SavePlaybookRequest):
        from fool_code.runtime.playbook import write_playbook
        if not filename.endswith(".md"):
            filename += ".md"
        path = write_playbook(category, filename, req.content)
        state.system_prompt = build_system_prompt(state.workspace_root)
        return {"ok": True, "path": str(path)}

    @router.delete("/api/playbooks/{category}/{filename}")
    async def delete_playbook_doc(category: str, filename: str):
        from fool_code.runtime.playbook import delete_playbook
        if delete_playbook(category, filename):
            state.system_prompt = build_system_prompt(state.workspace_root)
            return {"ok": True}
        return JSONResponse({"error": "Document not found"}, status_code=404)

    @router.get("/api/playbooks/template")
    async def get_playbook_template():
        from fool_code.runtime.playbook import get_document_template
        return {"template": get_document_template()}

    # ---- MAGMA episodic memory endpoints ----

    @router.get("/api/magma/stats")
    async def magma_stats():
        """Return MAGMA memory statistics."""
        from fool_code.magma.store import get_store, is_magma_enabled, magma_db_path
        import json as _json
        if not is_magma_enabled():
            return {"enabled": False, "db_path": str(magma_db_path())}
        store = get_store()
        if store is None:
            return {"enabled": True, "available": False, "db_path": str(magma_db_path())}
        try:
            stats = _json.loads(store.stats())
        except Exception:
            stats = {}
        return {"enabled": True, "available": True, "db_path": str(magma_db_path()), **stats}

    @router.post("/api/magma/toggle")
    async def magma_toggle(req: Request):
        """Enable or disable MAGMA episodic memory."""
        body = await req.json()
        enabled = bool(body.get("enabled", True))
        root = read_config_root()
        root["magmaMemoryEnabled"] = enabled
        write_config_root(root)
        return {"ok": True, "enabled": enabled}

    @router.get("/api/magma/embedding-config")
    async def get_embedding_config():
        """Get the dedicated embedding API configuration."""
        root = read_config_root()
        cfg = root.get("embeddingConfig", {})
        return {
            "baseUrl": cfg.get("baseUrl", ""),
            "model": cfg.get("model", "text-embedding-3-small"),
            "hasKey": bool((cfg.get("apiKey") or "").strip()),
        }

    @router.post("/api/magma/embedding-config")
    async def save_embedding_config(req: Request):
        """Save the dedicated embedding API configuration.

        Body: { "baseUrl": "...", "apiKey": "...", "model": "..." }
        If apiKey is empty string, the previous key is preserved.
        """
        body = await req.json()
        root = read_config_root()
        prev = root.get("embeddingConfig", {})
        new_key = (body.get("apiKey") or "").strip()
        root["embeddingConfig"] = {
            "baseUrl": (body.get("baseUrl") or "").strip(),
            "apiKey": new_key if new_key else (prev.get("apiKey") or ""),
            "model": (body.get("model") or "text-embedding-3-small").strip(),
        }
        write_config_root(root)
        return {"ok": True}

    @router.get("/api/magma/events")
    async def magma_events(limit: int = 20, offset: int = 0):
        """List recent events from the MAGMA memory graph."""
        from fool_code.magma.store import get_store
        import json as _json
        store = get_store()
        if store is None:
            return {"events": [], "total": 0}
        try:
            stats = _json.loads(store.stats())
            total = stats.get("node_count", 0)
        except Exception:
            total = 0
        try:
            raw = store.get_recent_nodes(limit, offset)
            events = _json.loads(raw)
        except Exception:
            events = []
        return {"events": events, "total": total}

    @router.get("/api/magma/node/{node_id}")
    async def magma_node(node_id: str):
        """Get a single MAGMA memory node."""
        from fool_code.magma.store import get_store
        import json as _json
        store = get_store()
        if store is None:
            return JSONResponse({"error": "MAGMA not available"}, status_code=503)
        raw = store.get_node(node_id)
        if raw is None:
            return JSONResponse({"error": "Node not found"}, status_code=404)
        return _json.loads(raw)

    @router.get("/api/magma/entities")
    async def magma_entities(query: str = "", limit: int = 20):
        """Search entities in the MAGMA memory graph."""
        from fool_code.magma.store import get_store
        import json as _json
        store = get_store()
        if store is None:
            return {"entities": []}
        raw = store.search_entities(query if query else "%", limit)
        return {"entities": _json.loads(raw) if raw else []}

    return router
