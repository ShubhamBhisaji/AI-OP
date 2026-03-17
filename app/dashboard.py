"""
app/dashboard.py — AetheerAI Streamlit dashboard entry point.

Usage:
    streamlit run app/dashboard.py
    python -m streamlit run app/dashboard.py

This is a thin wrapper.  All Streamlit logic lives in AetheerAI/app.py.
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_AETHEERAI_ROOT = os.path.join(_PROJECT_ROOT, "AetheerAI")

for _p in (_PROJECT_ROOT, _AETHEERAI_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Streamlit executes the module body directly; delegate via exec so that
# all Streamlit page-config calls happen in the correct module context.
_dashboard_path = os.path.join(_AETHEERAI_ROOT, "app.py")

with open(_dashboard_path, encoding="utf-8") as _fh:
    exec(compile(_fh.read(), _dashboard_path, "exec"), {"__name__": "__main__"})  # noqa: S102
