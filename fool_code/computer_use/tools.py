"""Computer Use tools — ToolHandler implementations for screen control.

Each tool maps to one or more calls into `executor.py` which in turn
calls the Rust native module.  The tools are registered as a group via
`register_computer_use()` in `__init__.py`.

Screenshots are automatically resized to ≤1280px long edge so the model
works in a smaller, well-defined coordinate space.  All coordinate-based
tools (click, scroll, drag) transparently scale model coordinates back
to logical screen coordinates via `ScreenshotContext`.
"""

from __future__ import annotations

from typing import Any

from fool_code.computer_use import executor
from fool_code.computer_use.scaling import (
    draw_coordinate_grid,
    get_screenshot_context,
    resize_screenshot_b64,
)
from fool_code.computer_use.window_manager import hidden_self_windows
from fool_code.tools.tool_protocol import (
    ToolCategory,
    ToolContext,
    ToolHandler,
    ToolMeta,
    ToolResult,
)
from fool_code.types import ToolDefinition, ToolFunction, ToolParameter


def _td(name: str, desc: str, props: dict, required: list[str]) -> ToolDefinition:
    return ToolDefinition(
        function=ToolFunction(
            name=name,
            description=desc,
            parameters=ToolParameter(properties=props, required=required),
        )
    )


def _int(val: Any) -> int:
    """Coerce a value to int — LLMs sometimes pass coordinates as strings."""
    return int(val)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

