"""Root API entry point.

Usage:
    uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import importlib
import os
import sys

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_AETHEERAI_ROOT = os.path.join(_PROJECT_ROOT, "AetheerAI")

for _p in (_AETHEERAI_ROOT, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Ensure `api.*` imports inside AetheerAI resolve to `AetheerAI.api.*`
# instead of this root-level gateway package.
sys.modules["api"] = importlib.import_module("AetheerAI.api")

from AetheerAI.api.server import (  # noqa: E402
    _parse_api_keys,
    _required_role_for,
    _role_allows,
    app,
)

__all__ = ["app", "_parse_api_keys", "_required_role_for", "_role_allows"]
