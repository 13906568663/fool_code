"""Python wrapper around the Rust SkillStore engine.

Handles DB path resolution, lazy initialization, and graceful fallback.
The native Rust module ``skill_store`` must be built with maturin first.
If the native module is not found, all operations silently return None.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_store_instance: Any | None = None
_import_failed: bool = False


def is_skill_store_enabled() -> bool:
    try:
        from fool_code.runtime.config import read_config_root
        root = read_config_root()
        return bool(root.get("skillStoreEnabled", True))
    except Exception:
        return True


def skill_store_db_path() -> Path:
    try:
        from fool_code.runtime.config import app_data_root
        return app_data_root() / "data" / "skills.db"
    except Exception:
        return Path.home() / ".fool-code" / "data" / "skills.db"


def get_store() -> Any | None:
    global _store_instance, _import_failed
    if _store_instance is not None:
        return _store_instance

    if _import_failed:
        return None

    if not is_skill_store_enabled():
        return None

    try:
        import skill_store as _mod  # type: ignore[import-untyped]
    except ImportError:
        _import_failed = True
        logger.info("skill_store native module not available — Skill Store disabled")
        return None

    db = skill_store_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        _store_instance = _mod.SkillStore(str(db))
        logger.info("Skill Store opened: %s", db)
    except Exception as exc:
        logger.warning("Failed to open Skill Store: %s", exc)
        return None

    return _store_instance


def close_store() -> None:
    global _store_instance
    if _store_instance is not None:
        try:
            _store_instance.close()
        except Exception:
            pass
        _store_instance = None


def reset_store() -> None:
    """Close and re-open the store. Useful after a full reindex."""
    close_store()
    get_store()
