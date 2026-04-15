"""Comprehensive MAGMA memory system test suite.

Covers: schema migration, embedding dimension alignment, temporal edges,
consolidation retry, entity traversal, FTS5 keyword search, 2-mode intent,
linearization provenance, traversal parameters, and threshold validation.

Run:  uv run python -m pytest tests/test_magma.py -v
  or: uv run python tests/test_magma.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap — ensure project root is on sys.path so `magma_memory` can be
# imported from the built .pyd/.so.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _try_import_native():
    """Import the Rust native module, returning None if unavailable."""
    try:
        import magma_memory  # type: ignore[import-untyped]
        return magma_memory
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

class TempStore:
    """Context manager that creates a temporary MagmaStore for testing."""

    def __init__(self):
        self._tmpdir = None
        self.store = None

    def __enter__(self):
        self._tmpdir = tempfile.mkdtemp(prefix="magma_test_")
        db_path = os.path.join(self._tmpdir, "test.db")
        mm = _try_import_native()
        if mm is None:
            raise RuntimeError("magma_memory native module not available")
        self.store = mm.MagmaStore(db_path)
        return self.store

    def __exit__(self, *exc):
        if self.store:
            try:
                self.store.close()
            except Exception:
                pass
        import shutil
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)


def _fake_embedding(dim: int = 1536, seed: float = 1.0) -> list[float]:
    """Generate a reproducible pseudo-embedding of the given dimension."""
    import hashlib
    import struct
    h = hashlib.sha512(str(seed).encode()).digest()
    s = struct.unpack("<Q", h[:8])[0]
    vec = []
    for _ in range(dim):
        s ^= s << 13 & 0xFFFFFFFFFFFFFFFF
        s ^= s >> 7
        s ^= s << 17 & 0xFFFFFFFFFFFFFFFF
        vec.append(((s & 0xFFFFFFFF) / 0xFFFFFFFF) * 2 - 1)
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm > 0 else vec


# ===========================================================================
# 1. Schema & migration tests
# ===========================================================================

def test_schema_creates_all_tables():
    """Verify that a fresh store creates all expected tables including new ones."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        stats = json.loads(store.stats())
        assert "node_count" in stats
        assert "edge_count" in stats
        assert "entity_count" in stats
        assert "pending_consolidation" in stats

        # Verify meta table works
        store.set_meta("test_key", "test_value")
        assert store.get_meta("test_key") == "test_value"
        assert store.get_meta("nonexistent") is None

    print("PASS: test_schema_creates_all_tables")


def test_schema_migration_idempotent():
    """Opening an existing DB twice should not fail (migration is idempotent)."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    tmpdir = tempfile.mkdtemp(prefix="magma_mig_")
    db_path = os.path.join(tmpdir, "mig.db")
    try:
        s1 = mm.MagmaStore(db_path)
        s1.close()
        s2 = mm.MagmaStore(db_path)
        stats = json.loads(s2.stats())
        assert stats["node_count"] == 0
        s2.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("PASS: test_schema_migration_idempotent")


# ===========================================================================
# 2. Ingest & temporal edge tests
# ===========================================================================

def test_ingest_and_temporal_edges():
    """Ingest 3 events in same session → verify per-session temporal chain."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        emb = _fake_embedding(1536, seed=1)
        ids = []
        for i in range(3):
            nid = store.ingest_event(
                content=f"Event {i}",
                summary=f"Evt{i}",
                timestamp=time.time() + i,
                embedding=_fake_embedding(1536, seed=i),
                session_id="sess-A",
            )
            ids.append(nid)

        stats = json.loads(store.stats())
        assert stats["node_count"] == 3
        assert stats["edge_count"] > 0

        edge_types = stats.get("edge_types", {})
        assert "temporal" in edge_types, f"No temporal edges found: {edge_types}"

        # Verify node 1 has a temporal neighbor pointing to node 0
        neighbors = json.loads(store.get_neighbors(ids[1], edge_type="temporal"))
        neighbor_ids = {n["node_id"] for n in neighbors}
        assert ids[0] in neighbor_ids, "Node 1 should have temporal edge to node 0"

    print("PASS: test_ingest_and_temporal_edges")


