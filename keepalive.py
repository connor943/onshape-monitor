"""
Runs in a background thread.
Pings the app's own URL every 4 minutes so Streamlit Cloud
never hits the 5-minute inactivity timeout.
"""

import threading
import time
import requests
import os

_thread = None
_running = False


def _loop(url: str, interval: int):
    global _running
    while _running:
        try:
            requests.get(url, timeout=10)
        except Exception:
            pass  # silence — we don't care about the response
        time.sleep(interval)


def start(url: str, interval: int = 240):
    """Start the keepalive thread. Safe to call multiple times."""
    global _thread, _running
    if _thread and _thread.is_alive():
        return  # already running
    _running = True
    _thread = threading.Thread(target=_loop, args=(url, interval), daemon=True)
    _thread.start()


def stop():
    global _running
    _running = False
