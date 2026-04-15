"""MAGMA Fast Path: extract events from conversation turns, generate
embeddings, and ingest them into the Rust store.

Runs in a background thread after each conversation turn — mirrors
the existing _BackgroundMemoryExtractor pattern.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fool_code.magma.schemas import EVENT_EXTRACTION_SCHEMA, EntityRef, MagmaEvent
from fool_code.magma.store import get_store, is_magma_enabled

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = """\
你是一个事件提取子代理。你的任务是分析用户与 AI 助手的对话，从中提取有意义的事件。
每个"事件"代表对话中一个值得长期记住的动作、决策或关键信息交换。

事件字段说明：
- content: 事件完整描述（2-4 句话，包含足够上下文使其独立可理解）
- summary: 一句话摘要（10-20 字）
- entities: 涉及的实体列表，每个为 {"name": "...", "type": "person|project|technology|file|concept"}
- topic: 主题标签（1-3 个词）
- is_decision: 是否为用户做出的决策或偏好表达

规则：
- 只提取有长期记忆价值的事件，不要提取寒暄、确认等琐碎交互
- 每轮对话通常提取 0-3 个事件
- 如果对话没有值得记忆的内容，返回空的 events 数组
- 重点关注：用户做了什么决策、遇到了什么问题、使用了什么技术、完成了什么任务

请以 JSON 格式输出结果。"""

EXTRACTION_USER_TEMPLATE = """\
## 对话内容

{recent_messages}

