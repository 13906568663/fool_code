"""Local WebSocket bridge server for the browser MCP sidecar."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from fool_code.internal_mcp.browser_mcp.bridge_pool import BrowserBridgePool
from fool_code.internal_mcp.browser_mcp.types import BrowserMcpRuntimeConfig

logger = logging.getLogger(__name__)


class BrowserBridgeWebSocketServer:
    """Accepts extension connections and forwards tool results into the pool."""

    def __init__(
        self,
        config: BrowserMcpRuntimeConfig,
        pool: BrowserBridgePool,
    ) -> None:
        self.config = config
        self.pool = pool
        self._server: Server | None = None

    async def start(self) -> None:
        if self._server is not None:
            return

        port = self.config.port
        self._kill_stale_port_holder(port)

        try:
            self._server = await serve(
                self._handle_connection,
                self.config.host,
                port,
                ping_interval=20,
                ping_timeout=20,
            )
        except OSError as exc:
            logger.warning(
                "Port %s still in use after cleanup (%s), falling back to random port",
                port, exc,
            )
            self._server = await serve(
                self._handle_connection,
                self.config.host,
                0,
                ping_interval=20,
                ping_timeout=20,
            )
        actual_port = self._actual_port()
        if actual_port and actual_port != self.config.port:
            object.__setattr__(self.config, "port", actual_port)
        logger.info(
            "Browser bridge listening on ws://%s:%s%s",
            self.config.host,
            self.config.port,
            self.config.path,
        )

    def _actual_port(self) -> int | None:
        """Return the port the server actually bound to."""
        if self._server is None:
            return None
        for sock in self._server.sockets:
            addr = sock.getsockname()
            if isinstance(addr, tuple) and len(addr) >= 2:
                return addr[1]
        return None

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    @staticmethod
    def _kill_stale_port_holder(port: int) -> None:
        """Try to kill a leftover sidecar process that still holds our bridge port."""
        import os
        import signal
        import socket
        import sys

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return
            except OSError:
                pass

        if sys.platform == "win32":
            import subprocess
            try:
                out = subprocess.check_output(
                    ["netstat", "-ano", "-p", "TCP"],
                    text=True, timeout=5, encoding="utf-8", errors="replace",
                )
                for line in out.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.split()
                        pid = int(parts[-1])
                        if pid != os.getpid():
                            logger.info("Killing stale process PID %d holding port %d", pid, port)
                            os.kill(pid, signal.SIGTERM)
                            import time
                            time.sleep(0.5)
                        break
            except Exception as exc:
                logger.debug("Failed to kill stale port holder: %s", exc)
        else:
            import subprocess
            try:
                out = subprocess.check_output(
                    ["lsof", "-ti", f":{port}"],
                    text=True, timeout=5,
                ).strip()
                for pid_str in out.splitlines():
                    pid = int(pid_str.strip())
                    if pid != os.getpid():
                        logger.info("Killing stale process PID %d holding port %d", pid, port)
                        os.kill(pid, signal.SIGTERM)
                        import time
                        time.sleep(0.5)
            except Exception as exc:
                logger.debug("Failed to kill stale port holder: %s", exc)

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        token = self._token_from_request(websocket)
        if token is None:
            await websocket.close(code=4001, reason="Invalid bridge path or missing token.")
            return

        if token != self.config.token:
            await websocket.close(code=4003, reason="Invalid connection token.")
            return

        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=15.0)
        except TimeoutError:
            await websocket.close(code=4004, reason="Expected hello message.")
            return

        hello = self._parse_json(raw)
        if hello.get("type") != "hello":
            await websocket.close(code=4005, reason="First message must be type=hello.")
            return

        tools = hello.get("tools")
        reported_tools = tools if isinstance(tools, list) else []
        self.pool.register(token, websocket, reported_tools)
        logger.info("Browser extension connected with %d reported tools", len(reported_tools))

        try:
            async for raw_msg in websocket:
                msg = self._parse_json(raw_msg)
                msg_type = str(msg.get("type") or "")
                call_id = str(msg.get("call_id") or "")
                if msg_type == "tool_result" and call_id:
                    content = msg.get("content")
                    if not isinstance(content, list):
                        content = []
                    self.pool.resolve_call(
                        call_id,
                        {"ok": True, "content": content},
                    )
                elif msg_type == "tool_error" and call_id:
                    self.pool.resolve_call(
                        call_id,
                        {
                            "ok": False,
                            "error": str(msg.get("error") or "Unknown extension error."),
                        },
                    )
        except ConnectionClosed:
            logger.info("Browser extension disconnected")
        finally:
            self.pool.unregister(token)

    def _token_from_request(self, websocket: ServerConnection) -> str | None:
        request = getattr(websocket, "request", None)
        path = getattr(request, "path", "")
        parts = urlsplit(path)
        if parts.path != self.config.path:
            return None
        token = parse_qs(parts.query).get("token", [""])[0].strip()
        return token or None

    @staticmethod
    def _parse_json(raw: Any) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if not isinstance(raw, str):
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
