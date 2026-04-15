"""MCP Streamable HTTP transport — newer MCP protocol using POST + optional SSE responses.

Ref: https://spec.modelcontextprotocol.io/specification/2025-03-26/basic/transports/#streamable-http
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from fool_code.mcp.types import JsonRpcRequest, JsonRpcResponse, McpTool, McpToolCallResult

logger = logging.getLogger(__name__)


class McpHttpProcess:
    """MCP client over Streamable HTTP transport.

    All communication happens via POST to a single endpoint.
    Server may respond with JSON or SSE stream.
    Session tracking via Mcp-Session-Id header.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.headers = headers or {}
        self._client = httpx.AsyncClient(timeout=300, headers=self.headers)
        self._request_id = 0
        self._initialized = False
        self._session_id: str | None = None

    async def start(self) -> None:
        pass

    async def initialize(self) -> dict[str, Any]:
        response = await self._send_request("initialize", {
            "protocolVersion": "2025-03-26",
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
        if self._session_id:
            try:
                await self._client.delete(
                    self.url,
                    headers=self._build_headers(),
                )
            except Exception:
                pass
        await self._client.aclose()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def _build_headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request = JsonRpcRequest(id=self._request_id, method=method, params=params)

        resp = await self._client.post(
            self.url,
            json=request.model_dump(),
            headers=self._build_headers(),
        )

        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]

        if resp.status_code not in (200, 202):
            raise RuntimeError(f"MCP HTTP error: {resp.status_code} {resp.text}")

        content_type = resp.headers.get("content-type", "")

        if "text/event-stream" in content_type:
            return self._parse_sse_response(resp.text, self._request_id)

        if resp.status_code == 202:
            return {}

        data = resp.json()
        if isinstance(data, list):
            for item in data:
                if item.get("id") == self._request_id:
                    if item.get("error"):
                        err = item["error"]
                        raise RuntimeError(f"MCP error ({err.get('code')}): {err.get('message')}")
                    return item.get("result", {})
            return {}

        if data.get("error"):
            err = data["error"]
            raise RuntimeError(f"MCP error ({err.get('code')}): {err.get('message')}")
        return data.get("result", {})

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._client.post(
            self.url,
            json=msg,
            headers=self._build_headers(),
        )

    @staticmethod
    def _parse_sse_response(text: str, request_id: int) -> dict[str, Any]:
        for line in text.splitlines():
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    msg = json.loads(data_str)
                    if msg.get("id") == request_id:
                        if msg.get("error"):
                            err = msg["error"]
                            raise RuntimeError(f"MCP error ({err.get('code')}): {err.get('message')}")
                        return msg.get("result", {})
                except json.JSONDecodeError:
                    continue
        return {}
