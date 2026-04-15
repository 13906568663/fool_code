"""Session persistence — load/save JSON files + JSONL transcript support.

Supports both formats:
  - Legacy: {session_id}.json (single JSON dump)
  - New: {session_id}.jsonl (append-only transcript)
"""

from __future__ import annotations

import json
from pathlib import Path

from fool_code.types import Session


def save_session(session: Session, path: Path) -> None:
    """Save session as JSON (legacy format, used as fallback/snapshot)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = session.model_dump(exclude_none=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_session(path: Path) -> Session:
    """Load session from JSON file (legacy format)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return Session.model_validate(data)
