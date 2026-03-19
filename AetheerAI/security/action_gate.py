"""action_gate.py — Centralized mandatory action gate.

Closes ISSUE 1: Permission Enforcement Still Too Soft.

Every sensitive operation MUST pass through the ActionGate before execution.
This is the single, mandatory checkpoint that cannot be bypassed — it wraps
the GuardrailController, PermissionEnforcer, PolicyEngine, and ApprovalGate
into one unavoidable gateway.

Key features:
    - Decorator (@action_gate.require) for enforcing at function level
    - Cooperative cancellation token for in-flight task termination
    - Per-task timeout with thread-based enforcement
    - Audit trail on every gate decision
    - Cannot be bypassed — all sensitive paths route through here

Usage
-----
    gate = ActionGate.from_manifest(manifest, audit_logger=audit)

    # Decorator usage (preferred — cannot be forgotten)
    @gate.require(action="process_refund", category="financial")
    def process_refund(order_id, amount):
        ...

    # Imperative usage
    token = gate.enter("send_email", agent_name="bot", context={"to": "x@y.com"})
    try:
        result = do_work()
        gate.exit_success(token)
    except Exception as e:
        gate.exit_failure(token, str(e))

    # Execute with timeout + cancellation
    result = gate.execute_guarded(
        agent_name="bot",
        action="process_refund",
        fn=lambda ctx: refund(ctx["order_id"]),
        context={"order_id": "123", "amount": 50},
        timeout_seconds=30,
    )
"""

from __future__ import annotations

import functools
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Action categories ────────────────────────────────────────────────────────

class ActionCategory(str, Enum):
    FINANCIAL    = "financial"     # Refunds, payments, transfers
    DATA_ACCESS  = "data_access"  # Customer data, orders, PII
    EXTERNAL_API = "external_api" # Calls to 3rd-party services
    SYSTEM_CMD   = "system_cmd"   # Shell, file system, deployment
    BULK_OP      = "bulk_op"      # Batch operations, mass updates
    COMMUNICATION = "communication"  # Email, SMS, Slack
    GENERAL      = "general"      # Non-sensitive operations


# ── Cancellation Token ───────────────────────────────────────────────────────

