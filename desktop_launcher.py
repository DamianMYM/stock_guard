#!/usr/bin/env python3
"""Desktop launcher that opens 鼓手 Stock Guard in the default browser."""

from __future__ import annotations

import threading
import time
import webbrowser

from web_app import main as run_server


def open_browser() -> None:
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:8787/")


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    run_server()
