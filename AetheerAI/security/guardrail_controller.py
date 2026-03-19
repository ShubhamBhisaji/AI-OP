"""guardrail_controller.py — Unified permission guardrail system.

Closes GAP 4: Permission Guardrails Minimal.

This controller unifies all existing security components into a single
gateway that every agent action passes through before execution:

    1. PermissionEnforcer   — business rules (refund limits, rate limits)
    2. PolicyEngine         — tool-level authorization (permission levels)
    3. ApprovalGate         — human-in-the-loop for destructive actions
    4. GovernanceLayer      — runtime budget/time limits
    5. AuditLogger          — append-only audit trail

The GuardrailController is the single entry point:

    controller = GuardrailController.from_manifest(manifest)
    verdict = controller.authorize(
        agent_name="support_bot",
        action="process_refund",
        tool="payment_tool",
        context={"amount": 500, "customer_id": "C123"},
    )
    if not verdict.allowed:
        handle_denial(verdict)

Guardrail Rules (configurable per-agent):
    - Max transaction amount
    - Allowed/blocked API list
    - Rate limits per action
    - Human approval triggers
    - Restricted operations (permanent deny)
    - Data access scope enforcement
    - Budget and runtime limits

Usage
-----
    # From manifest
    gc = GuardrailController.from_manifest(manifest)

    # Or from explicit config
    gc = GuardrailController(
        rules=GuardrailRules(
            max_transaction=500.0,
            allowed_apis=["shopify", "stripe"],
            rate_limits={"refund": 10, "email": 50},
            restricted_operations=["delete_customer", "drop_table"],
            human_approval_triggers=["refund_over_100", "customer_data_export"],
        )
    )

    verdict = gc.authorize("bot", "process_refund", context={"amount": 75})
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Guardrail Rules ──────────────────────────────────────────────────────────

@dataclass
class GuardrailRules:
    """Configurable guardrail rules for an agent."""
    max_transaction: float = 0.0                     # 0 = unlimited
    allowed_apis: list[str] = field(default_factory=list)
    blocked_apis: list[str] = field(default_factory=list)
    rate_limits: dict[str, int] = field(default_factory=dict)  # action → max/hour
    restricted_operations: list[str] = field(default_factory=list)
    human_approval_triggers: list[str] = field(default_factory=list)
    data_access_scope: str = "read_only"             # read_only | orders_only | full
    max_budget_usd: float = 0.0                      # 0 = unlimited
    max_runtime_seconds: int = 0                     # 0 = unlimited
    permission_level: int = 2                        # 1-5 (STANDARD default)
    require_approval_for_write: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_transaction": self.max_transaction,
            "allowed_apis": self.allowed_apis,
            "blocked_apis": self.blocked_apis,
            "rate_limits": self.rate_limits,
            "restricted_operations": self.restricted_operations,
            "human_approval_triggers": self.human_approval_triggers,
            "data_access_scope": self.data_access_scope,
            "max_budget_usd": self.max_budget_usd,
            "max_runtime_seconds": self.max_runtime_seconds,
            "permission_level": self.permission_level,
            "require_approval_for_write": self.require_approval_for_write,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GuardrailRules":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Verdict ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GuardrailVerdict:
    """Result of a guardrail authorization check."""
    allowed: bool
    reason: str
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    requires_human_approval: bool = False
    escalation_context: dict[str, Any] = field(default_factory=dict)
    agent_name: str = ""
    action: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "requires_human_approval": self.requires_human_approval,
            "agent_name": self.agent_name,
            "action": self.action,
            "timestamp": self.timestamp,
        }

    def raise_if_denied(self) -> None:
        if not self.allowed:
            raise PermissionError(f"[GuardrailController] {self.reason}")


# ── Rate limiter ─────────────────────────────────────────────────────────────

class _RateLimiter:
    """Rolling-window rate limiter."""

    def __init__(self, window_seconds: int = 3600):
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = {}

    def check(self, action: str, limit: int) -> tuple[bool, int]:
        """Check if action is within rate limit. Returns (allowed, current_count)."""
        now = time.time()
        key = action.lower()
        if key not in self._buckets:
            self._buckets[key] = []
        # Evict old timestamps
        self._buckets[key] = [t for t in self._buckets[key] if now - t < self._window]
        count = len(self._buckets[key])
        return count < limit, count

    def record(self, action: str) -> None:
        """Record an action execution."""
        key = action.lower()
        if key not in self._buckets:
            self._buckets[key] = []
        self._buckets[key].append(time.time())

    def counts(self) -> dict[str, int]:
        """Return current counts for all tracked actions."""
        now = time.time()
        return {
            action: len([t for t in ts if now - t < self._window])
            for action, ts in self._buckets.items()
        }


# ── GuardrailController ─────────────────────────────────────────────────────

class GuardrailController:
    """
    Unified guardrail gateway for agent actions.

    Every action should pass through `authorize()` before execution.
    The controller checks all rules and returns a single verdict.

    Parameters
    ----------
    rules       : GuardrailRules configuration.
    audit_logger: Optional AuditLogger instance for recording decisions.
    """

    def __init__(
        self,
        rules: GuardrailRules | None = None,
        audit_logger: Any = None,
    ) -> None:
        self._rules = rules or GuardrailRules()
        self._audit = audit_logger
        self._rate_limiter = _RateLimiter()
        self._spent_usd: float = 0.0
        self._started_at: float = time.time()

    @classmethod
    def from_manifest(cls, manifest: Any, audit_logger: Any = None) -> "GuardrailController":
        """Build a GuardrailController from an AgentManifest."""
        perm = getattr(manifest, "permissions", {}) or {}
        runtime = getattr(manifest, "runtime", {}) or {}

        rules = GuardrailRules(
            max_transaction=float(perm.get("refund_limit", 0)),
            allowed_apis=list(perm.get("allowed_apis", [])),
            rate_limits=dict(perm.get("rate_limits", {})),
            restricted_operations=list(perm.get("restricted_commands", [])),
            human_approval_triggers=list(perm.get("escalation_triggers", [])),
            data_access_scope=str(perm.get("data_access", "read_only")),
            permission_level=int(runtime.get("permission_level", 2)),
        )
        return cls(rules=rules, audit_logger=audit_logger)

    @classmethod
    def from_dict(cls, data: dict[str, Any], audit_logger: Any = None) -> "GuardrailController":
        """Build from a plain dict config."""
        return cls(rules=GuardrailRules.from_dict(data), audit_logger=audit_logger)

    # ── Primary authorization interface ──────────────────────────────────

    def authorize(
        self,
        agent_name: str,
        action: str,
        tool: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> GuardrailVerdict:
        """
        Run all guardrail checks and return a unified verdict.

        Parameters
        ----------
        agent_name : The agent requesting authorization.
        action     : The action being attempted (e.g. "process_refund").
        tool       : Optional tool name being invoked.
        context    : Optional dict with action-specific data.
        """
        ctx = context or {}
        passed: list[str] = []
        failed: list[str] = []
        needs_approval = False

        # 1. Restricted operations check
        result = self._check_restricted(action, ctx)
        if result:
            failed.append(f"restricted: {result}")
        else:
            passed.append("restricted_ops")

        # 2. Transaction limit check
        result = self._check_transaction(action, ctx)
        if result:
            failed.append(f"transaction_limit: {result}")
        else:
            passed.append("transaction_limit")

        # 3. API whitelist/blocklist check
        result = self._check_api_access(action, ctx)
        if result:
            failed.append(f"api_access: {result}")
        else:
            passed.append("api_access")

        # 4. Rate limit check
        result = self._check_rate_limit(action)
        if result:
            failed.append(f"rate_limit: {result}")
        else:
            passed.append("rate_limit")

        # 5. Data access scope check
        result = self._check_data_scope(action, ctx)
        if result:
            failed.append(f"data_scope: {result}")
        else:
            passed.append("data_scope")

        # 6. Budget limit check
        result = self._check_budget(ctx)
        if result:
            failed.append(f"budget: {result}")
        else:
            passed.append("budget")

        # 7. Runtime limit check
        result = self._check_runtime()
        if result:
            failed.append(f"runtime: {result}")
        else:
            passed.append("runtime")

        # 8. Human approval check
        if self._needs_human_approval(action, ctx):
            needs_approval = True

        # 9. Write approval check
        if self._rules.require_approval_for_write and self._is_write_action(action):
            needs_approval = True

        # Build verdict
        allowed = len(failed) == 0
        if needs_approval and allowed:
            reason = f"Action '{action}' requires human approval before execution."
        elif not allowed:
            reason = f"Action '{action}' blocked: {'; '.join(failed)}"
        else:
            reason = f"Action '{action}' authorized."

        verdict = GuardrailVerdict(
            allowed=allowed,
            reason=reason,
            checks_passed=passed,
            checks_failed=failed,
            requires_human_approval=needs_approval,
            agent_name=agent_name,
            action=action,
        )

        # Audit log
        self._log_audit(agent_name, action, tool, ctx, verdict)

        if not allowed:
            logger.warning("GuardrailController: DENIED %s/%s — %s",
                           agent_name, action, reason)
        else:
            logger.debug("GuardrailController: ALLOWED %s/%s", agent_name, action)

        return verdict

    def record_execution(self, action: str, cost_usd: float = 0.0) -> None:
        """Record a successful action execution for rate limiting and budget tracking."""
        self._rate_limiter.record(action)
        if cost_usd > 0:
            self._spent_usd += cost_usd

    # ── Individual checks ────────────────────────────────────────────────

    def _check_restricted(self, action: str, ctx: dict[str, Any]) -> str:
        """Returns error string if action is restricted, empty if OK."""
        action_lower = action.lower()
        for op in self._rules.restricted_operations:
            if op.lower() in action_lower:
                return f"'{action}' matches restricted operation '{op}'"
        return ""

    def _check_transaction(self, action: str, ctx: dict[str, Any]) -> str:
        """Returns error if transaction exceeds limit."""
        if self._rules.max_transaction <= 0:
            return ""  # No limit
        amount = ctx.get("amount")
        if amount is None:
            return ""
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return ""
        if amount > self._rules.max_transaction:
            return f"Amount {amount:.2f} exceeds max {self._rules.max_transaction:.2f}"
        return ""

    def _check_api_access(self, action: str, ctx: dict[str, Any]) -> str:
        """Returns error if API is blocked or not in allowlist."""
        api = ctx.get("api") or ctx.get("service") or ""
        if not api:
            return ""

        api_lower = api.lower()

        # Check blocklist first
        for blocked in self._rules.blocked_apis:
            if blocked.lower() == api_lower:
                return f"API '{api}' is explicitly blocked"

        # Check allowlist (only if non-empty)
        if self._rules.allowed_apis:
            if api_lower not in [a.lower() for a in self._rules.allowed_apis]:
                return f"API '{api}' not in allowed list: {self._rules.allowed_apis}"

        return ""

    def _check_rate_limit(self, action: str) -> str:
        """Returns error if rate limit exceeded."""
        # Check exact match first, then prefix match
        limit = self._rules.rate_limits.get(action)
        if limit is None:
            for key, val in self._rules.rate_limits.items():
                if key.lower() in action.lower():
                    limit = val
                    break
        if limit is None:
            return ""

        allowed, count = self._rate_limiter.check(action, limit)
        if not allowed:
            return f"{count}/{limit} calls this hour (limit reached)"
        return ""

    def _check_data_scope(self, action: str, ctx: dict[str, Any]) -> str:
        """Returns error if data access scope is insufficient."""
        requested_scope = ctx.get("data_scope") or ctx.get("scope")
        if not requested_scope:
            return ""

        scope_rank = {
            "read_only": 0,
            "orders_only": 1,
            "restricted": 1,
            "crm": 2,
            "full": 3,
        }
        agent_rank = scope_rank.get(self._rules.data_access_scope.lower(), 0)
        required_rank = scope_rank.get(str(requested_scope).lower(), 99)

        if required_rank > agent_rank:
            return (
                f"Scope '{requested_scope}' exceeds agent's "
                f"'{self._rules.data_access_scope}' access level"
            )
        return ""

    def _check_budget(self, ctx: dict[str, Any]) -> str:
        """Returns error if budget exceeded."""
        if self._rules.max_budget_usd <= 0:
            return ""
        cost = ctx.get("cost_usd", 0)
        projected = self._spent_usd + float(cost)
        if projected > self._rules.max_budget_usd:
            return (
                f"Budget would exceed limit: ${projected:.2f} > "
                f"${self._rules.max_budget_usd:.2f}"
            )
        return ""

    def _check_runtime(self) -> str:
        """Returns error if runtime exceeded."""
        if self._rules.max_runtime_seconds <= 0:
            return ""
        elapsed = time.time() - self._started_at
        if elapsed > self._rules.max_runtime_seconds:
            return f"Runtime exceeded: {elapsed:.0f}s > {self._rules.max_runtime_seconds}s"
        return ""

    def _needs_human_approval(self, action: str, ctx: dict[str, Any]) -> bool:
        """Check if action triggers human approval."""
        action_lower = action.lower()
        ctx_str = str(ctx).lower()
        for trigger in self._rules.human_approval_triggers:
            if trigger.lower() in action_lower or trigger.lower() in ctx_str:
                return True
        return False

    @staticmethod
    def _is_write_action(action: str) -> bool:
        """Heuristic: is this a write/mutating action?"""
        write_markers = (
            "write", "create", "update", "delete", "send", "post",
            "deploy", "execute", "modify", "remove", "drop",
        )
        action_lower = action.lower()
        return any(m in action_lower for m in write_markers)

    # ── Audit ────────────────────────────────────────────────────────────

    def _log_audit(
        self,
        agent_name: str,
        action: str,
        tool: str | None,
        context: dict[str, Any],
        verdict: GuardrailVerdict,
    ) -> None:
        """Log the authorization decision to the audit trail."""
        if self._audit is None:
            return
        try:
            self._audit.log({
                "event": "guardrail_check",
                "agent": agent_name,
                "action": action,
                "tool": tool or "",
                "allowed": verdict.allowed,
                "reason": verdict.reason,
                "requires_approval": verdict.requires_human_approval,
                "checks_passed": verdict.checks_passed,
                "checks_failed": verdict.checks_failed,
            })
        except Exception as exc:
            logger.debug("GuardrailController: audit log failed: %s", exc)

    # ── Configuration management ─────────────────────────────────────────

    def update_rules(self, updates: dict[str, Any]) -> None:
        """Dynamically update guardrail rules."""
        for key, value in updates.items():
            if hasattr(self._rules, key):
                setattr(self._rules, key, value)
                logger.info("GuardrailController: rule updated — %s = %s", key, value)

    @property
    def rules(self) -> GuardrailRules:
        return self._rules

    def status(self) -> dict[str, Any]:
        """Return current guardrail status."""
        return {
            "rules": self._rules.to_dict(),
            "rate_counts": self._rate_limiter.counts(),
            "spent_usd": round(self._spent_usd, 4),
            "uptime_seconds": round(time.time() - self._started_at, 1),
        }

    def __repr__(self) -> str:
        return (
            f"GuardrailController(max_tx={self._rules.max_transaction}, "
            f"apis={len(self._rules.allowed_apis)}, "
            f"restricted={len(self._rules.restricted_operations)}, "
            f"rate_limits={self._rules.rate_limits})"
        )
