"""MCP server management and browser MCP routes."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

from fastapi import APIRouter

from fool_code.api_types import (
    BuiltinBrowserMcpResponse,
    ConnectMcpServerRequest,
    ConnectMcpServerResponse,
    DeleteMcpServerRequest,
    DisconnectMcpServerRequest,
    McpServerInfo,
    McpServersResponse,
    SaveBuiltinBrowserMcpRequest,
    SaveMcpServerRequest,
    ToggleMcpServerRequest,
)
from fool_code.internal_mcp.browser_mcp import BrowserMcpRuntimeConfig, build_stdio_server_config
from fool_code.internal_mcp.browser_mcp.manifest import (
    DEFAULT_BRIDGE_HOST,
    DEFAULT_BRIDGE_PATH,
    DEFAULT_BRIDGE_PORT,
    DEFAULT_BRIDGE_TOKEN,
)
from fool_code.internal_mcp.registry import INTERNAL_MCP_CONFIG_KEY
from fool_code.mcp.manager import McpServerManager, mcp_tool_to_definition
from fool_code.runtime.config import config_path, read_config_root, write_config_root
from fool_code.runtime.prompt import build_system_prompt
from fool_code.state import AppState

logger = logging.getLogger(__name__)


def _browser_settings_from_root(root: dict[str, Any]) -> dict[str, Any]:
    builtin_root = root.get(INTERNAL_MCP_CONFIG_KEY) or {}
    raw = builtin_root.get("browser") or {}
    try:
        bridge_port = int(raw.get("bridgePort", DEFAULT_BRIDGE_PORT))
    except (TypeError, ValueError):
        bridge_port = DEFAULT_BRIDGE_PORT
    pairing_token = str(raw.get("pairingToken", DEFAULT_BRIDGE_TOKEN)).strip()
    if not pairing_token:
        pairing_token = DEFAULT_BRIDGE_TOKEN
    return {
        "enabled": bool(raw.get("enabled", True)),
        "autoStart": bool(raw.get("autoStart", True)),
        "bridgeHost": DEFAULT_BRIDGE_HOST,
        "bridgePort": bridge_port,
        "bridgePath": DEFAULT_BRIDGE_PATH,
        "pairingToken": pairing_token,
    }


def _save_browser_settings(workspace_root, settings: dict[str, Any]) -> dict[str, Any]:
    root = read_config_root(workspace_root)
    builtin_root = root.setdefault(INTERNAL_MCP_CONFIG_KEY, {})
    builtin_root["browser"] = {
        "enabled": bool(settings.get("enabled", True)),
        "autoStart": bool(settings.get("autoStart", True)),
        "bridgePort": int(settings.get("bridgePort", DEFAULT_BRIDGE_PORT)),
        "pairingToken": str(settings.get("pairingToken", DEFAULT_BRIDGE_TOKEN)),
    }
    write_config_root(workspace_root, root)
    return root


def _browser_runtime_config(settings: dict[str, Any]) -> BrowserMcpRuntimeConfig:
    cfg = BrowserMcpRuntimeConfig(
        host=str(settings["bridgeHost"]), port=int(settings["bridgePort"]),
        path=str(settings["bridgePath"]), token=str(settings["pairingToken"]),
    )
    token = cfg.normalized_token()
    if token == cfg.token:
        return cfg
    return BrowserMcpRuntimeConfig(
        host=cfg.host, port=cfg.port, path=cfg.path, token=token,
        call_timeout_seconds=cfg.call_timeout_seconds,
    )


def effective_mcp_configs(root: dict[str, Any]) -> dict[str, dict[str, Any]]:
    servers_map = {
        str(name): cfg
        for name, cfg in (root.get("mcpServers") or {}).items()
        if isinstance(cfg, dict) and not cfg.get("disabled", False)
    }
    browser_settings = _browser_settings_from_root(root)
    if browser_settings["enabled"] and browser_settings["autoStart"]:
        runtime_cfg = _browser_runtime_config(browser_settings)
        servers_map["browser"] = build_stdio_server_config(runtime_cfg)
    return servers_map


def _browser_mcp_response(state: AppState) -> BuiltinBrowserMcpResponse:
    root = read_config_root(state.workspace_root)
    settings = _browser_settings_from_root(root)
    runtime_cfg = _browser_runtime_config(settings)
    status = "disabled" if not settings["enabled"] else "disconnected"
    tools: list[str] = []
    error = state.mcp_errors.get("browser")
    if state.mcp_manager and state.mcp_manager.server_initialized("browser"):
        status = "connected"
        tools = state.mcp_manager.tools_for_server("browser")
    elif settings["enabled"] and error:
        status = "error"
    return BuiltinBrowserMcpResponse(
        enabled=bool(settings["enabled"]), auto_start=bool(settings["autoStart"]),
        status=status, bridge_host=runtime_cfg.host, bridge_port=runtime_cfg.port,
        bridge_path=runtime_cfg.path, pairing_token=runtime_cfg.token,
        ws_url=runtime_cfg.ws_url(), tools=tools, error=error,
    )


def _read_mcp_servers_response(state: AppState) -> McpServersResponse:
    root = read_config_root(state.workspace_root)
    servers_map = root.get("mcpServers", {})
    cp = str(config_path(state.workspace_root))
    servers: list[McpServerInfo] = []
    for name, cfg in servers_map.items():
        server_type = cfg.get("type", "stdio")
        command = cfg.get("command", "")
        args = cfg.get("args", [])
        url = cfg.get("url", "")
        enabled = not cfg.get("disabled", False)
        status = "disconnected"
        tools: list[str] = []
        error = state.mcp_errors.get(name)
        if not enabled:
            status = "disabled"
        elif state.mcp_manager:
            if state.mcp_manager.server_initialized(name):
                status = "connected"
                tools = state.mcp_manager.tools_for_server(name)
            elif error:
                status = "error"
        servers.append(McpServerInfo(
            name=name, server_type=server_type, command=command,
            args=args, url=url, status=status, enabled=enabled,
            error=error, tools=tools,
        ))
    return McpServersResponse(servers=servers, config_path=cp)


def create_mcp_router(state: AppState, *, init_mcp) -> APIRouter:
    """Create MCP router. `init_mcp` is the async MCP init callback from app.py."""
    router = APIRouter()

    def _refresh_system_prompt() -> None:
        """Rebuild system prompt so LLM sees the current set of MCP tools."""
        mcp_names = state.tool_registry.mcp_tool_names()
        state.system_prompt = build_system_prompt(
            state.workspace_root, mcp_names or None,
        )

    @router.get("/api/mcp-servers")
    async def get_mcp_servers() -> McpServersResponse:
        return _read_mcp_servers_response(state)

    @router.get("/api/internal-mcp/browser")
    async def get_builtin_browser_mcp() -> BuiltinBrowserMcpResponse:
        return _browser_mcp_response(state)

    @router.post("/api/internal-mcp/browser")
    async def save_builtin_browser_mcp(
        req: SaveBuiltinBrowserMcpRequest,
    ) -> BuiltinBrowserMcpResponse:
        root = read_config_root(state.workspace_root)
        current = _browser_settings_from_root(root)
        pairing_token = (
            secrets.token_urlsafe(24)
            if req.regenerate_token
            else (req.pairing_token or current["pairingToken"] or DEFAULT_BRIDGE_TOKEN)
        )
        bridge_port = req.bridge_port or int(current["bridgePort"])
        _save_browser_settings(state.workspace_root, {
            "enabled": req.enabled, "autoStart": req.auto_start,
            "bridgePort": bridge_port, "pairingToken": pairing_token,
        })
        await init_mcp(state)
        return _browser_mcp_response(state)

    @router.post("/api/internal-mcp/browser/reconnect")
    async def reconnect_builtin_browser_mcp() -> BuiltinBrowserMcpResponse:
        await init_mcp(state)
        return _browser_mcp_response(state)

    @router.post("/api/mcp-servers/save")
    async def save_mcp_server(req: SaveMcpServerRequest) -> McpServersResponse:
        root = read_config_root(state.workspace_root)
        mcp_servers = root.setdefault("mcpServers", {})
        existing = mcp_servers.get(req.name, {})
        server_obj: dict[str, Any] = {"type": req.server_type}
        if req.server_type == "stdio":
            server_obj["command"] = req.command
            if req.args:
                server_obj["args"] = req.args
        else:
            if req.url:
                server_obj["url"] = req.url
        if not req.enabled:
            server_obj["disabled"] = True
        elif "disabled" in existing:
            pass  # don't carry over disabled flag when enabling
        mcp_servers[req.name] = server_obj
        write_config_root(state.workspace_root, root)
        return _read_mcp_servers_response(state)

    @router.post("/api/mcp-servers/toggle")
    async def toggle_mcp_server(req: ToggleMcpServerRequest) -> McpServersResponse:
        root = read_config_root(state.workspace_root)
        mcp_servers = root.get("mcpServers", {})
        cfg = mcp_servers.get(req.name)
        if cfg is None:
            return _read_mcp_servers_response(state)
        if req.enabled:
            cfg.pop("disabled", None)
        else:
            cfg["disabled"] = True
            # Stop the server when disabling
            if state.mcp_manager:
                await state.mcp_manager.stop_server(req.name)
                state.tool_registry.unregister_mcp_server(req.name)
            state.mcp_errors.pop(req.name, None)
        write_config_root(state.workspace_root, root)
        _refresh_system_prompt()
        return _read_mcp_servers_response(state)

    @router.post("/api/mcp-servers/disconnect")
    async def disconnect_mcp_server(req: DisconnectMcpServerRequest) -> McpServersResponse:
        if state.mcp_manager:
            await state.mcp_manager.stop_server(req.name)
            state.tool_registry.unregister_mcp_server(req.name)
        state.mcp_errors.pop(req.name, None)
        _refresh_system_prompt()
        return _read_mcp_servers_response(state)

    @router.post("/api/mcp-servers/delete")
    async def delete_mcp_server(req: DeleteMcpServerRequest) -> McpServersResponse:
        root = read_config_root(state.workspace_root)
        mcp = root.get("mcpServers", {})
        mcp.pop(req.name, None)
        write_config_root(state.workspace_root, root)
        state.mcp_errors.pop(req.name, None)
        if state.mcp_manager:
            await state.mcp_manager.stop_server(req.name)
            state.tool_registry.unregister_mcp_server(req.name)
        _refresh_system_prompt()
        return _read_mcp_servers_response(state)

    @router.post("/api/mcp-servers/connect")
    async def connect_mcp_server(req: ConnectMcpServerRequest) -> ConnectMcpServerResponse:
        if state.mcp_manager is None:
            root = read_config_root(state.workspace_root)
            servers_map = effective_mcp_configs(root)
            if servers_map:
                state.mcp_manager = McpServerManager()
                for name, cfg in servers_map.items():
                    state.mcp_manager.add_server_config(name, cfg)
        if state.mcp_manager is None:
            return ConnectMcpServerResponse(
                success=False, status="error", error="MCP manager not initialized",
            )
        root = read_config_root(state.workspace_root)
        server_cfg = root.get("mcpServers", {}).get(req.name)
        if server_cfg and not state.mcp_manager.has_server_config(req.name):
            state.mcp_manager.add_server_config(req.name, server_cfg)
        try:
            tools = await asyncio.wait_for(
                state.mcp_manager.discover_tools_for_server(req.name), timeout=30,
            )
            for mt in tools:
                defn = mcp_tool_to_definition(mt)
                state.tool_registry.register_mcp_tool(mt.qualified_name, defn)
            tool_names = [t.qualified_name for t in tools]
            state.mcp_errors.pop(req.name, None)
            _refresh_system_prompt()
            logger.info("[MCP] Connected %s, discovered %d tools", req.name, len(tools))
            return ConnectMcpServerResponse(
                success=True, status="connected", tools=tool_names,
            )
        except asyncio.TimeoutError:
            state.mcp_errors[req.name] = "Connection timed out (30s)"
            return ConnectMcpServerResponse(
                success=False, status="error", error="Connection timed out (30s)",
            )
        except Exception as exc:
            state.mcp_errors[req.name] = str(exc)
            return ConnectMcpServerResponse(
                success=False, status="error", error=str(exc),
            )

    return router
