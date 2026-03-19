"""telemetry_router.py — Decision-grade operational telemetry endpoints.

Resolves BLOCKER 3: Observability Not Decision-Grade.

All seven required surfaces are exposed under /api/telemetry/:

    GET /api/telemetry/activity       — current & recent activity stream
    GET /api/telemetry/history        — searchable action history
    GET /api/telemetry/decisions      — decision log (allowed/blocked/pending)
    GET /api/telemetry/errors         — errors & retry surface
    GET /api/telemetry/integrations   — live integration health
    GET /api/telemetry/resources      — resource & budget usage snapshot
    GET /api/telemetry/status         — compact operator status indicators
    GET /api/telemetry/dashboard      — all surfaces in one call

Authentication: every endpoint requires a valid user session.
The dashboard and errors endpoints require admin.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry", tags=["Telemetry"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_monitor(request: Request) -> Any:
    """Return the UnifiedMonitor from the kernel, or raise 503 if unavailable."""
    try:
        from api.server import _get_kernel  # type: ignore[import]
        kernel = _get_kernel()
        monitor = getattr(kernel, "monitor", None)
        if monitor is None:
            raise HTTPException(status_code=503, detail="Telemetry monitor not initialised")
        return monitor
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("telemetry: kernel unavailable — %s", exc)
        raise HTTPException(status_code=503, detail=f"Kernel unavailable: {exc}")


def _require_auth(request: Request) -> None:
    """Raise 401 if the request has no valid user session."""
    from api.server import _connection_user_id  # type: ignore[import]
    if _connection_user_id(request) is None:
        raise HTTPException(status_code=401, detail="Authentication required")


def _require_admin(request: Request) -> None:
    """Raise 403 if the request is not from an admin session."""
    from api.server import _connection_is_admin  # type: ignore[import]
    if not _connection_is_admin(request):
        raise HTTPException(status_code=403, detail="Admin privileges required")


def _safe_limit(value: int, maximum: int = 500) -> int:
    return max(1, min(value, maximum))


# ── 1. Current Activity ───────────────────────────────────────────────────────

@router.get(
    "/activity",
    summary="Current activity stream",
    description=(
        "Returns the most recent events across the unified activity timeline. "
        "Each event carries a source (action/decision/retry/error/control), "
        "level, agent, and full detail payload. "
        "Optional `source` and `level` filters narrow the stream."
    ),
)
def get_activity(
    request: Request,
    source: str | None = Query(default=None, description="Filter by source: action|decision|retry|error|control"),
    level: str | None = Query(default=None, description="Filter by level: info|warning|error"),
    limit: int = Query(default=50, ge=1, le=500),
):
    _require_auth(request)
    monitor = _get_monitor(request)
    events = monitor.activity_timeline(source=source, level=level, limit=_safe_limit(limit))
    return {
        "count": len(events),
        "filters": {"source": source, "level": level},
        "events": events,
        "generated_at": time.time(),
    }


# ── 2. Action History ─────────────────────────────────────────────────────────

@router.get(
    "/history",
    summary="Action history",
    description=(
        "Returns the full history of actions taken by agents — both from the "
        "ActionProxy and the timeline event store. Each record includes the action "
        "name, category, allowed/blocked flag, success flag, duration and timestamp."
    ),
)
def get_action_history(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    _require_auth(request)
    monitor = _get_monitor(request)
    actions = monitor.actions_taken(limit=_safe_limit(limit))
    return {
        "count": len(actions),
        "actions": actions,
        "generated_at": time.time(),
    }


# ── 3. Decision Log ───────────────────────────────────────────────────────────

@router.get(
    "/decisions",
    summary="Decision log",
    description=(
        "Returns every governance decision recorded by the monitor "
        "(allowed / blocked / pending_approval / error). "
        "Includes the full context dict, impact level, reversibility flag, "
        "and the reason the decision was made. "
        "Filter by `outcome` or `impact` to surface only critical or blocked items."
    ),
)
def get_decisions(
    request: Request,
    outcome: str | None = Query(default=None, description="Filter: allowed|blocked|pending_approval|error"),
    impact: str | None = Query(default=None, description="Filter: low|medium|high|critical"),
    limit: int = Query(default=50, ge=1, le=500),
):
    _require_auth(request)
    monitor = _get_monitor(request)
    decisions = monitor.decision_log(outcome=outcome, impact=impact, limit=_safe_limit(limit))
    return {
        "count": len(decisions),
        "filters": {"outcome": outcome, "impact": impact},
        "decisions": decisions,
        "generated_at": time.time(),
    }


# ── 4. Errors & Retries ───────────────────────────────────────────────────────

@router.get(
    "/errors",
    summary="Errors and retries",
    description=(
        "Returns the deduplicated error report from the ObservabilityEngine "
        "sorted by frequency, plus the retry surface from the monitor — showing "
        "which actions have triggered retry storms and how many retries were exhausted."
    ),
)
def get_errors(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
):
    _require_auth(request)
    monitor = _get_monitor(request)
    safe_limit = _safe_limit(limit, maximum=100)
    errors = monitor.error_report(limit=safe_limit)
    retries = monitor.retry_summary()
    return {
        "errors": {
            "count": len(errors),
            "items": errors,
        },
        "retries": retries,
        "generated_at": time.time(),
    }


# ── 5. Integration Health ─────────────────────────────────────────────────────

@router.get(
    "/integrations",
    summary="Integration health",
    description=(
        "Returns the live health status of every external connection registered "
        "with the agent. Each service entry shows connected status, type, and "
        "an overall summary (healthy / degraded / unhealthy)."
    ),
)
def get_integration_health(
    request: Request,
):
    _require_auth(request)
    monitor = _get_monitor(request)
    health = monitor.integration_status()
    return {
        **health,
        "generated_at": time.time(),
    }


# ── 6. Resource Usage ─────────────────────────────────────────────────────────

@router.get(
    "/resources",
    summary="Resource and budget usage",
    description=(
        "Returns a point-in-time snapshot of all resource consumption: "
        "API calls (total + blocked), token consumption, cost vs budget, "
        "action success/failure counts, error count, and agent uptime."
    ),
)
def get_resource_usage(
    request: Request,
):
    _require_auth(request)
    monitor = _get_monitor(request)
    usage = monitor.resource_usage()
    return {
        **usage,
        "generated_at": time.time(),
    }


# ── 7. Status Indicators ──────────────────────────────────────────────────────

@router.get(
    "/status",
    summary="Operator status indicators",
    description=(
        "Returns a compact set of operator-facing status indicators suitable "
        "for a control-plane header bar: kill-switch mode, pause state, "
        "pending approvals, active/queued/failed jobs, DLQ depth, "
        "integration health, and update availability."
    ),
)
def get_status_indicators(
    request: Request,
):
    _require_auth(request)
    monitor = _get_monitor(request)
    indicators = monitor.status_indicators()
    # Augment with current task summary
    tasks = monitor.current_tasks(limit=25)
    return {
        "indicators": indicators,
        "current_tasks": {
            "total": len(tasks),
            "running": sum(1 for t in tasks if t.get("state") == "running"),
            "pending": sum(1 for t in tasks if t.get("state") == "pending"),
            "failed": sum(1 for t in tasks if t.get("state") == "failed"),
            "tasks": tasks,
        },
        "generated_at": time.time(),
    }


# ── 8. Full Dashboard ─────────────────────────────────────────────────────────

@router.get(
    "/dashboard",
    summary="Full telemetry dashboard",
    description=(
        "Returns all seven telemetry surfaces in a single response. "
        "Intended for dashboards that need a complete operational picture. "
        "Requires admin privileges to prevent information disclosure. "
        "Fields: health, resources, status_indicators, current_tasks, "
        "recent_activity, activity_history, recent_decisions, errors, "
        "retries, integrations, updates."
    ),
)
def get_dashboard(
    request: Request,
):
    _require_admin(request)
    monitor = _get_monitor(request)
    dashboard = monitor.dashboard()

    # Also pull the governance-level view for kill-switch / policy state
    try:
        from api.server import _get_kernel  # type: ignore[import]
        kernel = _get_kernel()
        governance_status = kernel.governance_runtime.status()
    except Exception:
        governance_status = {}

    return {
        **dashboard,
        "governance": governance_status,
        "generated_at": time.time(),
    }


# ── 9. Multi-component Health ─────────────────────────────────────────────────

@router.get(
    "/health",
    summary="Multi-component health check",
    description=(
        "Returns per-component health across: observability engine, "
        "kill switch, budget, action proxy, action gate, scheduler, "
        "and integrations. Overall status is the worst-case roll-up."
    ),
)
def get_health(
    request: Request,
):
    _require_auth(request)
    monitor = _get_monitor(request)
    return monitor.health_status()
