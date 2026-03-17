"""
app/dashboard.py — AetheerAI Streamlit dashboard entry point.

Usage:
    streamlit run app/dashboard.py
    python -m streamlit run app/dashboard.py
"""

from __future__ import annotations

import os
import runpy
import sys

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_AETHEERAI_ROOT = os.path.join(_PROJECT_ROOT, "AetheerAI")

for _p in (_PROJECT_ROOT, _AETHEERAI_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_dashboard_path = os.path.join(_AETHEERAI_ROOT, "app.py")
runpy.run_path(_dashboard_path, run_name="__main__")
