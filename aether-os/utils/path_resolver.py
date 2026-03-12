"""
path_resolver.py — Universal file-path resolver.

Works correctly in two environments:
  1. Normal Python execution  (python app.py or streamlit run app.py)
  2. PyInstaller --onefile .exe  (files are extracted to sys._MEIPASS)

Usage:
    from utils.path_resolver import get_path

    cfg_path  = get_path("config.json")
    icon_path = get_path("aether_icon.svg")
    mem_path  = get_path("memory/memory_store.json")
"""

from __future__ import annotations

import os
import sys


# Root of the project when running normally
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_path(relative_path: str) -> str:
    """
    Return the absolute path to *relative_path*, resolving correctly whether
    the code is running as plain Python or inside a PyInstaller bundle.

    Parameters
    ----------
    relative_path : str
        Path relative to the project root (e.g. ``"memory/memory_store.json"``).

    Returns
    -------
    str
        Absolute path that exists at runtime.
    """
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller extracts bundled files here at runtime
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(_PROJECT_ROOT, relative_path)


def get_exe_dir() -> str:
    """
    Return the directory that contains the running executable (or the project
    root when running as plain Python).  Use this to find user-editable files
    like ``.env`` that live *next to* the .exe rather than inside the bundle.
    """
    if getattr(sys, "frozen", False):
        # sys.executable is the .exe path when frozen by PyInstaller
        return os.path.dirname(sys.executable)
    return _PROJECT_ROOT
