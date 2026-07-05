#!/usr/bin/env python3
"""Desktop launcher that opens 鼓手 in the default browser."""

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
        input("鼓手已在运行。按回车关闭此窗口。\n")
        return 0

    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=open_browser, daemon=True).start()
    try:
        input(
            "鼓手正在运行：http://127.0.0.1:8787\n"
            "保持此窗口开启。按回车停止鼓手。\n"
        )
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
