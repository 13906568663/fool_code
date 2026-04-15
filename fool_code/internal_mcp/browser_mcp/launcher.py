"""Helpers for launching the built-in browser MCP sidecar as a stdio service."""

from __future__ import annotations

import sys
from typing import Any

from fool_code.internal_mcp.browser_mcp.types import BrowserMcpRuntimeConfig


def build_stdio_server_config(
    config: BrowserMcpRuntimeConfig,
    *,
    command: str | None = None,
) -> dict[str, Any]:
    """Build a normal stdio MCP config for the browser sidecar.

    This intentionally returns the same config shape that `McpServerManager`
    already understands, so the sidecar can plug into the existing architecture
    without a special transport.
    """

    resolved_command = command or sys.executable
    if getattr(sys, "frozen", False):
        args = ["--browser-mcp-sidecar"]
    else:
        args = ["-m", "fool_code.main", "--browser-mcp-sidecar"]
    return {
        "type": "stdio",
        "command": resolved_command,
        "args": args,
        "env": config.env_overrides(),
    }
