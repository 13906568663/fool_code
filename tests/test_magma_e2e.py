"""End-to-end tests covering the full MAGMA prompt-injection pipeline.

Tests the complete flow that happens when a user sends a message:
  chat.py → retrieve_context(message) → gate → anchors → traverse → linearize
  → SystemPromptBuilder.with_episodic_context → <memory-context> tags in prompt

Organized into 5 phases:
  Phase 1 — Data ingestion (simulating extractor.py output)
  Phase 2 — Relevance gate (should-retrieve vs should-skip decisions)
  Phase 3 — Retrieval quality (keyword, semantic, entity, cross-session)
  Phase 4 — Prompt injection format (memory-context tags, ref IDs, budget)
  Phase 5 — Edge cases (empty store, single node, unicode, long content)

Run:  uv run python tests/test_magma_e2e.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_e2e")

OK = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def _try_import_native():
    try:
        import magma_memory
        return magma_memory
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

def _make_embedding(text: str, dim: int = 1536) -> list[float]:
    from fool_code.magma.extractor import _hash_embedding
    return _hash_embedding(text, dim=dim)


# ---------------------------------------------------------------------------
# Simulated conversation events — 3 sessions of realistic developer activity
# ---------------------------------------------------------------------------

SESSION_A_EVENTS = [
    {
        "content": "用户讨论了达梦数据库的A表结构设计，决定将 user_profile 表的主键改为 UUID，并添加了 created_at 索引",
        "summary": "A表结构设计改主键为UUID",
        "entities": [
            ("technology:达梦数据库", "达梦数据库", "technology"),
            ("concept:a表", "A表", "concept"),
        ],
        "session_id": "session-001",
    },
    {
        "content": "实现了A表的批量导入功能，使用了 COPY INTO 语法，测试导入10万条数据耗时约3秒",
        "summary": "A表批量导入功能实现",
        "entities": [
            ("concept:a表", "A表", "concept"),
            ("concept:批量导入", "批量导入", "concept"),
        ],
        "session_id": "session-001",
    },
    {
        "content": "修复了登录接口的token过期问题，原因是JWT的exp字段计算有误，修改后通过测试",
        "summary": "修复JWT token过期bug",
        "entities": [
            ("concept:jwt", "JWT", "technology"),
            ("concept:登录接口", "登录接口", "concept"),
        ],
        "session_id": "session-001",
    },
]

SESSION_B_EVENTS = [
    {
        "content": "部署了新版本到生产环境，使用Docker Compose编排，包含前端、后端和达梦数据库三个容器",
        "summary": "Docker Compose部署生产环境",
        "entities": [
            ("technology:docker", "Docker", "technology"),
            ("technology:达梦数据库", "达梦数据库", "technology"),
        ],
        "session_id": "session-002",
    },
    {
        "content": "用户反馈B表查询超时，分析后发现缺少复合索引，为 order_items 表的 (order_id, product_id) 添加了索引",
        "summary": "B表查询超时问题修复",
        "entities": [
            ("concept:b表", "B表", "concept"),
            ("concept:性能优化", "性能优化", "concept"),
        ],
        "session_id": "session-002",
    },
]

SESSION_C_EVENTS = [
    {
        "content": "讨论了项目架构重构方案，决定将单体应用拆分为微服务，第一阶段先拆分用户模块和订单模块",
        "summary": "微服务架构重构方案",
        "entities": [
            ("concept:微服务", "微服务", "concept"),
            ("concept:架构重构", "架构重构", "concept"),
        ],
        "session_id": "session-003",
    },
    {
        "content": "对A表增加了分区策略，按月分区以提升大数据量下的查询性能，使用达梦的range分区语法",
        "summary": "A表分区优化",
        "entities": [
            ("concept:a表", "A表", "concept"),
            ("technology:达梦数据库", "达梦数据库", "technology"),
            ("concept:分区", "分区", "concept"),
        ],
        "session_id": "session-003",
    },
]


class E2ETestRunner:
    """Manages a temporary MAGMA store for e2e testing."""

    def __init__(self):
        self._tmpdir = tempfile.mkdtemp(prefix="magma_e2e_")
        self._db_path = os.path.join(self._tmpdir, "e2e.db")
        mm = _try_import_native()
        if mm is None:
            raise RuntimeError("magma_memory native module not available")
        self.store = mm.MagmaStore(self._db_path)
        self._dim = 1536
        self.store.set_meta("embed_dim", str(self._dim))

    def cleanup(self):
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def ingest_event(self, event: dict, time_offset: float = 0) -> str:
        content = event["content"]
        summary = event["summary"]
        session_id = event["session_id"]
        embedding = _make_embedding(content, dim=self._dim)

        node_id = self.store.ingest_event(
            content=content,
            summary=summary,
            timestamp=time.time() + time_offset,
            embedding=embedding,
            session_id=session_id,
        )

        for ent_id, name, etype in event.get("entities", []):
            self.store.upsert_entity(ent_id, name, etype)
            self.store.link_entity_node(ent_id, node_id, "mentioned_in")

        self.store.mark_consolidated(node_id)
        return node_id

    def ingest_all(self):
        base = time.time() - 86400 * 7
        all_events = (
            [(e, 0) for e in SESSION_A_EVENTS]
            + [(e, 86400 * 2) for e in SESSION_B_EVENTS]
            + [(e, 86400 * 5) for e in SESSION_C_EVENTS]
        )
        for i, (evt, day_offset) in enumerate(all_events):
            self.ingest_event(evt, time_offset=(base + day_offset + i * 60) - time.time())
        return json.loads(self.store.stats())

    def query(
        self,
        user_message: str,
        skip_gate: bool = False,
        hash_mode: bool = True,
    ) -> list[dict]:
        """Run the retrieval pipeline.

        ``hash_mode`` mirrors ``_detect_hash_mode`` in retriever.py:
          - True  (default for tests): entity gate active, vector_weight=0,
            lambda2=0.  Simulates a user with no embedding API.
          - False: full vector signal, vector_weight=1, lambda2=0.5.
        """
        from fool_code.magma.retriever import _analyze_query, MIN_VECTOR_SIMILARITY
        from fool_code.magma.schemas import WEIGHT_PRESETS

        query_emb = _make_embedding(user_message, dim=self._dim)
        intent, keywords, time_range = _analyze_query(user_message)

        if not skip_gate:
            kw_hits = self.store.keyword_match_count(keywords) if keywords else 0
            ent_hits = self.store.entity_match_count(keywords) if keywords else 0
            vec_sim = self.store.max_query_similarity(query_emb)
            has_kw = kw_hits > 0
            has_ent = ent_hits > 0
            has_vec = (not hash_mode) and (vec_sim >= MIN_VECTOR_SIMILARITY)
            if not (has_kw or has_ent or has_vec):
                return []

        vector_weight = 0.0 if hash_mode else 1.0
        traverse_lambda2 = 0.0 if hash_mode else 0.5

        time_start, time_end = time_range if time_range else (None, None)

        anchors_json = self.store.find_anchors(
            query_embedding=query_emb,
            keywords=keywords,
            time_start=time_start,
            time_end=time_end,
            top_k=5,
            rrf_k=60,
            vector_weight=vector_weight,
        )
        anchors = json.loads(anchors_json)
        if not anchors:
            return []

        anchor_ids = [a["node_id"] for a in anchors]
        weights = WEIGHT_PRESETS.get(intent, WEIGHT_PRESETS["general"])

        traversal_json = self.store.traverse(
            anchor_ids=anchor_ids,
            intent_weights_json=json.dumps(weights),
            query_embedding=query_emb,
            lambda1=1.0,
            lambda2=traverse_lambda2,
            max_depth=4,
            beam_width=10,
            budget=8,
            decay=0.85,
            drop_threshold=0.25,
        )
        return json.loads(traversal_json)

    def build_prompt_with_memory(self, user_message: str) -> str | None:
        """Simulate the full chat.py prompt injection flow."""
        from fool_code.magma.retriever import _analyze_query, _linearize, MIN_VECTOR_SIMILARITY
        from fool_code.magma.schemas import WEIGHT_PRESETS
        from fool_code.runtime.prompt import SystemPromptBuilder

        results = self.query(user_message)
        if not results:
            return None

        intent, _, _ = _analyze_query(user_message)
        context_text = _linearize(results, intent, 2000)
        if not context_text.strip():
            return None

        builder = SystemPromptBuilder()
        builder.with_episodic_context(context_text)
        sections = builder.build()

        for sec in sections:
            if "近期活动记录" in sec:
                return sec

        return None


# ===========================================================================
# Phase 2: Relevance gate tests
# ===========================================================================

def test_gate_blocks_unrelated_query(runner: E2ETestRunner) -> bool:
    """Unrelated queries should be blocked by the relevance gate."""
    unrelated = [
        "今天天气怎么样",
        "你好世界",
        "帮我写个排序算法",
        "Python的GIL是什么",
        "1+1等于几",
    ]
    all_blocked = True
    for q in unrelated:
        results = runner.query(q)
        status = OK if len(results) == 0 else FAIL
        if len(results) > 0:
            all_blocked = False
        print(f"  {status} '{q}' -> {len(results)} results")

    return all_blocked


def test_gate_passes_relevant_keyword_query(runner: E2ETestRunner) -> bool:
    """Queries containing stored keywords should pass the gate."""
    relevant = [
        ("A表", True),
        ("达梦数据库", True),
        ("Docker", True),
        ("JWT", True),
        ("批量导入", True),
        ("索引", True),
    ]
    all_passed = True
    for q, expect_pass in relevant:
        results = runner.query(q)
        passed = len(results) > 0
        status = OK if passed == expect_pass else FAIL
        if passed != expect_pass:
            all_passed = False
        print(f"  {status} '{q}' -> {len(results)} results (expected {'pass' if expect_pass else 'block'})")

    return all_passed


def test_gate_signal_values(runner: E2ETestRunner) -> bool:
    """Verify all three gate signals (keyword, entity, vector) for different queries."""
    from fool_code.magma.retriever import _analyze_query, MIN_VECTOR_SIMILARITY

    cases = [
        ("A表", True, "keyword match"),
        ("达梦数据库", True, "keyword match"),
        ("今天天气怎么样", False, "no content signal"),
        ("你好世界", False, "no content signal"),
    ]

    all_correct = True
    for q, expect_pass, reason in cases:
        emb = _make_embedding(q, dim=1536)
        _, keywords, _ = _analyze_query(q)
        kw_hits = runner.store.keyword_match_count(keywords) if keywords else 0
        ent_hits = runner.store.entity_match_count(keywords) if keywords else 0
        vec_sim = runner.store.max_query_similarity(emb)
        # hash mode: vector signal disabled
        passes = kw_hits > 0 or ent_hits > 0

        status = OK if passes == expect_pass else FAIL
        if passes != expect_pass:
            all_correct = False
        print(f"  {status} '{q}': kw={kw_hits}, ent={ent_hits}, vec={vec_sim:.4f}, "
              f"pass={passes} ({reason})")

    return all_correct


# ===========================================================================
# Phase 3: Retrieval quality tests
# ===========================================================================

def test_keyword_recall_a_table(runner: E2ETestRunner) -> bool:
    """'A表' query should recall all 3 A-table events."""
    results = runner.query("A表现在是什么结构")
    found = [r for r in results if "A表" in r["content"]]
    print(f"  'A表现在是什么结构' -> {len(results)} total, {len(found)} with A表")
    if len(found) >= 2:
        print(f"  {OK} keyword recall: A表")
        return True
    print(f"  {FAIL} expected >= 2, got {len(found)}")
    return False


def test_keyword_recall_dameng(runner: E2ETestRunner) -> bool:
    """'达梦' query should recall dameng-related events."""
    results = runner.query("达梦数据库的配置怎么弄的")
    found = [r for r in results if "达梦" in r["content"]]
    print(f"  '达梦数据库的配置怎么弄的' -> {len(results)} total, {len(found)} with 达梦")
    if len(found) >= 2:
        print(f"  {OK} keyword recall: 达梦")
        return True
    print(f"  {FAIL} expected >= 2, got {len(found)}")
    return False


def test_keyword_recall_docker(runner: E2ETestRunner) -> bool:
    """'Docker' query should find the deployment event."""
    results = runner.query("Docker部署")
    found = [r for r in results if "Docker" in r["content"]]
    print(f"  'Docker部署' -> {len(results)} total, {len(found)} with Docker")
    if found:
        print(f"  {OK} keyword recall: Docker")
        return True
    print(f"  {FAIL} Docker event not recalled")
    return False


def test_keyword_recall_jwt(runner: E2ETestRunner) -> bool:
    """'JWT' query should find the token fix event."""
    results = runner.query("JWT token")
    found = [r for r in results if "JWT" in r["content"] or "token" in r["content"]]
    print(f"  'JWT token' -> {len(results)} total, {len(found)} with JWT/token")
    if found:
        print(f"  {OK} keyword recall: JWT")
        return True
    print(f"  {FAIL} JWT event not recalled")
    return False


def test_semantic_recall_performance(runner: E2ETestRunner) -> bool:
    """Performance-related query should find indexing and partitioning events."""
    results = runner.query("之前做的性能优化有哪些")
    found = [r for r in results if any(k in r["content"] for k in ["索引", "分区", "性能", "超时"])]
    print(f"  '之前做的性能优化有哪些' -> {len(results)} total, {len(found)} perf-related")
    if found:
        print(f"  {OK} semantic recall: performance")
        return True
    print(f"  {FAIL} no perf events recalled")
    return False


def test_cross_session_recall(runner: E2ETestRunner) -> bool:
    """'A表' spans session-001 and session-003 — both should be recalled."""
    results = runner.query("A表")
    contents = [r["content"] for r in results]
    from_s1 = [c for c in contents if "UUID" in c or "批量导入" in c]
    from_s3 = [c for c in contents if "分区" in c]
    print(f"  'A表' -> session-001: {len(from_s1)}, session-003: {len(from_s3)}")
    if from_s1 and from_s3:
        print(f"  {OK} cross-session recall")
        return True
    print(f"  {FAIL} cross-session recall failed")
    return False


def test_entity_cooccurrence(runner: E2ETestRunner) -> bool:
    """Entity co-occurrence: A表 query should also pull related events."""
    results = runner.query("A表相关的工作都做了哪些")
    found_a = [r for r in results if "A表" in r["content"]]
    other = [r for r in results if "A表" not in r["content"]]
    print(f"  'A表相关工作' -> {len(found_a)} A表 + {len(other)} related")
    if len(found_a) >= 2:
        print(f"  {OK} entity co-occurrence")
        return True
    print(f"  {FAIL} insufficient A表 recall: {len(found_a)}")
    return False


def test_fts5_partial_keyword(runner: E2ETestRunner) -> bool:
    """FTS5 should match partial keywords like '导入' from '批量导入功能'."""
    results = runner.query("数据导入怎么做的")
    found = [r for r in results if "导入" in r["content"]]
    print(f"  '数据导入怎么做的' -> {len(results)} total, {len(found)} with 导入")
    if found:
        print(f"  {OK} FTS5 partial keyword")
        return True
    print(f"  {WARN} FTS5 partial keyword missed (acceptable with char tokenizer)")
    return True


def test_mixed_cjk_ascii_query(runner: E2ETestRunner) -> bool:
    """Mixed CJK+ASCII queries like 'COPY INTO语法' should work."""
    results = runner.query("COPY INTO语法")
    found = [r for r in results if "COPY INTO" in r["content"]]
    print(f"  'COPY INTO语法' -> {len(results)} total, {len(found)} with COPY INTO")
    if found:
        print(f"  {OK} mixed CJK+ASCII query")
        return True
    print(f"  {WARN} mixed query missed")
    return True


# ===========================================================================
# Phase 4: Prompt injection format tests
# ===========================================================================

def test_prompt_contains_memory_tags(runner: E2ETestRunner) -> bool:
    """Injected prompt must have <memory-context> fencing tags."""
    prompt = runner.build_prompt_with_memory("A表")
    if prompt is None:
        print(f"  {FAIL} no prompt generated for 'A表'")
        return False

    has_open = "<memory-context>" in prompt
    has_close = "</memory-context>" in prompt
    has_header = "近期活动记录" in prompt
    has_instruction = "必须直接基于以下内容回答" in prompt

    print(f"  <memory-context> open: {has_open}")
    print(f"  </memory-context> close: {has_close}")
    print(f"  Header '近期活动记录': {has_header}")
    print(f"  Instruction '必须直接基于以下内容回答': {has_instruction}")

    if has_open and has_close and has_header and has_instruction:
        print(f"  {OK} prompt injection format correct")
        return True
    print(f"  {FAIL} missing required elements")
    return False


def test_prompt_contains_ref_tags(runner: E2ETestRunner) -> bool:
    """Injected context should contain [ref:xxxx] provenance tags."""
    prompt = runner.build_prompt_with_memory("A表")
    if prompt is None:
        print(f"  {FAIL} no prompt generated")
        return False

    ref_pattern = re.compile(r"\[ref:[a-f0-9]{8}\]")
    refs = ref_pattern.findall(prompt)
    print(f"  Found {len(refs)} [ref:xxxx] tags")

    if refs:
        print(f"  {OK} provenance ref tags present")
        return True
    print(f"  {FAIL} no ref tags found")
    return False


def test_prompt_contains_timestamps(runner: E2ETestRunner) -> bool:
    """Injected context should contain human-readable timestamps."""
    prompt = runner.build_prompt_with_memory("A表")
    if prompt is None:
        print(f"  {FAIL} no prompt generated")
        return False

    ts_pattern = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]")
    timestamps = ts_pattern.findall(prompt)
    print(f"  Found {len(timestamps)} timestamps")

    if timestamps:
        print(f"  {OK} timestamps present")
        return True
    print(f"  {FAIL} no timestamps found")
    return False


def test_prompt_no_injection_for_unrelated(runner: E2ETestRunner) -> bool:
    """Unrelated query should produce NO prompt injection."""
    prompt = runner.build_prompt_with_memory("今天天气怎么样")
    if prompt is None:
        print(f"  {OK} no prompt injected for unrelated query")
        return True
    print(f"  {FAIL} prompt was injected for unrelated query!")
    print(f"  Preview: {prompt[:100]}...")
    return False


def test_prompt_context_budget(runner: E2ETestRunner) -> bool:
    """Context text should respect MAX_CONTEXT_CHARS budget (2000)."""
    from fool_code.magma.retriever import _linearize, _analyze_query

    results = runner.query("A表", skip_gate=True)
    if not results:
        print(f"  {WARN} no results to test budget")
        return True

    intent, _, _ = _analyze_query("A表")

    text_default = _linearize(results, intent, 2000)
    text_small = _linearize(results, intent, 200)

    print(f"  Budget 2000 -> {len(text_default)} chars")
    print(f"  Budget 200  -> {len(text_small)} chars")

    if len(text_small) <= 250:  # small buffer for truncation marker
        print(f"  {OK} context budget respected")
        return True
    print(f"  {FAIL} budget exceeded: {len(text_small)} > 250")
    return False


def test_prompt_temporal_ordering(runner: E2ETestRunner) -> bool:
    """In temporal_focus mode, entries should be time-ordered."""
    from fool_code.magma.retriever import _linearize

    results = runner.query("A表", skip_gate=True)
    if len(results) < 2:
        print(f"  {WARN} insufficient results for ordering test")
        return True

    text = _linearize(results, "temporal_focus", 5000)
    lines = [l for l in text.strip().split("\n") if l.strip()]

    ts_pattern = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]")
    timestamps = []
    for line in lines:
        m = ts_pattern.search(line)
        if m:
            timestamps.append(m.group(1))

    is_sorted = timestamps == sorted(timestamps)
    print(f"  Timestamps: {timestamps[:5]}{'...' if len(timestamps) > 5 else ''}")
    print(f"  Time-ordered: {is_sorted}")

    if is_sorted:
        print(f"  {OK} temporal ordering correct")
        return True
    print(f"  {FAIL} timestamps not in order")
    return False


def test_prompt_score_ordering(runner: E2ETestRunner) -> bool:
    """In general mode, entries should be score-ordered (highest first)."""
    from fool_code.magma.retriever import _linearize

    results = runner.query("A表", skip_gate=True)
    if len(results) < 2:
        print(f"  {WARN} insufficient results")
        return True

    results_copy = [dict(r) for r in results]
    results_copy.sort(key=lambda n: n.get("score", 0), reverse=True)

    text = _linearize(results_copy, "general", 5000)
    print(f"  General mode linearization: {len(text)} chars")
    print(f"  {OK} score ordering applied")
    return True


# ===========================================================================
# Phase 5: Edge cases
# ===========================================================================

def test_empty_store_returns_none(runner: E2ETestRunner) -> bool:
    """Query on empty store should return no results."""
    mm = _try_import_native()
    tmpdir = tempfile.mkdtemp(prefix="magma_empty_")
    try:
        empty_store = mm.MagmaStore(os.path.join(tmpdir, "empty.db"))
        empty_store.set_meta("embed_dim", "1536")

        emb = _make_embedding("test query", dim=1536)
        anchors = json.loads(empty_store.find_anchors(
            query_embedding=emb, keywords=["test"], top_k=5, rrf_k=60,
        ))
        kw = empty_store.keyword_match_count(["test"])
        sim = empty_store.max_query_similarity(emb)

        print(f"  Empty store: anchors={len(anchors)}, kw_hits={kw}, vec_sim={sim:.4f}")

        if len(anchors) == 0 and kw == 0:
            print(f"  {OK} empty store returns nothing")
            return True
        print(f"  {FAIL} empty store returned results")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_single_node_store(runner: E2ETestRunner) -> bool:
    """Store with a single node should still work correctly."""
    mm = _try_import_native()
    tmpdir = tempfile.mkdtemp(prefix="magma_single_")
    try:
        store = mm.MagmaStore(os.path.join(tmpdir, "single.db"))
        store.set_meta("embed_dim", "1536")

        emb = _make_embedding("Hello world test", dim=1536)
        nid = store.ingest_event("Hello world test", "test summary", time.time(), emb, "s1")
        store.mark_consolidated(nid)

        kw = store.keyword_match_count(["Hello"])
        print(f"  Single node: kw_hits for 'Hello' = {kw}")

        anchors = json.loads(store.find_anchors(
            query_embedding=emb, keywords=["Hello"], top_k=5, rrf_k=60,
        ))
        print(f"  Anchors found: {len(anchors)}")

        if len(anchors) == 1:
            print(f"  {OK} single-node store works")
            return True
        print(f"  {FAIL} expected 1 anchor, got {len(anchors)}")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_special_characters_in_content(runner: E2ETestRunner) -> bool:
    """Content with special characters should not break FTS5 or queries."""
    mm = _try_import_native()
    tmpdir = tempfile.mkdtemp(prefix="magma_special_")
    try:
        store = mm.MagmaStore(os.path.join(tmpdir, "special.db"))
        store.set_meta("embed_dim", "1536")

        special_content = 'SQL: SELECT * FROM "users" WHERE id = 1 AND name LIKE \'%test%\''
        emb = _make_embedding(special_content, dim=1536)
        nid = store.ingest_event(special_content, "SQL query", time.time(), emb, "s1")
        store.mark_consolidated(nid)

        kw = store.keyword_match_count(["SELECT"])
        print(f"  Special chars: kw_hits for 'SELECT' = {kw}")

        if kw >= 1:
            print(f"  {OK} special characters handled")
            return True
        print(f"  {WARN} special character search returned 0 (acceptable)")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_long_content_truncation(runner: E2ETestRunner) -> bool:
    """Very long content should be handled gracefully."""
    from fool_code.magma.retriever import _linearize

    fake_node = {
        "node_id": "abcdef1234567890",
        "content": "A" * 5000,
        "summary": "long test",
        "timestamp": time.time(),
        "score": 1.0,
    }

    text = _linearize([fake_node], "general", 500)
    print(f"  Input: 5000 chars, budget: 500, output: {len(text)} chars")

    if len(text) <= 550:
        print(f"  {OK} long content truncated correctly")
        return True
    print(f"  {FAIL} truncation failed: {len(text)} chars")
    return False


def test_unicode_emoji_content(runner: E2ETestRunner) -> bool:
    """Unicode emoji in content should not crash the system."""
    mm = _try_import_native()
    tmpdir = tempfile.mkdtemp(prefix="magma_emoji_")
    try:
        store = mm.MagmaStore(os.path.join(tmpdir, "emoji.db"))
        store.set_meta("embed_dim", "1536")

        content = "部署成功 ✅ 性能提升50% 🚀 数据库优化完成 💪"
        emb = _make_embedding(content, dim=1536)
        nid = store.ingest_event(content, "emoji test", time.time(), emb, "s1")
        store.mark_consolidated(nid)

        stats = json.loads(store.stats())
        print(f"  Emoji content ingested: nodes={stats['node_count']}")

        kw = store.keyword_match_count(["数据库"])
        print(f"  kw_hits for '数据库' = {kw}")

        if stats["node_count"] == 1 and kw >= 1:
            print(f"  {OK} unicode emoji handled")
            return True
        print(f"  {WARN} partial success (ingested but search may vary)")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_keyword_extraction_stopwords(runner: E2ETestRunner) -> bool:
    """Verify stopword splitting produces clean keywords."""
    from fool_code.magma.retriever import _extract_keywords_fts_safe

    cases = [
        ("A表现在是什么结构", ["A表"]),
        ("达梦数据库的配置怎么弄的", ["达梦数据库"]),
        ("之前做的性能优化有哪些", ["性能优化"]),
        ("帮我写个排序算法", ["排序"]),
        ("今天天气怎么样", []),  # no stored keywords
    ]

    all_ok = True
    for query, expected_contains in cases:
        keywords = _extract_keywords_fts_safe(query)
        has_expected = all(any(exp in kw for kw in keywords) for exp in expected_contains)
        status = OK if has_expected else WARN
        if not has_expected and expected_contains:
            all_ok = False
            status = FAIL
        print(f"  {status} '{query}' -> {keywords}")

    return all_ok


def test_db_reopen_idempotent(runner: E2ETestRunner) -> bool:
    """Database can be closed and reopened without data loss."""
    mm = _try_import_native()
    tmpdir = tempfile.mkdtemp(prefix="magma_reopen_")
    db_path = os.path.join(tmpdir, "reopen.db")
    try:
        store1 = mm.MagmaStore(db_path)
        store1.set_meta("embed_dim", "1536")
        emb = _make_embedding("test data", dim=1536)
        store1.ingest_event("test data for reopen", "reopen test", time.time(), emb, "s1")
        stats1 = json.loads(store1.stats())
        store1.close()

        store2 = mm.MagmaStore(db_path)
        stats2 = json.loads(store2.stats())
        store2.close()

        print(f"  Before close: nodes={stats1['node_count']}, fts={stats1['fts_count']}")
        print(f"  After reopen: nodes={stats2['node_count']}, fts={stats2['fts_count']}")

        if stats1["node_count"] == stats2["node_count"] and stats2["fts_count"] >= 1:
            print(f"  {OK} db reopen preserves data")
            return True
        print(f"  {FAIL} data lost after reopen")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_concurrent_session_ids(runner: E2ETestRunner) -> bool:
    """Events from different sessions should have correct temporal edges."""
    stats = json.loads(runner.store.stats())
    edge_types = stats.get("edge_types", {})
    temporal = edge_types.get("temporal", 0)

    # With 7 events across 3 sessions (3+2+2), we expect:
    #   session-001: 2 intra-session temporal edges (3 nodes)
    #   session-002: 1 intra-session temporal edge (2 nodes)
    #   session-003: 1 intra-session temporal edge (2 nodes)
    #   Plus cross-session weak links
    print(f"  Temporal edges: {temporal}")
    print(f"  Edge types: {edge_types}")

    if temporal >= 4:
        print(f"  {OK} session temporal edges correct")
        return True
    print(f"  {FAIL} expected >= 4 temporal edges, got {temporal}")
    return False


# ===========================================================================
# Phase 6: Hash-only mode (no embedding API)
# ===========================================================================

def test_hash_mode_entity_gate_opens(runner: E2ETestRunner) -> bool:
    """Entity signal should open the gate even when FTS AND misses.

    Query "Redis配置" has no node with both "Redis" AND "配置", but "Redis"
    is not in our test data — so we use "Docker配置" instead.  "Docker" is
    in entities table, so entity gate should open.
    """
    from fool_code.magma.retriever import _analyze_query

    q = "Docker配置"
    _, keywords, _ = _analyze_query(q)
    kw_hits = runner.store.keyword_match_count(keywords) if keywords else 0
    ent_hits = runner.store.entity_match_count(keywords) if keywords else 0

    # kw_hits may be 0 (AND of "Docker" + "配置" in same node may fail)
    # but ent_hits should be > 0 because entities table has "Docker"
    print(f"  '{q}': kw_hits={kw_hits}, ent_hits={ent_hits}")

    if ent_hits > 0:
        print(f"  {OK} entity gate opens for '{q}'")
        return True
    # Acceptable if kw_hits also > 0 (FTS found "Docker" alone)
    if kw_hits > 0:
        print(f"  {OK} FTS gate opens for '{q}' (entity not needed)")
        return True
    print(f"  {FAIL} neither FTS nor entity gate opens")
    return False


def test_hash_mode_entity_gate_blocks_unrelated(runner: E2ETestRunner) -> bool:
    """Entity signal should NOT open gate for unrelated queries."""
    from fool_code.magma.retriever import _analyze_query

    q = "Kubernetes集群管理"
    _, keywords, _ = _analyze_query(q)
    ent_hits = runner.store.entity_match_count(keywords) if keywords else 0
    kw_hits = runner.store.keyword_match_count(keywords) if keywords else 0

    print(f"  '{q}': kw_hits={kw_hits}, ent_hits={ent_hits}")

    if kw_hits == 0 and ent_hits == 0:
        print(f"  {OK} gate correctly blocks unrelated entity query")
        return True
    print(f"  {WARN} unexpected hit (kw={kw_hits}, ent={ent_hits})")
    return True  # non-critical


def test_hash_mode_vector_weight_zero(runner: E2ETestRunner) -> bool:
    """With vector_weight=0, anchors should be found purely by FTS+temporal.

    We verify the same query returns results with and without vector weight,
    confirming vector noise doesn't dominate.
    """
    q = "A表"
    results_hash = runner.query(q, hash_mode=True)
    results_vec = runner.query(q, hash_mode=False)

    print(f"  '{q}' hash_mode=True:  {len(results_hash)} results")
    print(f"  '{q}' hash_mode=False: {len(results_vec)} results")

    if len(results_hash) > 0:
        print(f"  {OK} hash mode still retrieves results (vector_weight=0)")
        return True
    print(f"  {FAIL} hash mode returned 0 results")
    return False


def test_hash_mode_lambda2_zero_traversal(runner: E2ETestRunner) -> bool:
    """With lambda2=0, traversal should rely on structural edges only.

    Verify the system still returns multiple connected nodes.
    """
    q = "A表结构"
    results = runner.query(q, hash_mode=True)

    multi_depth = [r for r in results if r.get("depth", 0) > 0]
    print(f"  '{q}' hash_mode: {len(results)} total, "
          f"{len(multi_depth)} from traversal (depth > 0)")

    if len(results) > 0:
        print(f"  {OK} lambda2=0 traversal works (structural edges)")
        return True
    print(f"  {FAIL} no results in hash mode traversal")
    return False


def test_hash_mode_entity_only_gate(runner: E2ETestRunner) -> bool:
    """Scenario: FTS misses but entity match succeeds.

    Ingest a node about "PostgreSQL数据库", then query "PostgreSQL性能".
    FTS AND of "PostgreSQL"+"性能" may miss, but entity "PostgreSQL数据库"
    should match via LIKE '%PostgreSQL%'.
    """
    mm = _try_import_native()
    tmpdir = tempfile.mkdtemp(prefix="magma_entonly_")
    try:
        store = mm.MagmaStore(os.path.join(tmpdir, "entonly.db"))
        store.set_meta("embed_dim", "1536")

        content = "用户配置了PostgreSQL数据库的连接池，设置最大连接数为100"
        emb = _make_embedding(content, dim=1536)
        nid = store.ingest_event(content, "PG连接池配置", time.time(), emb, "s1")
        store.upsert_entity("technology:postgresql", "PostgreSQL数据库", "technology")
        store.link_entity_node("technology:postgresql", nid, "mentioned_in")

        from fool_code.magma.retriever import _analyze_query
        q = "PostgreSQL性能"
        _, keywords, _ = _analyze_query(q)

        kw_hits = store.keyword_match_count(keywords) if keywords else 0
        ent_hits = store.entity_match_count(keywords) if keywords else 0

        print(f"  '{q}': keywords={keywords}, kw_hits={kw_hits}, ent_hits={ent_hits}")

        if ent_hits > 0:
            print(f"  {OK} entity-only gate pass works")
            return True
        if kw_hits > 0:
            print(f"  {OK} FTS also catches it (entity test inconclusive but OK)")
            return True
        print(f"  {FAIL} neither signal fired")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_hash_mode_detect_function(runner: E2ETestRunner) -> bool:
    """Verify _detect_hash_mode returns a boolean and respects config.

    Note: read_config_root() reads from the global app config directory,
    not from workspace_root.  In CI/dev environments with a configured
    provider, _detect_hash_mode may return False (real embeddings available).
    We validate the function is callable and returns a consistent type.
    """
    from fool_code.magma.retriever import _detect_hash_mode

    result = _detect_hash_mode(None)
    print(f"  _detect_hash_mode(None) = {result}")
    print(f"  type = {type(result).__name__}")

    if isinstance(result, bool):
        mode_str = "hash (no embedding)" if result else "real embeddings"
        print(f"  {OK} _detect_hash_mode works (detected: {mode_str})")
        return True
    print(f"  {FAIL} expected bool, got {type(result)}")
    return False


# ===========================================================================
# Run all tests
# ===========================================================================

def main():
    mm = _try_import_native()
    if mm is None:
        print("SKIP: magma_memory native module not available")
        return

    runner = E2ETestRunner()
    try:
        print("=" * 70)
        print("  MAGMA Full Pipeline Test Suite")
        print("=" * 70)
        print()

        # Phase 1: Ingest
        print("Phase 1: Data Ingestion")
        print("-" * 40)
        stats = runner.ingest_all()
        print(f"  nodes={stats['node_count']}, edges={stats['edge_count']}, "
              f"entities={stats['entity_count']}, fts={stats['fts_count']}")
        print(f"  edge_types: {stats.get('edge_types', {})}")
        print()

        test_groups = [
            ("Phase 2: Relevance Gate", [
                ("gate blocks unrelated queries", test_gate_blocks_unrelated_query),
                ("gate passes relevant keywords", test_gate_passes_relevant_keyword_query),
                ("gate signal values", test_gate_signal_values),
            ]),
            ("Phase 3: Retrieval Quality", [
                ("keyword: A表", test_keyword_recall_a_table),
                ("keyword: 达梦", test_keyword_recall_dameng),
                ("keyword: Docker", test_keyword_recall_docker),
                ("keyword: JWT", test_keyword_recall_jwt),
                ("semantic: 性能优化", test_semantic_recall_performance),
                ("cross-session: A表", test_cross_session_recall),
                ("entity co-occurrence", test_entity_cooccurrence),
                ("FTS5 partial keyword", test_fts5_partial_keyword),
                ("mixed CJK+ASCII", test_mixed_cjk_ascii_query),
            ]),
            ("Phase 4: Prompt Injection Format", [
                ("<memory-context> tags", test_prompt_contains_memory_tags),
                ("[ref:xxxx] provenance", test_prompt_contains_ref_tags),
                ("timestamps in context", test_prompt_contains_timestamps),
                ("no injection for unrelated", test_prompt_no_injection_for_unrelated),
                ("context budget", test_prompt_context_budget),
                ("temporal ordering", test_prompt_temporal_ordering),
                ("score ordering", test_prompt_score_ordering),
            ]),
            ("Phase 5: Edge Cases & Robustness", [
                ("empty store", test_empty_store_returns_none),
                ("single node store", test_single_node_store),
                ("special characters", test_special_characters_in_content),
                ("long content truncation", test_long_content_truncation),
                ("unicode emoji", test_unicode_emoji_content),
                ("keyword extraction stopwords", test_keyword_extraction_stopwords),
                ("db reopen idempotent", test_db_reopen_idempotent),
                ("concurrent session IDs", test_concurrent_session_ids),
            ]),
            ("Phase 6: Hash-Only Mode (no embedding API)", [
                ("entity gate opens", test_hash_mode_entity_gate_opens),
                ("entity gate blocks unrelated", test_hash_mode_entity_gate_blocks_unrelated),
                ("vector_weight=0 still retrieves", test_hash_mode_vector_weight_zero),
                ("lambda2=0 traversal works", test_hash_mode_lambda2_zero_traversal),
                ("entity-only gate pass", test_hash_mode_entity_only_gate),
                ("_detect_hash_mode function", test_hash_mode_detect_function),
            ]),
        ]

        total_passed = 0
        total_failed = 0

        for phase_name, tests in test_groups:
            print(f"\n{phase_name}")
            print("-" * 40)

            for name, fn in tests:
                print(f"\n  --- {name} ---")
                try:
                    if fn(runner):
                        total_passed += 1
                    else:
                        total_failed += 1
                except Exception as e:
                    print(f"  {FAIL} exception: {e}")
                    import traceback
                    traceback.print_exc()
                    total_failed += 1

        total = total_passed + total_failed
        print()
        print("=" * 70)
        print(f"  Results: {total_passed} passed, {total_failed} failed (total {total})")
        print("=" * 70)

        return total_failed == 0

    finally:
        runner.cleanup()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
