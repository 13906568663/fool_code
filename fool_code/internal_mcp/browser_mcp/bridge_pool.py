"""Connection pool for browser extension bridge sessions."""

from __future__ import annotations

import asyncio
import time
import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BrowserBridgeConnection:
    token: str
    websocket: Any
    reported_tools: list[dict[str, Any]]
    connected_at: float


class BrowserBridgePool:
    """Tracks active extension connections and pending tool calls."""

    def __init__(self) -> None:
        self._connections: dict[str, BrowserBridgeConnection] = {}
        self._ready_futures: dict[str, asyncio.Future[None]] = {}
        self._pending_calls: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}

    def is_connected(self, token: str) -> bool:
        return token in self._connections

    def register(self, token: str, websocket: Any, tools: list[dict[str, Any]]) -> None:
        self._connections[token] = BrowserBridgeConnection(
            token=token,
            websocket=websocket,
            reported_tools=tools,
            connected_at=time.time(),
        )
        future = self._ready_futures.pop(token, None)
        if future and not future.done():
            future.set_result(None)

    def unregister(self, token: str) -> None:
        self._connections.pop(token, None)
        for call_id, (pending_token, future) in list(self._pending_calls.items()):
            if pending_token != token:
                continue
            self._pending_calls.pop(call_id, None)
            if not future.done():
                future.set_result(
                    {
                        "ok": False,
                        "error": "Browser extension disconnected.",
                    }
                )

    def reported_tools(self, token: str) -> list[dict[str, Any]]:
        conn = self._connections.get(token)
        if conn is None:
            return []
        return list(conn.reported_tools)

    async def wait_until_ready(self, token: str, timeout: float = 10.0) -> bool:
        if self.is_connected(token):
            return True
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._ready_futures[token] = future
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            return True
        except TimeoutError:
            self._ready_futures.pop(token, None)
            return False

    async def send_call(
        self,
        token: str,
        call_id: str,
        tool_name: str,
        args: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        conn = self._connections.get(token)
        if conn is None:
            return {"ok": False, "error": "Browser extension is not connected."}

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_calls[call_id] = (token, future)

        try:
            await conn.websocket.send(
                json.dumps(
                    {
                        "type": "call_tool",
                        "call_id": call_id,
                        "tool_name": tool_name,
                        "args": args,
                    },
                    ensure_ascii=False,
                )
            )
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError:
            return {
                "ok": False,
                "error": f"Tool call timed out after {timeout:.0f}s.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self._pending_calls.pop(call_id, None)

    def resolve_call(self, call_id: str, result: dict[str, Any]) -> None:
        entry = self._pending_calls.get(call_id)
        if entry is None:
            return
        _token, future = entry
        if not future.done():
            future.set_result(result)
