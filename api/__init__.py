"""Top-level API package for clean project architecture.

This package provides stable entry points at repository root while the
implementation continues to live under AetheerAI/api.
"""

from .server import app

__all__ = ["app"]
