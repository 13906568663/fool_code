"""Executor — thin wrapper around the Rust native module with graceful fallback.

All interaction with `fool_code_cu` goes through this module so that
`tools.py` never imports the native extension directly.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import fool_code_cu as _native  # type: ignore[import-untyped]

    AVAILABLE = True
except ImportError:
    _native = None  # type: ignore[assignment]
    AVAILABLE = False
    logger.debug("fool_code_cu native module not found — Computer Use disabled")


def _require() -> Any:
    if not AVAILABLE:
        raise RuntimeError(
            "Computer Use requires the fool_code_cu native extension. "
            "Build it with: cd fool_code/computer_use/_native && maturin develop --release"
        )
    return _native


# -- Screenshot ----------------------------------------------------------------

def screenshot(quality: int = 75) -> tuple[str, int, int]:
    """Return (base64_jpeg, width, height) of the full screen."""
    return _require().screenshot(quality)


def screenshot_region(x: int, y: int, w: int, h: int, quality: int = 75) -> tuple[str, int, int]:
    """Return (base64_jpeg, width, height) of a screen region."""
    return _require().screenshot_region(x, y, w, h, quality)


# -- Display -------------------------------------------------------------------

def get_display_size() -> dict[str, Any]:
    return _require().get_display_size()


def list_displays() -> list[dict[str, Any]]:
    return _require().list_displays()


# -- Mouse ---------------------------------------------------------------------

def move_mouse(x: int, y: int) -> None:
    _require().move_mouse(x, y)


def click(x: int, y: int, button: str = "left", count: int = 1) -> None:
    _require().click(x, y, button, count)


def mouse_down() -> None:
    _require().mouse_down()


def mouse_up() -> None:
    _require().mouse_up()


def scroll(x: int, y: int, dx: int, dy: int) -> None:
    _require().scroll(x, y, dx, dy)


def drag(to_x: int, to_y: int, from_x: int | None = None, from_y: int | None = None) -> None:
    _require().drag(to_x, to_y, from_x, from_y)


def get_cursor_position() -> tuple[int, int]:
    return _require().get_cursor_position()


# -- Keyboard ------------------------------------------------------------------

def key(key_sequence: str, repeat: int = 1) -> None:
    _require().key(key_sequence, repeat)


def type_text(text: str) -> None:
    _require().type_text(text)


def hold_key(keys: list[str], duration_ms: int) -> None:
    _require().hold_key(keys, duration_ms)


# -- Clipboard -----------------------------------------------------------------

def read_clipboard() -> str:
    return _require().read_clipboard()


def write_clipboard(text: str) -> None:
    _require().write_clipboard(text)


# -- Apps ----------------------------------------------------------------------

def get_foreground_app() -> dict[str, Any] | None:
    return _require().get_foreground_app()


def list_running_apps() -> list[dict[str, Any]]:
    return _require().list_running_apps()


def list_installed_apps() -> list[dict[str, Any]]:
    return _require().list_installed_apps()


def open_app(exe_path: str) -> None:
    _require().open_app(exe_path)


def app_under_point(x: int, y: int) -> dict[str, Any] | None:
    return _require().app_under_point(x, y)


# -- Window management ---------------------------------------------------------

def find_windows_by_title(pattern: str) -> list[dict[str, Any]]:
    """Find visible top-level windows whose title contains *pattern* (case-insensitive)."""
    return _require().find_windows_by_title(pattern)


def hide_window(hwnd: int) -> None:
    _require().hide_window(hwnd)


def show_window(hwnd: int) -> None:
    _require().show_window(hwnd)


def minimize_window(hwnd: int) -> None:
    _require().minimize_window(hwnd)


def restore_window(hwnd: int) -> None:
    _require().restore_window(hwnd)


def set_foreground(hwnd: int) -> bool:
    return _require().set_foreground(hwnd)


def set_capture_excluded(hwnd: int, excluded: bool = True) -> bool:
    """Mark a window as excluded from screen capture (zero flicker)."""
    return _require().set_capture_excluded(hwnd, excluded)
