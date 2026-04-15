"""Desktop entry point — start FastAPI server + pywebview window."""

from __future__ import annotations

import io
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


class DesktopApi:
    """Bridge desktop-only helpers into the webview frontend."""

    def __init__(self) -> None:
        try:
            from webview.dom import _dnd_state

            # React handles the DOM drop event, so pywebview's internal
            # drag-and-drop bookkeeping needs to be kept alive explicitly.
            _dnd_state["num_listeners"] = max(int(_dnd_state.get("num_listeners", 0)), 1)
        except Exception:
            pass

    def resolve_dropped_files(self, payload: dict | None = None) -> list[str]:
        try:
            from webview.dom import _dnd_state
        except Exception:
            return []

        files = payload.get("files", []) if isinstance(payload, dict) else []
        if not isinstance(files, list):
            return []

        resolved: list[str] = []
        pending = list(_dnd_state.get("paths", []))

        for item in files:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip()
            if not name:
                continue

            match_index = next(
                (
                    idx
                    for idx, pair in enumerate(pending)
                    if Path(str(pair[1])).name.lower() == name.lower()
                ),
                None,
            )

            if match_index is None:
                continue

            _, full_path = pending.pop(match_index)
            resolved.append(str(full_path))

        _dnd_state["paths"] = pending
        return resolved


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _setup_frozen_env() -> None:
    """When bundled by PyInstaller, adjust working paths."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        os.environ.setdefault(
            "FOOL_CODE_FRONTEND_DIR", os.path.join(base, "desktop-ui", "dist")
        )
        os.environ.setdefault("FOOL_CODE_SKIP_GIT_CONTEXT", "1")


def _setup_file_logging(log_dir: Path) -> None:
    """Configure logging to write to both console and daily rotating log files."""
    from logging.handlers import TimedRotatingFileHandler

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "foolcode.log"

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", backupCount=7, encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(fmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def main() -> None:
    _setup_frozen_env()

    from fool_code.runtime.config import app_data_root
    _setup_file_logging(app_data_root() / "logs")

    if "--browser-mcp-sidecar" in sys.argv:
        from fool_code.internal_mcp.browser_mcp.__main__ import main as browser_mcp_main

        sys.argv = [arg for arg in sys.argv if arg != "--browser-mcp-sidecar"]
        browser_mcp_main()
        return

    import uvicorn

    from fool_code.app import create_app

    port = find_free_port()
    app = create_app()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not wait_for_server(port):
        print("Failed to start backend server", file=sys.stderr)
        sys.exit(1)

    print(f"Fool Code backend started on http://127.0.0.1:{port}")

    url = f"http://127.0.0.1:{port}"
    opened_in_browser = False

    try:
        import webview

        window = webview.create_window(
            "Fool Code",
            url=url,
            width=1200,
            height=800,
            min_size=(800, 600),
            js_api=DesktopApi(),
        )
        webview.start()
        return
    except ImportError:
        print("pywebview not available — running in browser mode")
    except Exception as exc:
        print(f"pywebview failed ({exc}) — falling back to browser mode")

    if not opened_in_browser:
        try:
            import webbrowser
            webbrowser.open(url)
            opened_in_browser = True
            print(f"Opened {url} in your default browser")
        except Exception:
            print(f"Open {url} in your browser")

    try:
        server_thread.join()
    except KeyboardInterrupt:
        pass


def main_server_only() -> None:
    """Run only the HTTP server (no desktop window) — useful for development."""
    from fool_code.runtime.config import app_data_root
    _setup_file_logging(app_data_root() / "logs")

    import uvicorn

    from fool_code.app import create_app

    port = find_free_port()
    app = create_app()
    print(f"Starting Fool Code server on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    if "--server-only" in sys.argv:
        main_server_only()
    else:
        main()
