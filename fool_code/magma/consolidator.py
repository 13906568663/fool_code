"""MAGMA Slow Path: asynchronous structural consolidation.

Background worker that dequeues recently ingested events and uses LLM
to infer causal and entity relationships, densifying the multi-graph.
Mirrors Algorithm 3 in the MAGMA paper.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from fool_code.magma.schemas import CONSOLIDATION_SCHEMA
from fool_code.magma.store import get_store, is_magma_enabled

logger = logging.getLogger(__name__)

CONSOLIDATION_SYSTEM = """\
你是一个记忆图谱巩固代理。给定一个新事件及其局部邻居，你的任务是推理出潜在的因果关系和实体关联。

字段说明：
- causal_edges: 如果事件 A 导致或影响了事件 B，添加 A→B 的因果边，含简短原因描述
- entity_edges: 如果两个事件涉及同一实体且有逻辑关联，添加实体边，含共享实体名和关系描述

规则：
- 只添加有高置信度的关系，宁缺毋滥
- 如果没有发现值得添加的关系，返回空数组

请以 JSON 格式输出结果。"""

CONSOLIDATION_USER_TEMPLATE = """\
## 新事件
ID: {node_id}
内容: {content}
摘要: {summary}
时间: {timestamp}

## 邻居事件
{neighbors_text}

请分析上述事件，推理因果关系和实体关联："""


class MagmaConsolidator:
    """Background worker that periodically consolidates pending events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = threading.Event()

    def start(self, workspace_root: Any = None, interval: float = 30.0) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()

        def _worker() -> None:
            logger.info("MAGMA consolidator started (interval=%.0fs)", interval)
            while not self._stop_event.is_set():
                try:
                    self._consolidate_batch(workspace_root)
                except Exception as exc:
                    logger.debug("MAGMA consolidation cycle error: %s", exc)
                self._stop_event.wait(timeout=interval)
            logger.info("MAGMA consolidator stopped")
            with self._lock:
                self._running = False

        threading.Thread(target=_worker, daemon=True, name="magma-consolidator").start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()

    def _consolidate_batch(self, workspace_root: Any) -> int:
        if not is_magma_enabled():
            return 0

        store = get_store()
        if store is None:
            return 0

        pending = store.pending_consolidation(limit=5)
        if not pending:
            return 0

        count = 0
        for node_id in pending:
            try:
                if self._consolidate_one(store, node_id, workspace_root):
                    store.mark_consolidated(node_id)
                    count += 1
                else:
                    store.increment_retry(node_id)
            except Exception as exc:
                logger.debug("Consolidation failed for %s: %s", node_id[:8], exc)
                try:
                    store.increment_retry(node_id)
                except Exception:
                    pass

        if count > 0:
            logger.info("MAGMA consolidated %d/%d events", count, len(pending))
        return count

    def _consolidate_one(
        self,
        store: Any,
        node_id: str,
        workspace_root: Any,
    ) -> bool:
        node_json = store.get_node(node_id)
        if not node_json:
            return False
        node = json.loads(node_json)

        neighbors_json = store.get_neighbors(node_id)
        neighbors_raw = json.loads(neighbors_json) if neighbors_json else []

        # 2-hop neighbor expansion (per MAGMA paper Algorithm 3)
        neighbor_details: list[dict] = []
        seen_ids: set[str] = {node_id}
        hop1_ids: list[str] = []

        for nb in neighbors_raw:
            nb_id = nb.get("node_id", "")
            if nb_id and nb_id not in seen_ids:
                seen_ids.add(nb_id)
                hop1_ids.append(nb_id)
                nb_node_json = store.get_node(nb_id)
                if nb_node_json:
                    nb_node = json.loads(nb_node_json)
                    nb_node["edge_type"] = nb.get("edge_type", "")
                    nb_node["hop"] = 1
                    neighbor_details.append(nb_node)

        # Hop 2: expand neighbors of hop-1 nodes
        for h1_id in hop1_ids:
            if len(neighbor_details) >= 12:
                break
            try:
                h2_json = store.get_neighbors(h1_id)
                h2_raw = json.loads(h2_json) if h2_json else []
            except Exception:
                continue
            for h2 in h2_raw:
                h2_id = h2.get("node_id", "")
                if h2_id and h2_id not in seen_ids:
                    seen_ids.add(h2_id)
                    h2_node_json = store.get_node(h2_id)
                    if h2_node_json:
                        h2_node = json.loads(h2_node_json)
                        h2_node["edge_type"] = h2.get("edge_type", "")
                        h2_node["hop"] = 2
                        neighbor_details.append(h2_node)
                        if len(neighbor_details) >= 12:
                            break

        if not neighbor_details:
            return False

        # Build LLM prompt
        neighbors_text = _format_neighbors(neighbor_details)
        ts_str = time.strftime(
            "%Y-%m-%d %H:%M",
            time.localtime(node.get("timestamp", 0)),
        )
        prompt = CONSOLIDATION_USER_TEMPLATE.format(
            node_id=node_id,
            content=node.get("content", ""),
            summary=node.get("summary", ""),
            timestamp=ts_str,
            neighbors_text=neighbors_text,
        )

        # Call LLM
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

        return _apply_consolidation(store, node_id, result)


def _apply_consolidation(store: Any, node_id: str, raw: str) -> bool:
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return False

    if not isinstance(data, dict):
        return False

    edges: list[dict] = []

    for ce in data.get("causal_edges", []):
        if isinstance(ce, dict) and ce.get("source_id") and ce.get("target_id"):
            edges.append({
                "source_id": ce["source_id"],
                "target_id": ce["target_id"],
                "edge_type": "causal",
                "weight": 1.0,
                "metadata": json.dumps(
                    {"reason": ce.get("reason", "")}, ensure_ascii=False
                ),
            })

    for ee in data.get("entity_edges", []):
        if isinstance(ee, dict) and ee.get("source_id") and ee.get("target_id"):
            edges.append({
                "source_id": ee["source_id"],
                "target_id": ee["target_id"],
                "edge_type": "entity",
                "weight": 1.0,
                "metadata": json.dumps(
                    {
                        "shared_entity": ee.get("shared_entity", ""),
                        "relation": ee.get("relation", ""),
                    },
                    ensure_ascii=False,
                ),
            })

    if edges:
        store.add_edges(json.dumps(edges))
        logger.debug("Consolidation added %d edges for node %s", len(edges), node_id[:8])
        return True

    return False


def _format_neighbors(neighbors: list[dict]) -> str:
    lines: list[str] = []
    for nb in neighbors[:8]:
        nid = nb.get("id", "?")
        edge = nb.get("edge_type", "?")
        summary = nb.get("summary", nb.get("content", "")[:100])
        lines.append(f"- [{edge}] {nid}: {summary}")
    return "\n".join(lines) if lines else "(无邻居)"


# Global singleton
_consolidator = MagmaConsolidator()


def start_consolidator(workspace_root: Any = None, interval: float = 30.0) -> None:
    _consolidator.start(workspace_root, interval)


def stop_consolidator() -> None:
    _consolidator.stop()
