"""
src/aetheerai/core — re-exports AetheerAI/core for src-layout consumers.

Usage:
    from aetheerai.core.orchestrator import Orchestrator
    from aetheerai.core.aetheerai_kernel import AetheerAiKernel
"""

from __future__ import annotations
import importlib, sys, os

_IMPL_CORE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "AetheerAI", "core")
)

def __getattr__(name: str):
    """Lazily proxy attribute access to the AetheerAI.core package."""
    import importlib.util
    mod_path = os.path.join(_IMPL_CORE, f"{name}.py")
    if os.path.isfile(mod_path):
        spec = importlib.util.spec_from_file_location(f"aetheerai.core.{name}", mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"aetheerai.core.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod
    raise AttributeError(f"module 'aetheerai.core' has no attribute {name!r}")
