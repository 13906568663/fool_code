"""Fool Code user storage and workspace configuration."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "qwen3.5-plus"
FOOL_CODE_HOME_ENV = "FOOL_CODE_HOME"
FOOL_CODE_WORKSPACE_ENV = "FOOL_CODE_WORKSPACE_ROOT"
APP_DIRNAME = ".fool-code"
_LEGACY_DIRNAME = ".claw"


def user_home_dir() -> Path:
    home = (os.environ.get("HOME") or os.environ.get("USERPROFILE") or "").strip()
    if home:
        return Path(home).expanduser().resolve()
    return Path.home().resolve()


def default_workspace_root() -> Path:
    return user_home_dir()


def app_data_root() -> Path:
    override = (os.environ.get(FOOL_CODE_HOME_ENV) or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return default_workspace_root() / APP_DIRNAME


def config_dir(_workspace_root: Path | None = None) -> Path:
    return app_data_root()


def config_path(_workspace_root: Path | None = None) -> Path:
    return config_dir() / "settings.json"


def sessions_path(_workspace_root: Path | None = None) -> Path:
    return config_dir() / "sessions"


def skills_path(_workspace_root: Path | None = None) -> Path:
    return config_dir() / "skills"


def ensure_app_dirs(_workspace_root: Path | None = None) -> None:
    base = config_dir()
    base.mkdir(parents=True, exist_ok=True)
    (base / "sessions").mkdir(exist_ok=True)
    (base / "skills").mkdir(exist_ok=True)
    (base / "plans").mkdir(exist_ok=True)
    (base / "image-cache").mkdir(exist_ok=True)
    (base / "tool-results").mkdir(exist_ok=True)
    _migrate_legacy_storage(base)
    cfg = base / "settings.json"
    if not cfg.exists():
        cfg.write_text("{}", encoding="utf-8")


def read_config_root(_workspace_root: Path | None = None) -> dict[str, Any]:
    ensure_app_dirs()
    path = config_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_config_root(
    workspace_root_or_root: Path | dict[str, Any] | None,
    root: dict[str, Any] | None = None,
) -> None:
    if root is None:
        if not isinstance(workspace_root_or_root, dict):
            raise TypeError("write_config_root expects a config dict")
        payload = workspace_root_or_root
    else:
        payload = root

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_api_config(_workspace_root: Path | None = None) -> dict[str, Any] | None:
    from fool_code.runtime import providers_config

    return providers_config.read_api_config()


def load_api_config_to_env(_workspace_root: Path | None = None) -> None:
    api = read_api_config()
    if api is None:
        return
    api_key = api.get("apiKey", "")
    base_url = api.get("baseUrl", "")
    if not api_key:
        return

    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = api_key
    if base_url and not os.environ.get("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = base_url


def resolve_workspace_root() -> Path:
    ensure_app_dirs()

    raw = _workspace_override_from_env()
    if raw:
        return raw

    data = read_config_root()
    wr = str(data.get("workspace_root", "")).strip()
    if wr:
        p = Path(wr).expanduser()
        if p.is_dir():
            return p.resolve()

    return default_workspace_root()


def active_workspace_root() -> Path:
    override = _workspace_override_from_env()
    if override:
        return override
    data = read_config_root()
    raw = str(data.get("workspace_root", "")).strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_dir():
            return p.resolve()
    return default_workspace_root()


def export_runtime_env(workspace_root: Path) -> Path:
    ensure_app_dirs()
    resolved = workspace_root.expanduser().resolve()
    os.environ[FOOL_CODE_HOME_ENV] = str(app_data_root())
    os.environ[FOOL_CODE_WORKSPACE_ENV] = str(resolved)
    return resolved


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _workspace_override_from_env() -> Path | None:
    raw = (os.environ.get(FOOL_CODE_WORKSPACE_ENV) or "").strip()
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
    except OSError:
        return None
    return None


def _migrate_legacy_storage(target_root: Path) -> None:
    target_cfg = target_root / "settings.json"
    target_sessions = target_root / "sessions"
    target_skills = target_root / "skills"

    for legacy_root in _legacy_storage_candidates():
        legacy_cfg = legacy_root / "settings.json"
        legacy_sessions = legacy_root / "sessions"
        legacy_skills = legacy_root / "skills"

        if _config_missing_or_empty(target_cfg) and legacy_cfg.is_file():
            shutil.copy2(legacy_cfg, target_cfg)

        if _dir_missing_or_empty(target_sessions) and legacy_sessions.is_dir():
            shutil.copytree(legacy_sessions, target_sessions, dirs_exist_ok=True)

        if _dir_missing_or_empty(target_skills) and legacy_skills.is_dir():
            shutil.copytree(legacy_skills, target_skills, dirs_exist_ok=True)


def _legacy_storage_candidates() -> list[Path]:
    candidates: list[Path] = []
    for base in (
        Path.cwd(),
        Path(__file__).resolve().parents[2],
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None,
    ):
        if base is None:
            continue
        candidate = (base / _LEGACY_DIRNAME).resolve()
        if not candidate.is_dir():
            continue
        if candidate == app_data_root():
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _config_missing_or_empty(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not raw or raw == "{}":
        return True
    try:
        data = json.loads(raw)
    except Exception:
        return False
    return not bool(data)


def _dir_missing_or_empty(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False
    return False
