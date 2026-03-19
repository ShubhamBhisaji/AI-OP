"""enforcement_gate.py — Single, mandatory, non-bypassable gate for ALL tool calls.

BLOCKER 2 FIX — Enforcement Layer Now Provably Non-Bypassable.

ARCHITECTURE
============
                    ┌────────────────────────────────────────────────────────┐
    Any caller      │              EnforcementGate  (singleton)               │
    (ToolManager,   │  1. PolicyEngine  — permission level / deny-by-default   │
     skill,     ───►│  2. ApprovalGate  — human-in-loop for Tier 1 / Tier 2   │──► Tool fn
     script,        │  3. AuditLogger   — every decision recorded              │
     direct import) │                                                          │
                    └────────────────────────────────────────────────────────┘
                                         ▲
                        installed once by AetheerAiKernel at boot

                    ┌──────────────────────────────────────────────────────────┐
                    │  tools/__init__.py  installs _ToolImportHook into         │
                    │  sys.meta_path — every tools.* module loaded AFTER that   │
                    │  has its public callables replaced with _GatedCallable.   │
                    └──────────────────────────────────────────────────────────┘

GUARANTEES
==========
1. **Fail-closed.** Gate starts CLOSED. All tool calls raise PolicyViolation
   until AetheerAiKernel calls EnforcementGate.install().

2. **No bypass via direct import.** `from tools.email_tool import email_tool`
   returns a _GatedCallable, not the raw function. The gate fires on every
   `email_tool(...)` call regardless of how the caller obtained the reference.

3. **No bypass via ToolManager.** ToolManager.call() already enforces
   PolicyEngine + ApprovalGate. When it passes _approval_bypass_token,
   _GatedCallable trusts the token and skips double-prompting — but the gate
   singleton must still be installed or the call is denied.

4. **Audit trail.** Every gate decision (allow/deny) is written to AuditLogger
   with the source ("enforcement_gate" for direct calls,
   "tool_manager_bypass" when ToolManager already ran checks).

5. **Future-proof.** New tool files added to tools/ are automatically gated
   because the sys.meta_path hook intercepts every tools.* import.

USAGE (kernel)
==============
    from security.enforcement_gate import EnforcementGate
    from security.policy_engine import PolicyEngine
    from security.audit_logger import AuditLogger
    from tools.tool_manager import TOOL_PERMISSIONS

    EnforcementGate.install(
        policy_engine=PolicyEngine(),
        audit_logger=AuditLogger.default(),
        tool_permissions=TOOL_PERMISSIONS,
    )

USAGE (direct call — gate fires automatically via _GatedCallable)
=================================================================
    from tools.email_tool import email_tool
    # Raises PolicyViolation — gate closed (called before install)
    email_tool(...)

    # After install — gate checks permission level
    email_tool(_agent_name="bot", _agent_level=2, to="x@y.com", subject="Hi")
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import logging
import sys
import threading
import types
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Thread-safety lock for singleton install / reset ───────────────────────
_GATE_LOCK = threading.Lock()

# ── Modules inside tools/ that should NOT be gated (management, not tools) ─
_HOOK_SKIP_MODULES: frozenset[str] = frozenset(
    {
        "tools",
        "tools.__init__",
        "tools.tool_manager",    # ToolManager class — not a tool callable
        "tools.plugin_loader",   # PluginLoader class — not a tool callable
    }
)


# ── Exception ─────────────────────────────────────────────────────────────

class PolicyViolation(PermissionError):
    """Raised by EnforcementGate when a tool call is denied."""

    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(f"[EnforcementGate] '{tool_name}' denied: {reason}")
        self.tool_name = tool_name
        self.reason = reason


# ── Explicit gate signature used for all _GatedCallable instances ──────────
# Ensures inspect.signature(_GatedCallable(fn)) always shows **kwargs so
# ToolManager reliably injects _approval_bypass_token / _agent_name.
_GATE_SIGNATURE = inspect.Signature(
    [
        inspect.Parameter("args", inspect.Parameter.VAR_POSITIONAL),
        inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD),
    ]
)


# ── _GatedCallable ─────────────────────────────────────────────────────────

class _GatedCallable:
    """
    Wraps a tool callable. EnforcementGate.check() fires before every invocation.

    Control kwargs (popped before the inner function is called)
    -----------------------------------------------------------
    _agent_name           : Name of the calling agent (str, default "unknown").
    _agent_level          : Permission level of the calling agent (int, default 0).
    _approval_bypass_token: Opaque object produced by
                            security.approval_gate.get_approval_bypass_token().
                            When present and valid, ToolManager already ran all
                            checks — skip re-prompting but still require an
                            installed gate and still audit.

    Callers that do NOT supply these kwargs are treated as "direct" calls and
    undergo the full gate check (PolicyEngine + ApprovalGate).
    """

    # No __slots__ — dunder attribute assignment in __init__ requires __dict__.

    def __init__(self, fn: Callable, tool_name: str) -> None:
        self._fn = fn
        self._tool_name = tool_name
        # Copy metadata (but NOT __wrapped__) so inspect.signature sees ours.
        self.__name__ = getattr(fn, "__name__", tool_name)
        self.__doc__ = getattr(fn, "__doc__", "")
        self.__module__ = getattr(fn, "__module__", "")
        self.__qualname__ = getattr(fn, "__qualname__", tool_name)
        self.__signature__ = _GATE_SIGNATURE  # always shows (*args, **kwargs)

    # ------------------------------------------------------------------
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        from security.approval_gate import (
            get_approval_bypass_token,
            ApprovalDenied,
        )

        bypass_token = kwargs.get("_approval_bypass_token")

        if bypass_token is get_approval_bypass_token():
            # ── ToolManager path: already checked — audit only ──────────
            # Leave _approval_bypass_token in kwargs so inner @require_approval
            # decorators (e.g. on file_writer, terminal_tool) can see it and
            # skip their own re-prompts.
            gate = EnforcementGate.get()   # still fails-closed if not installed
            gate._audit.log(
                {
                    "event": "enforcement_gate",
                    "tool": self._tool_name,
                    "agent": kwargs.get("_agent_name", "unknown"),
                    "agent_level": kwargs.get("_agent_level", "unknown"),
                    "decision": "allow",
                    "source": "tool_manager_bypass",
                }
            )
        else:
            # ── Direct-call path: pop control kwargs and run full check ─
            agent_name: str = kwargs.pop("_agent_name", "unknown")
            agent_level: int = int(kwargs.pop("_agent_level", 0))
            kwargs.pop("_approval_bypass_token", None)  # remove if present

            # This raises PolicyViolation if the gate is closed or denied.
            EnforcementGate.get().check(
                self._tool_name,
                agent_name=agent_name,
                agent_level=agent_level,
                context=dict(kwargs),
            )

        return self._fn(*args, **kwargs)

    def __repr__(self) -> str:
        return f"_GatedCallable({self._tool_name!r})"


# ── EnforcementGate singleton ──────────────────────────────────────────────

class EnforcementGate:
    """
    Process-level singleton enforcement gate.

    Starts CLOSED (fail-closed). Must be installed via install() before any
    tool call. All subsequent tool calls are authorized through this gate.
    """

    _instance: "EnforcementGate | None" = None

    def __init__(
        self,
        policy_engine: Any,
        audit_logger: Any,
        tool_permissions: dict[str, int] | None = None,
        default_permission: int = 3,
    ) -> None:
        self._policy = policy_engine
        self._audit = audit_logger
        self._tool_perms: dict[str, int] = tool_permissions or {}
        self._default_perm: int = int(default_permission)

    # ── Lifecycle ─────────────────────────────────────────────────────

    @classmethod
    def install(
        cls,
        policy_engine: Any,
        audit_logger: Any,
        tool_permissions: dict[str, int] | None = None,
        default_permission: int = 3,
    ) -> "EnforcementGate":
        """
        Install the singleton gate. Call exactly once at kernel startup.

        Parameters
        ----------
        policy_engine     : PolicyEngine instance for tool-level authorization.
        audit_logger      : AuditLogger instance for decision records.
        tool_permissions  : Dict mapping tool_name → required permission level.
                            Defaults to an empty dict (all tools require default).
        default_permission: Minimum level required for unregistered tools.
                            Defaults to 3 (ADMIN) — fail-secure for new tools.
        """
        with _GATE_LOCK:
            cls._instance = cls(
                policy_engine=policy_engine,
                audit_logger=audit_logger,
                tool_permissions=tool_permissions,
                default_permission=default_permission,
            )
            logger.info(
                "EnforcementGate: installed and OPEN. %d tool entries registered.",
                len(cls._instance._tool_perms),
            )
            return cls._instance

    @classmethod
    def get(cls) -> "EnforcementGate":
        """
        Return the installed gate.

        Raises PolicyViolation("<unknown>", ...) if the gate has not been
        installed yet — upholding the fail-closed guarantee.
        """
        if cls._instance is None:
            raise PolicyViolation(
                "<unknown>",
                "EnforcementGate has not been installed. "
                "AetheerAiKernel must call EnforcementGate.install() at startup "
                "before any tool may execute.",
            )
        return cls._instance

    @classmethod
    def is_installed(cls) -> bool:
        """Return True if the gate singleton has been installed."""
        return cls._instance is not None

    @classmethod
    def reset(cls) -> None:
        """
        Reset the gate to CLOSED state.

        Intended for use in test teardown only. Not safe in production.
        """
        with _GATE_LOCK:
            cls._instance = None
            logger.warning("EnforcementGate: RESET — gate is now CLOSED.")

    # ── Authorization ─────────────────────────────────────────────────

    def check(
        self,
        tool_name: str,
        *,
        agent_name: str = "unknown",
        agent_level: int = 0,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Run all enforcement checks for a direct tool call.

        Raises PolicyViolation if any check denies the call.
        On success, logs an "allow" entry to the audit logger.

        Parameters
        ----------
        tool_name   : Name of the tool being invoked.
        agent_name  : Identity of the calling agent (for audit / approval prompt).
        agent_level : Integer permission level of the caller.
        context     : Call-site kwargs forwarded to context for audit.
        """
        ctx = context or {}

        # ── 1. PolicyEngine — RBAC authorization ──────────────────────
        required = self._tool_perms.get(tool_name, self._default_perm)
        tool_registered = tool_name in self._tool_perms

        decision = self._policy.evaluate_tool_call(
            tool_name=tool_name,
            tool_registered=tool_registered,
            agent_level=agent_level,
            required_level=required,
        )
        if not decision.allowed:
            self._audit.log(
                {
                    "event": "enforcement_gate",
                    "tool": tool_name,
                    "agent": agent_name,
                    "agent_level": agent_level,
                    "required_level": required,
                    "decision": "deny",
                    "reason": decision.reason,
                    "source": "policy_engine",
                }
            )
            raise PolicyViolation(tool_name, decision.reason)

        # ── 2. ApprovalGate — human-in-the-loop for Tier 1 / Tier 2 ──
        from security.approval_gate import ALL_GUARDED_TOOLS, ApprovalDenied

        if tool_name in ALL_GUARDED_TOOLS:
            try:
                from security.approval_gate import ApprovalGate

                ApprovalGate.request(
                    tool_name=tool_name,
                    agent_name=agent_name,
                    args_summary=str(ctx),
                )
            except ApprovalDenied as exc:
                self._audit.log(
                    {
                        "event": "enforcement_gate",
                        "tool": tool_name,
                        "agent": agent_name,
                        "decision": "deny",
                        "reason": str(exc),
                        "source": "approval_gate",
                    }
                )
                raise PolicyViolation(tool_name, str(exc)) from exc

        # ── 3. Audit allow ─────────────────────────────────────────────
        self._audit.log(
            {
                "event": "enforcement_gate",
                "tool": tool_name,
                "agent": agent_name,
                "agent_level": agent_level,
                "required_level": required,
                "decision": "allow",
                "source": "direct_call",
            }
        )


