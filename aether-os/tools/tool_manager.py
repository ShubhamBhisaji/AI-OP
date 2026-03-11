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
        # ── Original tools ────────────────────────────────────────────
        from tools.web_search import web_search
        from tools.file_writer import file_writer
        from tools.code_runner import code_runner

        self.register("web_search",   web_search)
        self.register("file_writer",  file_writer)
        self.register("code_runner",  code_runner)

        # ── Data tools ────────────────────────────────────────────────
        from tools.calculator    import calculator
        from tools.json_tool     import json_tool
        from tools.csv_tool      import csv_tool
        from tools.text_analyzer import text_analyzer

        self.register("calculator",    calculator)
        self.register("json_tool",     json_tool)
        self.register("csv_tool",      csv_tool)
        self.register("text_analyzer", text_analyzer)

        # ── File tools ────────────────────────────────────────────────
        from tools.file_reader        import file_reader
        from tools.directory_scanner  import directory_scanner
        from tools.diff_tool          import diff_tool

        self.register("file_reader",       file_reader)
        self.register("directory_scanner", directory_scanner)
        self.register("diff_tool",         diff_tool)

        # ── Network / browser tools ──────────────────────────────────
        from tools.http_client  import http_client
        from tools.browser_tool import browser_tool

        self.register("http_client",  http_client)
        self.register("browser_tool", browser_tool)

        # ── Utility tools ─────────────────────────────────────────────
        from tools.datetime_tool  import datetime_tool
        from tools.regex_tool     import regex_tool
        from tools.hash_tool      import hash_tool
        from tools.base64_tool    import base64_tool
        from tools.system_info    import system_info
        from tools.note_taker     import note_taker
        from tools.template_tool  import template_tool
        from tools.markdown_tool  import markdown_tool
        from tools.url_tool       import url_tool

        self.register("datetime_tool",  datetime_tool)
        self.register("regex_tool",     regex_tool)
        self.register("hash_tool",      hash_tool)
        self.register("base64_tool",    base64_tool)
        self.register("system_info",    system_info)
        self.register("note_taker",     note_taker)
        self.register("template_tool",  template_tool)
        self.register("markdown_tool",  markdown_tool)
        self.register("url_tool",       url_tool)

        # ── Coding & analytics tools ──────────────────────────────────
        from tools.code_analyzer  import code_analyzer
        from tools.analytics_tool import analytics_tool

        self.register("code_analyzer",  code_analyzer)
        self.register("analytics_tool", analytics_tool)

        # ── Security tool ─────────────────────────────────────────────
        from tools.security_tool import security_tool

        self.register("security_tool", security_tool)

        # ── Document & media tools ────────────────────────────────────
        from tools.pdf_tool   import pdf_tool
        from tools.media_tool import media_tool

        self.register("pdf_tool",   pdf_tool)
        self.register("media_tool", media_tool)

        # ── Code examination & terminal tools ─────────────────────────
        from tools.code_search    import code_search
        from tools.linter_tool    import linter_tool
        from tools.code_formatter import code_formatter
        from tools.terminal_tool  import terminal_tool

        self.register("code_search",    code_search)
        self.register("linter_tool",    linter_tool)
        self.register("code_formatter", code_formatter)
        self.register("terminal_tool",  terminal_tool)

        # ── Local file system ──────────────────────────────────────────
        from tools.local_file_tool import local_file_tool

        self.register("local_file_tool", local_file_tool)

        logger.info("ToolManager: %d tools registered: %s", len(self._tools), self.list_tools())
