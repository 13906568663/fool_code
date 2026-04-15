"""Skill Market API routes — browse and install skills from ClawHub."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fool_code.state import AppState

logger = logging.getLogger(__name__)

CLAWHUB_API = "https://clawhub.atomicbot.ai"
MAX_SKILL_FILE_SIZE = 100 * 1024  # 100 KB


def create_skill_market_router(state: AppState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/skill-market/search")
    async def search_skills(q: str = "", limit: int = 20):
        """Search ClawHub skills by keyword."""
        import httpx

        if not q.strip():
            return {"skills": [], "total": 0}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{CLAWHUB_API}/api/skills",
                    params={"q": q, "limit": min(limit, 50)},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.debug("ClawHub search failed: %s", exc)
            return JSONResponse({"error": f"搜索失败: {exc}"}, status_code=502)

        skills = _normalize_items(data)
        return {"skills": skills, "total": data.get("total", len(skills))}

    @router.get("/api/skill-market/popular")
    async def popular_skills(limit: int = 20):
        """Get popular skills from ClawHub."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{CLAWHUB_API}/api/skills",
                    params={
                        "sort": "downloads",
                        "dir": "desc",
                        "limit": min(limit, 50),
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.debug("ClawHub popular fetch failed: %s", exc)
            return JSONResponse({"error": f"获取热门技能失败: {exc}"}, status_code=502)

        skills = _normalize_items(data)
        return {"skills": skills, "total": data.get("total", len(skills))}

    @router.post("/api/skill-market/install")
    async def install_skill(req: Request):
        """Install a skill from ClawHub by slug — download only, no auto-ingest."""
        import httpx

        body = await req.json()
        slug = body.get("slug", "").strip()
        if not slug:
            return JSONResponse({"error": "slug 不能为空"}, status_code=400)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                detail_resp = await client.get(f"{CLAWHUB_API}/api/skills/{slug}")
                detail_resp.raise_for_status()
                detail = detail_resp.json()
        except Exception as exc:
            logger.debug("ClawHub install fetch failed for %s: %s", slug, exc)
            return JSONResponse({"error": f"获取技能内容失败: {exc}"}, status_code=502)

        skill_md_content = detail.get("skillMd", "")
        if not skill_md_content:
            return JSONResponse({"error": f"技能 {slug} 中未找到 SKILL.md 内容"}, status_code=404)

        if len(skill_md_content.encode("utf-8")) > MAX_SKILL_FILE_SIZE:
            return JSONResponse({"error": f"SKILL.md 文件过大（>{MAX_SKILL_FILE_SIZE // 1024}KB），已拒绝"}, status_code=400)

        from fool_code.runtime.config import skills_path

        safe_slug = slug.replace("/", "-").replace("\\", "-").strip("-")
        skill_dir = skills_path() / safe_slug
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(skill_md_content, encoding="utf-8")

        display_name = detail.get("displayName", slug)
        return {
            "ok": True,
            "skill_id": safe_slug,
            "slug": slug,
            "path": str(skill_dir),
            "message": f"技能「{display_name}」已下载到本地，请点击「扫描新增」将其入库。",
        }

    return router


def _normalize_items(data: dict) -> list[dict]:
    """Normalize ClawHub /api/skills response into a uniform list."""
    items = data.get("items", [])
    if not isinstance(items, list):
        return []

    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        stats = item.get("stats") or {}
        owner = item.get("owner") or {}
        latest = item.get("latestVersion") or {}
        results.append({
            "slug": item.get("slug", ""),
            "name": item.get("displayName", item.get("slug", "")),
            "description": item.get("summary", ""),
            "author": owner.get("displayName", owner.get("handle", "")),
            "downloads": stats.get("downloads", 0),
            "stars": stats.get("stars", 0),
            "staff_pick": (item.get("badges") or {}).get("highlighted", False),
            "created_at": item.get("createdAt", ""),
            "version": latest.get("version", ""),
        })
    return results
