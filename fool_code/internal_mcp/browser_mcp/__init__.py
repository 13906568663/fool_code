"""Built-in browser MCP sidecar package."""

from fool_code.internal_mcp.browser_mcp.manifest import (
    BROWSER_MCP_SERVICE,
    BROWSER_MCP_TOOLS,
)
from fool_code.internal_mcp.browser_mcp.launcher import build_stdio_server_config
from fool_code.internal_mcp.browser_mcp.server import BrowserMcpServer
from fool_code.internal_mcp.browser_mcp.types import BrowserMcpRuntimeConfig

__all__ = [
    "BROWSER_MCP_SERVICE",
    "BROWSER_MCP_TOOLS",
    "BrowserMcpRuntimeConfig",
    "BrowserMcpServer",
    "build_stdio_server_config",
]
