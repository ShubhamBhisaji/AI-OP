"""governance_api.py — REST endpoints for operator governance controls.

Exposes the GovernanceRuntime through FastAPI routes so operators
can control agents via HTTP without code changes.

Endpoints:
    GET  /api/governance/status        — Quick status check
    GET  /api/governance/dashboard     — Full governance dashboard
    GET  /api/governance/health        — Health check
    POST /api/governance/pause         — Pause agent
    POST /api/governance/resume        — Resume agent
    POST /api/governance/emergency-stop — Emergency kill
    POST /api/governance/safe-shutdown  — Graceful shutdown
    POST /api/governance/throttle       — Set throttle rate
    POST /api/governance/policy         — Policy hotswap
    GET  /api/governance/approvals      — Pending approvals
    POST /api/governance/approve/{id}   — Approve action
    POST /api/governance/reject/{id}    — Reject action
    GET  /api/governance/decisions      — Decision log
    GET  /api/governance/actions        — Actions taken
    GET  /api/governance/costs          — Cost breakdown
    GET  /api/governance/updates        — Available updates
    POST /api/governance/updates/apply  — Apply update (staged)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/governance", tags=["Governance"])


# ── Request/Response Models ──────────────────────────────────────────────────

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


@router.get("/health")
def governance_health(request: Request) -> dict[str, Any]:
    """Health check for governance subsystem."""
    return _get_governance(request).health()


# ── Operator Controls ────────────────────────────────────────────────────────

@router.post("/pause")
def governance_pause(request: Request, body: OperatorAction) -> dict[str, Any]:
    """Pause the agent — no actions will execute."""
    return _get_governance(request).pause(
        operator=body.operator, reason=body.reason,
    )


@router.post("/resume")
def governance_resume(request: Request, body: OperatorAction) -> dict[str, Any]:
    """Resume the agent after pause."""
    return _get_governance(request).resume(
        operator=body.operator, reason=body.reason,
    )


@router.post("/emergency-stop")
def governance_emergency_stop(
    request: Request, body: OperatorAction,
) -> dict[str, Any]:
    """Emergency kill — cancels everything, disables gate."""
    return _get_governance(request).emergency_stop(
        operator=body.operator, reason=body.reason,
    )


@router.post("/safe-shutdown")
def governance_safe_shutdown(
    request: Request, body: OperatorAction,
) -> dict[str, Any]:
    """Graceful shutdown — finish current work, then stop."""
    return _get_governance(request).safe_shutdown(
        operator=body.operator, reason=body.reason,
    )


@router.post("/throttle")
def governance_throttle(
    request: Request, body: ThrottleRequest,
) -> dict[str, str]:
    """Set throttle rate (0.0 = near-blocked, 1.0 = full speed)."""
    _get_governance(request).throttle(rate=body.rate, operator=body.operator)
    return {"status": "throttled", "rate": str(body.rate)}


@router.post("/policy")
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


@router.post("/approve/{request_id}")
def governance_approve(
    request: Request, request_id: str, body: ApprovalAction,
) -> dict[str, Any]:
    """Approve a pending action."""
    gov = _get_governance(request)
    return gov.human_override.approve(
        request_id, operator=body.operator, reason=body.reason,
    )


@router.post("/reject/{request_id}")
def governance_reject(
    request: Request, request_id: str, body: ApprovalAction,
) -> dict[str, Any]:
    """Reject a pending action."""
    gov = _get_governance(request)
    return gov.human_override.reject(
        request_id, operator=body.operator, reason=body.reason,
    )


# ── Observability Reports ───────────────────────────────────────────────────

@router.get("/decisions")
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


@router.get("/costs")
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


@router.post("/updates/apply")
def governance_apply_update(
    request: Request, body: ApplyUpdateRequest,
) -> dict[str, Any]:
    """Apply update with staged verification."""
    gov = _get_governance(request)
    return gov.update_channel.apply_staged(body.version)
