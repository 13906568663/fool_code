"""Types for the built-in browser MCP sidecar."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any

from fool_code.internal_mcp.browser_mcp.manifest import (
    DEFAULT_BRIDGE_HOST,
    DEFAULT_BRIDGE_PATH,
    DEFAULT_BRIDGE_PORT,
    DEFAULT_BRIDGE_TOKEN,
    DEFAULT_CALL_TIMEOUT_SECONDS,
)

ENV_BRIDGE_HOST = "FOOL_BROWSER_MCP_HOST"
ENV_BRIDGE_PORT = "FOOL_BROWSER_MCP_PORT"
ENV_BRIDGE_PATH = "FOOL_BROWSER_MCP_PATH"
ENV_BRIDGE_TOKEN = "FOOL_BROWSER_MCP_TOKEN"
ENV_CALL_TIMEOUT = "FOOL_BROWSER_MCP_CALL_TIMEOUT"


@dataclass(frozen=True, slots=True)
class BrowserMcpRuntimeConfig:
    host: str = DEFAULT_BRIDGE_HOST
    port: int = DEFAULT_BRIDGE_PORT
    path: str = DEFAULT_BRIDGE_PATH
    token: str = ""
    call_timeout_seconds: float = DEFAULT_CALL_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "BrowserMcpRuntimeConfig":
        raw_port = (os.environ.get(ENV_BRIDGE_PORT) or "").strip()
        raw_timeout = (os.environ.get(ENV_CALL_TIMEOUT) or "").strip()
        return cls(
            host=(os.environ.get(ENV_BRIDGE_HOST) or DEFAULT_BRIDGE_HOST).strip(),
            port=int(raw_port) if raw_port else DEFAULT_BRIDGE_PORT,
            path=(os.environ.get(ENV_BRIDGE_PATH) or DEFAULT_BRIDGE_PATH).strip(),
            token=(os.environ.get(ENV_BRIDGE_TOKEN) or "").strip(),
            call_timeout_seconds=(
                float(raw_timeout)
                if raw_timeout
                else DEFAULT_CALL_TIMEOUT_SECONDS
            ),
        )

    def normalized_token(self) -> str:
        return self.token or DEFAULT_BRIDGE_TOKEN or secrets.token_urlsafe(24)

    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}{self.path}?token={self.token}"

    def env_overrides(self) -> dict[str, Any]:
        return {
            ENV_BRIDGE_HOST: self.host,
            ENV_BRIDGE_PORT: str(self.port),
            ENV_BRIDGE_PATH: self.path,
            ENV_BRIDGE_TOKEN: self.token,
            ENV_CALL_TIMEOUT: str(self.call_timeout_seconds),
        }
