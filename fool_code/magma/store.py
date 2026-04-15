"""Python wrapper around the Rust MagmaStore engine.

Handles DB path resolution, lazy initialization, and graceful fallback
if the native module is not available.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fool_code.runtime.config import app_data_root, read_config_root

logger = logging.getLogger(__name__)

_store_instance: Any | None = None


def is_magma_enabled() -> bool:
    root = read_config_root()
    return bool(root.get("magmaMemoryEnabled", True))


def magma_db_path() -> Path:
    return app_data_root() / "data" / "magma.db"


def get_store() -> Any | None:
    """Return the global MagmaStore singleton, creating it on first call.

    Returns None if MAGMA is disabled or the native module is unavailable.
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    if not is_magma_enabled():
        return None

    try:
        import magma_memory  # type: ignore[import-untyped]
    except ImportError:
        logger.info("magma_memory native module not available — MAGMA disabled")
        return None

    db = magma_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        _store_instance = magma_memory.MagmaStore(str(db))
        logger.info("MAGMA store opened: %s", db)
    except Exception as exc:
        logger.warning("Failed to open MAGMA store: %s", exc)
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
