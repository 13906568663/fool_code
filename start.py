"""Quick server launch — opens browser automatically.
Usage: uv run start.py
"""

import logging
import socket
import sys
import time
import webbrowser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    import uvicorn
    from fool_code.app import create_app

    port = find_free_port()
    app = create_app()

    url = f"http://127.0.0.1:{port}"
    print(f"Starting Fool Code on {url}")
    webbrowser.open(url)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
