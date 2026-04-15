"""Registry of first-party MCP sidecars.

This package-level registry is intentionally separate from the runtime MCP
manager. It only describes which built-in services exist; startup and launch
logic can consume these definitions later without mixing them into
`fool_code.mcp`.
"""

from __future__ import annotations

from fool_code.internal_mcp.browser_mcp.manifest import BROWSER_MCP_SERVICE
from fool_code.internal_mcp.types import InternalMcpServiceDefinition

INTERNAL_MCP_CONFIG_KEY = "builtinMcpServices"


def list_internal_mcp_services() -> list[InternalMcpServiceDefinition]:
    """Return all built-in MCP service definitions known to the app."""

    return [
        BROWSER_MCP_SERVICE,
    ]
