"""permission_enforcer.py — Business-level permission enforcement for agents.

Sits above policy_engine.py (which handles tool-level authorization) and
enforces domain-specific business rules that vary per agent and customer:

  - Maximum refund amounts agents can approve autonomously
  - Allowed external APIs and services
  - Action rate limits (e.g. max 20 refunds per hour)
  - Restricted commands that must never run
  - Escalation triggers that pause the agent and notify a supervisor

Why a separate layer?
---------------------
policy_engine.py enforces *access control* (can this agent call this tool?).
permission_enforcer.py enforces *business rules* (can this agent approve a
$10,000 refund? Can it send more than 100 emails today?).

Usage
-----
# Build from manifest
enforcer = PermissionEnforcer.from_manifest(manifest)

# Check before executing an action
decision = enforcer.check("process_refund", context={"amount": 250})
if not decision.allowed:
    raise PermissionError(decision.reason)

# Check rate limit
decision = enforcer.check_rate("send_email")
if decision.requires_escalation:
    notify_supervisor(decision.reason)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Decision types ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EnforcerDecision:
    allowed: bool
    reason: str
    requires_escalation: bool = False
    action: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def raise_if_denied(self) -> None:
        if not self.allowed:
            raise PermissionError(f"[PermissionEnforcer] {self.reason}")


# ── Enforcer ──────────────────────────────────────────────────────────────────

class PermissionEnforcer:
    """
    Business-level permission enforcement.

    Parameters
    ----------
    refund_limit        : Maximum refund amount agent can approve (0 = disabled).
    data_access         : Data scope label (e.g. "orders_only", "read_only", "full").
    allowed_apis        : Whitelist of API names the agent may call.
    rate_limits         : Dict of action → max calls per hour.
    restricted_commands : Commands the agent must never execute.
    escalation_triggers : Conditions (strings) that pause and notify supervisor.
    """

    def __init__(
        self,
        refund_limit: float = 0.0,
        data_access: str = "read_only",
        allowed_apis: list[str] | None = None,
        rate_limits: dict[str, int] | None = None,
        restricted_commands: list[str] | None = None,
        escalation_triggers: list[str] | None = None,
    ) -> None:
        self.refund_limit = float(refund_limit)
        self.data_access = str(data_access)
        self.allowed_apis: list[str] = list(allowed_apis or [])
        self.rate_limits: dict[str, int] = dict(rate_limits or {})
        self.restricted_commands: list[str] = list(restricted_commands or [])
        self.escalation_triggers: list[str] = list(escalation_triggers or [])

        # Rate limit tracking: action → list of timestamps in the current window
        self._rate_windows: dict[str, list[float]] = defaultdict(list)
        self._WINDOW_SECONDS = 3600  # 1-hour rolling window

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_manifest(cls, manifest: Any) -> "PermissionEnforcer":
        """Build a PermissionEnforcer from an AgentManifest."""
        perm = getattr(manifest, "permissions", {}) or {}
        return cls(
            refund_limit=float(perm.get("refund_limit", 0)),
            data_access=str(perm.get("data_access", "read_only")),
            allowed_apis=list(perm.get("allowed_apis", [])),
            rate_limits=dict(perm.get("rate_limits", {})),
            restricted_commands=list(perm.get("restricted_commands", [])),
            escalation_triggers=list(perm.get("escalation_triggers", [])),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermissionEnforcer":
        return cls(
            refund_limit=float(data.get("refund_limit", 0)),
            data_access=str(data.get("data_access", "read_only")),
            allowed_apis=list(data.get("allowed_apis", [])),
            rate_limits=dict(data.get("rate_limits", {})),
            restricted_commands=list(data.get("restricted_commands", [])),
            escalation_triggers=list(data.get("escalation_triggers", [])),
        )

    # ── Primary check interface ───────────────────────────────────────────────

    def check(self, action: str, context: dict[str, Any] | None = None) -> EnforcerDecision:
        """
        Evaluate whether an action is permitted under business rules.

        Parameters
        ----------
        action  : Name of the action (e.g. "process_refund", "send_email").
        context : Optional dict with action-specific data (e.g. {"amount": 250}).

        Returns
        -------
        EnforcerDecision with allowed, reason, and requires_escalation.
        """
        ctx = context or {}

        # 1. Restricted command check
        decision = self._check_restricted(action, ctx)
        if not decision.allowed:
            return decision

        # 2. Refund limit check
        if "refund" in action.lower() or ctx.get("amount") is not None:
            decision = self._check_refund(action, ctx)
            if not decision.allowed:
                return decision

        # 3. API whitelist check
        if ctx.get("api") or ctx.get("service"):
            decision = self._check_api(action, ctx)
            if not decision.allowed:
                return decision

        # 4. Rate limit check
        decision = self.check_rate(action)
        if not decision.allowed:
            return decision

        # 5. Escalation trigger check
        decision = self._check_escalation_triggers(action, ctx)
        if decision.requires_escalation:
            return decision

        return EnforcerDecision(
            allowed=True,
            reason=f"Action '{action}' permitted by business rules.",
            action=action,
            context=ctx,
        )

    # ── Individual rule checks ────────────────────────────────────────────────

    def _check_restricted(self, action: str, ctx: dict[str, Any]) -> EnforcerDecision:
        for cmd in self.restricted_commands:
            if cmd.lower() in action.lower():
                reason = (
                    f"Action '{action}' matches restricted command '{cmd}'. "
                    f"This action is permanently blocked for this agent."
                )
                logger.warning("PermissionEnforcer: restricted command blocked — %s", action)
                return EnforcerDecision(
                    allowed=False,
                    reason=reason,
                    requires_escalation=True,
                    action=action,
                    context=ctx,
                )
        return EnforcerDecision(allowed=True, reason="", action=action)

    def _check_refund(self, action: str, ctx: dict[str, Any]) -> EnforcerDecision:
        if self.refund_limit <= 0:
            # No limit configured — allow but log
            return EnforcerDecision(allowed=True, reason="No refund limit configured.", action=action)

        amount = float(ctx.get("amount", 0))
        if amount > self.refund_limit:
            reason = (
                f"Refund of {amount:.2f} exceeds agent limit of {self.refund_limit:.2f}. "
                f"Escalation required."
            )
            logger.warning("PermissionEnforcer: refund limit exceeded — %s > %s", amount, self.refund_limit)
            return EnforcerDecision(
                allowed=False,
                reason=reason,
                requires_escalation=True,
                action=action,
                context=ctx,
            )

        return EnforcerDecision(
            allowed=True,
            reason=f"Refund {amount:.2f} within limit {self.refund_limit:.2f}.",
            action=action,
            context=ctx,
        )

    def _check_api(self, action: str, ctx: dict[str, Any]) -> EnforcerDecision:
        if not self.allowed_apis:
            return EnforcerDecision(allowed=True, reason="No API whitelist configured.", action=action)

        requested = ctx.get("api") or ctx.get("service") or ""
        if requested and requested.lower() not in [a.lower() for a in self.allowed_apis]:
            reason = (
                f"API '{requested}' is not in the allowed API list: "
                f"{self.allowed_apis}."
            )
            logger.warning("PermissionEnforcer: API not whitelisted — %s", requested)
            return EnforcerDecision(
                allowed=False,
                reason=reason,
                action=action,
                context=ctx,
            )

        return EnforcerDecision(
            allowed=True,
            reason=f"API '{requested}' is whitelisted.",
            action=action,
            context=ctx,
        )

    def check_rate(self, action: str) -> EnforcerDecision:
        """
        Evaluate rate limits for an action.

        Tracks calls in a rolling 1-hour window.
        Call record_action() after each successful execution.
        """
        limit = self.rate_limits.get(action)
        if limit is None:
            # Try prefix matching (e.g. "refund" matches "process_refund")
            for key, val in self.rate_limits.items():
                if key.lower() in action.lower():
                    limit = val
                    action = key  # use canonical key for tracking
                    break

        if limit is None:
            return EnforcerDecision(allowed=True, reason="No rate limit for this action.", action=action)

        now = time.time()
        window = self._WINDOW_SECONDS
        # Evict timestamps outside the rolling window
        self._rate_windows[action] = [
            t for t in self._rate_windows[action] if now - t < window
        ]
        count = len(self._rate_windows[action])

        if count >= limit:
            reason = (
                f"Rate limit reached for '{action}': {count}/{limit} calls in the last hour. "
                f"Try again later or escalate."
            )
            logger.warning("PermissionEnforcer: rate limit hit — %s (%d/%d)", action, count, limit)
            return EnforcerDecision(
                allowed=False,
                reason=reason,
                requires_escalation=(count >= limit * 1.5),
                action=action,
            )

        return EnforcerDecision(
            allowed=True,
            reason=f"Rate OK: {count}/{limit} calls this hour.",
            action=action,
        )

    def record_action(self, action: str) -> None:
        """Record that an action was executed. Call after each successful run."""
        self._rate_windows[action].append(time.time())

    def _check_escalation_triggers(self, action: str, ctx: dict[str, Any]) -> EnforcerDecision:
        """Check if any escalation trigger condition is met."""
        ctx_str = str(ctx).lower()
        action_lower = action.lower()

        for trigger in self.escalation_triggers:
            trigger_lower = trigger.lower()
            # Simple string match against action name and context
            if trigger_lower in action_lower or trigger_lower in ctx_str:
                reason = (
                    f"Escalation trigger matched: '{trigger}'. "
                    f"Human supervisor notification required."
                )
                logger.warning("PermissionEnforcer: escalation trigger hit — %s", trigger)
                return EnforcerDecision(
                    allowed=False,
                    reason=reason,
                    requires_escalation=True,
                    action=action,
                    context=ctx,
                )

        return EnforcerDecision(
            allowed=True,
            reason="No escalation triggers matched.",
            action=action,
            context=ctx,
        )

    # ── Data access check ─────────────────────────────────────────────────────

    def check_data_access(self, requested_scope: str) -> EnforcerDecision:
        """
        Verify the agent is allowed to access the requested data scope.

        Scope hierarchy: read_only < orders_only < restricted < full
        """
        _SCOPE_RANK = {
            "read_only": 0,
            "orders_only": 1,
            "restricted": 1,
            "crm": 2,
            "full": 3,
        }
        agent_rank = _SCOPE_RANK.get(self.data_access.lower(), 0)
        required_rank = _SCOPE_RANK.get(requested_scope.lower(), 99)

        if required_rank > agent_rank:
            return EnforcerDecision(
                allowed=False,
                reason=(
                    f"Data scope '{requested_scope}' exceeds agent's allowed scope "
                    f"'{self.data_access}'."
                ),
            )
        return EnforcerDecision(
            allowed=True,
            reason=f"Data scope '{requested_scope}' within agent's '{self.data_access}' scope.",
        )

    # ── Introspection ─────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        return {
            "refund_limit": self.refund_limit,
            "data_access": self.data_access,
            "allowed_apis": self.allowed_apis,
            "rate_limits": self.rate_limits,
            "restricted_commands": self.restricted_commands,
            "escalation_triggers": self.escalation_triggers,
            "rate_window_current": {
                action: len(timestamps)
                for action, timestamps in self._rate_windows.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"PermissionEnforcer(refund_limit={self.refund_limit}, "
            f"data_access={self.data_access!r}, "
            f"allowed_apis={self.allowed_apis}, "
            f"rate_limits={self.rate_limits})"
        )
