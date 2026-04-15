"""Window manager — exclude our own app window from screenshots.

Three modes (controlled via ``set_hide_mode``):

  ``"none"`` (default)
      No window manipulation. The model sees our chat UI in screenshots.
      System prompt instructs it to ignore the Fool Code window.
      **Zero flicker.**

  ``"hide"``
      SW_HIDE before capture, SW_SHOW after.  The model never sees our UI
      but the browser window **flickers** briefly on each screenshot.

  ``"affinity"``
      Uses ``SetWindowDisplayAffinity(WDA_EXCLUDEDFROMCAPTURE)`` — zero
      flicker, window is invisible to captures.  Only works when the
      Fool Code UI runs in a window **owned by our process** (future
      Electron/Tauri desktop app).  Fails silently for browser windows.
"""

from __future__ import annotations

import logging
import time
import threading
from contextlib import contextmanager
from typing import Generator, Literal

from fool_code.computer_use import executor

logger = logging.getLogger(__name__)

HideMode = Literal["none", "hide", "affinity"]

_self_window_pattern: str | None = None
_hide_mode: HideMode = "none"
_excluded_hwnds: set[int] = set()
_lock = threading.Lock()

_SETTLE_MS = 80


def set_self_window_pattern(pattern: str | None) -> None:
    global _self_window_pattern
    _self_window_pattern = pattern
    logger.info("Window manager: self pattern = %r", pattern)


def get_self_window_pattern() -> str | None:
    return _self_window_pattern


def set_hide_mode(mode: HideMode) -> None:
    global _hide_mode
    _hide_mode = mode
    logger.info("Window manager: hide mode = %r", mode)
    if mode == "affinity":
        _try_mark_excluded()


def get_hide_mode() -> HideMode:
    return _hide_mode


def _find_self_windows() -> list[dict]:
    pattern = _self_window_pattern
    if not pattern or not executor.AVAILABLE:
        return []
    try:
        return executor.find_windows_by_title(pattern)
    except Exception as e:
        logger.warning("find_windows_by_title(%r) failed: %s", pattern, e)
        return []


def _try_mark_excluded() -> int:
    """Try to set WDA_EXCLUDEDFROMCAPTURE on matching windows.

    Only succeeds for windows owned by our process.
    """
    windows = _find_self_windows()
    count = 0
    with _lock:
        for w in windows:
            hwnd = w["hwnd"]
            if hwnd in _excluded_hwnds:
                continue
            try:
                ok = executor.set_capture_excluded(hwnd, True)
                if ok:
                    _excluded_hwnds.add(hwnd)
                    count += 1
                    logger.info("Excluded from capture: hwnd=%d title=%r", hwnd, w.get("title"))
            except Exception:
                pass
    return count


def _hide_windows() -> list[int]:
    windows = _find_self_windows()
    hidden = []
    for w in windows:
        hwnd = w["hwnd"]
        try:
            executor.hide_window(hwnd)
            hidden.append(hwnd)
        except Exception:
            pass
    if hidden:
        time.sleep(_SETTLE_MS / 1000.0)
    return hidden


def _show_windows(hwnds: list[int]) -> None:
    for hwnd in hwnds:
        try:
            executor.show_window(hwnd)
        except Exception:
            pass


@contextmanager
def hidden_self_windows() -> Generator[None, None, None]:
    """Context manager: temporarily exclude our windows from capture.

    Behaviour depends on the current hide mode:
      - "none":     no-op (zero flicker, model sees our UI)
      - "hide":     SW_HIDE → yield → SW_SHOW (flickers)
      - "affinity": one-time WDA_EXCLUDEDFROMCAPTURE (zero flicker)
    """
    if _hide_mode == "none":
        yield
        return

    if _hide_mode == "affinity":
        if not _excluded_hwnds:
            _try_mark_excluded()
        yield
        return

    # "hide" mode — SW_HIDE/SW_SHOW cycle
    hwnds = _hide_windows()
    try:
        yield
    finally:
        _show_windows(hwnds)


def activate_window_by_title(pattern: str) -> bool:
    """Bring the first window matching *pattern* to the foreground."""
    if not executor.AVAILABLE:
        return False
    try:
        windows = executor.find_windows_by_title(pattern)
        if windows:
            return executor.set_foreground(windows[0]["hwnd"])
    except Exception as e:
        logger.warning("activate_window_by_title(%r) failed: %s", pattern, e)
    return False
