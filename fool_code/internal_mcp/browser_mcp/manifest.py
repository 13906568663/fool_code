"""Static metadata and tool catalog for the built-in browser MCP service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fool_code.internal_mcp.types import InternalMcpServiceDefinition
from fool_code.mcp.types import McpTool

DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 17373
DEFAULT_BRIDGE_PATH = "/api/v1/browser-bridge/ws"
DEFAULT_BRIDGE_TOKEN = "fool-code-browser"
DEFAULT_CALL_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class BrowserToolSpec:
    """Static browser tool description used by the MCP sidecar."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_mcp_tool(self) -> McpTool:
        return McpTool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )


def _schema(
    properties: dict[str, Any] | None = None,
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
    }


BROWSER_MCP_SERVICE = InternalMcpServiceDefinition(
    name="browser_mcp",
    config_key="browser",
    display_name="Browser MCP",
    description=(
        "Built-in browser bridge MCP sidecar used for extension-backed browser "
        "automation."
    ),
    package="fool_code.internal_mcp.browser_mcp",
)

BROWSER_TOOL_SPECS: tuple[BrowserToolSpec, ...] = (
    BrowserToolSpec(
        name="get_browser_state",
        description=(
            "Get the current browser page state as text optimized for agent "
            "reasoning, including indexed interactive elements."
        ),
        input_schema=_schema(),
    ),
    BrowserToolSpec(
        name="click_element",
        description="Click an interactive element by index from get_browser_state.",
        input_schema=_schema(
            {
                "index": {"type": "number", "description": "Element index."},
                "expected_text": {
                    "type": "string",
                    "description": "Optional text guard to avoid misclicks.",
                },
            },
            required=["index"],
        ),
    ),
    BrowserToolSpec(
        name="input_text",
        description="Type text into an input or textarea element by index.",
        input_schema=_schema(
            {
                "index": {"type": "number", "description": "Element index."},
                "text": {"type": "string", "description": "Text to enter."},
                "submit": {
                    "type": "boolean",
                    "description": "Whether to submit after input.",
                },
            },
            required=["index", "text"],
        ),
    ),
    BrowserToolSpec(
        name="select_option",
        description="Select an option in a select element by index.",
        input_schema=_schema(
            {
                "index": {"type": "number", "description": "Element index."},
                "value": {
                    "type": "string",
                    "description": "Option value or visible text to select.",
                },
            },
            required=["index", "value"],
        ),
    ),
    BrowserToolSpec(
        name="scroll",
        description="Scroll the page vertically or horizontally.",
        input_schema=_schema(
            {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                },
                "amount": {
                    "type": "number",
                    "description": "Pages or pixels depending on direction.",
                },
                "index": {
                    "type": "number",
                    "description": "Optional container element index.",
                },
            }
        ),
    ),
    BrowserToolSpec(
        name="navigate",
        description="Navigate the current tab to a target URL.",
        input_schema=_schema(
            {
                "url": {"type": "string", "description": "Target URL."},
            },
            required=["url"],
        ),
    ),
    BrowserToolSpec(
        name="open_tab",
        description="Open a new browser tab, optionally with a URL.",
        input_schema=_schema(
            {
                "url": {"type": "string", "description": "Optional target URL."},
                "active": {
                    "type": "boolean",
                    "description": "Whether the new tab should become active.",
                },
            }
        ),
    ),
    BrowserToolSpec(
        name="wait",
        description="Sleep for a short period while keeping browser context intact.",
        input_schema=_schema(
            {
                "seconds": {
                    "type": "number",
                    "description": "Seconds to wait.",
                }
            }
        ),
    ),
    BrowserToolSpec(
        name="wait_for_page_stable",
        description="Wait until page activity settles before continuing.",
        input_schema=_schema(
            {
                "timeout_ms": {
                    "type": "number",
                    "description": "Optional timeout in milliseconds.",
                }
            }
        ),
    ),
    BrowserToolSpec(
        name="execute_javascript",
        description="Execute JavaScript in the active tab and return the result.",
        input_schema=_schema(
            {
                "script": {"type": "string", "description": "JavaScript source."},
            },
            required=["script"],
        ),
    ),
    # BrowserToolSpec(
    #     name="take_screenshot",
    #     description="Capture a screenshot of the current tab or viewport.",
    #     input_schema=_schema(
    #         {
    #             "full_page": {
    #                 "type": "boolean",
    #                 "description": "Whether to capture the full page.",
    #             }
    #         }
    #     ),
    # ),
    BrowserToolSpec(
        name="close_tab",
        description="Close a browser tab.",
        input_schema=_schema(
            {
                "tab_id": {
                    "type": "number",
                    "description": "Optional tab id; defaults to current tab.",
                }
            }
        ),
    ),
    BrowserToolSpec(
        name="switch_tab",
        description="Switch focus to another browser tab.",
        input_schema=_schema(
            {
                "tab_id": {
                    "type": "number",
                    "description": "Tab id to activate.",
                }
            },
            required=["tab_id"],
        ),
    ),
    BrowserToolSpec(
        name="list_tabs",
        description="List current browser tabs and their titles/URLs.",
        input_schema=_schema(),
    ),
    BrowserToolSpec(
        name="get_cookies",
        description="Read cookies for a URL, including httpOnly cookies.",
        input_schema=_schema(
            {
                "url": {"type": "string", "description": "Target URL."},
                "name": {
                    "type": "string",
                    "description": "Optional cookie name filter.",
                },
            },
            required=["url"],
        ),
    ),
    BrowserToolSpec(
        name="set_cookie",
        description="Set or update a browser cookie.",
        input_schema=_schema(
            {
                "url": {"type": "string"},
                "name": {"type": "string"},
                "value": {"type": "string"},
                "domain": {"type": "string"},
                "path": {"type": "string"},
                "secure": {"type": "boolean"},
                "http_only": {"type": "boolean"},
                "httpOnly": {"type": "boolean"},
                "expiration_date": {"type": "number"},
                "expirationDate": {"type": "number"},
            },
            required=["url", "name", "value"],
        ),
    ),
    BrowserToolSpec(
        name="remove_cookie",
        description="Remove a specific browser cookie.",
        input_schema=_schema(
            {
                "url": {"type": "string"},
                "name": {"type": "string"},
            },
            required=["url", "name"],
        ),
    ),
    BrowserToolSpec(
        name="clear_cookies",
        description="Clear all cookies for a URL.",
        input_schema=_schema(
            {
                "url": {"type": "string"},
            },
            required=["url"],
        ),
    ),
)

BROWSER_MCP_TOOLS: tuple[McpTool, ...] = tuple(
    spec.to_mcp_tool() for spec in BROWSER_TOOL_SPECS
)

BROWSER_MCP_TOOL_NAMES = frozenset(tool.name for tool in BROWSER_MCP_TOOLS)
