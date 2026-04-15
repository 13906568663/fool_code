"""Skill Store CRUD API routes.

Route ordering: fixed paths first, then {skill_id:path} sub-routes,
then catch-all {skill_id:path} last — so FastAPI matches specific
routes before the greedy path parameter.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from fool_code.state import AppState


def create_skill_store_router(state: AppState) -> APIRouter:
    router = APIRouter()

    # ── Fixed-path routes (registered first to avoid :path swallowing) ──

    @router.get("/api/skill-store/stats")
    async def skill_store_stats():
        from fool_code.skill_store.store import get_store, is_skill_store_enabled, skill_store_db_path
        if not is_skill_store_enabled():
            return {"enabled": False, "db_path": str(skill_store_db_path())}
        store = get_store()
        if store is None:
            return {"enabled": True, "available": False, "db_path": str(skill_store_db_path())}
        try:
            stats = json.loads(store.stats())
        except Exception:
            stats = {}
        return {"enabled": True, "available": True, "db_path": str(skill_store_db_path()), **stats}

    @router.get("/api/skill-store/list")
    async def list_skills(category: str | None = None, enabled: bool | None = None, pinned: bool | None = None):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return {"skills": [], "total": 0}
        try:
            raw = store.list_skills(category=category, enabled=enabled, pinned=pinned)
            skills = json.loads(raw)
            for s in skills:
                if isinstance(s.get("trigger_terms"), str):
                    try:
                        s["trigger_terms"] = json.loads(s["trigger_terms"])
                    except Exception:
                        s["trigger_terms"] = []
                s["has_embeddings"] = store.has_embedding(s["id"])
        except Exception:
            skills = []
        return {"skills": skills, "total": len(skills)}

    @router.get("/api/skill-store/search")
    async def search_skills(q: str = "", limit: int = 10):
        """Semantic search over local skill store using embedding + RRF (for frontend UI)."""
        from fool_code.skill_store.store import get_store
        from fool_code.skill_store.retriever import _extract_keywords, _get_query_embedding

        store = get_store()
        if store is None:
            return {"skills": [], "total": 0}

        if not q.strip():
            return {"skills": [], "total": 0}

        keywords = _extract_keywords(q)
        query_emb = _get_query_embedding(q, state.workspace_root) or []

        try:
            anchors_json = store.find_anchors(
                query_embedding=query_emb,
                keywords=keywords,
                top_k=min(limit, 20),
                rrf_k=60,
            )
            anchors = json.loads(anchors_json)
        except Exception:
            anchors = []

        if not anchors:
            return {"skills": [], "total": 0}

        ref_max = 2.0 / 61
        results = []
        for a in anchors:
            sid = a.get("skill_id", "")
            score = a.get("score", 0)
            try:
                raw = store.get_skill(sid)
                if not raw:
                    continue
                s = json.loads(raw)
                if isinstance(s.get("trigger_terms"), str):
                    try:
                        s["trigger_terms"] = json.loads(s["trigger_terms"])
                    except Exception:
                        s["trigger_terms"] = []
                s["has_embeddings"] = store.has_embedding(sid)
                s["relevance_score"] = round(min(score / ref_max, 1.0), 4)
                results.append(s)
            except Exception:
                continue

        return {"skills": results, "total": len(results)}

    @router.get("/api/skill-store/relations")
    async def get_all_relations():
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return {"nodes": [], "edges": []}
        try:
            skills_raw = store.list_skills(enabled=True)
            skills = json.loads(skills_raw) if skills_raw else []
            nodes = [{"id": s["id"], "name": s["display_name"], "category": s.get("category")} for s in skills]
        except Exception:
            nodes = []
        try:
            edges_raw = store.get_all_edges()
            edges = json.loads(edges_raw) if edges_raw else []
        except Exception:
            edges = []
        return {"nodes": nodes, "edges": edges}

    @router.post("/api/skill-store/import")
    async def import_skills(req: Request):
        body = await req.json()
        scan_root = body.get("scan_root", "")
        if not scan_root:
            return JSONResponse({"error": "scan_root is required"}, status_code=400)
        from fool_code.skill_store.ingestor import batch_ingest
        report = batch_ingest(scan_root, workspace_root=state.workspace_root)
        return {
            "added": report.added, "updated": report.updated,
            "disabled": report.disabled, "errors": report.errors,
            "summary": report.summary(),
        }

    @router.post("/api/skill-store/rescan")
    async def rescan():
        return _stream_ingest(state, force_reindex=False)

    @router.post("/api/skill-store/reindex")
    async def reindex():
        return _stream_ingest(state, force_reindex=True)

    # ── Sub-path routes with {skill_id:path} (have trailing segments) ──

    @router.get("/api/skill-store/relations/{skill_id:path}")
    async def get_skill_relations(skill_id: str):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return {"nodes": [], "edges": []}
        try:
            edges_raw = store.get_skill_edges(skill_id)
            edges = json.loads(edges_raw) if edges_raw else []
        except Exception:
            edges = []
        node_ids = {skill_id}
        for e in edges:
            node_ids.add(e.get("source_id", ""))
            node_ids.add(e.get("target_id", ""))
        node_ids.discard("")
        nodes = []
        for nid in node_ids:
            try:
                raw = store.get_skill(nid)
                if raw:
                    s = json.loads(raw)
                    nodes.append({"id": s["id"], "name": s["display_name"], "category": s.get("category")})
            except Exception:
                nodes.append({"id": nid, "name": nid, "category": None})
        return {"nodes": nodes, "edges": edges}

    @router.post("/api/skill-store/{skill_id:path}/toggle")
    async def toggle_skill(skill_id: str, req: Request):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return JSONResponse({"error": "Skill Store not available"}, status_code=503)
        body = await req.json()
        enabled = bool(body.get("enabled", True))
        changed = store.set_enabled(skill_id, enabled)
        if not changed:
            return JSONResponse({"error": "Skill not found"}, status_code=404)
        return {"ok": True, "enabled": enabled}

    @router.post("/api/skill-store/{skill_id:path}/pin")
    async def pin_skill(skill_id: str, req: Request):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return JSONResponse({"error": "Skill Store not available"}, status_code=503)
        body = await req.json()
        pinned = bool(body.get("pinned", True))
        changed = store.set_pinned(skill_id, pinned)
        if not changed:
            return JSONResponse({"error": "Skill not found"}, status_code=404)
        return {"ok": True, "pinned": pinned}

    @router.post("/api/skill-store/{skill_id:path}/feedback")
    async def record_feedback(skill_id: str, req: Request):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return JSONResponse({"error": "Skill Store not available"}, status_code=503)
        body = await req.json()
        helpful = body.get("helpful")
        if helpful is None:
            return JSONResponse({"error": "helpful field required (true/false)"}, status_code=400)
        session_id = body.get("session_id", "")
        query_text = body.get("query_text", "")
        try:
            store.record_usage(skill_id, session_id, query_text)
        except Exception:
            pass
        return {"ok": True, "skill_id": skill_id, "helpful": helpful}

    @router.get("/api/skill-store/{skill_id:path}/usage")
    async def get_skill_usage(skill_id: str):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return {"skill_id": skill_id, "total_uses": 0, "helpful_count": 0}
        try:
            raw = store.stats()
            stats = json.loads(raw)
        except Exception:
            stats = {}
        return {"skill_id": skill_id, "stats": stats}

    # ── Catch-all {skill_id:path} routes (registered last) ──

    @router.get("/api/skill-store/{skill_id:path}")
    async def get_skill(skill_id: str):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return JSONResponse({"error": "Skill Store not available"}, status_code=503)
        raw = store.get_skill(skill_id)
        if raw is None:
            return JSONResponse({"error": "Skill not found"}, status_code=404)
        skill = json.loads(raw)
        if isinstance(skill.get("trigger_terms"), str):
            try:
                skill["trigger_terms"] = json.loads(skill["trigger_terms"])
            except Exception:
                skill["trigger_terms"] = []
        try:
            entities_raw = store.get_skill_entities(skill_id)
            skill["entities"] = json.loads(entities_raw) if entities_raw else []
        except Exception:
            skill["entities"] = []
        try:
            edges_raw = store.get_skill_edges(skill_id)
            skill["edges"] = json.loads(edges_raw) if edges_raw else []
        except Exception:
            skill["edges"] = []
        skill["has_embeddings"] = store.has_embedding(skill_id)
        body_path = skill.get("body_path", "")
        if body_path:
            from pathlib import Path
            p = Path(body_path)
            if p.exists():
                try:
                    skill["body_content"] = p.read_text(encoding="utf-8")
                except Exception:
                    skill["body_content"] = ""
            else:
                skill["body_content"] = ""
        else:
            skill["body_content"] = ""
        return skill

    @router.put("/api/skill-store/{skill_id:path}")
    async def update_skill(skill_id: str, req: Request):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return JSONResponse({"error": "Skill Store not available"}, status_code=503)
        body = await req.json()
        display_name = body.get("display_name")
        description = body.get("description")
        category = body.get("category")
        trigger_terms = body.get("trigger_terms")
        trigger_json = None
        if trigger_terms is not None:
            trigger_json = json.dumps(trigger_terms, ensure_ascii=False)
        changed = store.update_metadata(
            skill_id, display_name=display_name, description=description,
            category=category, trigger_terms_json=trigger_json,
        )
        if not changed:
            return JSONResponse({"error": "Skill not found"}, status_code=404)
        if description:
            try:
                from fool_code.magma.extractor import _generate_embedding
                emb = _generate_embedding(description, state.workspace_root)
                if emb:
                    store.upsert_embedding(skill_id, "description", emb)
            except Exception:
                pass
        return {"ok": True}

    @router.delete("/api/skill-store/{skill_id:path}")
    async def delete_skill(skill_id: str):
        from fool_code.skill_store.store import get_store
        store = get_store()
        if store is None:
            return JSONResponse({"error": "Skill Store not available"}, status_code=503)
        deleted = store.delete_skill(skill_id)
        if not deleted:
            return JSONResponse({"error": "Skill not found"}, status_code=404)
        return {"ok": True}

    return router


def _stream_ingest(state: AppState, force_reindex: bool) -> StreamingResponse:
    """Run rescan/reindex in a background thread, streaming SSE progress events."""

    q: queue.Queue[dict | None] = queue.Queue()

    def _on_progress(current: int, total: int, skill: str, status: str) -> None:
        q.put({"type": "progress", "current": current, "total": total, "skill": skill, "status": status})

    def _worker() -> None:
        try:
            if force_reindex:
                from fool_code.skill_store.ingestor import reindex_all
                report = reindex_all(workspace_root=state.workspace_root, on_progress=_on_progress)
            else:
                from fool_code.skill_store.ingestor import rescan
                report = rescan(workspace_root=state.workspace_root, on_progress=_on_progress)
            q.put({"type": "done", "summary": report.summary(), "added": len(report.added), "updated": len(report.updated), "errors": len(report.errors), "total_scanned": report.total_scanned})
        except Exception as exc:
            q.put({"type": "error", "message": str(exc)})
        q.put(None)

    threading.Thread(target=_worker, daemon=True).start()

    async def _generate():
        while True:
            try:
                msg = await asyncio.get_event_loop().run_in_executor(None, q.get, True, 0.5)
            except Exception:
                await asyncio.sleep(0.3)
                continue
            if msg is None:
                break
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")
