"""Type definitions and JSON schemas for the Skill Store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedSkill:
    id: str
    display_name: str
    description: str
    category: str | None = None
    trigger_terms: list[str] = field(default_factory=list)
    body_text: str = ""
    body_summary: str = ""
    body_path: str = ""
    body_hash: str = ""
    has_scripts: bool = False
    script_langs: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


@dataclass
class EnrichedMeta:
    trigger_terms: list[str] = field(default_factory=list)
    category: str = "other"
    entities: list[dict] = field(default_factory=list)
    improved_description: str = ""
    display_name_zh: str = ""


@dataclass
class IngestReport:
    total_scanned: int = 0
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"扫描 {self.total_scanned} 个 skill | "
            f"新增 {len(self.added)} | 更新 {len(self.updated)} | "
            f"禁用 {len(self.disabled)} | 错误 {len(self.errors)}"
        )


ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "skill_enrichment",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "trigger_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "category": {"type": "string"},
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                        },
                        "required": ["name", "type"],
                        "additionalProperties": False,
                    },
                },
                "improved_description": {"type": "string"},
                "display_name_zh": {"type": "string"},
            },
            "required": [
                "trigger_terms",
                "category",
                "entities",
                "improved_description",
                "display_name_zh",
            ],
            "additionalProperties": False,
        },
    },
}

CONSOLIDATION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "skill_consolidation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_id": {"type": "string"},
                            "target_id": {"type": "string"},
                            "edge_type": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["source_id", "target_id", "edge_type", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["edges"],
            "additionalProperties": False,
        },
    },
}

SKILL_INTENT_WEIGHTS: dict[str, dict[str, float]] = {
    "CREATE": {
        "prerequisite": 2.0,
        "complementary": 5.0,
        "alternative": 0.5,
        "composes_with": 4.0,
        "shared_domain": 1.0,
    },
    "FIX": {
        "prerequisite": 5.0,
        "complementary": 2.0,
        "alternative": 3.0,
        "composes_with": 1.0,
        "shared_domain": 2.0,
    },
    "TRANSFORM": {
        "prerequisite": 1.0,
        "complementary": 3.0,
        "alternative": 0.5,
        "composes_with": 5.0,
        "shared_domain": 2.0,
    },
    "QUERY": {
        "prerequisite": 1.0,
        "complementary": 2.0,
        "alternative": 1.0,
        "composes_with": 1.0,
        "shared_domain": 5.0,
    },
}

SUGGESTED_CATEGORIES = {
    "dev-tools", "data-processing", "deployment", "documentation",
    "testing", "code-quality", "ai-ml", "database", "frontend",
    "backend", "devops", "security", "e-commerce", "social-media",
    "marketing", "finance", "education", "healthcare", "gaming",
    "iot", "blockchain", "cloud", "mobile", "desktop", "cli",
    "other",
}
