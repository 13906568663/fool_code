"""MCP protocol types for JSON-RPC communication."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int
    method: str
    params: dict[str, Any] | None = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | None = None
    result: Any | None = None
    error: JsonRpcError | None = None


class McpTool(BaseModel):
    name: str
    description: str = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class McpToolCallContent(BaseModel):
    type: str = "text"
    text: str = ""


class McpToolCallResult(BaseModel):
    content: list[McpToolCallContent] = Field(default_factory=list)
    isError: bool | None = None
