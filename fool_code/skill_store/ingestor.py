"""Phase 4-5: Generate embeddings and ingest skills into the Rust store."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from fool_code.skill_store.enricher import enrich_skill
from fool_code.skill_store.scanner import parse_skill_md, scan_skill_dir, validate_skill
from fool_code.skill_store.schemas import EnrichedMeta, IngestReport, ParsedSkill
from fool_code.skill_store.store import get_store

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str, str], None]
"""(current_index, total, skill_display, status_text) -> None"""


def batch_ingest(
    scan_root: str,
    workspace_root: Any = None,
    force_reindex: bool = False,
    on_progress: ProgressCallback | None = None,
) -> IngestReport:
    report = IngestReport()

    store = get_store()
    if store is None:
        report.errors.append({"path": scan_root, "reason": "Skill Store not available"})
        return report

    skill_dirs = scan_skill_dir(scan_root)
    report.total_scanned = len(skill_dirs)

    existing_hashes: dict[str, str] = {}
    if not force_reindex:
        try:
            raw = store.list_skills()
            skills_list = json.loads(raw)
            for s in skills_list:
                if s.get("body_hash"):
                    existing_hashes[s["id"]] = s["body_hash"]
        except Exception:
            pass

    total = len(skill_dirs)
    for idx, skill_dir in enumerate(skill_dirs):
        try:
            parsed = parse_skill_md(skill_dir)
            if parsed is None:
                report.errors.append({"path": str(skill_dir), "reason": "Failed to parse SKILL.md"})
                if on_progress:
                    on_progress(idx + 1, total, skill_dir.name, "解析失败，已跳过")
                continue

            skill_label = parsed.display_name or parsed.id or skill_dir.name

            if not force_reindex and parsed.id in existing_hashes:
                if existing_hashes[parsed.id] == parsed.body_hash:
                    if on_progress:
                        on_progress(idx + 1, total, skill_label, "未变更，已跳过")
                    continue

            ok, reason = validate_skill(parsed)
            if not ok:
                report.errors.append({"path": str(skill_dir), "reason": reason})
                if on_progress:
                    on_progress(idx + 1, total, skill_label, f"校验失败: {reason}")
                continue

            if on_progress:
                on_progress(idx + 1, total, skill_label, "正在 LLM 增强…")

            enriched = enrich_skill(parsed, workspace_root)

            if on_progress:
                on_progress(idx + 1, total, skill_label, "正在写入数据库…")

            _ingest_one(store, parsed, enriched, workspace_root)

            if parsed.id in existing_hashes:
                report.updated.append(parsed.id)
            else:
                report.added.append(parsed.id)

            if on_progress:
                on_progress(idx + 1, total, skill_label, "完成")

        except Exception as exc:
            report.errors.append({"path": str(skill_dir), "reason": str(exc)})
            if on_progress:
                on_progress(idx + 1, total, skill_dir.name, f"出错: {exc}")

    return report


def ingest_single(
    skill_dir: str | Path,
    workspace_root: Any = None,
) -> str | None:
    store = get_store()
    if store is None:
        return None

    parsed = parse_skill_md(Path(skill_dir))
    if parsed is None:
        return None

    ok, reason = validate_skill(parsed)
    if not ok:
        logger.warning("Skill validation failed for %s: %s", skill_dir, reason)
        return None

    enriched = enrich_skill(parsed, workspace_root)
    _ingest_one(store, parsed, enriched, workspace_root)
    return parsed.id


def rescan(workspace_root: Any = None, on_progress: ProgressCallback | None = None) -> IngestReport:
    """Incremental scan — only processes new/changed skills."""
    return _scan_all_roots(workspace_root, force_reindex=False, on_progress=on_progress)


def reindex_all(workspace_root: Any = None, on_progress: ProgressCallback | None = None) -> IngestReport:
    """Full reindex — re-processes every skill (re-enriches metadata)."""
    return _scan_all_roots(workspace_root, force_reindex=True, on_progress=on_progress)


def _scan_all_roots(workspace_root: Any, force_reindex: bool, on_progress: ProgressCallback | None = None) -> IngestReport:
    from fool_code.runtime.config import read_config_root

    root = read_config_root()
    config = root.get("skillStoreConfig", {})
    scan_roots = config.get("scanRoots", [])

    if not scan_roots:
        from fool_code.runtime.config import skills_path
        default_dir = skills_path()
        scan_roots = [str(default_dir)]

    combined = IngestReport()
    for sr in scan_roots:
        sr_expanded = str(Path(sr).expanduser())
        sub = batch_ingest(sr_expanded, workspace_root, force_reindex=force_reindex, on_progress=on_progress)
        combined.total_scanned += sub.total_scanned
        combined.added.extend(sub.added)
        combined.updated.extend(sub.updated)
        combined.disabled.extend(sub.disabled)
        combined.errors.extend(sub.errors)

    return combined


def _ingest_one(
    store: Any,
    parsed: ParsedSkill,
    enriched: EnrichedMeta,
    workspace_root: Any = None,
) -> None:
    desc = enriched.improved_description or parsed.description
    display_name = enriched.display_name_zh or parsed.display_name
    category = enriched.category if enriched.category != "other" else (parsed.category or "other")
    trigger_json = json.dumps(enriched.trigger_terms, ensure_ascii=False)

    metadata = {
        "has_scripts": parsed.has_scripts,
        "script_langs": parsed.script_langs,
        "references": parsed.references,
        "original_display_name": parsed.display_name,
        "original_description": parsed.description,
    }

    store.upsert_skill(
        id=parsed.id,
        display_name=display_name,
        description=desc,
        category=category,
        body_path=parsed.body_path,
        body_hash=parsed.body_hash,
        trigger_terms_json=trigger_json,
        metadata_json=json.dumps(metadata, ensure_ascii=False),
    )

    _generate_and_store_embeddings(store, parsed, enriched, desc, workspace_root)

    store.clear_entity_links_for_skill(parsed.id)
    for ent in enriched.entities:
        ent_name = ent.get("name", "")
        ent_type = ent.get("type", "concept")
        if not ent_name:
            continue
        ent_id = f"{ent_type}:{ent_name.lower().replace(' ', '_')}"
        store.upsert_entity(ent_id, ent_name, ent_type)
        store.link_skill_entity(ent_id, parsed.id)

    try:
        store.enqueue_consolidation(parsed.id)
    except Exception:
        pass


def _generate_and_store_embeddings(
    store: Any,
    parsed: ParsedSkill,
    enriched: EnrichedMeta,
    description: str,
    workspace_root: Any = None,
) -> None:
    try:
        from fool_code.magma.extractor import _generate_embedding
    except ImportError:
        logger.debug("MAGMA extractor not available, skipping embedding generation")
        return

    desc_emb = _generate_embedding(description, workspace_root)
    if desc_emb:
        store.upsert_embedding(parsed.id, "description", desc_emb)

    if enriched.trigger_terms:
        trigger_text = " | ".join(enriched.trigger_terms)
        trigger_emb = _generate_embedding(trigger_text, workspace_root)
        if trigger_emb:
            store.upsert_embedding(parsed.id, "trigger_terms", trigger_emb)

    if parsed.body_summary:
        body_emb = _generate_embedding(parsed.body_summary, workspace_root)
        if body_emb:
            store.upsert_embedding(parsed.id, "body_summary", body_emb)