class CancellationToken:
    """Cooperative cancellation token for in-flight task termination.

    Pass this to long-running operations. They should periodically check
    ``token.is_cancelled`` and abort gracefully when True.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._reason: str = ""

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "Cancelled by operator") -> None:
        self._reason = reason
        self._cancelled.set()

    def check(self) -> None:
        """Raise if cancelled — call this in loops."""
        if self._cancelled.is_set():
            raise InterruptedError(f"Task cancelled: {self._reason}")


# ── Gate Token ───────────────────────────────────────────────────────────────

@dataclass
class GateToken:
    """Tracks an action through the gate lifecycle."""
    token_id: str
    agent_name: str
    action: str
    category: str
    context: dict[str, Any]
    cancellation: CancellationToken
    entered_at: float = field(default_factory=time.time)
    exited_at: float = 0.0
    status: str = "active"   # active | completed | failed | cancelled | timed_out | denied | awaiting_approval
    result: str = ""
    error: str = ""


# ── Execution Result ─────────────────────────────────────────────────────────

@dataclass
class GuardedResult:
    """Result of a guarded execution."""
    success: bool
    result: Any = None
    error: str = ""
    token_id: str = ""
    action: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    denied: bool = False
    denial_reason: str = ""


# ── ActionGate ───────────────────────────────────────────────────────────────

class ActionGate:
    """
    Centralized, mandatory action gate.

    All sensitive operations must pass through this gate. It unifies:
    - GuardrailController (business rules, rate limits, budgets)
    - Audit logging (every decision recorded)
    - Timeout enforcement (per-task deadline)
    - Cooperative cancellation (in-flight abort)

    Parameters
    ----------
    guardrail   : GuardrailController instance.
    audit       : Optional AuditLogger instance.
    default_timeout : Default per-action timeout in seconds (0 = unlimited).
    """

    def __init__(
        self,
        guardrail: Any = None,
        audit: Any = None,
        default_timeout: float = 120.0,
    ) -> None:
        self._guardrail = guardrail
        self._audit = audit
        self._default_timeout = default_timeout
        self._approval_controller = None
        self._active_tokens: dict[str, GateToken] = {}
        self._history: list[dict[str, Any]] = []
        self._max_history = 500
        self._lock = threading.Lock()
        self._enabled = True   # Master switch
        self._safe_mode = False  # Safe mode — all non-trivial categories require approval

    @classmethod
    def from_manifest(cls, manifest: Any, audit_logger: Any = None) -> "ActionGate":
        """Build an ActionGate from an AgentManifest."""
        from security.guardrail_controller import GuardrailController
        gc = GuardrailController.from_manifest(manifest, audit_logger=audit_logger)
        return cls(guardrail=gc, audit=audit_logger)

    # ── Master switch ────────────────────────────────────────────────────

    def enable(self) -> None:
        """Enable the gate (default state)."""
        self._enabled = True
        logger.info("ActionGate: ENABLED.")

    def disable(self) -> None:
        """Disable the gate — all actions are DENIED. Use for emergency lockdown."""
        self._enabled = False
        logger.warning("ActionGate: DISABLED — all actions will be denied.")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enter_safe_mode(self) -> None:
        """Enter safe mode — all non-GENERAL categories require manual approval."""
        self._safe_mode = True
        logger.warning("ActionGate: SAFE MODE entered — all non-trivial actions require approval.")

    def exit_safe_mode(self) -> None:
        """Exit safe mode — return to normal approval policy."""
        self._safe_mode = False
        logger.info("ActionGate: SAFE MODE exited — normal policy resumed.")

    @property
    def is_safe_mode(self) -> bool:
        """Return True if safe mode is active."""
        return self._safe_mode

    def register_approval_controller(self, controller: Any) -> None:
        """Register a human approval controller used for policy-driven approvals."""
        self._approval_controller = controller

    # ── Imperative API ───────────────────────────────────────────────────

    def enter(
        self,
        action: str,
        agent_name: str,
        category: str = "general",
        context: dict[str, Any] | None = None,
    ) -> GateToken:
        """
        Request permission to execute an action.

        Raises PermissionError if denied.
        Returns a GateToken to track the action lifecycle.
        """
        ctx = context or {}
        token = GateToken(
            token_id=str(uuid.uuid4()),
            agent_name=agent_name,
            action=action,
            category=category,
            context=ctx,
            cancellation=CancellationToken(),
        )

        # Master switch check
        if not self._enabled:
            token.status = "denied"
            token.error = "ActionGate is disabled (emergency lockdown)."
            token.exited_at = time.time()
            self._record_terminal_decision(token, allowed=False)
            self._log_decision(token, allowed=False)
            raise PermissionError(token.error)

        # Guardrail check
        guardrail_requested = False
        guardrail_reason = ""
        if self._guardrail is not None:
            verdict = self._guardrail.authorize(
                agent_name=agent_name,
                action=action,
                context=ctx,
            )
            if not verdict.allowed:
                token.status = "denied"
                token.error = verdict.reason
                token.exited_at = time.time()
                self._record_terminal_decision(token, allowed=False)
                self._log_decision(token, allowed=False)
                raise PermissionError(f"ActionGate denied: {verdict.reason}")
            guardrail_requested = verdict.requires_human_approval
            guardrail_reason = verdict.reason if verdict.requires_human_approval else ""

        approval_required, approval_reason = self._resolve_approval_requirement(
            action=action,
            category=category,
            context=ctx,
            guardrail_reason=guardrail_reason,
            guardrail_requested=guardrail_requested,
        )
        if approval_required:
            token.status = "awaiting_approval"
            request_id = self._queue_approval_request(
                action=action,
                category=category,
                context=ctx,
            )
            if request_id:
                token.context["approval_request_id"] = request_id
            token.error = f"Requires human approval: {approval_reason}"
            token.exited_at = time.time()
            self._record_terminal_decision(
                token,
                allowed=False,
                needs_approval=True,
            )
            self._log_decision(token, allowed=False, needs_approval=True)
            request_suffix = f" (request_id={request_id})" if request_id else ""
            raise PermissionError(
                f"ActionGate: human approval required — {approval_reason}{request_suffix}"
            )

        # Approved — track it
        with self._lock:
            self._active_tokens[token.token_id] = token
        self._log_decision(token, allowed=True)
        return token

    def exit_success(self, token: GateToken, result: str = "") -> None:
        """Mark an action as completed successfully."""
        token.status = "completed"
        token.result = result[:2000]
        token.exited_at = time.time()
        self._finalize_token(token)
        if self._guardrail is not None:
            self._guardrail.record_execution(token.action)

    def exit_failure(self, token: GateToken, error: str = "") -> None:
        """Mark an action as failed."""
        token.status = "failed"
        token.error = error[:2000]
        token.exited_at = time.time()
        self._finalize_token(token)

    # ── Guarded execution (timeout + cancellation) ───────────────────────

    def execute_guarded(
        self,
        agent_name: str,
        action: str,
        fn: Callable[[dict[str, Any]], Any],
        context: dict[str, Any] | None = None,
        category: str = "general",
        timeout_seconds: float | None = None,
    ) -> GuardedResult:
        """
        Execute a function through the gate with timeout and cancellation.

        Parameters
        ----------
        agent_name      : Agent requesting execution.
        action          : Action name for guardrail checks.
        fn              : Callable(context) → result. The function to execute.
        context         : Context dict passed to guardrails and to fn.
        category        : Action category for classification.
        timeout_seconds : Max execution time (None = use default).

        Returns
        -------
        GuardedResult with success flag, result/error, timing, and status.
        """
        ctx = context or {}
        timeout = timeout_seconds if timeout_seconds is not None else self._default_timeout
        start = time.time()

        # Gate entry (authorization check)
        try:
            token = self.enter(action, agent_name, category, ctx)
        except PermissionError as exc:
            return GuardedResult(
                success=False,
                error=str(exc),
                action=action,
                denied=True,
                denial_reason=str(exc),
                duration_seconds=time.time() - start,
            )

        # Execute with timeout
        result_holder: list[Any] = []
        error_holder: list[str] = []

        def _run():
            try:
                # Inject cancellation token into context
                ctx["_cancellation_token"] = token.cancellation
                output = fn(ctx)
                result_holder.append(output)
            except InterruptedError as exc:
                error_holder.append(f"Cancelled: {exc}")
            except Exception as exc:
                error_holder.append(str(exc))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout if timeout > 0 else None)

        duration = time.time() - start

        if thread.is_alive():
            # Timeout — signal cancellation
            token.cancellation.cancel("Execution timed out")
            token.status = "timed_out"
            token.exited_at = time.time()
            self._finalize_token(token)
            return GuardedResult(
                success=False,
                error=f"Timed out after {timeout}s",
                token_id=token.token_id,
                action=action,
                duration_seconds=duration,
                timed_out=True,
            )

        if error_holder:
            self.exit_failure(token, error_holder[0])
            return GuardedResult(
                success=False,
                error=error_holder[0],
                token_id=token.token_id,
                action=action,
                duration_seconds=duration,
                cancelled="Cancelled" in error_holder[0],
            )

        result = result_holder[0] if result_holder else None
        self.exit_success(token, str(result)[:2000] if result else "")
        return GuardedResult(
            success=True,
            result=result,
            token_id=token.token_id,
            action=action,
            duration_seconds=duration,
        )

    # ── Decorator API ────────────────────────────────────────────────────

    def require(
        self,
        action: str,
        category: str = "general",
        timeout_seconds: float | None = None,
    ) -> Callable:
        """
        Decorator that gates a function through the ActionGate.

        Usage::

            @gate.require(action="process_refund", category="financial")
            def process_refund(order_id, amount):
                ...

        The decorated function will:
        1. Check guardrails before execution
        2. Enforce timeout
        3. Support cooperative cancellation
        4. Log the decision and result to audit
        """
        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                # Build context from kwargs
                ctx = dict(kwargs)
                agent_name = ctx.pop("_agent_name", "unknown")

                result = self.execute_guarded(
                    agent_name=agent_name,
                    action=action,
                    fn=lambda c: fn(*args, **kwargs),
                    context=ctx,
                    category=category,
                    timeout_seconds=timeout_seconds,
                )
                if not result.success:
                    if result.denied:
                        raise PermissionError(result.denial_reason)
                    raise RuntimeError(result.error)
                return result.result
            return wrapper
        return decorator

    # ── Cancel in-flight actions ─────────────────────────────────────────

    def cancel_action(self, token_id: str, reason: str = "Operator cancellation") -> bool:
        """Cancel an in-flight action by token ID."""
        with self._lock:
            token = self._active_tokens.get(token_id)
        if token is None:
            return False

        token.cancellation.cancel(reason)
        token.status = "cancelled"
        token.error = reason
        token.exited_at = time.time()
        self._finalize_token(token)
        logger.info("ActionGate: cancelled action %s (token=%s): %s",
                     token.action, token_id, reason)
        return True

    def cancel_all(self, agent_name: str | None = None, reason: str = "Emergency stop") -> int:
        """Cancel all in-flight actions (optionally scoped to an agent)."""
        count = 0
        with self._lock:
            tokens = list(self._active_tokens.values())

        for token in tokens:
            if agent_name and token.agent_name != agent_name:
                continue
            token.cancellation.cancel(reason)
            token.status = "cancelled"
            token.error = reason
            token.exited_at = time.time()
            self._finalize_token(token)
            count += 1

        if count:
            logger.warning("ActionGate: cancelled %d in-flight actions: %s", count, reason)
        return count

    # ── Introspection ────────────────────────────────────────────────────

    def active_actions(self) -> list[dict[str, Any]]:
        """Return all currently active (in-flight) actions."""
        with self._lock:
            return [
                {
                    "token_id": t.token_id,
                    "agent": t.agent_name,
                    "action": t.action,
                    "category": t.category,
                    "started_at": t.entered_at,
                    "elapsed": round(time.time() - t.entered_at, 1),
                }
                for t in self._active_tokens.values()
                if t.status == "active"
            ]

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent gate decisions."""
        return list(self._history[-limit:])

    def stats(self) -> dict[str, Any]:
        """Return gate statistics."""
        total = len(self._history)
        allowed = sum(1 for h in self._history if h.get("allowed"))
        denied = sum(1 for h in self._history if not h.get("allowed"))
        timed_out = sum(1 for h in self._history if h.get("status") == "timed_out")
        cancelled = sum(1 for h in self._history if h.get("status") == "cancelled")
        return {
            "enabled": self._enabled,
            "safe_mode": self._safe_mode,
            "total_decisions": total,
            "allowed": allowed,
            "denied": denied,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "active_count": len(self._active_tokens),
            "default_timeout": self._default_timeout,
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    def _finalize_token(self, token: GateToken) -> None:
        """Move token from active to history."""
        with self._lock:
            self._active_tokens.pop(token.token_id, None)
        self._record_terminal_decision(token, allowed=True)

    def _record_terminal_decision(
        self,
        token: GateToken,
        *,
        allowed: bool,
        needs_approval: bool = False,
    ) -> None:
        entry = {
            "token_id": token.token_id,
            "agent": token.agent_name,
            "action": token.action,
            "category": token.category,
            "status": token.status,
            "allowed": allowed,
            "success": token.status == "completed",
            "needs_approval": needs_approval,
            "approval_request_id": token.context.get("approval_request_id", ""),
            "error": token.error,
            "duration": round(token.exited_at - token.entered_at, 3) if token.exited_at else 0,
            "timestamp": token.entered_at,
        }
        with self._lock:
            self._history.append(entry)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def _resolve_approval_requirement(
        self,
        *,
        action: str,
        category: str,
        context: dict[str, Any],
        guardrail_reason: str,
        guardrail_requested: bool,
    ) -> tuple[bool, str]:
        controller = self._approval_controller
        if controller is not None and hasattr(controller, "consume_approval"):
            try:
                approved = controller.consume_approval(
                    action,
                    category=category,
                    context=context,
                )
            except TypeError:
                approved = controller.consume_approval(action)
            except Exception as exc:
                logger.debug("ActionGate: approval consume check failed: %s", exc)
                approved = False
            if approved:
                return False, ""

        if guardrail_requested:
            return True, guardrail_reason or "Guardrail policy requested approval."

        # Safe mode: all non-trivial categories require manual approval
        if self._safe_mode and category != ActionCategory.GENERAL.value and category != "general":
            return True, "Safe mode: all non-trivial actions require operator approval."

        if controller is not None and hasattr(controller, "needs_approval"):
            try:
                if controller.needs_approval(action):
                    return True, "Matched operator approval policy."
            except Exception as exc:
                logger.debug("ActionGate: approval policy lookup failed: %s", exc)

        # Check for operator-staged pending approval (trigger_manual_approval)
        if controller is not None and hasattr(controller, "has_pending_approval"):
            try:
                if controller.has_pending_approval(action):
                    return True, "Pre-staged approval gate: operator requires sign-off."
            except Exception as exc:
                logger.debug("ActionGate: pending approval check failed: %s", exc)

        return False, ""

    def _queue_approval_request(
        self,
        *,
        action: str,
        category: str,
        context: dict[str, Any],
    ) -> str:
        controller = self._approval_controller
        if controller is None or not hasattr(controller, "request_approval"):
            return ""
        try:
            request = controller.request_approval(
                action=action,
                category=category,
                context=context,
            )
        except TypeError:
            request = controller.request_approval(action)
        except Exception as exc:
            logger.debug("ActionGate: approval request enqueue failed: %s", exc)
            return ""
        return str(getattr(request, "id", "") or "")

    def _log_decision(
        self,
        token: GateToken,
        allowed: bool,
        needs_approval: bool = False,
    ) -> None:
        """Log gate decision to audit trail."""
        if self._audit is None:
            return
        try:
            self._audit.log({
                "event": "action_gate",
                "token_id": token.token_id,
                "agent": token.agent_name,
                "action": token.action,
                "category": token.category,
                "allowed": allowed,
                "needs_approval": needs_approval,
                "error": token.error,
            })
        except Exception:
            pass

    def __repr__(self) -> str:
        return (
            f"ActionGate(enabled={self._enabled}, "
            f"active={len(self._active_tokens)}, "
            f"decisions={len(self._history)})"
        )
