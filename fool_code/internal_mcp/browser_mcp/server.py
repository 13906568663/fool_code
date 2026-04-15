"""Stdio MCP server for the built-in browser bridge sidecar."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any

from fool_code.internal_mcp.browser_mcp.bridge_pool import BrowserBridgePool
from fool_code.internal_mcp.browser_mcp.manifest import (
    BROWSER_MCP_TOOLS,
    BROWSER_MCP_TOOL_NAMES,
)
from fool_code.internal_mcp.browser_mcp.types import BrowserMcpRuntimeConfig
from fool_code.internal_mcp.browser_mcp.ws_server import BrowserBridgeWebSocketServer
from fool_code.mcp.types import McpToolCallContent, McpToolCallResult

logger = logging.getLogger(__name__)


class BrowserMcpServer:
    """Minimal stdio MCP server backed by a local browser-extension bridge."""

    def __init__(self, config: BrowserMcpRuntimeConfig) -> None:
        self.config = config
        self.pool = BrowserBridgePool()
        self.ws_server = BrowserBridgeWebSocketServer(config, self.pool)
        self._running = False

    async def serve_stdio(self) -> None:
        self._running = True
        try:
            await self.ws_server.start()
        except Exception as exc:
            logger.error("Failed to start browser bridge WS server: %s", exc)
            return
        logger.info("Browser MCP sidecar ready")
        logger.info("Extension bridge URL: %s", self.config.ws_url())

        try:
            while self._running:
                try:
                    raw = await asyncio.to_thread(sys.stdin.buffer.readline)
                except OSError as exc:
                    logger.warning("stdin read error, stopping: %s", exc)
                    break

                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    request = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning("Ignoring non-JSON MCP stdin line")
                    continue

                req_id = request.get("id")
                try:
                    response = await self._handle_request(request)
                    if response is not None:
                        self._write_stdout(response)
                except Exception as exc:
                    logger.exception("Unhandled error while processing request id=%s", req_id)
                    try:
                        self._write_stdout(self._error(req_id, -32603, str(exc)))
                    except Exception:
                        logger.exception("Failed to write error response for id=%s", req_id)
        finally:
            self._running = False
            await self.ws_server.stop()

    @staticmethod
    def _write_stdout(payload: dict[str, Any]) -> None:
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            logger.warning("stdout pipe broken, parent likely closed the connection")
            raise
        except OSError as exc:
            logger.warning("stdout write error: %s", exc)
            raise

    async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        req_id = request.get("id")
        method = str(request.get("method") or "")
        params = request.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "initialize":
            return self._ok(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "browser-mcp",
                        "version": "0.1.0",
                    },
                },
            )

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return self._ok(
                req_id,
                {
                    "tools": [tool.model_dump() for tool in BROWSER_MCP_TOOLS],
                },
            )

        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            result = await self.call_tool(name, arguments)
            return self._ok(req_id, result.model_dump())

        return self._error(req_id, -32601, f"Method not found: {method}")

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> McpToolCallResult:
        if name not in BROWSER_MCP_TOOL_NAMES:
            return McpToolCallResult(
                content=[McpToolCallContent(text=f"Unknown browser tool: {name}")],
                isError=True,
            )

        if not self.pool.is_connected(self.config.token):
            logger.info("Browser extension not yet connected, waiting up to 8s...")
            connected = await self.pool.wait_until_ready(self.config.token, timeout=8.0)
            if not connected:
                return McpToolCallResult(
                    content=[McpToolCallContent(
                        text="Browser extension is not connected. "
                        "Please check that the browser extension is installed, "
                        "enabled, and the pairing token matches."
                    )],
                    isError=True,
                )
            logger.info("Browser extension connected, proceeding with tool call")

        result = await self.pool.send_call(
            self.config.token,
            call_id=str(uuid.uuid4()),
            tool_name=name,
            args=arguments or {},
            timeout=self.config.call_timeout_seconds,
        )

        if result.get("ok"):
            content_items = result.get("content")
            contents: list[McpToolCallContent] = []
            if isinstance(content_items, list):
                for item in content_items:
                    if isinstance(item, dict) and item.get("type") == "text":
                        contents.append(
                            McpToolCallContent(text=str(item.get("text") or ""))
                        )
                    else:
                        contents.append(
                            McpToolCallContent(
                                text=json.dumps(item, ensure_ascii=False)
                                if not isinstance(item, str)
                                else item
                            )
                        )
            if not contents:
                contents.append(McpToolCallContent(text=""))
            return McpToolCallResult(content=contents, isError=False)

        return McpToolCallResult(
            content=[
                McpToolCallContent(text=str(result.get("error") or "Unknown browser error"))
            ],
            isError=True,
        )

    @staticmethod
    def _ok(req_id: Any, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