请提取值得长期记忆的事件："""


def extract_and_ingest(
    messages: list[dict],
    session_id: str,
    workspace_root: Any = None,
) -> int:
    """Extract events from messages and ingest into the MAGMA store.

    Returns the number of events ingested.
    """
    if not is_magma_enabled():
        return 0

    store = get_store()
    if store is None:
        return 0

    events = _extract_events_via_llm(messages, workspace_root)
    if not events:
        return 0

    count = 0
    for event in events:
        try:
            embedding = _generate_embedding(event.content, workspace_root)
            if not embedding:
                embedding = _generate_embedding(event.summary, workspace_root)
            if not embedding:
                logger.debug("Skipping event — no embedding available")
                continue

            metadata = {
                "entities": [{"name": e.name, "type": e.entity_type} for e in event.entities],
                "topic": event.topic,
                "is_decision": event.is_decision,
            }

            node_id = store.ingest_event(
                content=event.content,
                summary=event.summary,
                timestamp=time.time(),
                embedding=embedding,
                session_id=session_id,
                metadata_json=json.dumps(metadata, ensure_ascii=False),
            )

            for ent in event.entities:
                ent_id = f"{ent.entity_type}:{ent.name.lower().replace(' ', '_')}"
                store.upsert_entity(ent_id, ent.name, ent.entity_type)
                store.link_entity_node(ent_id, node_id, "mentioned_in")

            count += 1
            logger.debug("MAGMA ingested event: %s — %s", node_id[:8], event.summary)

        except Exception as exc:
            logger.warning("MAGMA ingest failed for event: %s", exc)

    return count


# ---------------------------------------------------------------------------
# LLM-based event extraction
# ---------------------------------------------------------------------------

def _extract_events_via_llm(
    messages: list[dict],
    workspace_root: Any,
) -> list[MagmaEvent]:
    from fool_code.runtime.subagent import create_role_provider

    provider = create_role_provider("memory", workspace_root)
    if provider is None:
        logger.debug("MAGMA extraction: no LLM provider for 'memory' role")
        return []

    recent_text = _format_messages(messages, max_messages=10)
    if not recent_text.strip():
        return []

    prompt = EXTRACTION_USER_TEMPLATE.format(recent_messages=recent_text)

    try:
        result = provider.simple_chat(
            [{"role": "user", "content": prompt}],
            system=EXTRACTION_SYSTEM,
            max_tokens=2048,
            response_format=EVENT_EXTRACTION_SCHEMA,
        )
        provider.close()
    except Exception as exc:
        logger.warning("MAGMA event extraction LLM call failed: %s", exc)
        return []

    return _parse_events(result)


def _parse_events(raw: str) -> list[MagmaEvent]:
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        logger.debug("MAGMA extraction: invalid JSON")
        return []

    items = data.get("events", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return []

    events: list[MagmaEvent] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content", "")
        summary = item.get("summary", "")
        if not content or not summary:
            continue

        entities: list[EntityRef] = []
        for e in item.get("entities", []):
            if isinstance(e, dict) and e.get("name"):
                entities.append(EntityRef(
                    name=e["name"],
                    entity_type=e.get("type", "concept"),
                ))

        events.append(MagmaEvent(
            content=content,
            summary=summary,
            entities=entities,
            topic=item.get("topic", ""),
            is_decision=bool(item.get("is_decision", False)),
        ))

    return events


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

def _generate_embedding(text: str, workspace_root: Any) -> list[float] | None:
    """Generate embedding vector via the dedicated embedding API config.

    Reads ``embeddingConfig`` from settings.json:
        { "baseUrl": "...", "apiKey": "...", "model": "text-embedding-3-small" }

    Falls back to the chat provider's /embeddings endpoint if embeddingConfig
    is absent, then to a hash-based pseudo-embedding as last resort.

    All returned vectors are aligned to the store's canonical dimension so
    that cosine similarity always works.
    """
    from fool_code.runtime.config import read_config_root

    root = read_config_root(workspace_root)

    raw_emb: list[float] | None = None

    # 1. Dedicated embedding config (preferred)
    emb_cfg = root.get("embeddingConfig")
    if isinstance(emb_cfg, dict):
        base_url = (emb_cfg.get("baseUrl") or "").strip().rstrip("/")
        api_key = (emb_cfg.get("apiKey") or "").strip()
        model = (emb_cfg.get("model") or "text-embedding-3-small").strip()
        if base_url and api_key:
            raw_emb = _call_embedding_api(base_url, api_key, text, model)
            if raw_emb is None:
                logger.debug("Dedicated embedding API failed, trying chat provider fallback")

    # 2. Fallback: reuse the memory-role (or default) chat provider's /embeddings
    if raw_emb is None:
        try:
            from fool_code.runtime.providers_config import (
                load_root_migrated,
                provider_row_by_id,
                default_provider_row,
                row_to_api_dict,
            )

            roles = root.get("modelRoles", {})
            memory_cfg = roles.get("memory", {})
            provider_id = memory_cfg.get("providerId", "")

            prov_root = load_root_migrated(workspace_root)
            if provider_id:
                row = provider_row_by_id(prov_root, provider_id)
            else:
                row = default_provider_row(prov_root)

            if row:
                api = row_to_api_dict(row)
                base_url = (api.get("baseUrl") or api.get("base_url") or "").strip().rstrip("/")
                api_key = (api.get("apiKey") or api.get("api_key") or "").strip()
                if base_url and api_key:
                    raw_emb = _call_embedding_api(base_url, api_key, text)
        except Exception as exc:
            logger.debug("Chat provider embedding fallback failed: %s", exc)

    # 3. Last resort: hash-based pseudo-embedding (no semantic meaning)
    if raw_emb is None:
        logger.debug("Using hash-based pseudo-embedding — configure embeddingConfig for real semantics")
        target_dim = _get_canonical_dim()
        raw_emb = _hash_embedding(text, dim=target_dim)

    return _align_dimension(raw_emb)


def _call_embedding_api(
    base_url: str,
    api_key: str,
    text: str,
    model: str = "text-embedding-3-small",
) -> list[float] | None:
    import httpx

    url = f"{base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {"input": text[:8000], "model": model}

    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=30)
        if resp.status_code != 200:
            logger.debug("Embedding API returned %d", resp.status_code)
            return None
        data = resp.json()
        emb = data.get("data", [{}])[0].get("embedding")
        if isinstance(emb, list) and len(emb) > 0:
            return emb
    except Exception as exc:
        logger.debug("Embedding API call failed: %s", exc)

    return None


def _hash_embedding(text: str, dim: int = 1536) -> list[float]:
    """Deterministic pseudo-embedding based on character trigram hashing.

    Not semantically meaningful, but provides a consistent fallback so the
    system can still record events and do basic temporal/entity retrieval.
    """
    import hashlib
    import struct

    h = hashlib.sha512(text.encode("utf-8")).digest()
    seed = struct.unpack("<Q", h[:8])[0]

    vec = []
    for i in range(dim):
        seed ^= seed << 13 & 0xFFFFFFFFFFFFFFFF
        seed ^= seed >> 7
        seed ^= seed << 17 & 0xFFFFFFFFFFFFFFFF
        val = ((seed & 0xFFFFFFFF) / 0xFFFFFFFF) * 2 - 1  # [-1, 1]
        vec.append(val)

    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]

    return vec


_canonical_dim: int | None = None


def _get_canonical_dim() -> int:
    """Return the embedding dimension already established in the store.

    Falls back to 1536 (OpenAI text-embedding-3-small) when the store is
    empty or unavailable.
    """
    global _canonical_dim
    if _canonical_dim is not None:
        return _canonical_dim

    try:
        store = get_store()
        if store is not None:
            val = store.get_meta("embed_dim")
            if val is not None:
                _canonical_dim = int(val)
                return _canonical_dim
    except Exception:
        pass
    return 1536


def _align_dimension(vec: list[float]) -> list[float]:
    """Ensure *vec* matches the store's canonical embedding dimension.

    On the very first embedding, we record the dimension as canonical.
    Subsequent embeddings are truncated or zero-padded to match.
    """
    global _canonical_dim
    dim = len(vec)

    if _canonical_dim is None:
        try:
            store = get_store()
            if store is not None:
                existing = store.get_meta("embed_dim")
                if existing is not None:
                    _canonical_dim = int(existing)
                else:
                    _canonical_dim = dim
                    store.set_meta("embed_dim", str(dim))
        except Exception:
            _canonical_dim = dim

    target = _canonical_dim or dim

    if dim == target:
        return vec
    if dim > target:
        return vec[:target]
    return vec + [0.0] * (target - dim)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_messages(messages: list[dict], max_messages: int = 10) -> str:
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    lines: list[str] = []
    for msg in recent:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if not content or role not in ("user", "assistant"):
            continue
        if isinstance(content, list):
            text_parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        if len(content) > 800:
            content = content[:800] + "…"
        label = "用户" if role == "user" else "助手"
        lines.append(f"**{label}**: {content}")
    return "\n\n".join(lines)