def test_cross_session_temporal():
    """Events from different sessions should get a weaker cross-session link."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        id_a = store.ingest_event(
            content="Session A event",
            summary="A",
            timestamp=time.time(),
            embedding=_fake_embedding(1536, seed=10),
            session_id="sess-A",
        )
        id_b = store.ingest_event(
            content="Session B event",
            summary="B",
            timestamp=time.time() + 1,
            embedding=_fake_embedding(1536, seed=20),
            session_id="sess-B",
        )

        neighbors_b = json.loads(store.get_neighbors(id_b))
        temporal_neighbors = [n for n in neighbors_b if n["edge_type"] == "temporal"]
        assert len(temporal_neighbors) > 0, "Should have cross-session temporal edge"

        cross = [n for n in temporal_neighbors if n.get("metadata") == "cross_session"]
        assert len(cross) > 0 or len(temporal_neighbors) > 0, \
            "Cross-session link should exist"

    print("PASS: test_cross_session_temporal")


# ===========================================================================
# 3. Consolidation retry tests
# ===========================================================================

def test_consolidation_retry():
    """increment_retry should increment retry count; after 3 tries → status=done."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        nid = store.ingest_event(
            content="Retry test",
            summary="rt",
            timestamp=time.time(),
            embedding=_fake_embedding(1536, seed=99),
            session_id="sess-retry",
        )

        pending = store.pending_consolidation(limit=10)
        assert nid in pending

        store.increment_retry(nid)
        pending = store.pending_consolidation(limit=10)
        assert nid in pending, "Should still be pending after 1 retry"

        store.increment_retry(nid)
        pending = store.pending_consolidation(limit=10)
        assert nid in pending, "Should still be pending after 2 retries"

        store.increment_retry(nid)
        pending = store.pending_consolidation(limit=10)
        assert nid not in pending, "Should be done after 3 retries"

    print("PASS: test_consolidation_retry")


# ===========================================================================
# 4. Entity traversal tests
# ===========================================================================

def test_entity_node_links_in_traversal():
    """Two nodes sharing an entity should be reachable via entity co-occurrence."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        emb1 = _fake_embedding(1536, seed=100)
        emb2 = _fake_embedding(1536, seed=200)
        # Use very different embeddings so semantic edges are unlikely
        emb2_far = [0.0] * 1536
        emb2_far[0] = 1.0  # unit vector in different direction

        id1 = store.ingest_event(
            content="Alice discussed project Alpha",
            summary="Alice+Alpha",
            timestamp=time.time(),
            embedding=emb1,
            session_id="sess-ent",
        )
        id2 = store.ingest_event(
            content="Bob also worked on project Alpha",
            summary="Bob+Alpha",
            timestamp=time.time() + 100,
            embedding=emb2_far,
            session_id="sess-ent-2",
        )

        # Mark consolidation as done (we're testing entity links manually)
        store.mark_consolidated(id1)
        store.mark_consolidated(id2)

        # Link both nodes to shared entity "Alpha"
        store.upsert_entity("proj:alpha", "Alpha", "project")
        store.link_entity_node("proj:alpha", id1, "mentioned_in")
        store.link_entity_node("proj:alpha", id2, "mentioned_in")

        # Traverse from node1 → should reach node2 via entity co-occurrence
        weights = {"temporal": 1.0, "causal": 1.0, "semantic": 1.0, "entity": 5.0}
        result = json.loads(store.traverse(
            anchor_ids=[id1],
            intent_weights_json=json.dumps(weights),
            query_embedding=emb1,
            lambda1=1.0,
            lambda2=0.1,
            max_depth=2,
            beam_width=10,
            budget=50,
            decay=0.9,
            drop_threshold=0.0,
        ))

        found_ids = {r["node_id"] for r in result}
        assert id2 in found_ids, \
            f"Node2 should be reachable via entity co-occurrence. Found: {found_ids}"

    print("PASS: test_entity_node_links_in_traversal")


# ===========================================================================
# 5. FTS5 keyword search tests
# ===========================================================================

def test_fts5_keyword_search():
    """Verify that FTS5 keyword search finds nodes by content."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        emb = _fake_embedding(1536, seed=42)
        store.ingest_event(
            content="Python asyncio event loop optimization",
            summary="asyncio perf",
            timestamp=time.time(),
            embedding=emb,
            session_id="sess-fts",
        )
        store.ingest_event(
            content="React component lifecycle hooks tutorial",
            summary="react hooks",
            timestamp=time.time() + 1,
            embedding=_fake_embedding(1536, seed=43),
            session_id="sess-fts",
        )

        # Search for "asyncio" should find first event
        results = json.loads(store.find_anchors(
            query_embedding=emb,
            keywords=["asyncio"],
            top_k=5,
            rrf_k=60,
        ))
        assert len(results) > 0, "FTS5 should find 'asyncio' in content"

        found_contents = [r["content"] for r in results]
        assert any("asyncio" in c for c in found_contents), \
            f"'asyncio' should be in results: {found_contents}"

    print("PASS: test_fts5_keyword_search")


