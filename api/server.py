"""Root API entry point.

Usage:
    uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any, Callable

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_AETHEERAI_ROOT = os.path.join(_PROJECT_ROOT, "AetheerAI")

for _p in (_AETHEERAI_ROOT, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Ensure `api.*` imports inside AetheerAI resolve to `AetheerAI.api.*`
# instead of this root-level gateway package.
sys.modules["api"] = importlib.import_module("AetheerAI.api")

_server_module = importlib.import_module("AetheerAI.api.server")
app = _server_module.app
custom_openapi = _server_module.custom_openapi


def _optional_callable(name: str, default: Callable[..., Any]) -> Callable[..., Any]:
    value = getattr(_server_module, name, None)
    if callable(value):
        return value
    return default


# Backward-compatible exports for legacy imports.
_parse_api_keys = _optional_callable("_parse_api_keys", lambda *_args, **_kwargs: [])
_strict_api_keys_required = _optional_callable("_strict_api_keys_required", lambda: False)
_required_role_for = _optional_callable("_required_role_for", lambda *_args, **_kwargs: "user")
_role_allows = _optional_callable(
    "_role_allows",
    lambda role, required_role: (str(role).strip().lower() == "admin") or (str(required_role).strip().lower() != "admin"),
)

__all__ = [
    "app",
    "custom_openapi",
    "_strict_api_keys_required",
    "_parse_api_keys",
    "_required_role_for",
    "_role_allows",
]
