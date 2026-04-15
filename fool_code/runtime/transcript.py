"""Transcript storage — JSONL append-only session persistence.

Replaces the single-JSON-file dump with a JSONL transcript:
  - Each line is a JSON object (TranscriptEntry)
  - Supports multiple entry types: messages, titles, tags, content replacements
  - Append-only writes (safe against corruption)
  - Rebuild session state from entries on load
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from fool_code.types import (
    ContentReplacementRecord,
    ConversationMessage,
    MessageRole,
    Session,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Entry types
# ------------------------------------------------------------------

EntryType = Literal[
    "user", "assistant", "tool", "system",
    "custom-title", "ai-title",
    "tag",
    "plan-slug",
    "plan-status",
    "content-replacement",
    "summary",
]


class TranscriptEntry(BaseModel):
    """One line in the JSONL transcript file."""
    type: EntryType

    # Message entries
    message: ConversationMessage | None = None

    # Metadata entries
    session_id: str | None = None
    timestamp: str | None = None
    version: str | None = None

    # Title entries
    custom_title: str | None = None
    ai_title: str | None = None

    # Tag
    tag: str | None = None

    # Plan slug
    slug: str | None = None

    # Plan execution status
    plan_status: str | None = None

    # Content replacement records
    content_replacements: list[ContentReplacementRecord] | None = None

    # Summary (from compaction)
    summary_text: str | None = None
    leaf_uuid: str | None = None


def entry_from_message(msg: ConversationMessage) -> TranscriptEntry:
    return TranscriptEntry(
        type=msg.role.value,  # type: ignore[arg-type]
        message=msg,
        timestamp=msg.timestamp,
    )


# ------------------------------------------------------------------
# Restored session result
# ------------------------------------------------------------------

@dataclass
class RestoredSession:
    session: Session = field(default_factory=Session)
    title: str = "新对话"
    plan_slug: str | None = None
    plan_status: str = "none"
    content_replacements: list[ContentReplacementRecord] = field(default_factory=list)
    tag: str | None = None
    custom_title: str | None = None
    ai_title: str | None = None


# ------------------------------------------------------------------
# TranscriptStorage
# ------------------------------------------------------------------

class TranscriptStorage:
    """JSONL-based session transcript."""

    def __init__(self, session_id: str, base_dir: Path) -> None:
        self.session_id = session_id
        self.base_dir = base_dir
        self.path = base_dir / f"{session_id}.jsonl"

    def exists(self) -> bool:
        return self.path.exists()

    def append(self, entry: TranscriptEntry) -> None:
        """Append a single entry as one JSON line."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        line = entry.model_dump_json(exclude_none=True) + "\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)

    def append_message(self, msg: ConversationMessage) -> None:
        self.append(entry_from_message(msg))

    def append_messages_from(
        self, session: Session, start_index: int,
        title: str | None = None,
    ) -> None:
        """Append messages starting from *start_index* (incremental persist).

        Also re-appends title / plan metadata so the tail window always
        contains the latest values (mirrors CC's reAppendSessionMetadata).
        """
        if start_index >= len(session.messages):
            return
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            for msg in session.messages[start_index:]:
                entry = entry_from_message(msg)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")
            if title and title != "新对话":
                entry = TranscriptEntry(type="ai-title", ai_title=title)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")
            if session.plan_slug:
                entry = TranscriptEntry(type="plan-slug", slug=session.plan_slug)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")
            if session.plan_status and session.plan_status != "none":
                entry = TranscriptEntry(type="plan-status", plan_status=session.plan_status)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")

    def append_title(self, title: str, is_custom: bool = True) -> None:
        if is_custom:
            self.append(TranscriptEntry(type="custom-title", custom_title=title))
        else:
            self.append(TranscriptEntry(type="ai-title", ai_title=title))

    def append_plan_slug(self, slug: str) -> None:
        self.append(TranscriptEntry(type="plan-slug", slug=slug))

    def append_content_replacements(self, records: list[ContentReplacementRecord]) -> None:
        if records:
            self.append(TranscriptEntry(
                type="content-replacement",
                content_replacements=records,
            ))

    def append_tag(self, tag: str) -> None:
        self.append(TranscriptEntry(type="tag", tag=tag))

    def append_plan_status(self, status: str) -> None:
        self.append(TranscriptEntry(type="plan-status", plan_status=status))

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_entries(self) -> list[TranscriptEntry]:
        if not self.path.exists():
            return []
        entries: list[TranscriptEntry] = []
        for line_num, raw_line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1,
        ):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
                entries.append(TranscriptEntry.model_validate(data))
            except Exception as exc:
                logger.warning(
                    "Skipping malformed transcript line %d in %s: %s",
                    line_num, self.path, exc,
                )
        return entries

    def restore_session(self) -> RestoredSession:
        """Rebuild full session state from JSONL entries."""
        entries = self.load_entries()
        result = RestoredSession()

        for entry in entries:
            if entry.type in ("user", "assistant", "tool", "system") and entry.message:
                result.session.messages.append(entry.message)

            elif entry.type == "custom-title" and entry.custom_title:
                result.custom_title = entry.custom_title
                result.title = entry.custom_title

            elif entry.type == "ai-title" and entry.ai_title:
                result.ai_title = entry.ai_title
                if not result.custom_title:
                    result.title = entry.ai_title

            elif entry.type == "plan-slug" and entry.slug:
                result.plan_slug = entry.slug

            elif entry.type == "content-replacement" and entry.content_replacements:
                result.content_replacements.extend(entry.content_replacements)

            elif entry.type == "tag" and entry.tag:
                result.tag = entry.tag

            elif entry.type == "plan-status" and entry.plan_status:
                result.plan_status = entry.plan_status

        if result.title == "新对话":
            result.title = _title_from_messages(result.session)

        if result.plan_slug:
            result.session.plan_slug = result.plan_slug

        if result.plan_status != "none":
            result.session.plan_status = result.plan_status

        return result

    # ------------------------------------------------------------------
    # Bulk write (for migration)
    # ------------------------------------------------------------------

    def write_from_session(
        self, session: Session, title: str | None = None,
    ) -> None:
        """Write an entire session as a JSONL transcript (used for migration)."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            for msg in session.messages:
                entry = entry_from_message(msg)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")
            if title and title != "新对话":
                entry = TranscriptEntry(type="ai-title", ai_title=title)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")
            if session.plan_slug:
                entry = TranscriptEntry(type="plan-slug", slug=session.plan_slug)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")
            if session.plan_status and session.plan_status != "none":
                entry = TranscriptEntry(type="plan-status", plan_status=session.plan_status)
                f.write(entry.model_dump_json(exclude_none=True) + "\n")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _title_from_messages(session: Session) -> str:
    for msg in session.messages:
        if msg.role == MessageRole.user:
            for block in msg.blocks:
                if block.type == "text" and block.text:
                    clean = block.text[:30].strip()
                    if not clean:
                        continue
                    return clean + ("..." if len(block.text) > 30 else "")
    return "新对话"
