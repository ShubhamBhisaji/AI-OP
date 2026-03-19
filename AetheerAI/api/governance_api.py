"""governance_api.py — REST endpoints for operator governance controls.

Exposes the GovernanceRuntime through FastAPI routes so operators
can control agents via HTTP without code changes.

Endpoints:
    GET  /api/governance/status        — Quick status check
    GET  /api/governance/dashboard     — Full governance dashboard
    GET  /api/governance/control-plane — Unified operator control plane
    GET  /api/governance/health        — Health check
    GET  /api/governance/activity      — Activity history
    GET  /api/governance/current-tasks — Live running / queued work
    GET  /api/governance/resources     — Resource usage snapshot
    GET  /api/governance/integrations  — Integration health
    GET  /api/governance/status-indicators — Compact operator indicators
    POST /api/governance/pause         — Pause agent
    POST /api/governance/resume        — Resume agent
    POST /api/governance/emergency-stop — Emergency kill
    POST /api/governance/safe-shutdown  — Graceful shutdown
    POST /api/governance/safe-mode      — Restricted-but-running safe mode
    POST /api/governance/restart        — Stop in-flight work, resume clean
    POST /api/governance/disable-integrations — Disable all external integrations
    POST /api/governance/throttle       — Set throttle rate
    POST /api/governance/policy         — Policy hotswap
    GET  /api/governance/approvals      — Pending approvals
    POST /api/governance/approve/{id}   — Approve action
    POST /api/governance/reject/{id}    — Reject action
    POST /api/governance/manual-approval — Operator-initiated approval gate
    GET  /api/governance/decisions      — Decision log
    GET  /api/governance/actions        — Actions taken
    GET  /api/governance/costs          — Cost breakdown
    GET  /api/governance/updates        — Available updates
    GET  /api/governance/updates/verify/{version} — Verify update
    POST /api/governance/updates/apply  — Apply update (staged)
    POST /api/governance/updates/rollback — Roll back update
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/governance", tags=["Governance"])


# ── Operator authentication dependency ──────────────────────────────────────

def _require_operator(request: Request) -> None:
    """
    Enforce operator token on sensitive governance endpoints.

    Behaviour
    ---------
    * If ``AETHEERAI_OPERATOR_TOKEN`` env var is set → caller MUST supply a
      matching ``Authorization: Bearer <token>`` header.  Constant-time
      comparison prevents timing-based token enumeration.
    * If the env var is NOT set → a warning is logged and all access is
      allowed (development / test mode).  Set the token in production.
    """
    token = os.environ.get("AETHEERAI_OPERATOR_TOKEN", "").strip()
    if not token:
        logger.warning(
            "SECURITY: AETHEERAI_OPERATOR_TOKEN is not set — governance "
            "control endpoints are OPEN to unauthenticated callers.  "
            "Set this variable in production."
        )
        return  # dev/test mode — allow

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Use: Authorization: Bearer <AETHEERAI_OPERATOR_TOKEN>",
        )
    provided = auth_header[7:].strip()
    if not hmac.compare_digest(provided.encode(), token.encode()):
        raise HTTPException(status_code=403, detail="Invalid operator token.")




class OperatorAction(BaseModel):
    operator: str = Field(default="api", description="Operator identifier")
    reason: str = Field(default="", description="Reason for the action")


class ThrottleRequest(BaseModel):
    rate: float = Field(ge=0.0, le=1.0, description="Throttle rate (0.0–1.0)")
    operator: str = "api"


class PolicyRequest(BaseModel):
    policy: dict[str, Any] = Field(description="Policy dict to apply")
    operator: str = "api"


class ApprovalAction(BaseModel):
    operator: str = "api"
    reason: str = ""


class ApplyUpdateRequest(BaseModel):
    version: str


class RollbackUpdateRequest(BaseModel):
    version: str | None = Field(default=None, description="Optional rollback target version")


class ManualApprovalRequest(BaseModel):
    action: str = Field(description="Action name to require approval for")
    category: str = Field(default="general", description="Action category")
    context: dict[str, Any] = Field(default_factory=dict, description="Additional context")
    operator: str = Field(default="api", description="Operator identifier")
    reason: str = Field(default="", description="Reason for the manual gate")


# ── Governance resolver ──────────────────────────────────────────────────────

def _get_governance(request: Request) -> Any:
    """Resolve GovernanceRuntime from app state."""
    gov = getattr(request.app.state, "governance", None)
    if gov is None:
        raise HTTPException(
            status_code=503,
            detail="Governance runtime not initialized.",
        )
    return gov


# ── Status & Observability ───────────────────────────────────────────────────

@router.get("/status")
def governance_status(request: Request) -> dict[str, Any]:
    """Quick governance status check."""
    return _get_governance(request).status()


@router.get("/dashboard")
def governance_dashboard(request: Request) -> dict[str, Any]:
    """Full governance dashboard — everything in one call."""
    return _get_governance(request).dashboard()


@router.get("/control-plane")
def governance_control_plane(request: Request) -> dict[str, Any]:
    """Unified operator control plane."""
    return _get_governance(request).control_plane_status()


@router.get("/health")
def governance_health(request: Request) -> dict[str, Any]:
    """Health check for governance subsystem."""
    return _get_governance(request).health()


@router.get("/activity")
def governance_activity(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    """Recent operator and runtime activity history."""
    gov = _get_governance(request)
    return gov.monitor.activity_timeline(limit=limit)


@router.get("/current-tasks")
def governance_current_tasks(request: Request, limit: int = 25) -> list[dict[str, Any]]:
    """Live running and queued tasks across the runtime."""
    gov = _get_governance(request)
    return gov.monitor.current_tasks(limit=limit)


@router.get("/resources")
def governance_resources(request: Request) -> dict[str, Any]:
    """Current resource usage snapshot."""
    gov = _get_governance(request)
    return gov.monitor.resource_usage()


@router.get("/integrations")
def governance_integrations(request: Request) -> dict[str, Any]:
    """Integration health and connectivity status."""
    gov = _get_governance(request)
    return gov.monitor.integration_status()


@router.get("/status-indicators")
def governance_status_indicators(request: Request) -> dict[str, Any]:
    """Compact operator-facing status indicators."""
    gov = _get_governance(request)
    return gov.monitor.status_indicators()


# ── Operator Controls ────────────────────────────────────────────────────────

@router.post("/pause", dependencies=[Depends(_require_operator)])
def governance_pause(request: Request, body: OperatorAction) -> dict[str, Any]:
    """Pause the agent — no actions will execute."""
    return _get_governance(request).pause(
        operator=body.operator, reason=body.reason,
    )


@router.post("/resume", dependencies=[Depends(_require_operator)])
def governance_resume(request: Request, body: OperatorAction) -> dict[str, Any]:
    """Resume the agent after pause."""
    return _get_governance(request).resume(
        operator=body.operator, reason=body.reason,
    )


@router.post("/emergency-stop", dependencies=[Depends(_require_operator)])
def governance_emergency_stop(
    request: Request, body: OperatorAction,
) -> dict[str, Any]:
    """Emergency kill — cancels everything, disables gate."""
    return _get_governance(request).emergency_stop(
        operator=body.operator, reason=body.reason,
    )


@router.post("/safe-shutdown", dependencies=[Depends(_require_operator)])
def governance_safe_shutdown(
    request: Request, body: OperatorAction,
) -> dict[str, Any]:
    """Graceful shutdown — finish current work, then stop."""
    return _get_governance(request).safe_shutdown(
        operator=body.operator, reason=body.reason,
    )


@router.post("/safe-mode", dependencies=[Depends(_require_operator)])
def governance_safe_mode(
    request: Request, body: OperatorAction,
) -> dict[str, Any]:
    """
    Enter safe mode — agent continues running under maximum restrictions.

    All non-trivial actions (financial, external API, bulk, system) require
    manual operator approval before execution. External HTTP transport is
    blocked. Agent remains alive and responsive.
    Use POST /resume to exit safe mode.
    """
    return _get_governance(request).safe_mode(
        operator=body.operator, reason=body.reason,
    )


@router.post("/restart", dependencies=[Depends(_require_operator)])
def governance_restart(
    request: Request, body: OperatorAction,
) -> dict[str, Any]:
    """
    Restart the agent — cancel all in-flight work, re-enable the gate,
    and resume the autonomous loop from a clean state.

    Unlike emergency-stop, restart automatically re-enables normal operation.
    Governance configuration, audit history, and memory are preserved.
    """
    return _get_governance(request).restart(
        operator=body.operator, reason=body.reason,
    )


@router.post("/disable-integrations", dependencies=[Depends(_require_operator)])
def governance_disable_integrations(
    request: Request, body: OperatorAction,
) -> dict[str, Any]:
    """Disable all external integrations without shutting down the runtime."""
    return _get_governance(request).disable_integrations(
        operator=body.operator,
        reason=body.reason,
    )


@router.post("/throttle", dependencies=[Depends(_require_operator)])
def governance_throttle(
    request: Request, body: ThrottleRequest,
) -> dict[str, str]:
    """Set throttle rate (0.0 = near-blocked, 1.0 = full speed)."""
    _get_governance(request).throttle(rate=body.rate, operator=body.operator)
    return {"status": "throttled", "rate": str(body.rate)}


@router.post("/policy", dependencies=[Depends(_require_operator)])
def governance_policy_update(
    request: Request, body: PolicyRequest,
) -> dict[str, Any]:
    """Hot-swap policy without redeploy."""
    return _get_governance(request).policy_update(
        policy=body.policy, operator=body.operator,
    )


# ── Approval Queue ──────────────────────────────────────────────────────────

@router.get("/approvals")
def governance_pending_approvals(request: Request) -> list[dict[str, Any]]:
    """List pending approval requests."""
    gov = _get_governance(request)
    return gov.human_override.pending_approvals()


@router.post("/approve/{request_id}", dependencies=[Depends(_require_operator)])
def governance_approve(
    request: Request, request_id: str, body: ApprovalAction,
) -> dict[str, Any]:
    """Approve a pending action."""
    gov = _get_governance(request)
    return gov.human_override.approve(
        request_id, operator=body.operator, reason=body.reason,
    )


@router.post("/reject/{request_id}", dependencies=[Depends(_require_operator)])
def governance_reject(
    request: Request, request_id: str, body: ApprovalAction,
) -> dict[str, Any]:
    """Reject a pending action."""
    gov = _get_governance(request)
    return gov.human_override.reject(
        request_id, operator=body.operator, reason=body.reason,
    )


@router.post("/manual-approval", dependencies=[Depends(_require_operator)])
def governance_manual_approval(
    request: Request, body: ManualApprovalRequest,
) -> dict[str, Any]:
    """
    Operator-initiated approval gate: pre-stage a pending approval for
    a named action before the agent has a chance to execute it.

    Useful ahead of scheduled batch runs, sensitive data exports,
    deployment windows, or any high-risk operation window.
    The action is blocked at the ActionGate until approved or rejected.
    """
    return _get_governance(request).trigger_manual_approval(
        action=body.action,
        category=body.category,
        context=body.context,
        operator=body.operator,
        reason=body.reason,
    )


# ── Observability Reports ───────────────────────────────────────────────────

@router.get("/decisions", dependencies=[Depends(_require_operator)])
def governance_decisions(
    request: Request,
    outcome: str | None = None,
    impact: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Decision log with optional filters."""
    gov = _get_governance(request)
    return gov.monitor.decision_log(
        outcome=outcome, impact=impact, limit=limit,
    )


