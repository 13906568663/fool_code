"""Phase 3: LLM enrichment of skill metadata with rule-based fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fool_code.skill_store.schemas import ENRICHMENT_SCHEMA, EnrichedMeta, ParsedSkill

logger = logging.getLogger(__name__)

ENRICHMENT_SYSTEM = """\
你是一个技能元数据增强代理。给定一个 AI 技能的描述和内容摘要，你的任务是：

重要：所有输出内容必须使用中文（简体），即使原始描述是英文的。

1. trigger_terms: 提取 5-10 个用户可能使用的触发词/短语
   - 必须包含中文触发词（如"创建表格"、"修复公式"），同时保留关键英文术语（如 Excel、CSV）
   - 包括：动词短语、技术名词、文件类型、场景描述

2. category: 归类到一个简短的 kebab-case 分类标签
   - 常见分类参考: dev-tools / data-processing / deployment / documentation
     / testing / code-quality / ai-ml / database / frontend / backend
     / devops / security / e-commerce / social-media / marketing
     / finance / education / gaming / cloud / mobile / other
   - 如果以上都不合适，可以自定义一个有意义的 kebab-case 分类名

3. entities: 提取涉及的技术实体
   - 每个: {"name": "...", "type": "technology|file_type|domain|workflow|language"}

4. improved_description: 用中文重写描述，使其简洁、检索友好
   - 必须包含：这个技能做什么、什么时候使用、支持的场景
   - 即使原始描述已经足够好，也要翻译成中文版本
   - 长度控制在 100-200 字

5. display_name_zh: 技能的中文显示名称
   - 简短、直观，如 "Excel 表格处理"、"Docker 部署"、"小红书内容生成"
   - 保留关键英文专有名词（如 Excel、Docker、React）

请以 JSON 格式输出结果。"""

ENRICHMENT_USER_TEMPLATE = """\
## 技能信息
Name: {name}
Description: {description}
Body summary: {body_summary}
Has scripts: {has_scripts}

## 已有 trigger_terms
{existing_triggers}

请分析并补全元数据："""


def enrich_skill(
    parsed: ParsedSkill,
    workspace_root: Any = None,
) -> EnrichedMeta:
    result = _enrich_via_llm(parsed, workspace_root)
    if result is not None:
        return result

    logger.debug("LLM enrichment unavailable, using rule-based fallback for %s", parsed.id)
    return _fallback_enrich(parsed)


def _enrich_via_llm(
    parsed: ParsedSkill,
    workspace_root: Any,
) -> EnrichedMeta | None:
    try:
        from fool_code.runtime.subagent import create_role_provider
    except ImportError:
        return None

    provider = create_role_provider("memory", workspace_root)
    if provider is None:
        return None

    existing = ", ".join(parsed.trigger_terms) if parsed.trigger_terms else "(无)"
    prompt = ENRICHMENT_USER_TEMPLATE.format(
        name=parsed.id,
        description=parsed.description,
        body_summary=parsed.body_summary[:300],
        has_scripts=parsed.has_scripts,
        existing_triggers=existing,
    )

    try:
        result = provider.simple_chat(
            [{"role": "user", "content": prompt}],
            system=ENRICHMENT_SYSTEM,
            max_tokens=1024,
            response_format=ENRICHMENT_SCHEMA,
        )
        provider.close()
    except Exception as exc:
        logger.debug("Skill enrichment LLM call failed: %s", exc)
        return None

    return _parse_enrichment(result, parsed)


def _parse_enrichment(raw: str, parsed: ParsedSkill) -> EnrichedMeta | None:
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    trigger_terms = data.get("trigger_terms", [])
    if not isinstance(trigger_terms, list):
        trigger_terms = []
    trigger_terms = [str(t) for t in trigger_terms][:20]

    if parsed.trigger_terms:
        existing_set = {t.lower() for t in parsed.trigger_terms}
        for t in parsed.trigger_terms:
            if t.lower() not in {x.lower() for x in trigger_terms}:
                trigger_terms.append(t)

    category = data.get("category", "other")
    if not isinstance(category, str) or not category.strip():
        category = parsed.category or "other"
    else:
        category = category.strip().lower().replace(" ", "-")

    entities = data.get("entities", [])
    if not isinstance(entities, list):
        entities = []

    improved_desc = data.get("improved_description", "")
    if not isinstance(improved_desc, str):
        improved_desc = ""

    display_name_zh = data.get("display_name_zh", "")
    if not isinstance(display_name_zh, str):
        display_name_zh = ""

    return EnrichedMeta(
        trigger_terms=trigger_terms,
        category=category,
        entities=[e for e in entities if isinstance(e, dict) and e.get("name")],
        improved_description=improved_desc,
        display_name_zh=display_name_zh,
    )


def _fallback_enrich(parsed: ParsedSkill) -> EnrichedMeta:
    tokens = re.split(r"[\s,，。？！?!、;；:：]+", parsed.description)
    trigger_terms = [t for t in tokens if len(t) >= 2][:10]

    if parsed.trigger_terms:
        for t in parsed.trigger_terms:
            if t not in trigger_terms:
                trigger_terms.append(t)

    return EnrichedMeta(
        trigger_terms=trigger_terms,
        category=parsed.category or "other",
        entities=[],
        improved_description="",
    )
