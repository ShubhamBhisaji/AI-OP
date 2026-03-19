"""human_override.py — Unified human override controller.

Closes GAP 2: No Clear Human Override Mechanism.

Provides a single interface for business operators to:
    1. Pause agent          — Freeze all activity, finish current task
    2. Require approval     — Force human sign-off on specific actions
    3. Modify behavior live — Change rules, thresholds, configs at runtime
    4. Shut down safely     — Graceful stop with state preservation

Architecture
------------
    Operator ──► HumanOverrideController
                    ├── AgentControlPanel   (pause/resume/stop)
                    ├── KillSwitch          (emergency stop)
                    ├── ActionGate          (approval enforcement)
                    ├── GuardrailController (rule updates)
                    └── ApprovalQueue       (pending approvals)

Usage
-----
    hoc = HumanOverrideController(agent_name="store_bot")
    hoc.register_control_panel(panel)
    hoc.register_kill_switch(ks)
    hoc.register_action_gate(gate)

    # Pause
    hoc.pause(operator="admin")

    # Require approval for specific actions
    hoc.require_approval("refund", operator="admin")

    # Modify rules
    hoc.modify_rules({"max_transaction_usd": 100}, operator="admin")

    # Approve a pending action
    hoc.approve(request_id, operator="admin")

    # Shut down
    hoc.shutdown(operator="admin", mode="safe")
"""

from __future__ import annotations

import logging
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Approval Request ────────────────────────────────────────────────────────

class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    """A pending action awaiting human approval."""
    id: str
    agent_name: str
    action: str
    category: str
    context: dict[str, Any]
    requested_at: float = field(default_factory=time.time)
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str = ""
    decided_at: float = 0.0
    reason: str = ""
    expires_at: float = 0.0  # 0 = no expiry
    callback: Callable | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent_name,
            "action": self.action,
            "category": self.category,
            "context": self.context,
            "requested_at": self.requested_at,
            "status": self.status.value,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "expires_at": self.expires_at,
        }


# ── Override Event ──────────────────────────────────────────────────────────

@dataclass
class OverrideEvent:
    action: str
    operator: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "operator": self.operator,
            "details": self.details,
            "timestamp": self.timestamp,
        }


# ── HumanOverrideController ────────────────────────────────────────────────

