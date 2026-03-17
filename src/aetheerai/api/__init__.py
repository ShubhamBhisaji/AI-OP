"""
src/aetheerai/api — re-exports AetheerAI/api for src-layout consumers.

Usage:
    from aetheerai.api.server import app as fastapi_app
    uvicorn aetheerai.api.server:app --reload
"""

from __future__ import annotations
import sys, os, importlib.util

_IMPL_API = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "AetheerAI", "api")
)

def __getattr__(name: str):
    mod_path = os.path.join(_IMPL_API, f"{name}.py")
    if os.path.isfile(mod_path):
        spec = importlib.util.spec_from_file_location(f"aetheerai.api.{name}", mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"aetheerai.api.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod
    raise AttributeError(f"module 'aetheerai.api' has no attribute {name!r}")