class ScreenshotTool(ToolHandler):
    meta = ToolMeta(
        name="computer_screenshot",
        category=ToolCategory.META,
        is_read_only=True,
        is_concurrency_safe=True,
        should_defer=True,
    )
    definition = _td(
        "computer_screenshot",
        "Take a full screenshot of the entire desktop screen. Returns a JPEG image. "
        "Use this to see what is currently visible on screen before performing any click/type action.",
        {"quality": {"type": "integer", "minimum": 1, "maximum": 100}},
        [],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        quality = args.get("quality", 75)
        with hidden_self_windows():
            b64, w, h = executor.screenshot(quality)
        b64_resized, img_w, img_h = resize_screenshot_b64(b64, w, h)
        b64_grid = draw_coordinate_grid(b64_resized, img_w, img_h, jpeg_quality=quality)
        ctx = get_screenshot_context()
        ctx.update(screen_w=w, screen_h=h, image_w=img_w, image_h=img_h)
        info = ctx.info
        return ToolResult(
            output=(
                f"Screenshot captured ({img_w}x{img_h}). {info}. "
                f"A coordinate grid is overlaid every 100px — use these reference lines "
                f"to pinpoint exact positions. "
                f"Coordinates you provide in subsequent click/scroll/drag calls "
                f"should be based on this {img_w}x{img_h} image."
            ),
            images=[b64_grid],
        )


# ---------------------------------------------------------------------------
# Screenshot Region
# ---------------------------------------------------------------------------

class ScreenshotRegionTool(ToolHandler):
    meta = ToolMeta(
        name="computer_screenshot_region",
        category=ToolCategory.META,
        is_read_only=True,
        is_concurrency_safe=True,
        should_defer=True,
    )
    definition = _td(
        "computer_screenshot_region",
        "Take a screenshot of a screen region (coordinates in image space from the last screenshot). "
        "Returns a higher-detail view of the region. Useful to zoom in for precise coordinate identification.",
        {
            "x": {"type": "integer", "description": "Left edge in image coordinates"},
            "y": {"type": "integer", "description": "Top edge in image coordinates"},
            "width": {"type": "integer", "minimum": 1},
            "height": {"type": "integer", "minimum": 1},
            "quality": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        ["x", "y", "width", "height"],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ctx = get_screenshot_context()
        sx, sy = ctx.scale_to_screen(_int(args["x"]), _int(args["y"]))
        sw, sh = ctx.scale_to_screen(_int(args["x"]) + _int(args["width"]), _int(args["y"]) + _int(args["height"]))
        real_w = sw - sx
        real_h = sh - sy
        with hidden_self_windows():
            b64, w, h = executor.screenshot_region(sx, sy, real_w, real_h, args.get("quality", 85))
        b64_resized, rw, rh = resize_screenshot_b64(b64, w, h)
        return ToolResult(
            output=(
                f"Region captured: {rw}x{rh}. "
                f"Note: this is a zoomed view of screen area ({sx},{sy} {real_w}x{real_h}). "
                f"Coordinates for click/scroll should still be based on the FULL screenshot, not this region."
            ),
            images=[b64_resized],
        )


# ---------------------------------------------------------------------------
# Click
# ---------------------------------------------------------------------------

class ClickTool(ToolHandler):
    meta = ToolMeta(name="computer_click", category=ToolCategory.EXECUTION, should_defer=True)
    definition = _td(
        "computer_click",
        "Simulate a real OS-level mouse click at coordinates (x, y) from the last screenshot image. "
        "Coordinates are automatically scaled to actual screen position. "
        "Works on ANY application visible on screen — browsers, desktop apps, system UI, etc. "
        "First use computer_screenshot to identify the target coordinates, then click.",
        {
            "x": {"type": "integer", "description": "X coordinate in the screenshot image"},
            "y": {"type": "integer", "description": "Y coordinate in the screenshot image"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "count": {"type": "integer", "minimum": 1, "maximum": 3},
        },
        ["x", "y"],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        img_x, img_y = _int(args["x"]), _int(args["y"])
        ctx = get_screenshot_context()
        sx, sy = ctx.scale_to_screen(img_x, img_y)
        executor.click(sx, sy, args.get("button", "left"), int(args.get("count", 1)))
        if (sx, sy) != (img_x, img_y):
            return ToolResult(output=f"Clicked image({img_x},{img_y}) → screen({sx},{sy})")
        return ToolResult(output=f"Clicked ({sx}, {sy})")


# ---------------------------------------------------------------------------
# Type text
# ---------------------------------------------------------------------------

class TypeTool(ToolHandler):
    meta = ToolMeta(name="computer_type", category=ToolCategory.EXECUTION, should_defer=True)
    definition = _td(
        "computer_type",
        "Simulate real keyboard typing in the currently focused window. "
        "The text is typed character-by-character as if the user pressed each key.",
        {"text": {"type": "string"}},
        ["text"],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        text = args["text"]
        executor.type_text(text)
        return ToolResult(output=f"Typed {len(text)} chars")


# ---------------------------------------------------------------------------
# Key
# ---------------------------------------------------------------------------

class KeyTool(ToolHandler):
    meta = ToolMeta(name="computer_key", category=ToolCategory.EXECUTION, should_defer=True)
    definition = _td(
        "computer_key",
        "Simulate pressing a key or key combination at the OS level (e.g. 'ctrl+c', 'enter', 'alt+tab'). "
        "Works on the currently focused window.",
        {
            "key_sequence": {"type": "string"},
            "repeat": {"type": "integer", "minimum": 1},
        },
        ["key_sequence"],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        seq = args["key_sequence"]
        executor.key(seq, int(args.get("repeat", 1)))
        return ToolResult(output=f"Pressed {seq}")


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------

class ScrollTool(ToolHandler):
    meta = ToolMeta(name="computer_scroll", category=ToolCategory.EXECUTION, should_defer=True)
    definition = _td(
        "computer_scroll",
        "Simulate mouse scroll at position (x, y) from the last screenshot image. "
        "dy>0 scrolls up, dy<0 scrolls down. dx for horizontal. Coordinates are auto-scaled.",
        {
            "x": {"type": "integer", "description": "X in screenshot image"},
            "y": {"type": "integer", "description": "Y in screenshot image"},
            "dx": {"type": "integer"},
            "dy": {"type": "integer"},
        },
        ["x", "y"],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ctx = get_screenshot_context()
        sx, sy = ctx.scale_to_screen(_int(args["x"]), _int(args["y"]))
        executor.scroll(sx, sy, int(args.get("dx", 0)), int(args.get("dy", 0)))
        return ToolResult(output=f"Scrolled at ({sx}, {sy})")


# ---------------------------------------------------------------------------
# Drag
# ---------------------------------------------------------------------------

class DragTool(ToolHandler):
    meta = ToolMeta(name="computer_drag", category=ToolCategory.EXECUTION, should_defer=True)
    definition = _td(
        "computer_drag",
        "Drag from one point to another (coordinates from screenshot image, auto-scaled). "
        "If from_x/from_y omitted, drags from current cursor position.",
        {
            "to_x": {"type": "integer", "description": "Target X in screenshot image"},
            "to_y": {"type": "integer", "description": "Target Y in screenshot image"},
            "from_x": {"type": "integer", "description": "Start X in screenshot image"},
            "from_y": {"type": "integer", "description": "Start Y in screenshot image"},
        },
        ["to_x", "to_y"],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        ctx = get_screenshot_context()
        stx, sty = ctx.scale_to_screen(_int(args["to_x"]), _int(args["to_y"]))
        sfx = sfy = None
        if args.get("from_x") is not None and args.get("from_y") is not None:
            sfx, sfy = ctx.scale_to_screen(_int(args["from_x"]), _int(args["from_y"]))
        executor.drag(stx, sty, sfx, sfy)
        return ToolResult(output=f"Dragged to ({stx}, {sty})")


# ---------------------------------------------------------------------------
# Cursor Position
# ---------------------------------------------------------------------------

class CursorPositionTool(ToolHandler):
    meta = ToolMeta(
        name="computer_cursor_position",
        category=ToolCategory.META,
        is_read_only=True,
        is_concurrency_safe=True,
        should_defer=True,
    )
    definition = _td(
        "computer_cursor_position",
        "Get the current mouse cursor position.",
        {},
        [],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        sx, sy = executor.get_cursor_position()
        ctx = get_screenshot_context()
        ix, iy = ctx.scale_to_image(sx, sy)
        if (ix, iy) != (sx, sy):
            return ToolResult(output=f"Cursor at image({ix}, {iy}) [screen({sx}, {sy})]")
        return ToolResult(output=f"Cursor at ({sx}, {sy})")


# ---------------------------------------------------------------------------
# Wait
# ---------------------------------------------------------------------------

class WaitTool(ToolHandler):
    meta = ToolMeta(name="computer_wait", category=ToolCategory.META, is_read_only=True, should_defer=True)
    definition = _td(
        "computer_wait",
        "Wait for a specified number of seconds. Useful between UI operations to allow animations, page loads, etc.",
        {"seconds": {"type": "number", "minimum": 0.1, "maximum": 30}},
        ["seconds"],
    )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        import time
        secs = float(args["seconds"])
        secs = max(0.1, min(secs, 30))
        time.sleep(secs)
        return ToolResult(output=f"Waited {secs}s")


# ---------------------------------------------------------------------------
# All tools list
# ---------------------------------------------------------------------------

ALL_TOOLS: list[type[ToolHandler]] = [
    ScreenshotTool,
    ScreenshotRegionTool,
    ClickTool,
    TypeTool,
    KeyTool,
    ScrollTool,
    DragTool,
    CursorPositionTool,
    WaitTool,
]
