#!/usr/bin/env python3
"""Desktop launcher that opens 鼓手 Stock Guard in the default browser."""

from __future__ import annotations

import os
import threading
import time
import webbrowser

from web_app import Handler, ThreadingHTTPServer


APP_URL = "http://127.0.0.1:8787/"


def open_browser() -> None:
    time.sleep(1.2)
    if not os.environ.get("STOCKGUARD_NO_BROWSER"):
        webbrowser.open(APP_URL)


def main() -> int:
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    except OSError:
        webbrowser.open(APP_URL)
        input("Stock Guard is already running. Press Enter to close this window.\n")
        return 0

    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        input(
            "Stock Guard is running at http://127.0.0.1:8787\n"
            "Keep this window open. Press Enter to stop Stock Guard.\n"
        )
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