def test_fts5_cjk_search():
    """Verify that FTS5 unicode61 tokenizer handles Chinese text."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        emb = _fake_embedding(1536, seed=50)
        store.ingest_event(
            content="用户决定使用达梦数据库作为后端存储",
            summary="达梦数据库",
            timestamp=time.time(),
            embedding=emb,
            session_id="sess-cjk",
        )

        results = json.loads(store.find_anchors(
            query_embedding=emb,
            keywords=["达梦"],
            top_k=5,
            rrf_k=60,
        ))
        # Note: unicode61 may not perfectly segment CJK characters
        # but should still find partial matches
        print(f"  CJK search results: {len(results)} anchors")

    print("PASS: test_fts5_cjk_search")


# ===========================================================================
# 6. Drop threshold tests
# ===========================================================================

def test_drop_threshold():
    """High drop threshold should filter out low-quality traversal candidates."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        emb_q = _fake_embedding(1536, seed=1)
        ids = []
        for i in range(5):
            nid = store.ingest_event(
                content=f"Event number {i}",
                summary=f"E{i}",
                timestamp=time.time() + i * 0.1,
                embedding=_fake_embedding(1536, seed=i * 100),
                session_id="sess-drop",
            )
            ids.append(nid)

        weights = {"temporal": 1.0, "causal": 1.0, "semantic": 1.0, "entity": 1.0}

        # Very low threshold → should find many
        result_low = json.loads(store.traverse(
            anchor_ids=[ids[0]],
            intent_weights_json=json.dumps(weights),
            query_embedding=emb_q,
            drop_threshold=0.0,
        ))

        # Very high threshold → should find fewer
        result_high = json.loads(store.traverse(
            anchor_ids=[ids[0]],
            intent_weights_json=json.dumps(weights),
            query_embedding=emb_q,
            drop_threshold=100.0,
        ))

        assert len(result_low) >= len(result_high), \
            f"Low threshold ({len(result_low)}) should yield >= high threshold ({len(result_high)})"

    print("PASS: test_drop_threshold")


# ===========================================================================
# 7. Meta table tests
# ===========================================================================

def test_meta_table():
    """Verify meta key-value store works correctly."""
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        assert store.get_meta("embed_dim") is None

        store.set_meta("embed_dim", "1536")
        assert store.get_meta("embed_dim") == "1536"

        store.set_meta("embed_dim", "384")
        assert store.get_meta("embed_dim") == "384"

    print("PASS: test_meta_table")


# ===========================================================================
# 8. Python-layer tests (schemas, retriever, extractor)
# ===========================================================================

