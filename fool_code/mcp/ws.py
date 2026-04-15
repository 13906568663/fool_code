"""MCP WebSocket transport — bidirectional JSON-RPC over WebSocket.

Uses Python's built-in websockets or falls back to httpx-ws.
For simplicity we use the `websockets` library if available.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fool_code.mcp.types import JsonRpcRequest, JsonRpcResponse, McpTool, McpToolCallResult

logger = logging.getLogger(__name__)


class McpWebSocketProcess:
    """MCP client over WebSocket transport."""

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.headers = headers or {}
        self._request_id = 0
        self._initialized = False
        self._ws: Any = None
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._listen_task: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            import websockets
            extra_headers = self.headers if self.headers else None
            self._ws = await websockets.connect(self.url, additional_headers=extra_headers)
        except ImportError:
            raise RuntimeError(
                "WebSocket MCP transport requires 'websockets' package. "
                "Install with: uv add websockets"
            )
        self._listen_task = asyncio.create_task(self._listen())

    async def initialize(self) -> dict[str, Any]:
        response = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "fool-code", "version": "0.1.0"},
        })
        self._initialized = True
        await self._send_notification("notifications/initialized", {})
        return response

    async def list_tools(self) -> list[McpTool]:
        result = await self._send_request("tools/list", {})
        return [McpTool.model_validate(t) for t in result.get("tools", [])]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> McpToolCallResult:
        result = await self._send_request("tools/call", {"name": name, "arguments": arguments or {}})
        return McpToolCallResult.model_validate(result)

    async def shutdown(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ws:
            await self._ws.close()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        self._request_id += 1
        req_id = self._request_id
        request = JsonRpcRequest(id=req_id, method=method, params=params)

        future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        await self._ws.send(json.dumps(request.model_dump()))

        result = await asyncio.wait_for(future, timeout=300)
        if result.get("error"):
            err = result["error"]
            raise RuntimeError(f"MCP error ({err.get('code')}): {err.get('message')}")
        return result.get("result", {})

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self._ws:
            return
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._ws.send(json.dumps(msg))

    async def _listen(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                    msg_id = msg.get("id")
                    if msg_id is not None and msg_id in self._pending:
                        self._pending.pop(msg_id).set_result(msg)
                except (json.JSONDecodeError, Exception):
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP WebSocket listen error: %s", exc)
