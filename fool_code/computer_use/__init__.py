"""Computer Use — self-contained sub-package for Windows desktop control.

Usage:
    from fool_code.computer_use import register_computer_use
    register_computer_use(registry)

To remove: delete this directory and remove the import from registry.py.

Build the native extension:
    cd fool_code/computer_use/_native
    maturin develop --release
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fool_code.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def register_computer_use(registry: ToolRegistry) -> bool:
    """Register all Computer Use tools into the given registry.

    Returns True if tools were registered, False if the native
    extension is missing (tools silently skipped).
    """
    from fool_code.computer_use.executor import AVAILABLE
    from fool_code.computer_use.tools import ALL_TOOLS
    from fool_code.computer_use.window_manager import set_self_window_pattern

    if not AVAILABLE:
        logger.info(
            "[Computer Use] Native module not available — skipping tool registration. "
            "Build with: cd fool_code/computer_use/_native && maturin develop --release"
        )
        return False

    set_self_window_pattern("Fool Code")

    for tool_cls in ALL_TOOLS:
        registry.register_handler(tool_cls())

    logger.info("[Computer Use] Registered %d tools", len(ALL_TOOLS))
    return True
