"""Background consolidation worker for auto-discovering skill relationships."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from fool_code.skill_store.schemas import CONSOLIDATION_SCHEMA
from fool_code.skill_store.store import get_store, is_skill_store_enabled

logger = logging.getLogger(__name__)

CONSOLIDATION_SYSTEM = """\
你是一个技能关系推理代理。给定一个新技能及现有技能列表，推理它们之间可能存在的关系：

- prerequisite: A 是 B 的前置知识/依赖
- complementary: A 和 B 经常配合使用
- alternative: A 和 B 功能相似，可互相替代
- composes_with: A 的输出可作为 B 的输入（数据流上下游）
- shared_domain: A 和 B 属于同一技术领域

规则：
- 只添加高置信度的关系，宁缺毋滥
- 每种 edge_type 最多添加 3 条
- 如果没有值得添加的关系，返回空 edges 数组

请以 JSON 格式输出结果。"""

CONSOLIDATION_USER = """\
## 新技能
Name: {name}
Description: {description}
Category: {category}

## 现有技能列表
{existing_skills}

请分析上述技能，推理关系："""


class SkillConsolidator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()

    def start(self, workspace_root: Any = None, interval: float = 60.0) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()

        def _worker() -> None:
            logger.info("Skill consolidator started (interval=%.0fs)", interval)
            while not self._stop_event.is_set():
                try:
                    self._consolidate_batch(workspace_root)
                except Exception as exc:
                    logger.debug("Skill consolidation error: %s", exc)
                self._stop_event.wait(timeout=interval)
            logger.info("Skill consolidator stopped")
            with self._lock:
                self._running = False

        threading.Thread(target=_worker, daemon=True, name="skill-consolidator").start()

    def stop(self) -> None:
        self._stop_event.set()

    def _consolidate_batch(self, workspace_root: Any) -> int:
        if not is_skill_store_enabled():
            return 0

        store = get_store()
        if store is None:
            return 0

        pending = store.pending_consolidation(limit=3)
        if not pending:
            return 0

        count = 0
        for skill_id in pending:
            try:
                if self._consolidate_one(store, skill_id, workspace_root):
                    count += 1
            except Exception as exc:
                logger.debug("Consolidation failed for %s: %s", skill_id, exc)
            finally:
                try:
                    store.mark_consolidated(skill_id)
                except Exception:
                    pass

        if count > 0:
            logger.info("Skill Store consolidated %d/%d skills", count, len(pending))
        return count

    def _consolidate_one(
        self,
        store: Any,
        skill_id: str,
        workspace_root: Any,
    ) -> bool:
        skill_json = store.get_skill(skill_id)
        if not skill_json:
            return False
        skill = json.loads(skill_json)

        all_raw = store.list_skills(enabled=True)
        all_skills = json.loads(all_raw) if all_raw else []

        others = [s for s in all_skills if s["id"] != skill_id]
        if not others:
            return False

        existing_lines = []
        for s in others[:30]:
            cat = s.get("category") or "other"
            existing_lines.append(f"- {s['id']}: {s['description'][:80]} [{cat}]")
        existing_text = "\n".join(existing_lines) if existing_lines else "(无其他技能)"

        prompt = CONSOLIDATION_USER.format(
            name=skill.get("id", skill_id),
            description=skill.get("description", ""),
            category=skill.get("category") or "other",
            existing_skills=existing_text,
        )

        from fool_code.runtime.subagent import create_role_provider

        provider = create_role_provider("memory", workspace_root)
        if provider is None:
            return False

        try:
            result = provider.simple_chat(
                [{"role": "user", "content": prompt}],
                system=CONSOLIDATION_SYSTEM,
                max_tokens=1024,
                response_format=CONSOLIDATION_SCHEMA,
            )
            provider.close()
        except Exception as exc:
            logger.debug("Consolidation LLM call failed: %s", exc)
            return False

        return _apply_consolidation(store, result)


def _apply_consolidation(store: Any, raw: str) -> bool:
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return False

    edges = data.get("edges", [])
    if not isinstance(edges, list) or not edges:
        return False

    edge_dicts = []
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = e.get("source_id", "")
        tgt = e.get("target_id", "")
        etype = e.get("edge_type", "")
        if src and tgt and etype:
            edge_dicts.append({
                "source_id": src,
                "target_id": tgt,
                "edge_type": etype,
                "weight": 1.0,
                "metadata": json.dumps({"reason": e.get("reason", "")}, ensure_ascii=False),
            })

    if edge_dicts:
        store.add_edges(json.dumps(edge_dicts))
        logger.debug("Consolidation added %d edges", len(edge_dicts))
        return True

    return False


_consolidator = SkillConsolidator()


def start_skill_consolidator(workspace_root: Any = None, interval: float = 60.0) -> None:
    _consolidator.start(workspace_root, interval)


def stop_skill_consolidator() -> None:
    _consolidator.stop()
