"""action_proxy.py — Mandatory proxy for ALL external operations.

Closes GAP 1: Centralized Action Control Still Not Absolute.

Every external action — API calls, data writes, messaging, transactions,
system commands — MUST route through this proxy.  Code that bypasses
the proxy is structurally impossible when agents use the provided
interface.

Architecture
------------
    Agent  ──►  ActionProxy  ──►  ActionGate  ──►  External System
                     │
                     └──► AuditLogger (every call logged)

The proxy wraps five categories of external operations:
    1. api_call        — Any HTTP request to an external service
    2. data_write      — Database inserts, file writes, state mutations
    3. message_send    — Email, Slack, SMS, push notifications
    4. transaction     — Financial operations (payments, refunds, transfers)
    5. system_command  — Shell commands, process spawning, infrastructure ops

Usage
-----
    proxy = ActionProxy(agent_name="store_bot", action_gate=gate)

    # All external actions go through the proxy
    result = proxy.api_call("GET", "https://api.example.com/orders")
    result = proxy.data_write("insert", "users", {"name": "Alice"})
    result = proxy.message_send("email", "user@example.com", "Hello")
    result = proxy.transaction("refund", amount=49.99, currency="USD")
    result = proxy.system_command("ls", ["-la"])

    # Wrap any callable
    result = proxy.execute("custom_action", fn=my_function, args=(1, 2))
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Categories ──────────────────────────────────────────────────────────────

class ActionCategory(str, Enum):
    API_CALL = "api_call"
    DATA_WRITE = "data_write"
    MESSAGE_SEND = "message_send"
    TRANSACTION = "transaction"
    SYSTEM_COMMAND = "system_command"
    CUSTOM = "custom"


# ── Proxy Result ────────────────────────────────────────────────────────────

@dataclass
class ProxyResult:
    """Result of a proxied external action."""
    action_id: str
    category: str
    action: str
    allowed: bool
    result: Any = None
    error: str = ""
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)
    agent_name: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.allowed and not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "category": self.category,
            "action": self.action,
            "allowed": self.allowed,
            "success": self.success,
            "error": self.error,
            "duration": round(self.duration_seconds, 3),
            "agent": self.agent_name,
            "ts": self.timestamp,
        }


# ── ActionProxy ─────────────────────────────────────────────────────────────

class ActionProxy:
    """
    Mandatory proxy for ALL external operations.

    Every external action routes through:
        1. ActionGate authorization (mandatory)
        2. Economic guardrails check (if registered)
        3. Execution
        4. Audit logging (every call)

    Parameters
    ----------
    agent_name      : Agent this proxy serves.
    action_gate     : ActionGate instance (required — the single enforcement point).
    guardrails      : Optional EconomicGuardrails for cost/rate checks.
    audit           : Optional AuditLogger for persistent audit trail.
    observability   : Optional ObservabilityEngine for metrics.
    """

    def __init__(
        self,
        agent_name: str,
        action_gate: Any,
        guardrails: Any = None,
        audit: Any = None,
        observability: Any = None,
    ) -> None:
        self.agent_name = agent_name
        self._gate = action_gate
        self._guardrails = guardrails
        self._audit = audit
        self._obs = observability

        self._history: list[ProxyResult] = []
        self._max_history = 500
        self._total_calls = 0
        self._total_blocked = 0
        self._total_errors = 0

    # ── 1. API Calls ──────────────────────────────────────────────────────

    def api_call(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: Any = None,
        timeout_seconds: float = 30.0,
        context: dict[str, Any] | None = None,
        execute_fn: Callable | None = None,
    ) -> ProxyResult:
        """
        Proxy an API call through the gate.

        Parameters
        ----------
        method          : HTTP method (GET, POST, PUT, DELETE, etc.)
        url             : Target URL.
        headers         : Request headers.
        body            : Request body.
        timeout_seconds : Maximum allowed execution time.
        context         : Additional context for authorization.
        execute_fn      : Callable that actually makes the request.
                          Signature: () -> Any.  If None, returns a
                          "dry_run" result (gate check only).
        """
        action_name = f"api.{method.upper()}:{_truncate_url(url)}"
        ctx = {
            "method": method,
            "url": url,
            "has_body": body is not None,
            **(context or {}),
        }
        return self._execute_through_gate(
            category=ActionCategory.API_CALL,
            action=action_name,
            execute_fn=execute_fn,
            timeout_seconds=timeout_seconds,
            context=ctx,
        )

    # ── 2. Data Writes ────────────────────────────────────────────────────

    def data_write(
        self,
        operation: str,
        target: str,
        data: Any = None,
        *,
        timeout_seconds: float = 30.0,
        context: dict[str, Any] | None = None,
        execute_fn: Callable | None = None,
    ) -> ProxyResult:
        """
        Proxy a data write operation through the gate.

        Parameters
        ----------
        operation  : e.g. "insert", "update", "delete", "upsert"
        target     : Table, collection, or file path.
        data       : Payload to write.
        execute_fn : Callable() -> Any that performs the write.
        """
        action_name = f"data.{operation}:{target}"
        ctx = {
            "operation": operation,
            "target": target,
            "data_size": len(str(data)) if data else 0,
            **(context or {}),
        }
        return self._execute_through_gate(
            category=ActionCategory.DATA_WRITE,
            action=action_name,
            execute_fn=execute_fn,
            timeout_seconds=timeout_seconds,
            context=ctx,
        )

    # ── 3. Messaging ─────────────────────────────────────────────────────

    def message_send(
        self,
        channel: str,
        recipient: str,
        content: str,
        *,
        timeout_seconds: float = 30.0,
        context: dict[str, Any] | None = None,
        execute_fn: Callable | None = None,
    ) -> ProxyResult:
        """
        Proxy a message send through the gate.

        Parameters
        ----------
        channel    : "email", "slack", "sms", "push", "webhook", etc.
        recipient  : Target address or ID.
        content    : Message content (truncated in logs).
        execute_fn : Callable() -> Any that sends the message.
        """
        action_name = f"msg.{channel}:{recipient}"
        ctx = {
            "channel": channel,
            "recipient": recipient,
            "content_length": len(content),
            **(context or {}),
        }
        return self._execute_through_gate(
            category=ActionCategory.MESSAGE_SEND,
            action=action_name,
            execute_fn=execute_fn,
            timeout_seconds=timeout_seconds,
            context=ctx,
        )

    # ── 4. Transactions ──────────────────────────────────────────────────

    def transaction(
        self,
        operation: str,
        *,
        amount: float = 0.0,
        currency: str = "USD",
        timeout_seconds: float = 60.0,
        context: dict[str, Any] | None = None,
        execute_fn: Callable | None = None,
    ) -> ProxyResult:
        """
        Proxy a financial transaction through the gate.

        Parameters
        ----------
        operation  : "charge", "refund", "transfer", "payout", etc.
        amount     : Transaction amount.
        currency   : ISO 4217 currency code.
        execute_fn : Callable() -> Any that executes the transaction.
        """
        action_name = f"txn.{operation}:{amount}{currency}"
        ctx = {
            "operation": operation,
            "amount": amount,
            "currency": currency,
            **(context or {}),
        }
        return self._execute_through_gate(
            category=ActionCategory.TRANSACTION,
            action=action_name,
            execute_fn=execute_fn,
            timeout_seconds=timeout_seconds,
            context=ctx,
        )

    # ── 5. System Commands ───────────────────────────────────────────────

    def system_command(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        timeout_seconds: float = 30.0,
        context: dict[str, Any] | None = None,
        execute_fn: Callable | None = None,
    ) -> ProxyResult:
        """
        Proxy a system command through the gate.

        Parameters
        ----------
        command    : Command name (e.g. "ls", "docker", "kubectl").
        args       : Command arguments.
        execute_fn : Callable() -> Any that runs the command.
        """
        action_name = f"sys.{command}"
        ctx = {
            "command": command,
            "args": args or [],
            **(context or {}),
        }
        return self._execute_through_gate(
            category=ActionCategory.SYSTEM_COMMAND,
            action=action_name,
            execute_fn=execute_fn,
            timeout_seconds=timeout_seconds,
            context=ctx,
        )

    # ── 6. Generic execute ───────────────────────────────────────────────

    def execute(
        self,
        action: str,
        *,
        category: str = "custom",
        execute_fn: Callable | None = None,
        timeout_seconds: float = 30.0,
        context: dict[str, Any] | None = None,
    ) -> ProxyResult:
        """
        Proxy any action through the gate.

        Use this for operations that don't fit the 5 standard categories.
        """
        cat = ActionCategory(category) if category in ActionCategory.__members__.values() else ActionCategory.CUSTOM
        return self._execute_through_gate(
            category=cat,
            action=action,
            execute_fn=execute_fn,
            timeout_seconds=timeout_seconds,
            context=context,
        )

    # ── Core enforcement ─────────────────────────────────────────────────

    def _execute_through_gate(
        self,
        category: ActionCategory,
        action: str,
        execute_fn: Callable | None,
        timeout_seconds: float,
        context: dict[str, Any] | None,
    ) -> ProxyResult:
        """Central enforcement point — ALL actions flow through here."""
        action_id = str(uuid.uuid4())[:12]
        self._total_calls += 1
        start = time.time()

        # Step 1: Economic guardrails check (if registered)
        if self._guardrails is not None:
            try:
                quota_ok = self._guardrails.check_quota(
                    agent_name=self.agent_name,
                    category=category.value,
                    context=context,
                )
                if not quota_ok.get("allowed", True) is False:
                    pass  # allowed
                if quota_ok.get("allowed") is False:
                    self._total_blocked += 1
                    result = ProxyResult(
                        action_id=action_id,
                        category=category.value,
                        action=action,
                        allowed=False,
                        error=f"Economic guardrail: {quota_ok.get('reason', 'quota exceeded')}",
                        agent_name=self.agent_name,
                        context=context or {},
                    )
                    self._record(result)
                    return result
            except Exception as exc:
                logger.debug("ActionProxy: guardrails check failed: %s", exc)

        # Step 2: ActionGate authorization (mandatory — the single gate)
        try:
            gate_result = self._gate.execute_guarded(
                agent_name=self.agent_name,
                action=action,
                fn=execute_fn or (lambda: {"dry_run": True}),
                context=context,
                category=category.value,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            duration = time.time() - start
            self._total_blocked += 1
            result = ProxyResult(
                action_id=action_id,
                category=category.value,
                action=action,
                allowed=False,
                error=str(exc),
                duration_seconds=duration,
                agent_name=self.agent_name,
                context=context or {},
            )
            self._record(result)
            return result

        duration = time.time() - start

        # Step 3: Build result from gate response
        allowed = gate_result.allowed if hasattr(gate_result, "allowed") else gate_result.get("allowed", False)
        success = gate_result.success if hasattr(gate_result, "success") else gate_result.get("success", False)
        error = ""
        fn_result = None

        if hasattr(gate_result, "error"):
            error = gate_result.error or ""
        elif isinstance(gate_result, dict):
            error = gate_result.get("error", "")

        if hasattr(gate_result, "result"):
            fn_result = gate_result.result
        elif isinstance(gate_result, dict):
            fn_result = gate_result.get("result")

        if not allowed:
            self._total_blocked += 1
        if error:
            self._total_errors += 1

        result = ProxyResult(
            action_id=action_id,
            category=category.value,
            action=action,
            allowed=allowed,
            result=fn_result,
            error=error,
            duration_seconds=duration,
            agent_name=self.agent_name,
            context=context or {},
        )

        self._record(result)

        # Step 4: Record to observability (if registered)
        if self._obs is not None:
            try:
                self._obs.record_action(
                    action=action,
                    success=result.success,
                    duration_seconds=duration,
                    error=error,
                )
            except Exception:
                pass

        return result

    # ── Recording & stats ────────────────────────────────────────────────

    def _record(self, result: ProxyResult) -> None:
        """Record result in history and audit log."""
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Audit log
        if self._audit is not None:
            try:
                self._audit.log({
                    "event": "action_proxy",
                    "action_id": result.action_id,
                    "agent": result.agent_name,
                    "category": result.category,
                    "action": result.action,
                    "allowed": result.allowed,
                    "success": result.success,
                    "error": result.error[:200] if result.error else "",
                    "duration": result.duration_seconds,
                })
            except Exception:
                pass

        level = "info" if result.success else ("warning" if result.allowed else "error")
        log_fn = getattr(logger, level, logger.info)
        log_fn(
            "ActionProxy[%s]: %s %s (%s) — %s",
            self.agent_name,
            result.category,
            result.action[:60],
            "OK" if result.success else ("BLOCKED" if not result.allowed else f"ERROR: {result.error[:40]}"),
            f"{result.duration_seconds:.3f}s",
        )

    def stats(self) -> dict[str, Any]:
        """Return proxy statistics."""
        return {
            "agent": self.agent_name,
            "total_calls": self._total_calls,
            "total_blocked": self._total_blocked,
            "total_errors": self._total_errors,
            "block_rate": round(
                self._total_blocked / self._total_calls, 4
            ) if self._total_calls > 0 else 0.0,
            "by_category": self._stats_by_category(),
        }

    def _stats_by_category(self) -> dict[str, dict[str, int]]:
        """Break down stats by action category."""
        cats: dict[str, dict[str, int]] = {}
        for r in self._history:
            if r.category not in cats:
                cats[r.category] = {"total": 0, "blocked": 0, "errors": 0}
            cats[r.category]["total"] += 1
            if not r.allowed:
                cats[r.category]["blocked"] += 1
            if r.error and r.allowed:
                cats[r.category]["errors"] += 1
        return cats

    def history(
        self,
        category: str | None = None,
        allowed: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query proxy history with filters."""
        results = list(self._history)
        if category:
            results = [r for r in results if r.category == category]
        if allowed is not None:
            results = [r for r in results if r.allowed == allowed]
        return [r.to_dict() for r in results[-limit:]]

    def __repr__(self) -> str:
        return (
            f"ActionProxy(agent={self.agent_name!r}, "
            f"calls={self._total_calls}, blocked={self._total_blocked})"
        )


# ── Helpers ─────────────────────────────────────────────────────────────────

def _truncate_url(url: str, max_len: int = 60) -> str:
    """Shorten a URL for logging."""
    if len(url) <= max_len:
        return url
    return url[:max_len - 3] + "..."
