"""Skill Store retrieval pipeline — dynamic skill selection for each query.

Stages:
  0. Always-on: pinned skills (bypass retrieval)
  1. Intent classification (rule-based, fast)
  2. Embedding generation + multi-signal RRF anchor search
  3. Graph traversal with intent-weighted beam search
  4. Linearization into prompt-ready text
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from fool_code.skill_store.schemas import SKILL_INTENT_WEIGHTS
from fool_code.skill_store.store import get_store, is_skill_store_enabled

logger = logging.getLogger(__name__)

MAX_SKILL_CHARS = 6_000
MAX_SKILL_COUNT = 8
MAX_PINNED_CHARS = 3_000


def retrieve_skills(
    query: str,
    workspace_root: Any = None,
    max_chars: int = MAX_SKILL_CHARS,
    max_count: int = MAX_SKILL_COUNT,
) -> str | None:
    """Retrieve relevant skills for the given query and return prompt text.

    Returns None if Skill Store is disabled or nothing matches.
    """
    t0 = time.perf_counter()

    if not is_skill_store_enabled():
        return None

    store = get_store()
    if store is None:
        return None

    try:
        stats_raw = store.stats()
        stats = json.loads(stats_raw)
        if stats.get("total", 0) == 0:
            return None
    except Exception:
        return None

    # Stage 0: Pinned skills (always included)
    pinned_text, pinned_ids = _get_pinned_skills(store, MAX_PINNED_CHARS)
    remaining_budget = max_chars - len(pinned_text)
    remaining_count = max_count - len(pinned_ids)

    if remaining_count <= 0 or remaining_budget <= 200:
        return _assemble_prompt(pinned_text, "")

    # Stage 1: Intent classification
    intent = _classify_intent(query)
    keywords = _extract_keywords(query)

    # Stage 2: Embedding + RRF anchor search
    query_emb = _get_query_embedding(query, workspace_root)
    if not query_emb:
        logger.debug("[SkillRetriever] embedding generation failed, using keyword-only")
        query_emb = []

    try:
        anchors_json = store.find_anchors(
            query_embedding=query_emb,
            keywords=keywords,
            top_k=remaining_count + 3,
            rrf_k=60,
        )
        anchors = json.loads(anchors_json)
    except Exception as exc:
        logger.debug("[SkillRetriever] anchor search failed: %s", exc)
        anchors = []

    anchors = [a for a in anchors if a["skill_id"] not in pinned_ids]

    if not anchors:
        t_total = time.perf_counter() - t0
        logger.info("[SkillRetriever] no anchors (%.0fms)", t_total * 1000)
        return _assemble_prompt(pinned_text, "") if pinned_text else None

    # Stage 3: Graph traversal
    anchor_ids = [a["skill_id"] for a in anchors[:remaining_count]]
    weights = SKILL_INTENT_WEIGHTS.get(intent, SKILL_INTENT_WEIGHTS["QUERY"])

    try:
        traversal_json = store.traverse(
            anchor_ids=anchor_ids,
            intent_weights_json=json.dumps(weights),
            query_embedding=query_emb if query_emb else [0.0] * 64,
            lambda1=1.0,
            lambda2=0.5,
            max_depth=2,
            beam_width=5,
            budget=remaining_count,
            decay=0.85,
        )
        results = json.loads(traversal_json)
    except Exception as exc:
        logger.debug("[SkillRetriever] traversal failed: %s", exc)
        results = anchors[:remaining_count]

    results = [r for r in results if r.get("skill_id") not in pinned_ids]

    # Stage 4: Linearize
    dynamic_text = _linearize_skills(store, results, remaining_budget, remaining_count)

    t_total = time.perf_counter() - t0
    total_skills = len(pinned_ids) + len(results)
    logger.info(
        "[SkillRetriever] %.0fms | intent=%s | pinned=%d dynamic=%d | chars=%d",
        t_total * 1000, intent, len(pinned_ids), len(results),
        len(pinned_text) + len(dynamic_text),
    )

    assembled = _assemble_prompt(pinned_text, dynamic_text)
    return assembled if assembled.strip() else None


def retrieve_skills_for_prompt(
    query: str,
    workspace_root: Any = None,
) -> str | None:
    """Convenience wrapper used in prompt builder integration."""
    return retrieve_skills(query, workspace_root)


def retrieve_skills_brief(
    query: str,
    top_k: int = 5,
    workspace_root: Any = None,
) -> tuple[list[dict], bool]:
    """RRF search returning top-K skill summaries for tool responses.

    Returns (results, has_embedding):
      - results: compact list of dicts with truncated fields
      - has_embedding: True if a real vector embedding was used in the search,
        False if only keyword + heat signals were available
    """
    if not is_skill_store_enabled():
        return [], False

    store = get_store()
    if store is None:
        return [], False

    keywords = _extract_keywords(query)
    query_emb = _get_query_embedding(query, workspace_root) or []
    has_embedding = bool(query_emb) and any(v != 0.0 for v in query_emb)

    try:
        anchors_json = store.find_anchors(
            query_embedding=query_emb,
            keywords=keywords,
            top_k=top_k,
            rrf_k=60,
        )
        anchors = json.loads(anchors_json)
    except Exception:
        return [], has_embedding

    results: list[dict] = []
    for a in anchors:
        sid = a.get("skill_id", "")
        rrf_score = a.get("score", 0)
        try:
            raw = store.get_skill(sid)
            if not raw:
                continue
            s = json.loads(raw)
        except Exception:
            continue

        triggers = s.get("trigger_terms", [])
        if isinstance(triggers, str):
            try:
                triggers = json.loads(triggers)
            except Exception:
                triggers = []

        results.append({
            "id": sid,
            "name": s.get("display_name", sid),
            "description": (s.get("description") or "")[:150],
            "category": s.get("category", ""),
            "triggers": triggers[:5] if isinstance(triggers, list) else [],
            "_score": rrf_score,
        })

    return results, has_embedding


# ---------------------------------------------------------------------------
# Stage 0: Pinned skills
# ---------------------------------------------------------------------------

def _get_pinned_skills(store: Any, max_chars: int) -> tuple[str, set[str]]:
    try:
        raw = store.get_pinned_skills()
        pinned = json.loads(raw) if raw else []
    except Exception:
        return "", set()

    if not pinned:
        return "", set()

    ids = set()
    lines: list[str] = []
    total = 0

    for s in pinned:
        sid = s["id"]
        name = s.get("display_name", sid)
        desc = s.get("description", "")[:150]
        entry = f"- **{name}** (`{sid}`): {desc}"

        body_text = ""
        body_path = s.get("body_path", "")
        if body_path:
            try:
                p = Path(body_path)
                if p.exists():
                    body_text = p.read_text(encoding="utf-8")[:800]
            except Exception:
                pass

        if body_text:
            entry += f"\n  <skill_content>\n  {body_text}\n  </skill_content>"

        if total + len(entry) > max_chars:
            break

        lines.append(entry)
        ids.add(sid)
        total += len(entry)

    return "\n".join(lines), ids


# ---------------------------------------------------------------------------
# Stage 1: Intent classification
# ---------------------------------------------------------------------------

def _classify_intent(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ["创建", "新建", "生成", "create", "generate", "scaffold", "init"]):
        return "CREATE"
    if any(w in q for w in ["修复", "bug", "fix", "error", "报错", "异常", "debug"]):
        return "FIX"
    if any(w in q for w in ["重构", "迁移", "转换", "refactor", "migrate", "transform", "convert"]):
        return "TRANSFORM"
    return "QUERY"


def _extract_keywords(query: str) -> list[str]:
    import jieba

    words = jieba.lcut(query)
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        w = w.strip()
        if len(w) < 2 or re.match(r'^[\s\W]+$', w):
            continue
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result[:12]


# ---------------------------------------------------------------------------
# Stage 2: Embedding
# ---------------------------------------------------------------------------

def _get_query_embedding(query: str, workspace_root: Any) -> list[float] | None:
    try:
        from fool_code.magma.extractor import _generate_embedding
        return _generate_embedding(query, workspace_root)
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stage 4: Linearization
# ---------------------------------------------------------------------------

def _linearize_skills(
    store: Any,
    results: list[dict],
    max_chars: int,
    max_count: int,
) -> str:
    lines: list[str] = []
    total = 0
    count = 0

    for r in results:
        if count >= max_count:
            break

        sid = r.get("skill_id", "")
        name = r.get("display_name", sid)
        desc = r.get("description", "")[:150]
        score = r.get("score", 0)

        entry = f"- **{name}** (`{sid}`, 相关度 {score:.2f}): {desc}"

        if total + len(entry) > max_chars:
            break

        lines.append(entry)
        total += len(entry)
        count += 1

    return "\n".join(lines)


def _assemble_prompt(pinned_text: str, dynamic_text: str) -> str:
    sections: list[str] = []

    if pinned_text:
        sections.append("## 常驻技能 (Pinned)\n\n" + pinned_text)
    if dynamic_text:
        sections.append("## 推荐技能 (根据当前查询动态匹配)\n\n" + dynamic_text)

    if not sections:
        return ""

    header = (
        "# Skill Store — 动态技能检索结果\n\n"
        "以下技能与当前查询高度相关。当用户请求匹配某个技能时，"
        "优先使用 `Skill(skill=\"<id>\")` 调用。\n"
    )
    return header + "\n\n".join(sections)
