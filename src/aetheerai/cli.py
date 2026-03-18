"""CLI entry point for ``pip install -e .`` → ``aetheerai`` command."""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Delegate to the root main.py which handles all CLI modes."""
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, root)
    from main import main as _main  # noqa: E402

    _main()


if __name__ == "__main__":
    main()
