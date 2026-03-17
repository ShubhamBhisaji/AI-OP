"""
app/server.py — AetheerAI REST API entry point.

Usage:
    uvicorn app.server:app --reload --host 0.0.0.0 --port 8000

This is a thin wrapper that imports the FastAPI application object
from AetheerAI/api/server.py and re-exports it so uvicorn can find it
at 'app.server:app' regardless of working directory.
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_AETHEERAI_ROOT = os.path.join(_PROJECT_ROOT, "AetheerAI")

for _p in (_PROJECT_ROOT, _AETHEERAI_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.server import app  # noqa: E402  (AetheerAI/api/server.py)

__all__ = ["app"]
