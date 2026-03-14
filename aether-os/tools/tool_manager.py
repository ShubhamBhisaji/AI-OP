"""
ToolManager — Central registry for all tools available to Aether agents.
Tools are callable functions that agents can invoke during task execution.

RBAC (Fix 6)
------------
Each tool has a minimum *permission level* (0–3).  Agents carry a
`permission_level` in their profile.  A tool call is rejected if the
agent's level is lower than the tool's required level.

Levels
------
  0 — GUEST      : read-only, safe utilities only
  1 — STANDARD   : file reading, web search, analysis
  2 — ELEVATED   : file writing, code analysis, local files
  3 — ADMIN      : code runner, terminal, security tool

Additionally, DESTRUCTIVE and HIGH_RISK tools (see security.approval_gate)
require interactive human approval before they execute (Fix 1).
"""

from __future__ import annotations

import logging
import inspect
from typing import Any, Callable

from security.approval_gate import (
    ApprovalDenied,
    ApprovalGate,
    ALL_GUARDED_TOOLS,
)  # re-exported for callers

logger = logging.getLogger(__name__)

# ── Minimum permission level required to call each tool ──────────────────────
# (0=guest, 1=standard, 2=elevated, 3=admin)
TOOL_PERMISSIONS: dict[str, int] = {
    # Level 0 — safe utilities
    "calculator":       0,
    "ping_agent":       1,   # inter-agent comms — standard level
    "datetime_tool":    0,
    "hash_tool":        0,
    "base64_tool":      0,
    "regex_tool":       0,
    "text_analyzer":    0,
    "json_tool":        0,
    "markdown_tool":    0,
    "url_tool":         0,
    "template_tool":    0,
    "diff_tool":        0,
    # Level 1 — standard operations (network + read)
    "web_search":       1,
    "http_client":      1,
    "browser_tool":     1,
    "file_reader":      1,
    "directory_scanner":1,
    "csv_tool":         1,
    "note_taker":       1,
    "analytics_tool":   1,
    "system_info":      1,
    # Level 2 — elevated (writes + code inspection)
    "file_writer":      2,
    "local_file_tool":  2,
    "code_analyzer":    2,
    "code_search":      2,
    "linter_tool":      2,
    "code_formatter":   2,
    "pdf_tool":         2,
    "media_tool":       2,
    # Level 3 — admin only
    "code_runner":      3,
    "terminal_tool":    3,
    "security_tool":    3,
    # ── Enterprise expansion tools ──────────────────────────────────
    # Level 1 — standard (read-only / notify outbound)
    "web_scraper_pro":  1,
    "vision_tool":      1,
    "speech_tool":      1,
    "slack_discord_tool": 1,
    # Level 2 — elevated (authenticated external services / read-write)
    "github_tool":      2,
    "sql_db_tool":      2,
    "playwright_tool":  2,
    "image_gen_tool":   2,
    "email_tool":       2,
    # Level 3 — admin (cloud infrastructure and commit/deploy)
    "aws_gcp_tool":     3,
    "kubernetes_tool":  3,
}

# Default level for any tool not listed above
_DEFAULT_TOOL_PERMISSION = 1


class PermissionDenied(PermissionError):
    """Raised when an agent lacks the permission level for a tool."""


