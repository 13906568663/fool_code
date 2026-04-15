"""MCP server manager — manages multiple MCP server connections.

Supports four transport types:
  - stdio  (subprocess with Content-Length framed JSON-RPC)
  - sse    (SSE stream for receiving, POST for sending)
  - http   (Streamable HTTP, POST with JSON or SSE responses)
  - ws     (bidirectional WebSocket JSON-RPC)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol

from fool_code.mcp.types import McpTool, McpToolCallResult
from fool_code.types import ToolDefinition, ToolFunction, ToolParameter

logger = logging.getLogger(__name__)

SUPPORTED_TRANSPORTS = {"stdio", "sse", "http", "ws", "websocket"}


class McpTransport(Protocol):
    """Common interface all MCP transports must implement."""

    async def start(self) -> None: ...
    async def initialize(self) -> dict[str, Any]: ...
    async def list_tools(self) -> list[McpTool]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> McpToolCallResult: ...
    async def shutdown(self) -> None: ...
    @property
    def is_initialized(self) -> bool: ...


class ManagedMcpTool:
    """An MCP tool bound to a specific server."""

    def __init__(self, server_name: str, tool: McpTool) -> None:
        self.server_name = server_name
        self.tool = tool
        self.qualified_name = f"mcp__{server_name}__{tool.name}"


def _create_transport(name: str, config: dict[str, Any]) -> McpTransport:
    """Create the appropriate transport instance from a server config dict."""
    server_type = config.get("type", "stdio")

    if server_type == "stdio":
        from fool_code.mcp.stdio import McpStdioProcess
        command = config.get("command", "")
        args = config.get("args", [])
        if not command:
            raise ValueError(f"MCP server '{name}' (stdio) has no command")
        env = {**os.environ}
        if config_env := config.get("env"):
            env.update(config_env)
        return McpStdioProcess(command, args, env)  # type: ignore[return-value]

    if server_type == "sse":
        from fool_code.mcp.sse import McpSseProcess
        url = config.get("url", "")
        if not url:
            raise ValueError(f"MCP server '{name}' (sse) has no url")
        headers = config.get("headers", {})
        return McpSseProcess(url, headers)  # type: ignore[return-value]

    if server_type == "http":
        from fool_code.mcp.http_transport import McpHttpProcess
        url = config.get("url", "")
        if not url:
            raise ValueError(f"MCP server '{name}' (http) has no url")
        headers = config.get("headers", {})
        return McpHttpProcess(url, headers)  # type: ignore[return-value]

    if server_type in ("ws", "websocket"):
        from fool_code.mcp.ws import McpWebSocketProcess
        url = config.get("url", "")
        if not url:
            raise ValueError(f"MCP server '{name}' (ws) has no url")
        headers = config.get("headers", {})
        return McpWebSocketProcess(url, headers)  # type: ignore[return-value]

    raise ValueError(f"Unsupported MCP transport type '{server_type}' for server '{name}'")


class McpServerManager:
    def __init__(self) -> None:
        self._servers: dict[str, Any] = {}
        self._server_configs: dict[str, dict[str, Any]] = {}
        self._tools: dict[str, ManagedMcpTool] = {}
        self._server_tools: dict[str, list[str]] = {}

    def add_server_config(self, name: str, config: dict[str, Any]) -> None:
        self._server_configs[name] = config

    def has_server_config(self, name: str) -> bool:
        return name in self._server_configs

    def server_configs(self) -> dict[str, dict[str, Any]]:
        return dict(self._server_configs)

    async def stop_server(self, name: str) -> None:
        proc = self._servers.pop(name, None)
        if proc:
            await proc.shutdown()
        tool_names = self._server_tools.pop(name, [])
        for tn in tool_names:
            self._tools.pop(tn, None)

    def server_initialized(self, name: str) -> bool:
        proc = self._servers.get(name)
        return proc is not None and proc.is_initialized

    def tools_for_server(self, name: str) -> list[str]:
        return self._server_tools.get(name, [])

    async def discover_tools(self) -> list[ManagedMcpTool]:
        all_tools: list[ManagedMcpTool] = []
        for name in list(self._server_configs.keys()):
            try:
                tools = await self.discover_tools_for_server(name)
                all_tools.extend(tools)
            except Exception as exc:
                logger.warning("Failed to discover tools for MCP server '%s': %s", name, exc)
        return all_tools

    async def discover_tools_for_server(self, name: str) -> list[ManagedMcpTool]:
        config = self._server_configs.get(name)
        if config is None:
            raise ValueError(f"No config for MCP server '{name}'")

        server_type = config.get("type", "stdio")
        if server_type not in SUPPORTED_TRANSPORTS:
            logger.info("Skipping unsupported MCP transport '%s' for server '%s'", server_type, name)
            return []

        proc = _create_transport(name, config)
        await proc.start()
        await proc.initialize()

        tools = await proc.list_tools()
        self._servers[name] = proc

        managed: list[ManagedMcpTool] = []
        tool_names: list[str] = []
        for tool in tools:
            mt = ManagedMcpTool(name, tool)
            self._tools[mt.qualified_name] = mt
            managed.append(mt)
            tool_names.append(mt.qualified_name)

        self._server_tools[name] = tool_names
        return managed

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any] | None = None) -> McpToolCallResult:
        mt = self._tools.get(qualified_name)
        if mt is None:
            raise ValueError(f"Unknown MCP tool: {qualified_name}")

        proc = self._servers.get(mt.server_name)
        if proc is None:
            raise RuntimeError(f"MCP server '{mt.server_name}' not running")

        return await proc.call_tool(mt.tool.name, arguments)

    async def shutdown_all(self) -> None:
        for proc in self._servers.values():
            try:
                await proc.shutdown()
            except Exception as exc:
                logger.warning("Error shutting down MCP server: %s", exc)
        self._servers.clear()
        self._tools.clear()


def mcp_tool_to_definition(mt: ManagedMcpTool) -> ToolDefinition:
    schema = mt.tool.inputSchema
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    return ToolDefinition(
        function=ToolFunction(
            name=mt.qualified_name,
            description=mt.tool.description or f"MCP tool: {mt.tool.name}",
            parameters=ToolParameter(
                properties=properties,
                required=required,
            ),
        )
    )
