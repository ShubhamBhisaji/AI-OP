"""Canonical runtime entrypoint for AetheerAI.

Run:
    python main.py
"""

from __future__ import annotations

from api.server import start_server


if __name__ == "__main__":
    start_server()
