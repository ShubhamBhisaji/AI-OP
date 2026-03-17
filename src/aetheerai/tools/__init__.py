"""
src/aetheerai/tools — re-exports AetheerAI/tools for src-layout consumers.

Usage:
    from aetheerai.tools.web_search import WebSearchTool
"""

from __future__ import annotations
import sys, os, importlib.util

_IMPL_TOOLS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "AetheerAI", "tools")
)

def __getattr__(name: str):
    mod_path = os.path.join(_IMPL_TOOLS, f"{name}.py")
    if os.path.isfile(mod_path):
        spec = importlib.util.spec_from_file_location(f"aetheerai.tools.{name}", mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"aetheerai.tools.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod
    raise AttributeError(f"module 'aetheerai.tools' has no attribute {name!r}")