@router.get("/actions")
def governance_actions(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    """Actions taken by the agent."""
    gov = _get_governance(request)
    return gov.monitor.actions_taken(limit=limit)


@router.get("/errors")
def governance_errors(request: Request, limit: int = 20) -> list[dict[str, Any]]:
    """Recent errors."""
    gov = _get_governance(request)
    return gov.monitor.error_report(limit=limit)


@router.get("/costs", dependencies=[Depends(_require_operator)])
def governance_costs(request: Request, hours: float = 24) -> dict[str, Any]:
    """Cost breakdown."""
    gov = _get_governance(request)
    return {
        "by_category": gov.economic_guardrails.cost_by_category(hours=hours),
        "by_agent": gov.economic_guardrails.cost_by_agent(hours=hours),
        "top_operations": gov.economic_guardrails.top_cost_operations(limit=10),
        "status": gov.economic_guardrails.status(),
    }


@router.get("/retries")
def governance_retries(request: Request) -> dict[str, Any]:
    """Retry summary — surfaces retry storms."""
    gov = _get_governance(request)
    return gov.monitor.retry_summary()


# ── Update Channel ──────────────────────────────────────────────────────────

@router.get("/updates")
def governance_updates(request: Request) -> dict[str, Any]:
    """Available updates and current version."""
    gov = _get_governance(request)
    return gov.update_channel.update_status()


@router.get("/updates/verify/{version}")
def governance_verify_update(request: Request, version: str) -> dict[str, Any]:
    """Verify an update before staged application."""
    gov = _get_governance(request)
    return gov.verify_update(version)


@router.post("/updates/apply", dependencies=[Depends(_require_operator)])
def governance_apply_update(
    request: Request, body: ApplyUpdateRequest,
) -> dict[str, Any]:
    """Apply update with staged verification."""
    gov = _get_governance(request)
    return gov.update_channel.apply_staged(body.version)


@router.post("/updates/rollback", dependencies=[Depends(_require_operator)])
def governance_rollback_update(
    request: Request, body: RollbackUpdateRequest,
) -> dict[str, Any]:
    """Rollback to the previous or specified compatible version."""
    gov = _get_governance(request)
    return gov.rollback_update(body.version)
