"""
app/cli.py — AetheerAI Command-Line Interface entry point.

Usage:
    python app/cli.py
    python app/cli.py --provider claude
    python app/cli.py --provider ollama --model llama3

This is a thin wrapper.  All logic lives in AetheerAI/main.py.
"""

from __future__ import annotations

import os
import sys

# Resolve project root so AetheerAI/ is importable regardless of cwd.
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_AETHEERAI_ROOT = os.path.join(_PROJECT_ROOT, "AetheerAI")

for _p in (_PROJECT_ROOT, _AETHEERAI_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Delegate to the canonical main module.
if __name__ == "__main__":
    import runpy
    runpy.run_path(
        os.path.join(_AETHEERAI_ROOT, "main.py"),
        run_name="__main__",
    )