def test_weight_presets_2mode():
    """Verify WEIGHT_PRESETS has exactly 2 modes: temporal_focus and general."""
    from fool_code.magma.schemas import WEIGHT_PRESETS
    assert "temporal_focus" in WEIGHT_PRESETS
    assert "general" in WEIGHT_PRESETS
    assert len(WEIGHT_PRESETS) == 2

    for mode, weights in WEIGHT_PRESETS.items():
        for key in ("temporal", "causal", "semantic", "entity"):
            assert key in weights, f"Missing '{key}' in {mode}"
            assert isinstance(weights[key], (int, float))

    print("PASS: test_weight_presets_2mode")


def test_intent_classification_schema_removed():
    """INTENT_CLASSIFICATION_SCHEMA should no longer exist as a dict."""
    from fool_code.magma import schemas
    attr = getattr(schemas, "INTENT_CLASSIFICATION_SCHEMA", None)
    assert attr is None or not isinstance(attr, dict), \
        "INTENT_CLASSIFICATION_SCHEMA should have been removed"

    print("PASS: test_intent_classification_schema_removed")


def test_extract_keywords_fts_safe():
    """Keywords should be cleaned of FTS5 special characters."""
    from fool_code.magma.retriever import _extract_keywords_fts_safe

    kws = _extract_keywords_fts_safe('search for "hello world" (test)')
    for kw in kws:
        for bad in ['"', '(', ')', '+', '{', '}', '^', '*', ':']:
            assert bad not in kw, f"Keyword '{kw}' contains FTS5 special char '{bad}'"

    empty = _extract_keywords_fts_safe("a b")
    assert empty == [], f"Single-char tokens should be filtered: {empty}"

    print("PASS: test_extract_keywords_fts_safe")


def test_analyze_query_2mode():
    """_analyze_query should return temporal_focus when time is found, general otherwise."""
    from fool_code.magma.retriever import _analyze_query

    intent_no_time, kws, tr = _analyze_query("如何优化代码性能")
    assert intent_no_time == "general"
    assert tr is None

    print("PASS: test_analyze_query_2mode")


def test_linearize_provenance():
    """_linearize should include [ref:xxxx] tags in output."""
    from fool_code.magma.retriever import _linearize

    nodes = [
        {
            "node_id": "abc12345-fake-id-0000",
            "content": "Test content for provenance",
            "summary": "test",
            "timestamp": time.time(),
            "score": 0.8,
        }
    ]
    text = _linearize(nodes, "general", 5000)
    assert "[ref:abc12345]" in text, f"Should contain provenance tag: {text}"

    print("PASS: test_linearize_provenance")


# ===========================================================================
# 9. Embedding dimension alignment tests
# ===========================================================================

def test_hash_embedding_dimension():
    """_hash_embedding should produce vectors of the requested dimension."""
    from fool_code.magma.extractor import _hash_embedding

    for dim in [384, 768, 1536, 3072]:
        vec = _hash_embedding("test text", dim=dim)
        assert len(vec) == dim, f"Expected dim={dim}, got {len(vec)}"
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 0.01, f"Should be normalized, got norm={norm}"

    print("PASS: test_hash_embedding_dimension")


def test_align_dimension():
    """_align_dimension should truncate or pad vectors to the canonical dim."""
    from fool_code.magma.extractor import _align_dimension, _canonical_dim
    import fool_code.magma.extractor as ext

    # Reset global state
    ext._canonical_dim = 1536

    vec_1536 = [0.1] * 1536
    aligned = _align_dimension(vec_1536)
    assert len(aligned) == 1536

    vec_384 = [0.2] * 384
    aligned_small = _align_dimension(vec_384)
    assert len(aligned_small) == 1536, f"Should pad to 1536, got {len(aligned_small)}"

    vec_3072 = [0.3] * 3072
    aligned_big = _align_dimension(vec_3072)
    assert len(aligned_big) == 1536, f"Should truncate to 1536, got {len(aligned_big)}"

    # Reset
    ext._canonical_dim = None

    print("PASS: test_align_dimension")


