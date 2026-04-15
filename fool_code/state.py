"""Application state — ChatSession, SessionStore, and AppState.

Extracted from app.py to reduce the monolithic module's complexity and provide
a clean boundary between state management and HTTP routing.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from fool_code.mcp.manager import McpServerManager
from fool_code.runtime.config import (
    DEFAULT_MODEL,
    default_workspace_root,
    read_config_root,
    sessions_path,
)
from fool_code.runtime.hooks import HookConfig
from fool_code.runtime.permissions import PermissionGate, PermissionMode, PermissionPolicy
from fool_code.runtime.providers_config import read_api_config_for_session
from fool_code.runtime.message_pipeline import normalize_for_display
from fool_code.runtime.session import load_session, save_session
from fool_code.runtime.transcript import TranscriptStorage
from fool_code.tools.registry import ToolRegistry
from fool_code.types import (
    ChatMessage,
    MessageRole,
    Session,
    SessionListItem,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ChatSession / SessionStore — in-memory session management
# ---------------------------------------------------------------------------

class ChatSession:
    def __init__(self, id: str | None = None) -> None:
        millis = int(time.time() * 1000)
        self.id = id or f"session-{millis}"
        self.title = "新对话"
        self.created_at = millis // 1000
        self.session = Session()
        self.messages: list[ChatMessage] = []
        self._persisted_msg_count: int = 0


def chat_messages_from_session(session: Session) -> list[ChatMessage]:
    """Build UI-layer ChatMessages via the message pipeline."""
    return normalize_for_display(session.messages)


def title_from_session(session: Session) -> str:
    for msg in session.messages:
        if msg.role == MessageRole.user:
            for block in msg.blocks:
                if block.type == "text" and block.text:
                    return extract_title(block.text)
    return "新对话"


def extract_title(text: str) -> str:
    clean = text[:30].strip()
    if not clean:
        return "新对话"
    if len(clean) < len(text[:30]):
        return clean + "..."
    return clean


def created_at_from_id(id: str) -> int:
    prefix = "session-"
    if id.startswith(prefix):
        try:
            return int(id[len(prefix):]) // 1000
        except ValueError:
            pass
    return int(time.time())


def persist_session(cs: ChatSession, workspace_root: Path) -> None:
    """Persist session incrementally (append new messages to JSONL) + JSON snapshot."""
    sess_dir = sessions_path(workspace_root)
    transcript = TranscriptStorage(cs.id, sess_dir)
    total = len(cs.session.messages)
    start = cs._persisted_msg_count

    if start == 0:
        transcript.write_from_session(cs.session, title=cs.title)
    else:
        transcript.append_messages_from(cs.session, start, title=cs.title)

    cs._persisted_msg_count = total

    json_path = sess_dir / f"{cs.id}.json"
    save_session(cs.session, json_path)


def read_saved_models(api: dict[str, Any] | None) -> list[str]:
    if not api:
        return []
    raw = api.get("savedModels", [])
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def session_effective_model(cs: ChatSession, workspace_root: Path) -> str:
    api = read_api_config_for_session(
        workspace_root, cs.session.chat_provider_id
    ) or {}
    default = (api.get("model", "") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    cm = (cs.session.chat_model or "").strip()
    return cm if cm else default


class SessionStore:
    def __init__(self, workspace_root: Path) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.active_id: str = ""
        self._load(workspace_root)

    def _load(self, workspace_root: Path) -> None:
        sess_dir = sessions_path(workspace_root)
        sess_dir.mkdir(parents=True, exist_ok=True)

        loaded_ids: set[str] = set()

        # Phase 1: Load JSONL transcripts (preferred format)
        for path in sess_dir.glob("*.jsonl"):
            sid = path.stem
            try:
                transcript = TranscriptStorage(sid, sess_dir)
                restored = transcript.restore_session()
                cs = ChatSession(id=sid)
                cs.session = restored.session
                cs.messages = chat_messages_from_session(restored.session)
                cs.title = restored.title
                cs.created_at = created_at_from_id(sid)
                cs._persisted_msg_count = len(restored.session.messages)
                self.sessions[sid] = cs
                loaded_ids.add(sid)
            except Exception as exc:
                logger.warning("Failed to load JSONL session %s: %s", sid, exc)

        # Phase 2: Load legacy JSON (migrate to JSONL on first load)
        for path in sess_dir.glob("*.json"):
            sid = path.stem
            if sid in loaded_ids:
                continue
            try:
                session = load_session(path)
                cs = ChatSession(id=sid)
                cs.session = session
                cs.messages = chat_messages_from_session(session)
                cs.title = title_from_session(session)
                cs.created_at = created_at_from_id(sid)
                cs._persisted_msg_count = len(session.messages)
                self.sessions[sid] = cs

                # Migrate: write JSONL
                transcript = TranscriptStorage(sid, sess_dir)
                transcript.write_from_session(session, title=cs.title)
                # Rename old JSON to .json.bak
                bak = path.with_suffix(".json.bak")
                try:
                    path.rename(bak)
                    logger.info("Migrated session %s from JSON to JSONL", sid)
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("Failed to load session %s: %s", sid, exc)

        if not self.sessions:
            initial = ChatSession()
            persist_session(initial, workspace_root)
            self.sessions[initial.id] = initial
            self.active_id = initial.id
            return

        self.active_id = max(self.sessions.values(), key=lambda s: s.created_at).id

    def active_session(self) -> ChatSession:
        return self.sessions[self.active_id]

    def sorted_sessions(self) -> list[SessionListItem]:
        items = [
            SessionListItem(
                id=s.id,
                title=s.title,
                created_at=s.created_at,
                message_count=len(s.messages),
                active=(s.id == self.active_id),
            )
            for s in self.sessions.values()
        ]
        items.sort(key=lambda x: x.created_at, reverse=True)
        return items


# ---------------------------------------------------------------------------
# AppState – shared application state
# ---------------------------------------------------------------------------

class AppState:
    def __init__(self) -> None:
        self.model: str = DEFAULT_MODEL
        self.system_prompt: list[str] = []
        self.store: SessionStore | None = None
        self.tool_registry: ToolRegistry = ToolRegistry()
        self.permission_policy = PermissionPolicy(PermissionMode.DANGER_FULL_ACCESS)
        self.permission_gate = PermissionGate(self.permission_policy)
        self.workspace_root: Path = default_workspace_root()
        self.mcp_manager: McpServerManager | None = None
        self.mcp_errors: dict[str, str] = {}
        self.hook_config: HookConfig = HookConfig()
        self.lock = threading.Lock()
        self.conversation_mode: str = "normal"  # "normal" | "plan"
        self.last_plan_text: str = ""

    def reload_hook_config(self) -> None:
        root = read_config_root(self.workspace_root)
        self.hook_config = HookConfig.from_settings(root)
