"""API server entry point for ``pip install -e .`` → ``aetheerai-server`` command."""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Delegate to the root main.py in --api mode."""
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, root)
    sys.argv = [sys.argv[0], "--api"] + sys.argv[1:]
    from main import main as _main  # noqa: E402

    _main()


if __name__ == "__main__":
    main()
