"""
src/aetheerai — AetheerAI public package (src-layout canonical entry).

This package re-exports the core public API from the AetheerAI implementation
so callers can do:

    from aetheerai import AetheerAiKernel, AgentFactory, orchestrator

Imports resolve at runtime via sys.path manipulation in pyproject.toml /
setup.cfg so that both the legacy `AetheerAI/` scripts and the new src-layout
coexist without duplication.
"""

from __future__ import annotations

import sys
import os

# Ensure the AetheerAI implementation directory is on the path when this
# package is imported directly (e.g. during development without an editable
# install).
_IMPL_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "AetheerAI")
)
if _IMPL_ROOT not in sys.path:
    sys.path.insert(0, _IMPL_ROOT)

# ── Public re-exports ──────────────────────────────────────────────────────
from core.aetheerai_kernel import AetheerAiKernel          # noqa: E402
from core.orchestrator import Orchestrator                  # noqa: E402
from factory.agent_factory import AgentFactory             # noqa: E402

__all__ = [
    "AetheerAiKernel",
    "Orchestrator",
    "AgentFactory",
]