class HumanOverrideController:
    """
    Unified human override controller for business operators.

    Aggregates all control surfaces into a single interface:
    pause, approve, modify, shutdown.

    Parameters
    ----------
    agent_name        : Agent to control.
    approval_timeout  : Default seconds before pending approvals expire.
    """

    def __init__(
        self,
        agent_name: str,
        approval_timeout: float = 300.0,
    ) -> None:
        self.agent_name = agent_name
        self._approval_timeout = approval_timeout
        self._lock = threading.Lock()

        # Registered components (all optional — degrade gracefully)
        self._control_panel = None
        self._kill_switch = None
        self._action_gate = None
        self._guardrails = None
        self._observability = None

        # Approval queue
        self._approvals: dict[str, ApprovalRequest] = {}
        self._required_approvals: set[str] = set()  # action patterns requiring approval
        self._approved_once: set[str] = set()

        # Event log
        self._events: list[OverrideEvent] = []
        self._max_events = 200

    # ── Component registration ────────────────────────────────────────────

    def register_control_panel(self, panel: Any) -> None:
        self._control_panel = panel

    def register_kill_switch(self, ks: Any) -> None:
        self._kill_switch = ks

    def register_action_gate(self, gate: Any) -> None:
        self._action_gate = gate

    def register_guardrails(self, guardrails: Any) -> None:
        self._guardrails = guardrails

    def register_observability(self, obs: Any) -> None:
        self._observability = obs

    # ── 1. Pause Agent ────────────────────────────────────────────────────

    def pause(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        Pause the agent — freeze all activity, finish current task.

        Uses AgentControlPanel.pause() if registered, otherwise
        falls back to KillSwitch.safe_shutdown().
        """
        result: dict[str, Any] = {"action": "pause", "agent": self.agent_name}

        if self._control_panel is not None:
            try:
                panel_result = self._control_panel.pause(operator=operator)
                result["control_panel"] = panel_result
            except Exception as exc:
                result["control_panel_error"] = str(exc)

        if self._kill_switch is not None:
            try:
                ks_result = self._kill_switch.safe_shutdown(operator=operator, reason=reason)
                result["kill_switch"] = ks_result
            except Exception as exc:
                result["kill_switch_error"] = str(exc)

        self._record_event("pause", operator, {"reason": reason})
        logger.warning("HumanOverride[%s]: PAUSED by %s. Reason: %s",
                       self.agent_name, operator, reason)
        return result

    # ── 2. Resume Agent ───────────────────────────────────────────────────

    def resume(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """Resume a paused agent."""
        result: dict[str, Any] = {"action": "resume", "agent": self.agent_name}

        if self._control_panel is not None:
            try:
                panel_result = self._control_panel.resume(operator=operator)
                result["control_panel"] = panel_result
            except Exception as exc:
                result["control_panel_error"] = str(exc)

        if self._kill_switch is not None:
            try:
                ks_result = self._kill_switch.reset(operator=operator, reason=reason)
                result["kill_switch"] = ks_result
            except Exception as exc:
                result["kill_switch_error"] = str(exc)

        self._record_event("resume", operator, {"reason": reason})
        logger.info("HumanOverride[%s]: RESUMED by %s.", self.agent_name, operator)
        return result

    # ── 3. Require Approval for Actions ───────────────────────────────────

    def require_approval(
        self,
        action_pattern: str,
        operator: str = "system",
    ) -> dict[str, Any]:
        """
        Add an action pattern that requires human approval.

        Any action matching this pattern will be queued for approval
        before execution.  Patterns are substring-matched.

        Parameters
        ----------
        action_pattern : e.g. "refund", "delete", "deploy", "txn."
        """
        with self._lock:
            self._required_approvals.add(action_pattern.lower())

        self._record_event("require_approval", operator, {"pattern": action_pattern})
        logger.info("HumanOverride[%s]: approval required for '%s' by %s.",
                    self.agent_name, action_pattern, operator)
        return {
            "status": "approval_required",
            "pattern": action_pattern,
            "total_patterns": len(self._required_approvals),
        }

    def remove_approval_requirement(
        self,
        action_pattern: str,
        operator: str = "system",
    ) -> bool:
        """Remove an approval requirement."""
        with self._lock:
            self._required_approvals.discard(action_pattern.lower())
        self._record_event("remove_approval", operator, {"pattern": action_pattern})
        return True

    def needs_approval(self, action: str) -> bool:
        """Check if an action requires human approval."""
        action_lower = action.lower()
        with self._lock:
            return any(pat in action_lower for pat in self._required_approvals)

    def has_pending_approval(self, action: str) -> bool:
        """Return True if a pending (operator-staged) approval already exists for this action."""
        self.expire_stale()
        with self._lock:
            return any(
                r.action == action and r.status == ApprovalStatus.PENDING
                for r in self._approvals.values()
            )

    def request_approval(
        self,
        action: str,
        category: str = "general",
        context: dict[str, Any] | None = None,
        callback: Callable | None = None,
        timeout: float | None = None,
    ) -> ApprovalRequest:
        """
        Submit an action for human approval.

        Returns an ApprovalRequest.  The action is blocked until
        approve() or reject() is called with the request ID.
        """
        fingerprint = self._approval_fingerprint(action, category, context)
        with self._lock:
            for existing in self._approvals.values():
                if existing.status != ApprovalStatus.PENDING:
                    continue
                if self._approval_fingerprint(
                    existing.action,
                    existing.category,
                    existing.context,
                ) == fingerprint:
                    return existing

        req = ApprovalRequest(
            id=str(uuid.uuid4())[:12],
            agent_name=self.agent_name,
            action=action,
            category=category,
            context=dict(context or {}),
            expires_at=time.time() + (timeout or self._approval_timeout),
            callback=callback,
        )

        with self._lock:
            self._approvals[req.id] = req

        logger.info("HumanOverride[%s]: approval requested for '%s' (id=%s).",
                    self.agent_name, action[:40], req.id)
        return req

    def approve(
        self,
        request_id: str,
        operator: str = "system",
        reason: str = "",
    ) -> dict[str, Any]:
        """Approve a pending action."""
        with self._lock:
            req = self._approvals.get(request_id)
            if req is None:
                return {"status": "error", "message": f"Request {request_id} not found."}
            if req.status != ApprovalStatus.PENDING:
                return {"status": "error", "message": f"Request already {req.status.value}."}

            req.status = ApprovalStatus.APPROVED
            req.decided_by = operator
            req.decided_at = time.time()
            req.reason = reason
            self._approved_once.add(
                self._approval_fingerprint(
                    req.action,
                    req.category,
                    req.context,
                )
            )

        # Invoke callback if registered
        if req.callback is not None:
            try:
                req.callback(req)
            except Exception as exc:
                logger.warning("HumanOverride: approval callback failed: %s", exc)

        self._record_event("approve", operator, {"request_id": request_id, "action": req.action})
        logger.info("HumanOverride[%s]: APPROVED '%s' by %s.",
                    self.agent_name, req.action[:40], operator)
        return {"status": "approved", "request_id": request_id}

    def reject(
        self,
        request_id: str,
        operator: str = "system",
        reason: str = "",
    ) -> dict[str, Any]:
        """Reject a pending action."""
        with self._lock:
            req = self._approvals.get(request_id)
            if req is None:
                return {"status": "error", "message": f"Request {request_id} not found."}
            if req.status != ApprovalStatus.PENDING:
                return {"status": "error", "message": f"Request already {req.status.value}."}

            req.status = ApprovalStatus.REJECTED
            req.decided_by = operator
            req.decided_at = time.time()
            req.reason = reason

        self._record_event("reject", operator, {"request_id": request_id, "action": req.action})
        logger.info("HumanOverride[%s]: REJECTED '%s' by %s. Reason: %s",
                    self.agent_name, req.action[:40], operator, reason)
        return {"status": "rejected", "request_id": request_id}

    def expire_stale(self) -> int:
        """Expire pending approvals that have timed out."""
        now = time.time()
        expired = 0
        with self._lock:
            for req in self._approvals.values():
                if (
                    req.status == ApprovalStatus.PENDING
                    and req.expires_at > 0
                    and now > req.expires_at
                ):
                    req.status = ApprovalStatus.EXPIRED
                    expired += 1
        return expired

    def pending_approvals(self) -> list[dict[str, Any]]:
        """List all pending approval requests."""
        self.expire_stale()
        with self._lock:
            return [
                r.to_dict() for r in self._approvals.values()
                if r.status == ApprovalStatus.PENDING
            ]

    def consume_approval(
        self,
        action: str,
        category: str = "general",
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Consume a one-time approval token for a matching action retry."""
        fingerprint = self._approval_fingerprint(action, category, context)
        with self._lock:
            if fingerprint not in self._approved_once:
                return False
            self._approved_once.remove(fingerprint)
        self._record_event(
            "consume_approval",
            "system",
            {"action": action, "category": category},
        )
        return True

    def approval_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent approval decisions."""
        with self._lock:
            items = sorted(
                self._approvals.values(),
                key=lambda r: r.decided_at or r.requested_at,
                reverse=True,
            )
        return [r.to_dict() for r in items[:limit]]

    # ── 4. Modify Behavior Live ───────────────────────────────────────────

    def modify_rules(
        self,
        updates: dict[str, Any],
        operator: str = "system",
    ) -> dict[str, Any]:
        """
        Modify agent rules/thresholds at runtime.

        Examples:
            {"max_transaction_usd": 100}
            {"rate_limit_per_minute": 10}
            {"restricted_operations": ["delete_all"]}
        """
        applied: dict[str, Any] = {}
        errors: list[str] = []

        if self._guardrails is not None:
            try:
                self._guardrails.update_rules(updates)
                applied["guardrails"] = updates
            except Exception as exc:
                errors.append(f"guardrails: {exc}")

        if self._control_panel is not None:
            try:
                self._control_panel.update_config(updates, operator=operator)
                applied["control_panel"] = updates
            except Exception as exc:
                errors.append(f"control_panel: {exc}")

        self._record_event("modify_rules", operator, {"updates": updates, "errors": errors})
        logger.info("HumanOverride[%s]: rules modified by %s: %s",
                    self.agent_name, operator, list(updates.keys()))
        return {"status": "modified", "applied": applied, "errors": errors}

    # ── 5. Shutdown ───────────────────────────────────────────────────────

    def shutdown(
        self,
        operator: str = "system",
        mode: str = "safe",
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Shut down the agent.

        Parameters
        ----------
        mode : "safe"      — Finish current task, then stop.
               "emergency" — Cancel everything immediately.
        """
        result: dict[str, Any] = {
            "action": "shutdown",
            "mode": mode,
            "agent": self.agent_name,
        }

        if mode == "emergency":
            if self._kill_switch is not None:
                try:
                    ks_result = self._kill_switch.emergency_stop(operator=operator, reason=reason)
                    result["kill_switch"] = ks_result
                except Exception as exc:
                    result["kill_switch_error"] = str(exc)

            if self._action_gate is not None:
                try:
                    self._action_gate.disable()
                    result["gate_disabled"] = True
                except Exception as exc:
                    result["gate_error"] = str(exc)

            logger.critical("HumanOverride[%s]: EMERGENCY SHUTDOWN by %s. Reason: %s",
                           self.agent_name, operator, reason)
        else:
            # Safe shutdown
            if self._kill_switch is not None:
                try:
                    ks_result = self._kill_switch.safe_shutdown(operator=operator, reason=reason)
                    result["kill_switch"] = ks_result
                except Exception as exc:
                    result["kill_switch_error"] = str(exc)

            logger.warning("HumanOverride[%s]: SAFE SHUTDOWN by %s. Reason: %s",
                          self.agent_name, operator, reason)

        self._record_event(f"shutdown_{mode}", operator, {"reason": reason})
        return result

    # ── Status dashboard ──────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return full override controller status."""
        self.expire_stale()

        agent_mode = "unknown"
        if self._kill_switch is not None:
            try:
                agent_mode = self._kill_switch.mode.value
            except Exception:
                pass

        pending = sum(
            1 for r in self._approvals.values()
            if r.status == ApprovalStatus.PENDING
        )

        return {
            "agent": self.agent_name,
            "agent_mode": agent_mode,
            "pending_approvals": pending,
            "approval_patterns": sorted(self._required_approvals),
            "total_events": len(self._events),
            "recent_events": [e.to_dict() for e in self._events[-5:]],
            "components": {
                "control_panel": self._control_panel is not None,
                "kill_switch": self._kill_switch is not None,
                "action_gate": self._action_gate is not None,
                "guardrails": self._guardrails is not None,
                "observability": self._observability is not None,
            },
        }

    # ── Event log ─────────────────────────────────────────────────────────

    def event_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent override events."""
        return [e.to_dict() for e in self._events[-limit:]]

    def _record_event(
        self, action: str, operator: str, details: dict[str, Any] | None = None
    ) -> None:
        event = OverrideEvent(action=action, operator=operator, details=details or {})
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    @staticmethod
    def _approval_fingerprint(
        action: str,
        category: str,
        context: dict[str, Any] | None,
    ) -> str:
        sanitized_context = {
            key: value
            for key, value in (context or {}).items()
            if key != "approval_request_id"
        }
        try:
            serialized = json.dumps(sanitized_context, sort_keys=True, default=str)
        except TypeError:
            serialized = json.dumps({"repr": repr(sanitized_context)}, sort_keys=True)
        return f"{action.lower()}|{category.lower()}|{serialized}"

    def __repr__(self) -> str:
        return (
            f"HumanOverrideController(agent={self.agent_name!r}, "
            f"patterns={len(self._required_approvals)}, "
            f"pending={sum(1 for r in self._approvals.values() if r.status == ApprovalStatus.PENDING)})"
        )

    # ── Emergency Disable ─────────────────────────────────────────────────

    def emergency_disable(
        self,
        operator: str = "system",
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Hard disable — immediately kills all activity and locks the agent.

        Unlike shutdown(mode="emergency"), this also:
            1. Cancels all pending approvals
            2. Blocks all future approval requests
            3. Disables the action gate
        """
        result: dict[str, Any] = {
            "action": "emergency_disable",
            "agent": self.agent_name,
        }

        # Cancel all pending approvals
        with self._lock:
            cancelled = 0
            for req in self._approvals.values():
                if req.status == ApprovalStatus.PENDING:
                    req.status = ApprovalStatus.REJECTED
                    req.decided_by = operator
                    req.decided_at = time.time()
                    req.reason = f"Emergency disable: {reason}"
                    cancelled += 1
            result["approvals_cancelled"] = cancelled

        # Kill switch
        if self._kill_switch is not None:
            try:
                ks_result = self._kill_switch.emergency_stop(
                    operator=operator, reason=reason
                )
                result["kill_switch"] = ks_result
            except Exception as exc:
                result["kill_switch_error"] = str(exc)

        # Disable action gate
        if self._action_gate is not None:
            try:
                self._action_gate.disable()
                result["gate_disabled"] = True
            except Exception as exc:
                result["gate_error"] = str(exc)

        self._record_event("emergency_disable", operator, {"reason": reason})
        logger.critical(
            "HumanOverride[%s]: EMERGENCY DISABLE by %s. Reason: %s",
            self.agent_name, operator, reason,
        )
        return result

    # ── Safe Mode ─────────────────────────────────────────────────────────

    def safe_mode(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        Enter safe mode — agent keeps running under maximum restrictions.

        All non-trivial actions require manual approval before execution.
        The agent remains alive but operates with minimum trust level.
        Use resume() to exit safe mode.
        """
        result: dict[str, Any] = {"action": "safe_mode", "agent": self.agent_name}

        if self._kill_switch is not None:
            try:
                ks_result = self._kill_switch.safe_mode(operator=operator, reason=reason)
                result["kill_switch"] = ks_result
                result["status"] = "safe_mode"
            except Exception as exc:
                result["kill_switch_error"] = str(exc)
                result["status"] = "error"
        else:
            result["status"] = "safe_mode"

        self._record_event("safe_mode", operator, {"reason": reason})
        logger.warning("HumanOverride[%s]: SAFE MODE by %s. Reason: %s",
                       self.agent_name, operator, reason)
        return result

    # ── Restart ───────────────────────────────────────────────────────────

    def restart(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        Restart the agent — cancel all in-flight work, reset kill switch,
        re-enable gate, and resume the loop from a clean state.
        """
        result: dict[str, Any] = {"action": "restart", "agent": self.agent_name}

        if self._kill_switch is not None:
            try:
                ks_result = self._kill_switch.restart(operator=operator, reason=reason)
                result["kill_switch"] = ks_result
                result["status"] = ks_result.get("status", "restarted")
            except Exception as exc:
                result["kill_switch_error"] = str(exc)
                result["status"] = "error"
        else:
            result["status"] = "restarted"

        self._record_event("restart", operator, {"reason": reason})
        logger.warning("HumanOverride[%s]: RESTART by %s. Reason: %s",
                       self.agent_name, operator, reason)
        return result

    # ── Manual Approval Trigger ───────────────────────────────────────────

    def trigger_manual_approval(
        self,
        action: str,
        category: str = "general",
        context: dict[str, Any] | None = None,
        operator: str = "system",
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Operator-initiated approval gate: create a pending approval request
        for a named action before the agent has a chance to execute it.

        This is the proactive form — operators can pre-stage an approval
        requirement for any action (e.g. ahead of a scheduled batch run,
        a high-risk deployment window, or a sensitive data export).

        Any matching action that reaches the ActionGate will be blocked
        until this approval is resolved.
        """
        req = self.request_approval(
            action=action,
            category=category,
            context=dict(context or {}),
        )
        self._record_event("trigger_manual_approval", operator, {
            "action": action,
            "request_id": req.id,
            "reason": reason,
        })
        logger.info(
            "HumanOverride[%s]: manual approval triggered for '%s' by %s (id=%s).",
            self.agent_name, action[:40], operator, req.id,
        )
        return {
            "status": "pending",
            "request_id": req.id,
            "action": action,
            "category": category,
            "expires_at": req.expires_at,
        }

    # ── Policy Hotswap ────────────────────────────────────────────────────

    def policy_hotswap(
        self,
        policy: dict[str, Any],
        operator: str = "system",
    ) -> dict[str, Any]:
        """
        Replace agent policy without redeploy.

        Accepts a policy dict that can include any combination of:
            - "rules"                : GuardrailController rule updates
            - "approval_patterns"    : Replace required approval patterns
            - "rate_limits"          : EconomicGuardrails rate limit updates
            - "quotas"              : EconomicGuardrails quota updates
            - "budget_usd"          : Budget cap update

        Returns a summary of what was applied.
        """
        applied: dict[str, Any] = {}
        errors: list[str] = []

        # Rules
        if "rules" in policy and self._guardrails is not None:
            try:
                self._guardrails.update_rules(policy["rules"])
                applied["rules"] = list(policy["rules"].keys())
            except Exception as exc:
                errors.append(f"rules: {exc}")

        # Approval patterns (replace entirely)
        if "approval_patterns" in policy:
            with self._lock:
                self._required_approvals = set(
                    p.lower() for p in policy["approval_patterns"]
                )
            applied["approval_patterns"] = sorted(self._required_approvals)

        # Forward rate limits / quotas / budget to control panel or guardrails
        if self._control_panel is not None:
            forward_keys = {"rate_limits", "quotas", "budget_usd"}
            panel_updates = {
                k: v for k, v in policy.items() if k in forward_keys
            }
            if panel_updates:
                try:
                    self._control_panel.update_config(panel_updates, operator=operator)
                    applied["config"] = list(panel_updates.keys())
                except Exception as exc:
                    errors.append(f"config: {exc}")

        self._record_event("policy_hotswap", operator, {
            "policy_keys": list(policy.keys()),
            "applied": applied,
            "errors": errors,
        })
        logger.info(
            "HumanOverride[%s]: policy hotswap by %s — applied: %s",
            self.agent_name, operator, list(applied.keys()),
        )
        return {"status": "applied", "applied": applied, "errors": errors}
