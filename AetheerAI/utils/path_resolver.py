"""
path_resolver.py — Universal file-path resolver.

Paths fall into two distinct categories that MUST NOT be mixed:

  get_asset_path(relative_path)
      Read-only files bundled inside the .exe (icons, HTML templates, prompts).
      → routes to sys._MEIPASS when frozen; project root otherwise.

  get_data_path(relative_path)
      Writable, persistent data that must survive across .exe launches
      (memory_store.json, ChromaDB, exported agents, .env).
      → routes to the directory that contains the .exe when frozen;
        project root otherwise.  Parent directories are created automatically.

  get_path(relative_path)  [backward-compat alias for get_asset_path]

Bug 2 fix — _MEIPASS Memory Wipe:
  PyInstaller extracts _MEIPASS into a *temporary* AppData/Temp folder and
  DELETES it when the .exe exits.  Any data written there is permanently lost.
  Always use get_data_path() for anything that must persist between sessions.
"""

from __future__ import annotations

import os
import sys


# Root of the project when running normally (one level up from utils/)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_asset_path(relative_path: str) -> str:
    """
    Resolve a *read-only* asset that was bundled into the .exe.

    When frozen, files land in sys._MEIPASS (the PyInstaller temp extraction
    directory).  When running normally, they live under the project root.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(_PROJECT_ROOT, relative_path)


def get_data_path(relative_path: str) -> str:
    """
    Resolve a *writable / persistent* data file.

    When frozen, data is stored next to the .exe so it survives app restarts.
    When running normally, data lives under the project root.
    Parent directories are created automatically.
    """
    if getattr(sys, "frozen", False):
        # Save next to the .exe, NOT inside _MEIPASS (which is deleted on exit)
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = _PROJECT_ROOT

    full_path = os.path.join(base_dir, relative_path)
    parent = os.path.dirname(full_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return full_path


# Backward-compatible alias — existing callers of get_path() continue to work.
get_path = get_asset_path


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
