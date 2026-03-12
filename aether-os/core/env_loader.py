"""
env_loader.py — Zero-dependency .env file loader.
Reads KEY=VALUE pairs from a .env file and sets them in os.environ.
Handles quoted values, inline comments, and blank lines.
Does NOT override variables already set in the environment.
"""
from __future__ import annotations
import os
import re
import sys


def load_env(env_path: str | None = None) -> None:
    """
    Load a .env file into os.environ without any third-party packages.
    If env_path is None, looks for .env next to this file's project root.
    """
    if env_path is None:
        if getattr(sys, "frozen", False):
            # PyInstaller .exe — .env lives next to the executable, not in the bundle
            env_path = os.path.join(os.path.dirname(sys.executable), ".env")
        else:
            # Normal execution — .env lives at the project root
            here = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(os.path.dirname(here), ".env")

    if not os.path.isfile(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        # Skip blank lines and comments
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue

        # Strip inline comment (only outside quotes)
        value = rest.strip()
        # Remove surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        else:
            # Strip trailing inline comment: value  # comment
            value = re.sub(r'\s+#.*$', '', value)

        # Only set if not already in environment
        if key not in os.environ:
            os.environ[key] = value
