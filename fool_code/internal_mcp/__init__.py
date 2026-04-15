"""First-party MCP sidecars shipped with Fool Code.

`fool_code.mcp` contains the generic MCP client/runtime pieces used to talk to
any MCP server.

`fool_code.internal_mcp` is reserved for MCP servers implemented by this
project itself, such as `browser_mcp` and future built-in sidecars.
"""

from fool_code.internal_mcp.registry import INTERNAL_MCP_CONFIG_KEY, list_internal_mcp_services
from fool_code.internal_mcp.types import InternalMcpServiceDefinition

__all__ = [
    "INTERNAL_MCP_CONFIG_KEY",
    "InternalMcpServiceDefinition",
    "list_internal_mcp_services",
]
