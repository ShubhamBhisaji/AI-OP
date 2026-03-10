"""
ToolManager — Central registry for all tools available to Aether agents.
Tools are callable functions that agents can invoke during task execution.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ToolManager:
    """
    Registers and provides tools to agents.
    Tools are plain Python callables: fn(input: str) -> str.
    """

    def __init__(self):
        self._tools: dict[str, Callable[..., Any]] = {}
        self._register_builtins()

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn
        logger.debug("ToolManager: registered tool '%s'.", name)

    def get(self, name: str) -> Callable[..., Any] | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def call(self, name: str, *args, **kwargs) -> Any:
        fn = self._tools.get(name)
        if fn is None:
            raise KeyError(f"Tool '{name}' is not registered.")
        return fn(*args, **kwargs)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    # ------------------------------------------------------------------
    # Built-in tools are registered automatically at startup
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        from tools.web_search import web_search
        from tools.file_writer import file_writer

        self.register("web_search", web_search)
        self.register("file_writer", file_writer)
        logger.info("ToolManager: built-in tools registered: %s", self.list_tools())
