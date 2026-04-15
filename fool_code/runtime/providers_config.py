"""Multi model-provider profiles in settings.json (modelProviders + defaultProviderId)."""

from __future__ import annotations

import uuid
from typing import Any

from fool_code.runtime.config import (
    DEFAULT_MODEL,
    read_config_root,
    write_config_root,
)


def _norm_saved(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def row_to_api_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": row.get("provider", "openai"),
        "apiKey": row.get("apiKey", "") or "",
        "baseUrl": row.get("baseUrl", "") or "",
        "model": (row.get("model") or DEFAULT_MODEL) or DEFAULT_MODEL,
        "savedModels": _norm_saved(row.get("savedModels")),
    }


def sync_legacy_api_from_providers(root: dict[str, Any]) -> None:
    row = default_provider_row(root)
    if row:
        root["api"] = row_to_api_dict(row)
    else:
        root.pop("api", None)


def default_provider_row(root: dict[str, Any]) -> dict[str, Any] | None:
    profs = root.get("modelProviders")
    if not isinstance(profs, list) or not profs:
        return None
    pid = (root.get("defaultProviderId") or "").strip()
    for p in profs:
        if isinstance(p, dict) and p.get("id") == pid:
            return p
    first = next((p for p in profs if isinstance(p, dict)), None)
    return first


def provider_row_by_id(root: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    if not provider_id.strip():
        return None
    profs = root.get("modelProviders")
    if not isinstance(profs, list):
        return None
    for p in profs:
        if isinstance(p, dict) and p.get("id") == provider_id.strip():
            return p
    return None


def provider_row_for_session(
    root: dict[str, Any], chat_provider_id: str | None
) -> dict[str, Any] | None:
    pid = (chat_provider_id or "").strip()
    if pid:
        row = provider_row_by_id(root, pid)
        if row:
            return row
    return default_provider_row(root)


def load_root_migrated(workspace_root=None) -> dict[str, Any]:
    root = read_config_root(workspace_root)
    changed = False
    if root.get("modelProviders") is None:
        api = root.get("api")
        if isinstance(api, dict) and (
            api.get("apiKey") or api.get("baseUrl") or api.get("model")
        ):
            root["modelProviders"] = [
                {
                    "id": "default",
                    "label": "默认",
                    "provider": api.get("provider", "openai"),
                    "apiKey": api.get("apiKey", ""),
                    "baseUrl": api.get("baseUrl", ""),
                    "model": api.get("model") or DEFAULT_MODEL,
                    "savedModels": _norm_saved(api.get("savedModels")),
                }
            ]
            root["defaultProviderId"] = "default"
            changed = True
        else:
            root["modelProviders"] = []
            root["defaultProviderId"] = ""
    sync_legacy_api_from_providers(root)
    if changed:
        write_config_root(workspace_root, root)
    return root


def read_api_config(workspace_root=None) -> dict[str, Any] | None:
    """Active default provider as legacy-shaped ``api`` dict (for env + tools)."""
    root = load_root_migrated(workspace_root)
    return root.get("api")


def read_api_config_for_session(
    workspace_root, chat_provider_id: str | None
) -> dict[str, Any] | None:
    root = load_root_migrated(workspace_root)
    row = provider_row_for_session(root, chat_provider_id)
    if not row:
        return None
    return row_to_api_dict(row)


def any_provider_has_key(workspace_root=None) -> bool:
    root = load_root_migrated(workspace_root)
    profs = root.get("modelProviders")
    if not isinstance(profs, list):
        return False
    return any(
        isinstance(p, dict) and (p.get("apiKey") or "").strip()
        for p in profs
    )


def provider_summaries(root: dict[str, Any]) -> list[dict[str, str]]:
    profs = root.get("modelProviders")
    if not isinstance(profs, list):
        return []
    out: list[dict[str, str]] = []
    for p in profs:
        if not isinstance(p, dict):
            continue
        pid = p.get("id", "")
        if not pid:
            continue
        out.append(
            {
                "id": str(pid),
                "label": str(p.get("label") or pid),
            }
        )
    return out


def new_provider_id() -> str:
    return f"p-{uuid.uuid4().hex[:12]}"


def save_model_providers(
    workspace_root,
    providers_raw: list[dict[str, Any]],
    default_provider_id: str,
) -> dict[str, Any]:
    """Merge api_key from previous file when empty string; write and return root."""
    prev_root = load_root_migrated(workspace_root)
    prev_by_id: dict[str, dict[str, Any]] = {}
    for p in prev_root.get("modelProviders") or []:
        if isinstance(p, dict) and p.get("id"):
            prev_by_id[str(p["id"])] = p

    cleaned: list[dict[str, Any]] = []
    for p in providers_raw:
        if not isinstance(p, dict):
            continue
        pid = (p.get("id") or "").strip() or new_provider_id()
        old = prev_by_id.get(pid, {})
        key = (p.get("apiKey") or p.get("api_key") or "").strip()
        if not key:
            key = (old.get("apiKey", "") or "").strip()
        cleaned.append(
            {
                "id": pid,
                "label": (p.get("label") or "未命名").strip() or pid,
                "provider": (p.get("provider") or "openai").strip() or "openai",
                "apiKey": key,
                "baseUrl": (p.get("baseUrl") or p.get("base_url") or "").strip()
                or (old.get("baseUrl", "") or ""),
                "model": (p.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
                "savedModels": _norm_saved(
                    p.get("savedModels") if p.get("savedModels") is not None else old.get("savedModels")
                ),
            }
        )

    root = read_config_root(workspace_root)
    root["modelProviders"] = cleaned
    dpid = (default_provider_id or "").strip()
    if cleaned and dpid not in {c["id"] for c in cleaned}:
        dpid = cleaned[0]["id"]
    root["defaultProviderId"] = dpid if cleaned else ""
    sync_legacy_api_from_providers(root)
    write_config_root(workspace_root, root)
    return root
