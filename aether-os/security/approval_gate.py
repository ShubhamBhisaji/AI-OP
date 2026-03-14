"""
approval_gate.py — Human-in-the-loop approval for destructive / high-risk tool calls.

Any tool marked as DESTRUCTIVE or HIGH_RISK requires explicit user confirmation
before execution.  In headless/CI mode the gate auto-rejects (fail-safe).

Usage
-----
    from security.approval_gate import require_approval, ApprovalDenied

    @require_approval
    def file_writer(filename, content, ...):
        ...

    # Or call directly:
    approved = ApprovalGate.request("file_writer", {"filename": "foo.py"})
"""

from __future__ import annotations

import logging
import os
import asyncio
import contextvars
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Tools that require human approval before execution ───────────────────────
# Tier 1 — DESTRUCTIVE: irreversible host-system mutations
DESTRUCTIVE_TOOLS: frozenset[str] = frozenset(
    {
        "file_writer",        # writes / overwrites files on disk
        "local_file_tool",    # generic local file operations
        "email_tool",         # sends emails — external irreversible action
        "slack_discord_tool", # posts to team channels — external irreversible action
    }
)

# Tier 2 — HIGH_RISK: run arbitrary code / system commands on the host
# or perform destructive mutations of cloud / external infrastructure
HIGH_RISK_TOOLS: frozenset[str] = frozenset(
    {
        "code_runner",      # executes Python code in a subprocess
        "terminal_tool",    # runs shell/PowerShell commands
        "github_tool",      # commits and PRs on real repos
        "aws_gcp_tool",     # cloud storage delete / EC2 stop-reboot
        "kubernetes_tool",  # pod deletion / deployment restart / scaling
        "sql_db_tool",      # DML mutations on live databases
    }
)

ALL_GUARDED_TOOLS: frozenset[str] = DESTRUCTIVE_TOOLS | HIGH_RISK_TOOLS

# Opaque token used to skip duplicate prompts only when ToolManager has
# already performed centralized approval in-process.
_APPROVAL_BYPASS_TOKEN = object()


def get_approval_bypass_token() -> object:
    """Return the process-local opaque bypass token for internal callers."""
    return _APPROVAL_BYPASS_TOKEN


class ApprovalDenied(PermissionError):
    """Raised when a user denies execution of a guarded tool."""


class ApprovalGate:
    """
    Singleton-style gate that prompts the operator before running risky tools.

    Modes
    -----
    interactive (default) — shows a yes/no prompt in the terminal.
    headless              — set AETHER_HEADLESS=1 or call set_headless(True);
                            auto-rejects (fail-safe — never run unattended risky ops).
    auto_approve          — set AETHER_AUTO_APPROVE=1 for dev/test convenience;
                            logs a warning but proceeds without prompting.
    """

    _headless_default: bool = os.environ.get("AETHER_HEADLESS", "0") == "1"
    _auto_approve_default: bool = os.environ.get("AETHER_AUTO_APPROVE", "0") == "1"

    # Context-local overrides avoid cross-workflow bleed in concurrent execution.
    _headless_override: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
        "approval_headless_override", default=None
    )
    _auto_approve_override: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
        "approval_auto_approve_override", default=None
    )

    @classmethod
    def set_headless(cls, value: bool) -> None:
        cls._headless_override.set(bool(value))

    @classmethod
    def set_auto_approve(cls, value: bool) -> None:
        cls._auto_approve_override.set(bool(value))

    @classmethod
    def _headless(cls) -> bool:
        override = cls._headless_override.get()
        return cls._headless_default if override is None else override

    @classmethod
    def _auto_approve(cls) -> bool:
        override = cls._auto_approve_override.get()
        return cls._auto_approve_default if override is None else override

    @classmethod
    def request(
        cls,
        tool_name: str,
        agent_name: str,
        args_summary: str,
    ) -> None:
        """
        Ask the operator whether to allow *tool_name* to run.

        Raises ApprovalDenied if rejected; returns normally if approved.
        """
        tier = (
            "DESTRUCTIVE"
            if tool_name in DESTRUCTIVE_TOOLS
            else "HIGH-RISK"
            if tool_name in HIGH_RISK_TOOLS
            else None
        )
        if tier is None:
            return  # not a guarded tool — no approval needed

        if cls._auto_approve():
            logger.warning(
                "[ApprovalGate] AUTO-APPROVE: agent=%s tool=%s (%s) args=%s",
                agent_name, tool_name, tier, args_summary,
            )
            return

        if cls._headless():
            msg = (
                f"[ApprovalGate] HEADLESS MODE — auto-rejecting {tier} tool "
                f"'{tool_name}' requested by agent '{agent_name}'."
            )
            logger.warning(msg)
            raise ApprovalDenied(msg)

        # Avoid blocking asyncio loops with a synchronous input() prompt.
        try:
            if asyncio.get_running_loop().is_running():
                msg = (
                    "[ApprovalGate] Interactive approval requested inside an active "
                    "async event loop. Use hitl callback or headless mode instead."
                )
                logger.warning(msg)
                raise ApprovalDenied(msg)
        except RuntimeError:
            # No active loop in this thread — interactive prompt is safe.
            pass

        # ── Interactive prompt ────────────────────────────────────────
        print(
            f"\n{'='*60}\n"
            f"  ⚠️  APPROVAL REQUIRED\n"
            f"  Tier      : {tier}\n"
            f"  Tool      : {tool_name}\n"
            f"  Agent     : {agent_name}\n"
            f"  Action    : {args_summary}\n"
            f"{'='*60}"
        )
        try:
            answer = input("  Allow this action? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer not in ("y", "yes"):
            logger.info("[ApprovalGate] DENIED: %s → %s", agent_name, tool_name)
            raise ApprovalDenied(
                f"User denied execution of '{tool_name}' by agent '{agent_name}'."
            )

        logger.info("[ApprovalGate] APPROVED: %s → %s", agent_name, tool_name)


# ── Decorator for tool functions ─────────────────────────────────────────────

def require_approval(fn: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator — wrap a tool function so that it goes through ApprovalGate
    before executing.  The decorator reads the tool name from fn.__name__.

    The decorated function must accept an optional `_agent_name` keyword
    argument (injected by ToolManager when calling guarded tools).
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # ToolManager may already have performed the approval check centrally.
        # In that case skip the duplicate prompt and execute immediately.
        bypass_token = kwargs.pop("_approval_bypass_token", None)
        kwargs.pop("_approval_already_granted", None)  # legacy flag ignored
        if bypass_token is _APPROVAL_BYPASS_TOKEN:
            kwargs.pop("_agent_name", None)
            return fn(*args, **kwargs)

        agent_name: str = kwargs.pop("_agent_name", "unknown-agent")
        # Build a short human-readable summary of the call arguments
        arg_parts = [repr(a)[:80] for a in args]
        kwarg_parts = [f"{k}={repr(v)[:60]}" for k, v in kwargs.items()]
        args_summary = ", ".join(arg_parts + kwarg_parts) or "(no args)"

        ApprovalGate.request(
            tool_name=fn.__name__,
            agent_name=agent_name,
            args_summary=args_summary,
        )
        return fn(*args, **kwargs)

    return wrapper