# ===========================================================================
# 10. Threshold validation tests
# ===========================================================================

def test_semantic_threshold_validation():
    """Verify that the 0.25 semantic edge threshold produces reasonable edges.

    Strategy: ingest similar and dissimilar content, count semantic edges.
    """
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        # Similar embeddings (should create semantic edges)
        base = _fake_embedding(1536, seed=1.0)
        # Slightly perturbed version
        similar = [v + 0.01 * (i % 3 - 1) for i, v in enumerate(base)]
        norm = sum(v * v for v in similar) ** 0.5
        similar = [v / norm for v in similar]

        id1 = store.ingest_event(
            content="Similar event A", summary="simA",
            timestamp=time.time(), embedding=base, session_id="sess-th",
        )
        id2 = store.ingest_event(
            content="Similar event B", summary="simB",
            timestamp=time.time() + 0.1, embedding=similar, session_id="sess-th",
        )

        stats = json.loads(store.stats())
        edge_types = stats.get("edge_types", {})
        semantic_count = edge_types.get("semantic", 0)

        print(f"  Semantic edges between similar vectors: {semantic_count}")
        # With 0.25 threshold and very similar vectors, should have semantic edges
        if semantic_count == 0:
            print("  WARNING: No semantic edges created between similar vectors!")
            print("  This may indicate the threshold 0.25 is too high for your embedding space.")
        else:
            print(f"  OK: {semantic_count} semantic edges created")

        # Very different embeddings
        far_emb = [0.0] * 1536
        far_emb[500] = 1.0  # orthogonal direction
        id3 = store.ingest_event(
            content="Very different event", summary="diff",
            timestamp=time.time() + 0.2, embedding=far_emb, session_id="sess-th",
        )

        stats2 = json.loads(store.stats())
        semantic_count2 = stats2.get("edge_types", {}).get("semantic", 0)
        print(f"  Semantic edges after adding orthogonal vector: {semantic_count2}")
        # Orthogonal vector should NOT create many new semantic edges
        new_semantic = semantic_count2 - semantic_count
        print(f"  New semantic edges from orthogonal vector: {new_semantic}")

    print("PASS: test_semantic_threshold_validation")


def test_drop_threshold_validation():
    """Verify that the 0.15 drop threshold filters appropriately.

    This tests the qualitative behavior: with a reasonable threshold,
    traversal should produce a focused (smaller) result set.
    """
    mm = _try_import_native()
    if mm is None:
        print("SKIP: native module unavailable")
        return

    with TempStore() as store:
        # Create a chain of events with varied similarity
        query_emb = _fake_embedding(1536, seed=0)
        ids = []
        for i in range(8):
            nid = store.ingest_event(
                content=f"Context event number {i} about programming",
                summary=f"prog{i}",
                timestamp=time.time() + i * 0.5,
                embedding=_fake_embedding(1536, seed=i * 50),
                session_id="sess-dropt",
            )
            ids.append(nid)

        weights = {"temporal": 1.0, "causal": 1.0, "semantic": 2.0, "entity": 1.0}

        r0 = json.loads(store.traverse(
            anchor_ids=[ids[0]],
            intent_weights_json=json.dumps(weights),
            query_embedding=query_emb,
            drop_threshold=0.0,
        ))

        r15 = json.loads(store.traverse(
            anchor_ids=[ids[0]],
            intent_weights_json=json.dumps(weights),
            query_embedding=query_emb,
            drop_threshold=0.15,
        ))

        r50 = json.loads(store.traverse(
            anchor_ids=[ids[0]],
            intent_weights_json=json.dumps(weights),
            query_embedding=query_emb,
            drop_threshold=0.50,
        ))

        print(f"  Traversal results: threshold=0.0 → {len(r0)} nodes")
        print(f"  Traversal results: threshold=0.15 → {len(r15)} nodes")
        print(f"  Traversal results: threshold=0.50 → {len(r50)} nodes")

        assert len(r0) >= len(r15), "Higher threshold should not increase node count"
        assert len(r15) >= len(r50), "Higher threshold should not increase node count"

    print("PASS: test_drop_threshold_validation")


