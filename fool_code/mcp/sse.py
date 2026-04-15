"""MCP SSE transport — connect to MCP servers via Server-Sent Events.

Protocol: client sends JSON-RPC via POST, receives responses/notifications via SSE stream.
Ref: https://spec.modelcontextprotocol.io/specification/2024-11-05/basic/transports/#sse
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from fool_code.mcp.types import JsonRpcRequest, JsonRpcResponse, McpTool, McpToolCallResult

logger = logging.getLogger(__name__)


class McpSseProcess:
    """MCP client over SSE transport.

    1. Connect to the SSE endpoint to receive server→client messages.
    2. The SSE stream sends an 'endpoint' event with the POST URL for client→server.
    3. Send JSON-RPC requests via POST to that endpoint.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self._client = httpx.AsyncClient(timeout=300, headers=self.headers)
        self._post_endpoint: str | None = None
        self._request_id = 0
        self._initialized = False
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._sse_task: asyncio.Task | None = None
        self._ready = asyncio.Event()

    async def start(self) -> None:
        self._sse_task = asyncio.create_task(self._listen_sse())
        await asyncio.wait_for(self._ready.wait(), timeout=30)

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
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except (asyncio.CancelledError, Exception):
                pass
        await self._client.aclose()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._post_endpoint:
            raise RuntimeError("SSE endpoint not discovered yet")

        self._request_id += 1
        req_id = self._request_id
        request = JsonRpcRequest(id=req_id, method=method, params=params)

        future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        resp = await self._client.post(
            self._post_endpoint,
            json=request.model_dump(),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 202):
            self._pending.pop(req_id, None)
            raise RuntimeError(f"MCP SSE POST failed: {resp.status_code} {resp.text}")

        result = await asyncio.wait_for(future, timeout=300)
        if "error" in result and result["error"]:
            err = result["error"]
            raise RuntimeError(f"MCP error ({err.get('code')}): {err.get('message')}")
        return result.get("result", {})

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self._post_endpoint:
            return
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._client.post(
            self._post_endpoint,
            json=msg,
            headers={"Content-Type": "application/json"},
        )

    async def _listen_sse(self) -> None:
        try:
            async with self._client.stream("GET", self.url, headers={"Accept": "text/event-stream"}) as resp:
                event_type = ""
                data_buf = ""

                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_buf += line[5:].strip()
                    elif line == "":
                        if event_type == "endpoint" and data_buf:
                            endpoint = data_buf.strip()
                            if endpoint.startswith("/"):
                                base = self.url.rsplit("/", 1)[0]
                                self._post_endpoint = f"{base}{endpoint}"
                            else:
                                self._post_endpoint = endpoint
                            self._ready.set()
                        elif event_type == "message" and data_buf:
                            try:
                                msg = json.loads(data_buf)
                                msg_id = msg.get("id")
                                if msg_id is not None and msg_id in self._pending:
                                    self._pending.pop(msg_id).set_result(msg)
                            except json.JSONDecodeError:
                                pass
                        event_type = ""
                        data_buf = ""
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("MCP SSE stream error: %s", exc)
