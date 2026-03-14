from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

import uvicorn

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from core.env_loader import load_env as _lenv
from server import app

_lenv(os.path.join(_ROOT, ".env"))
_HOST = "127.0.0.1"
_PORT = 8000
_URL = f"http://{_HOST}:{_PORT}"


def _start_server() -> None:
    uvicorn.run(app, host=_HOST, port=_PORT, log_level="critical")


if __name__ == "__main__":
    print("Starting __AGENT_NAME__ UI...")
    t = threading.Thread(target=_start_server, daemon=True)
    t.start()
    time.sleep(2)
    webbrowser.open(_URL)
    while True:
        time.sleep(1)
