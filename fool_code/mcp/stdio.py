"""MCP stdio process — spawn and communicate with MCP servers via JSON-RPC over stdio.

Supports two framing modes (auto-detected on first response):
  1. Content-Length framing (LSP-style): ``Content-Length: N\\r\\n\\r\\n{json}``
  2. Newline-delimited JSON: one JSON object per line
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
from typing import Any

from fool_code.mcp.types import JsonRpcRequest, JsonRpcResponse, McpTool, McpToolCallResult

logger = logging.getLogger(__name__)


class McpStdioProcess:
    """Manages a single MCP server subprocess communicating via JSON-RPC over stdio."""

    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        self.command = command
        self.args = args
        self.env = env
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._initialized = False
        self._framing: str | None = None  # "content-length" or "ndjson", auto-detected
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        cmd = self.command
        if sys.platform == "win32":
            resolved = shutil.which(cmd)
            if resolved:
                cmd = resolved
            if cmd.lower().endswith((".cmd", ".bat")):
                full_cmd = _build_shell_cmd(cmd, self.args)
                self._process = await asyncio.create_subprocess_shell(
                    full_cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=self.env,
                    limit=32 * 1024 * 1024,
                )
                self._start_stderr_drain()
                return
        self._process = await asyncio.create_subprocess_exec(
            cmd, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
            limit=32 * 1024 * 1024,
        )
        self._start_stderr_drain()

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
        tools_raw = result.get("tools", [])
        return [McpTool.model_validate(t) for t in tools_raw]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> McpToolCallResult:
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        return McpToolCallResult.model_validate(result)

    async def shutdown(self) -> None:
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._process and self._process.returncode is None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                self._process.kill()
                await self._process.wait()
            finally:
                self._initialized = False
                self._process = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def _start_stderr_drain(self) -> None:
        if self._process and self._process.stderr:
            self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        assert self._process and self._process.stderr
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug("[MCP-subprocess stderr] %s", text)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request = JsonRpcRequest(id=self._request_id, method=method, params=params)
        await self._write_message(request.model_dump())
        response = await self._read_response()
        if response.error:
            raise RuntimeError(
                f"MCP error ({response.error.code}): {response.error.message}"
            )
        return response.result or {}

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._write_message(msg)

    async def _write_message(self, data: dict) -> None:
        assert self._process and self._process.stdin
        body = json.dumps(data).encode("utf-8")
        if self._framing == "content-length":
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
            self._process.stdin.write(header + body)
        else:
            self._process.stdin.write(body + b"\n")
        await self._process.stdin.drain()

    async def _read_response(self) -> JsonRpcResponse:
        assert self._process and self._process.stdout
        while True:
            line = await self._process.stdout.readline()
            if not line:
                raise RuntimeError("MCP process closed stdout unexpectedly")
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            if text.startswith("Content-Length:"):
                if self._framing is None:
                    self._framing = "content-length"
                    logger.debug("MCP framing detected: Content-Length")
                content_length = int(text.split(":")[1].strip())
                while True:
                    sep = await self._process.stdout.readline()
                    if sep.strip() == b"":
                        break
                body = await self._process.stdout.readexactly(content_length)
                data = json.loads(body.decode("utf-8"))
            elif text.startswith("{"):
                if self._framing is None:
                    self._framing = "ndjson"
                    logger.debug("MCP framing detected: newline-delimited JSON")
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning("Skipping non-JSON stdout line from MCP server")
                    continue
            else:
                logger.debug("Skipping non-protocol MCP stdout: %s", text[:120])
                continue

            if "id" not in data:
                continue
            return JsonRpcResponse.model_validate(data)


def _build_shell_cmd(cmd: str, args: list[str]) -> str:
    """Build a shell command string with proper quoting for Windows."""
    parts = [f'"{cmd}"' if " " in cmd else cmd]
    for arg in args:
        if " " in arg or "=" in arg:
            parts.append(f'"{arg}"')
        else:
            parts.append(arg)
    return " ".join(parts)
