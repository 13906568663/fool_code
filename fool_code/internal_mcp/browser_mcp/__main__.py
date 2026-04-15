"""CLI entry point for the built-in browser MCP sidecar."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from fool_code.internal_mcp.browser_mcp.server import BrowserMcpServer
from fool_code.internal_mcp.browser_mcp.types import (
    BrowserMcpRuntimeConfig,
    ENV_BRIDGE_HOST,
    ENV_BRIDGE_PATH,
    ENV_BRIDGE_PORT,
    ENV_BRIDGE_TOKEN,
    ENV_CALL_TIMEOUT,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Fool Code built-in browser MCP sidecar.")
    parser.add_argument("--host", default="", help=f"Bridge host (env: {ENV_BRIDGE_HOST})")
    parser.add_argument("--port", type=int, default=0, help=f"Bridge port (env: {ENV_BRIDGE_PORT})")
    parser.add_argument("--path", default="", help=f"Bridge path (env: {ENV_BRIDGE_PATH})")
    parser.add_argument("--token", default="", help=f"Pairing token (env: {ENV_BRIDGE_TOKEN})")
    parser.add_argument(
        "--call-timeout",
        type=float,
        default=0,
        help=f"Tool call timeout in seconds (env: {ENV_CALL_TIMEOUT})",
    )
    return parser.parse_args()


def _build_config(args: argparse.Namespace) -> BrowserMcpRuntimeConfig:
    env_cfg = BrowserMcpRuntimeConfig.from_env()
    cfg = BrowserMcpRuntimeConfig(
        host=args.host or env_cfg.host,
        port=args.port or env_cfg.port,
        path=args.path or env_cfg.path,
        token=args.token or env_cfg.token,
        call_timeout_seconds=args.call_timeout or env_cfg.call_timeout_seconds,
    )
    token = cfg.normalized_token()
    if token != cfg.token:
        cfg = BrowserMcpRuntimeConfig(
            host=cfg.host,
            port=cfg.port,
            path=cfg.path,
            token=token,
            call_timeout_seconds=cfg.call_timeout_seconds,
        )
    return cfg


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("FOOL_BROWSER_MCP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cfg = _build_config(_parse_args())
    try:
        asyncio.run(BrowserMcpServer(cfg).serve_stdio())
    except Exception:
        logging.getLogger(__name__).exception("Browser MCP sidecar crashed")


if __name__ == "__main__":
    main()
