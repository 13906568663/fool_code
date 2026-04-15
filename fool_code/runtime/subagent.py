"""Sub-agent infrastructure — multi-model role management.

Uses agent_types.BUILT_IN_AGENTS as the single source of truth for which
model roles exist. Adding a new built-in agent with a non-empty model_role
automatically makes it configurable in settings.modelRoles.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fool_code.providers.openai_compat import OpenAICompatProvider
from fool_code.runtime.agent_types import BUILT_IN_AGENTS, AgentDefinition
from fool_code.runtime.config import DEFAULT_MODEL, read_config_root
from fool_code.runtime.providers_config import (
    load_root_migrated,
    provider_row_by_id,
    default_provider_row,
    row_to_api_dict,
)

logger = logging.getLogger(__name__)

_MODEL_ROLE_KEYS: list[str] = sorted(
    {a.model_role for a in BUILT_IN_AGENTS.values() if a.model_role}
)


def configurable_roles() -> list[str]:
    """Return the list of model-role keys derived from built-in agents."""
    return list(_MODEL_ROLE_KEYS)


def read_model_roles(workspace_root=None) -> dict[str, dict]:
    root = read_config_root(workspace_root)
    raw = root.get("modelRoles")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict] = {}
    for role in _MODEL_ROLE_KEYS:
        entry = raw.get(role)
        if isinstance(entry, dict):
            result[role] = {
                "providerId": str(entry.get("providerId", "") or "").strip(),
                "model": str(entry.get("model", "") or "").strip(),
                "enabled": entry.get("enabled", role != "verification"),
            }
    return result


def save_model_roles(workspace_root, roles: dict[str, dict]) -> None:
    from fool_code.runtime.config import write_config_root
    root = read_config_root(workspace_root)
    root["modelRoles"] = roles
    write_config_root(workspace_root, root)


def create_role_provider(
    role: str,
    workspace_root=None,
    fallback_api_key: str = "",
    fallback_base_url: str = "",
    fallback_model: str = "",
) -> OpenAICompatProvider | None:
    """Create an OpenAICompatProvider for the given role.

    Falls back to the default provider's credentials when the role has no
    dedicated provider configured. Returns None if the role is disabled.
    """
    roles = read_model_roles(workspace_root)
    role_cfg = roles.get(role, {})

    if not role_cfg.get("enabled", role != "verification"):
        logger.info("Role '%s' is disabled, skipping provider creation", role)
        return None

    role_provider_id = role_cfg.get("providerId", "")
    role_model = role_cfg.get("model", "")

    root = load_root_migrated(workspace_root)

    api_key = ""
    base_url = ""

    if role_provider_id:
        row = provider_row_by_id(root, role_provider_id)
        if row:
            api_dict = row_to_api_dict(row)
            api_key = api_dict.get("apiKey", "")
            base_url = api_dict.get("baseUrl", "")
            if not role_model:
                role_model = api_dict.get("model", "")

    if not api_key:
        row = default_provider_row(root)
        if row:
            api_dict = row_to_api_dict(row)
            api_key = api_dict.get("apiKey", "")
            base_url = base_url or api_dict.get("baseUrl", "")
            if not role_model:
                role_model = api_dict.get("model", "")

    if not api_key:
        api_key = fallback_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not base_url:
        base_url = fallback_base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if not role_model:
        role_model = fallback_model or DEFAULT_MODEL

    if not api_key:
        logger.warning("No API key available for role '%s'", role)
        return None

    return OpenAICompatProvider(
        api_key=api_key,
        base_url=base_url,
        model=role_model,
    )
