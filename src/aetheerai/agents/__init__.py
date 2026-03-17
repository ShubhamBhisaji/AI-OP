"""
src/aetheerai/agents — re-exports AetheerAI/agents for src-layout consumers.

Usage:
    from aetheerai.agents.base_agent import BaseAgent
    from aetheerai.agents.ceo_agent import CeoAgent
"""

from __future__ import annotations
import sys, os, importlib.util

_IMPL_AGENTS = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "AetheerAI", "agents")
)

def __getattr__(name: str):
    mod_path = os.path.join(_IMPL_AGENTS, f"{name}.py")
    if os.path.isfile(mod_path):
        spec = importlib.util.spec_from_file_location(f"aetheerai.agents.{name}", mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"aetheerai.agents.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod
    raise AttributeError(f"module 'aetheerai.agents' has no attribute {name!r}")
