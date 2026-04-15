"""MAGMA Query Process: intent-aware retrieval and context synthesis.

Implements the adaptive hierarchical retrieval pipeline:
  Stage 1 — Query analysis & 2-mode intent classification
  Stage 2 — Multi-signal anchor identification (via Rust)
  Stage 3 — Adaptive graph traversal (via Rust)
  Stage 4 — Narrative synthesis via linearization
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any

from fool_code.magma.schemas import WEIGHT_PRESETS, RetrievedContext
from fool_code.magma.store import get_store, is_magma_enabled

logger = logging.getLogger(__name__)

# Context budget aligned with Hermes (~2200 chars for memory + ~1375 for user
# profile).  We target a similar total footprint to avoid bloating the prompt.
MAX_CONTEXT_CHARS = 2000
MAX_NODES_IN_CONTEXT = 8

# ---------------------------------------------------------------------------
# Relevance gate thresholds
# ---------------------------------------------------------------------------
# The gate requires at least one content-relevance signal to proceed:
#   1. FTS5 keyword matches > 0          (text overlap)
#   2. Max cosine similarity >= threshold (semantic proximity — real embeddings only)
#   3. Entity name matches > 0           (structured entity lookup — LIKE '%kw%')
# Time is intentionally NOT used for gating (e.g. "今天天气" has time but is
# not memory-related).  Time narrows scope *after* the gate passes.
MIN_VECTOR_SIMILARITY = 0.35


def retrieve_context(
    query: str,
    workspace_root: Any = None,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> RetrievedContext | None:
    """Main entry: retrieve episodic context relevant to the user's query.

    Returns None if MAGMA is disabled or no relevant context is found.
    """
    t_total = time.perf_counter()

    if not is_magma_enabled():
        return None

    store = get_store()
    if store is None:
        return None

    try:
        stats = json.loads(store.stats())
        if stats.get("node_count", 0) == 0:
            return None
    except Exception:
        return None

    # Detect whether we have real embeddings or hash-only mode.
    # This affects the relevance gate and downstream RRF/traversal parameters.
    hash_mode = _detect_hash_mode(workspace_root)

    # Stage 1: Query analysis (2-mode: temporal_focus / general)
    t0 = time.perf_counter()
    intent, keywords, time_range = _analyze_query(query)
    t_intent = time.perf_counter() - t0

    # Stage 1b: Generate query embedding
    t0 = time.perf_counter()
    from fool_code.magma.extractor import _generate_embedding
    query_emb = _generate_embedding(query, workspace_root)
    t_embed = time.perf_counter() - t0
    if not query_emb:
        logger.info(
            "[MAGMA retriever] aborted: embedding failed "
            "(intent=%.0fms, embed=%.0fms)",
            t_intent * 1000, t_embed * 1000,
        )
        return None

    # ---------------------------------------------------------------------------
    # Relevance gate: skip retrieval if the query has no meaningful connection
    # to any stored memory.  Three independent signals — any one passing is
    # enough.  When real embeddings are configured all three are active; in
    # hash-only mode the vector signal is effectively dead so FTS and entity
    # signals carry the load.
    # ---------------------------------------------------------------------------
    t0 = time.perf_counter()
    try:
        kw_hits = store.keyword_match_count(keywords) if keywords else 0
        ent_hits = store.entity_match_count(keywords) if keywords else 0
        vec_sim = store.max_query_similarity(query_emb)
    except Exception:
        kw_hits, ent_hits, vec_sim = 0, 0, 0.0
    t_gate = time.perf_counter() - t0

    has_keyword_signal = kw_hits > 0
    has_entity_signal = ent_hits > 0
    # In hash mode vec_sim is meaningless noise — skip the check entirely
    # so it cannot accidentally pass the gate with a random high value.
    has_vector_signal = (not hash_mode) and (vec_sim >= MIN_VECTOR_SIMILARITY)

    if not (has_keyword_signal or has_vector_signal or has_entity_signal):
        logger.info(
            "[MAGMA retriever] skipped: no relevant signal "
            "(kw=%d, ent=%d, vec=%.3f, hash_mode=%s, time=%s, gate=%.0fms)",
            kw_hits, ent_hits, vec_sim, hash_mode, bool(time_range),
            t_gate * 1000,
        )
        return None

    # ---------------------------------------------------------------------------
    # Hash-mode parameter adjustments:
    #   - vector_weight=0  → exclude noisy hash vectors from RRF anchor fusion
    #   - lambda2=0        → disable semantic similarity in graph traversal
    # With real embeddings these stay at their normal values.
    # ---------------------------------------------------------------------------
    vector_weight = 0.0 if hash_mode else 1.0
    traverse_lambda2 = 0.0 if hash_mode else 0.5

    # Stage 2: Find anchors
    t0 = time.perf_counter()
    time_start, time_end = time_range if time_range else (None, None)
    try:
        anchors_json = store.find_anchors(
            query_embedding=query_emb,
            keywords=keywords,
            time_start=time_start,
            time_end=time_end,
            top_k=5,
            rrf_k=60,
            vector_weight=vector_weight,
        )
        anchors = json.loads(anchors_json)
    except Exception as exc:
        logger.debug("MAGMA anchor search failed: %s", exc)
        return None
    t_anchor = time.perf_counter() - t0

    if not anchors:
        logger.info(
            "[MAGMA retriever] no anchors found "
            "(intent=%.0fms, embed=%.0fms, anchor=%.0fms)",
            t_intent * 1000, t_embed * 1000, t_anchor * 1000,
        )
        return None

    # Stage 3: Graph traversal (paper Table 5 aligned parameters)
    t0 = time.perf_counter()
    anchor_ids = [a["node_id"] for a in anchors]
    weights = WEIGHT_PRESETS.get(intent, WEIGHT_PRESETS["general"])

    try:
        traversal_json = store.traverse(
            anchor_ids=anchor_ids,
            intent_weights_json=json.dumps(weights),
            query_embedding=query_emb,
            lambda1=1.0,
            lambda2=traverse_lambda2,
            max_depth=4,
            beam_width=10,
            budget=min(MAX_NODES_IN_CONTEXT, 100),
            decay=0.85,
            drop_threshold=0.25,
        )
        results = json.loads(traversal_json)
    except Exception as exc:
        logger.debug("MAGMA traversal failed: %s", exc)
        results = anchors
    t_traverse = time.perf_counter() - t0

    if not results:
        return None

    # Stage 4: Linearize
    t0 = time.perf_counter()
    context_text = _linearize(results, intent, max_chars)
    t_linear = time.perf_counter() - t0

    t_all = time.perf_counter() - t_total
    logger.info(
        "[MAGMA retriever] total=%.0fms | intent=%.0fms embed=%.0fms "
        "anchor=%.0fms traverse=%.0fms linear=%.0fms | "
        "nodes=%d chars=%d hash_mode=%s",
        t_all * 1000,
        t_intent * 1000, t_embed * 1000,
        t_anchor * 1000, t_traverse * 1000, t_linear * 1000,
        len(results), len(context_text), hash_mode,
    )

    if not context_text.strip():
        return None

    token_est = len(context_text) // 3

    return RetrievedContext(
        text=context_text,
        node_count=len(results),
        token_estimate=token_est,
    )


# ---------------------------------------------------------------------------
# Hash-mode detection
# ---------------------------------------------------------------------------

def _detect_hash_mode(workspace_root: Any = None) -> bool:
    """Return True if no real embedding API is configured.

    Checks ``embeddingConfig`` in settings.json for a valid baseUrl + apiKey.
    If neither the dedicated config nor the chat-provider fallback can supply
    real embeddings, the system falls back to deterministic hash vectors —
    which have no semantic meaning.  Callers use this flag to:
      - skip the vector similarity gate (avoids random pass/fail)
      - zero-out vector weight in RRF anchor fusion
      - disable semantic similarity in graph traversal (lambda2 = 0)
    """
    try:
        from fool_code.runtime.config import read_config_root

        root = read_config_root(workspace_root)

        # 1. Dedicated embeddingConfig
        emb_cfg = root.get("embeddingConfig")
        if isinstance(emb_cfg, dict):
            base_url = (emb_cfg.get("baseUrl") or "").strip()
            api_key = (emb_cfg.get("apiKey") or "").strip()
            if base_url and api_key:
                return False  # real embedding API available

        # 2. Chat-provider /embeddings fallback
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
        row = (
            provider_row_by_id(prov_root, provider_id)
            if provider_id
            else default_provider_row(prov_root)
        )
        if row:
            api = row_to_api_dict(row)
            base_url = (
                api.get("baseUrl") or api.get("base_url") or ""
            ).strip()
            api_key = (
                api.get("apiKey") or api.get("api_key") or ""
            ).strip()
            if base_url and api_key:
                return False  # chat provider can serve /embeddings
    except Exception:
        pass

    return True  # no viable embedding source → hash fallback


# ---------------------------------------------------------------------------
# Stage 1: Query analysis (simplified 2-mode)
# ---------------------------------------------------------------------------

def _analyze_query(
    query: str,
) -> tuple[str, list[str], tuple[float, float] | None]:
    """Classify intent, extract keywords and time hints.

    Returns (intent, keywords, time_range_or_none).
    Intent is purely determined by whether jionlp finds a time expression:
      - time found → "temporal_focus"
      - otherwise  → "general"
    """
    time_range = _parse_time_range(query)
    intent = "temporal_focus" if time_range else "general"

    keywords = _extract_keywords_fts_safe(query)

    return intent, keywords, time_range


# Only 2+ char stopwords for splitting.  Single-char Chinese particles (的/了/
# 在/是/...) are NOT used — they'd break compound words like "性能" → "性"+"优化"
# because "能" would match a single-char stop.
_CN_STOPWORDS = (
    "可以|可能|应该|需要|什么|怎么|哪些|哪个|怎样|如何"
    "|为什么|那个|这个|就是|但是|而且|因为|所以|如果|虽然"
    "|或者|还是|比较|已经|正在|曾经|之前|之后|现在|以前"
    "|一下|一些|一个|帮我|请问|告诉|写个|做过|做了"
    "|关于|相关|涉及|包括|通过|进行|使用|方面|部分|情况"
)
_CN_STOP_RE = re.compile(
    r"[\s,，。？！?!、；;：]+"
    + "|"
    + _CN_STOPWORDS,
    re.UNICODE,
)


def _extract_keywords_fts_safe(query: str) -> list[str]:
    """Extract keywords safe for FTS5 MATCH queries.

    Splits on FTS5 syntax chars and 2+ char Chinese stopwords, then further
    splits each token by common single-char particles (的/了/在/是/有) to avoid
    long compound phrases that fail FTS5 AND queries.  Caps at 5 terms.
    """
    cleaned = re.sub(r'[+{}"^*:()\[\]<>!@#$%&/\\|~`]', " ", query)
    tokens = _CN_STOP_RE.split(cleaned)
    # Secondary split by common single-char particles.  These are safe to
    # split on because they almost never form compound words in tech context.
    sub_tokens: list[str] = []
    for t in tokens:
        parts = re.split(r"[的了在是有把被对从到]", t)
        sub_tokens.extend(parts)
    return [t.strip() for t in sub_tokens if len(t.strip()) >= 2][:5]


def _parse_time_range(query: str) -> tuple[float, float] | None:
    """Extract a time range from the query using JioNLP's Chinese NLP time parser.

    Returns (start_unix_ts, end_unix_ts) or None if no time expression found.
    """
    if not query or not query.strip():
        return None

    try:
        import jionlp as jio
    except Exception:
        logger.debug("jionlp not available, time parsing disabled")
        return None

    try:
        result = jio.parse_time(query, time_base=datetime.now())
    except (ValueError, TypeError, Exception):
        return None

    if not result or not isinstance(result, dict):
        return None

    if result.get("type") == "time_delta":
        return None

    time_val = result.get("time")
    if not isinstance(time_val, list) or len(time_val) < 2:
        return None

    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        start_dt = datetime.strptime(time_val[0], fmt)
        end_dt = datetime.strptime(time_val[1], fmt)
        return (start_dt.timestamp(), end_dt.timestamp())
    except (ValueError, TypeError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Stage 4: Linearization (with provenance ref IDs)
# ---------------------------------------------------------------------------

def _linearize(
    nodes: list[dict],
    intent: str,
    max_chars: int,
) -> str:
    """Transform retrieved subgraph into a structured narrative context.

    Applies topological ordering based on intent type and enforces a
    character budget with salience-based pruning.  Each entry includes
    a short [ref:xxxx] provenance tag for traceability.
    """
    if intent == "temporal_focus":
        nodes.sort(key=lambda n: n.get("timestamp", 0))
    else:
        nodes.sort(key=lambda n: n.get("score", 0), reverse=True)

    lines: list[str] = []
    total_chars = 0

    for node in nodes:
        ts = node.get("timestamp", 0)
        time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "?"
        summary = node.get("summary", "")
        content = node.get("content", "")
        nid = node.get("node_id", "")
        ref_tag = f"[ref:{nid[:8]}]" if nid else ""

        score = node.get("score", 0)
        if score > 0.5 or not summary:
            text = content
        else:
            text = summary if summary else content

        entry = f"{ref_tag} [{time_str}] {text}"
        if total_chars + len(entry) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 50:
                entry = entry[:remaining] + "…"
                lines.append(entry)
            break

        lines.append(entry)
        total_chars += len(entry) + 1

    return "\n".join(lines)