class ToolManager:
    """
    Registers and provides tools to agents.
    Tools are plain Python callables: fn(input: str) -> str.

    All calls go through RBAC permission checks (Fix 6).
    Destructive/high-risk tool calls go through the ApprovalGate (Fix 1).
    """

    def __init__(self):
        self._tools: dict[str, Callable[..., Any]] = {}
        self._engine = None          # set later by inject_engine()
        self._register_builtins()

    def inject_engine(self, engine) -> None:
        """
        Wire the WorkflowEngine into tools that need cross-agent access.

        Must be called after both ToolManager and WorkflowEngine are created
        (i.e. inside AetherKernel.__init__ after workflow_engine is built).
        Currently wires: ping_agent.
        """
        import functools
        from tools.agent_ping_tool import ping_agent

        self._engine = engine
        bound = functools.partial(ping_agent, _engine=engine)
        # Preserve the name attribute so list_tools() / logging remain readable
        bound.__name__ = "ping_agent"   # type: ignore[attr-defined]
        self.register("ping_agent", bound)
        logger.info("ToolManager: WorkflowEngine injected into ping_agent.")

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn
        logger.debug("ToolManager: registered tool '%s'.", name)

    def get(self, name: str) -> Callable[..., Any] | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def call(self, name: str, *args, agent_name: str = "unknown", agent_level: int = 1, **kwargs) -> Any:
        """
        Invoke a tool by name, enforcing RBAC and approval gate.

        Parameters
        ----------
        name         : Registered tool name.
        *args        : Positional arguments forwarded to the tool function.
        agent_name   : Name of the calling agent (for audit logs and approval prompt).
        agent_level  : Agent's integer permission level (0-3).
        **kwargs     : Keyword arguments forwarded to the tool function.
        """
        fn = self._tools.get(name)
        if fn is None:
            raise KeyError(f"Tool '{name}' is not registered.")

        # ── RBAC check ────────────────────────────────────────────────
        required = TOOL_PERMISSIONS.get(name, _DEFAULT_TOOL_PERMISSION)
        if agent_level < required:
            raise PermissionDenied(
                f"Agent '{agent_name}' (level {agent_level}) cannot use '{name}' "
                f"(requires level {required})."
            )

        # ── Centralized approval gate ───────────────────────────────
        # Enforce approval for all guarded tools even if a specific tool
        # was not decorated with @require_approval.
        if name in ALL_GUARDED_TOOLS:
            arg_parts = [repr(a)[:80] for a in args]
            kwarg_parts = [f"{k}={repr(v)[:60]}" for k, v in kwargs.items()]
            args_summary = ", ".join(arg_parts + kwarg_parts) or "(no args)"
            ApprovalGate.request(
                tool_name=name,
                agent_name=agent_name,
                args_summary=args_summary,
            )

        # Only inject private control kwargs if the target function can accept
        # arbitrary kwargs. This prevents TypeError on plain function tools.
        try:
            sig = inspect.signature(fn)
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in sig.parameters.values()
            )
        except (TypeError, ValueError):
            accepts_var_kw = False
        if accepts_var_kw:
            # If the function is decorated with @require_approval, this flag
            # prevents a second prompt after the centralized check above.
            kwargs["_approval_already_granted"] = True
            kwargs["_agent_name"] = agent_name

        return fn(*args, **kwargs)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    # ------------------------------------------------------------------
    # Built-in tools are registered automatically at startup
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        # ── Inter-agent communication ─────────────────────────────────
        # ping_agent is registered with a None engine here; the engine is
        # injected properly via inject_engine() after the kernel is fully
        # initialised.  Until then the tool is present but returns an error
        # if called without the engine.
        from tools.agent_ping_tool import ping_agent
        self.register("ping_agent", ping_agent)

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
        # ── Enterprise expansion: Software Engineering ────────────────────
        from tools.github_tool   import github_tool
        from tools.sql_db_tool   import sql_db_tool

        self.register("github_tool",    github_tool)
        self.register("sql_db_tool",    sql_db_tool)

        # ── Enterprise expansion: Deep Web & Browser Automation ──────────
        from tools.playwright_tool  import playwright_tool
        from tools.web_scraper_pro  import web_scraper_pro

        self.register("playwright_tool", playwright_tool)
        self.register("web_scraper_pro", web_scraper_pro)

        # ── Enterprise expansion: Multimodal & Generative ───────────────
        from tools.vision_tool    import vision_tool
        from tools.image_gen_tool import image_gen_tool
        from tools.speech_tool    import speech_tool

        self.register("vision_tool",    vision_tool)
        self.register("image_gen_tool", image_gen_tool)
        self.register("speech_tool",    speech_tool)

        # ── Enterprise expansion: Communications ───────────────────────
        from tools.email_tool          import email_tool
        from tools.slack_discord_tool  import slack_discord_tool

        self.register("email_tool",          email_tool)
        self.register("slack_discord_tool",  slack_discord_tool)

        # ── Enterprise expansion: Cloud Infrastructure ──────────────────
        from tools.aws_gcp_tool    import aws_gcp_tool
        from tools.kubernetes_tool import kubernetes_tool

        self.register("aws_gcp_tool",    aws_gcp_tool)
        self.register("kubernetes_tool", kubernetes_tool)
        logger.info("ToolManager: %d tools registered: %s", len(self._tools), self.list_tools())