# ── Module-level callable wrapping ────────────────────────────────────────

def _wrap_module_callables(module: types.ModuleType) -> None:
    """
    Wrap all public callables DEFINED in *module* with _GatedCallable.

    "Defined in" means obj.__module__ == module.__name__ — this avoids
    wrapping imported helpers, enums, or classes from other modules.
    """
    mod_name = module.__name__
    for attr_name in list(vars(module)):
        if attr_name.startswith("_"):
            continue
        obj = getattr(module, attr_name, None)
        if obj is None:
            continue
        if isinstance(obj, (_GatedCallable, type, types.ModuleType)):
            continue
        if not callable(obj):
            continue
        # Only wrap callables that were defined in this module
        obj_module = getattr(obj, "__module__", None)
        if obj_module != mod_name:
            continue
        setattr(module, attr_name, _GatedCallable(obj, attr_name))
        logger.debug(
            "EnforcementGate: wrapped '%s.%s' with _GatedCallable.",
            mod_name,
            attr_name,
        )


# ── _GatingLoader ──────────────────────────────────────────────────────────

class _GatingLoader(importlib.machinery.SourceFileLoader):
    """
    SourceFileLoader subclass that wraps tool callables after module execution.

    Installed by _ToolImportHook for every tools.* sub-module.
    """

    def exec_module(self, module: types.ModuleType) -> None:  # type: ignore[override]
        # Execute the real module source normally.
        super().exec_module(module)
        # Post-process: wrap public callables defined in this module.
        _wrap_module_callables(module)