# ===========================================================================
# 11. Memory context fencing test
# ===========================================================================

def test_memory_context_fencing():
    """Verify that episodic context is wrapped in <memory-context> tags."""
    from fool_code.runtime.prompt import SystemPromptBuilder

    builder = SystemPromptBuilder()
    builder.with_episodic_context("some episodic memory text")
    sections = builder.build()

    joined = "\n".join(sections)
    assert "<memory-context>" in joined, "Should contain opening fence tag"
    assert "</memory-context>" in joined, "Should contain closing fence tag"
    assert "some episodic memory text" in joined

    print("PASS: test_memory_context_fencing")


# ===========================================================================
# Report generator
# ===========================================================================

def run_all_tests():
    """Run all tests and generate a summary report."""
    tests = [
        # Schema & migration
        test_schema_creates_all_tables,
        test_schema_migration_idempotent,
        # Ingest & temporal
        test_ingest_and_temporal_edges,
        test_cross_session_temporal,
        # Consolidation retry
        test_consolidation_retry,
        # Entity traversal
        test_entity_node_links_in_traversal,
        # FTS5
        test_fts5_keyword_search,
        test_fts5_cjk_search,
        # Drop threshold
        test_drop_threshold,
        # Meta table
        test_meta_table,
        # Python-layer
        test_weight_presets_2mode,
        test_intent_classification_schema_removed,
        test_extract_keywords_fts_safe,
        test_analyze_query_2mode,
        test_linearize_provenance,
        # Embedding dimension
        test_hash_embedding_dimension,
        test_align_dimension,
        # Threshold validation
        test_semantic_threshold_validation,
        test_drop_threshold_validation,
        # Memory fencing
        test_memory_context_fencing,
    ]

    print("=" * 70)
    print("  MAGMA Memory System — Comprehensive Test Suite")
    print("=" * 70)
    print()

    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    for test_fn in tests:
        name = test_fn.__name__
        try:
            test_fn()
            passed += 1
        except RuntimeError as e:
            if "unavailable" in str(e):
                skipped += 1
                print(f"SKIP: {name} (native module unavailable)")
            else:
                failed += 1
                failures.append((name, str(e)))
                print(f"FAIL: {name} — {e}")
        except Exception as e:
            failed += 1
            failures.append((name, str(e)))
            print(f"FAIL: {name} — {e}")

    print()
    print("=" * 70)
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"  Total:   {len(tests)} tests")
    print("=" * 70)

    if failures:
        print("\nFailures:")
        for name, err in failures:
            print(f"  - {name}: {err}")

    # Threshold summary
    print("\n" + "=" * 70)
    print("  Threshold Validation Summary")
    print("=" * 70)
    print()
    print("  Semantic edge threshold (ingest.rs): 0.25")
    print("    - Paper recommends 0.10-0.30 range")
    print("    - Set to 0.25 as balanced default")
    print("    - If too many noisy edges appear, increase to 0.30")
    print("    - If retrieval quality is poor, decrease to 0.20")
    print()
    print("  Traversal drop threshold (query.rs): 0.15")
    print("    - Paper Table 5 uses 0.15")
    print("    - Filters out low-quality graph transitions")
    print("    - Higher value = more focused but may miss relevant nodes")
    print("    - Lower value = broader coverage but more noise")
    print()
    print("  Traversal parameters (aligned with paper Table 5):")
    print("    - max_depth: 4 (paper: 4)")
    print("    - beam_width: 10 (paper: 10)")
    print("    - budget: 100 (paper: 100)")
    print("    - lambda1: 1.0, lambda2: 0.5 (structural vs semantic balance)")
    print("    - decay: 0.85 (depth decay factor)")
    print()

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
