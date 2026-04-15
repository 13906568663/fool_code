"""Type definitions for the MAGMA memory system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MagmaEvent:
    """A structured event extracted from a conversation turn."""
    content: str
    summary: str
    entities: list[EntityRef] = field(default_factory=list)
    topic: str = ""
    is_decision: bool = False


@dataclass
class EntityRef:
    """A reference to an entity mentioned in an event."""
    name: str
    entity_type: str  # person | project | technology | file | concept


@dataclass
class RetrievedContext:
    """Context assembled by the retriever for prompt injection."""
    text: str
    node_count: int
    token_estimate: int


WEIGHT_PRESETS: dict[str, dict[str, float]] = {
    "temporal_focus": {"temporal": 5.0, "causal": 0.5, "semantic": 1.0, "entity": 1.0},
    "general": {"temporal": 1.0, "causal": 1.0, "semantic": 4.0, "entity": 2.0},
}

# Backward-compat alias
INTENT_WEIGHT_PRESETS = WEIGHT_PRESETS


# ---------------------------------------------------------------------------
# Structured output schemas (OpenAI json_schema format, strict mode)
# ---------------------------------------------------------------------------

EVENT_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "event_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "summary": {"type": "string"},
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
                            "topic": {"type": "string"},
                            "is_decision": {"type": "boolean"},
                        },
                        "required": ["content", "summary", "entities", "topic", "is_decision"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["events"],
            "additionalProperties": False,
        },
    },
}

CONSOLIDATION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "consolidation_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "causal_edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_id": {"type": "string"},
                            "target_id": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["source_id", "target_id", "reason"],
                        "additionalProperties": False,
                    },
                },
                "entity_edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_id": {"type": "string"},
                            "target_id": {"type": "string"},
                            "shared_entity": {"type": "string"},
                            "relation": {"type": "string"},
                        },
                        "required": ["source_id", "target_id", "shared_entity", "relation"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["causal_edges", "entity_edges"],
            "additionalProperties": False,
        },
    },
}


# INTENT_CLASSIFICATION_SCHEMA removed — intent is now determined by time
# parsing alone (2-mode: temporal_focus / general).