# ── _ToolImportHook ────────────────────────────────────────────────────────

class _ToolImportHook(importlib.abc.MetaPathFinder):
    """
    sys.meta_path finder that intercepts imports of tools.* sub-modules and
    replaces their SourceFileLoader with _GatingLoader.

    Must be inserted at sys.meta_path[0] so it runs before all other finders.
    Installed exactly once by install_tool_import_hook() from tools/__init__.py.
    """

    def find_spec(
        self,
        fullname: str,
        path: Any,
        target: Any = None,
    ) -> importlib.machinery.ModuleSpec | None:

        # Only intercept tools.* direct sub-modules (one dot only)
        if not fullname.startswith("tools.") or fullname.count(".") != 1:
            return None
        if fullname in _HOOK_SKIP_MODULES:
            return None

        short = fullname.split(".")[-1]
        if short.startswith("_"):
            return None

        # If the module is already in sys.modules, the hook ran on first import;
        # retroactively wrap any un-gated callables and return None to reuse cache.
        if fullname in sys.modules:
            _wrap_module_callables(sys.modules[fullname])
            return None

        # Temporarily remove self to avoid infinite recursion when find_spec
        # calls importlib.util.find_spec which re-enters sys.meta_path.
        try:
            sys.meta_path.remove(self)
            real_spec = importlib.util.find_spec(fullname)
        finally:
            sys.meta_path.insert(0, self)

        if real_spec is None or not real_spec.origin:
            return None
        if not str(real_spec.origin).endswith(".py"):
            return None  # Only Python source files

        # Build a new spec using our gating loader.
        new_spec = importlib.util.spec_from_file_location(
            fullname,
            real_spec.origin,
            loader=_GatingLoader(fullname, real_spec.origin),
            submodule_search_locations=real_spec.submodule_search_locations,
        )
        return new_spec


# ── Public installation helper ─────────────────────────────────────────────

def install_tool_import_hook() -> None:
    """
    Install the _ToolImportHook into sys.meta_path[0].

    Called once from tools/__init__.py so every subsequent import of a
    tools.* module passes through the gating loader.

    Also retroactively patches any tools.* modules already present in
    sys.modules (e.g. imported before tools/__init__.py ran).
    """
    # Guard: only install once
    if any(isinstance(h, _ToolImportHook) for h in sys.meta_path):
        return

    sys.meta_path.insert(0, _ToolImportHook())
    logger.info("EnforcementGate: _ToolImportHook installed in sys.meta_path[0].")

    # Retroactively patch already-imported tool modules
    for mod_name, mod in list(sys.modules.items()):
        if (
            mod_name.startswith("tools.")
            and mod_name.count(".") == 1
            and mod_name not in _HOOK_SKIP_MODULES
            and isinstance(mod, types.ModuleType)
        ):
            short = mod_name.split(".")[-1]
            if not short.startswith("_"):
                _wrap_module_callables(mod)
                logger.debug(
                    "EnforcementGate: retroactively gated '%s'.", mod_name
                )
