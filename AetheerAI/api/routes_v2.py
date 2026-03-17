"""
routes_v2.py — REST API routes for AetheerAI v2 subsystems.

Adds endpoints for:
  /api/plans        — PlanningEngine (DAG goal decomposition + execution)
  /api/jobs         — JobScheduler  (persistent priority queue)
  /api/risk         — RiskAssessor  (multi-dimensional risk scoring)
  /api/lifecycle    — AgentLifecycleManager (warm/idle/cold/retired + capabilities)
    /api/business     — BusinessGrowthEngine (lead-to-revenue automation)

Mount this router from api/server.py:
    from api.routes_v2 import router as v2_router
    app.include_router(v2_router)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.database import ActivityLog, User, get_db
from api.job_security import (
    enforce_job_api_rate_limit,
    enforce_job_create_quota,
    enforce_job_submission_abuse_controls,
    record_job_create_usage,
)

logger = logging.getLogger("aetheer.api.v2")

router = APIRouter(tags=["v2"])

_VALID_JOB_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{7,127}$")

# ── Lazy kernel accessor (avoids import-time circular dependency) ─────────────

def _kernel():
    from api.server import _get_kernel
    return _get_kernel()


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else int(default)
    except ValueError:
        value = int(default)
    return max(minimum, value)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _tenant_id_for_user(current_user: User) -> str:
    prefix = (os.getenv("JOB_API_TENANT_PREFIX") or "user").strip().lower() or "user"
    return f"{prefix}:{int(current_user.id)}"


def _request_ip(request: Request | None) -> str | None:
    if request is None:
        return None

    trust_proxy_headers = _env_bool(
        "JOB_API_TRUST_PROXY_HEADERS",
        _env_bool("AETHEER_TRUST_PROXY_HEADERS", False),
    )
    if trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip() or None

    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host).strip() if host else None


def _audit_job_activity(
    db: Any,
    *,
    current_user: User | None,
    action: str,
    detail: dict[str, Any] | None,
    source_ip: str | None,
) -> None:
    if not (hasattr(db, "add") and hasattr(db, "commit")):
        return

    user_id: int | None
    try:
        user_id = int(current_user.id) if current_user is not None else None
    except (TypeError, ValueError):
        user_id = None

    try:
        db.add(
            ActivityLog(
                user_id=user_id,
                action=str(action or "scheduler_event")[:128],
                detail=dict(detail or {}),
                ip_address=source_ip,
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("Scheduler audit logging failed for action=%s: %s", action, exc)


def _scheduler_job_fingerprint(req: "JobRequest") -> str:
    payload = {
        "name": str(req.name or "").strip().lower(),
        "agent_name": str(req.agent_name or "").strip().lower(),
        "task": str(req.task or "").strip(),
        "priority": int(req.priority),
        "run_at_iso": str(req.run_at_iso or "").strip(),
        "interval_sec": float(req.interval_sec),
        "max_retries": int(req.max_retries),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _job_owner_user_id(job: dict[str, Any]) -> int | None:
    raw_owner = job.get("owner_user_id")
    try:
        return int(raw_owner) if raw_owner is not None else None
    except (TypeError, ValueError):
        return None


def _job_owner_tenant_id(job: dict[str, Any]) -> str | None:
    raw_tenant = str(job.get("owner_tenant_id") or "").strip().lower()
    return raw_tenant or None


def _job_is_visible(job: dict[str, Any], current_user: User) -> bool:
    if current_user.is_admin:
        return True
    owner_user_id = _job_owner_user_id(job)
    if owner_user_id is None or owner_user_id != int(current_user.id):
        return False

    owner_tenant_id = _job_owner_tenant_id(job)
    if owner_tenant_id is None:
        return True
    return owner_tenant_id == _tenant_id_for_user(current_user)


def _job_stats_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    return {
        "total": len(rows),
        "by_status": by_status,
        "scope": "user",
    }


def _normalize_job_status_filter(status: str | None) -> str | None:
    normalized = str(status or "").strip().lower()
    if not normalized:
        return None
    if normalized not in _VALID_JOB_STATUSES:
        allowed = ", ".join(sorted(_VALID_JOB_STATUSES))
        raise HTTPException(status_code=422, detail=f"Invalid status filter '{status}'. Allowed: {allowed}")
    return normalized


def _validated_job_lookup_id(job_id: str) -> str:
    normalized = str(job_id or "").strip()
    if not _JOB_ID_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="job_id format is invalid")
    return normalized


def _allow_admin_prefix_lookup() -> bool:
    return _env_bool("JOB_API_ALLOW_ADMIN_PREFIX_LOOKUP", False)


def _lookup_job_for_user(
    *,
    kernel: Any,
    requested_job_id: str,
    current_user: User,
) -> dict[str, Any] | None:
    direct = None
    status_fn = getattr(kernel, "job_status", None)
    if callable(status_fn):
        try:
            direct = status_fn(requested_job_id)
        except Exception:
            direct = None

    if isinstance(direct, dict) and _job_is_visible(direct, current_user):
        return direct

    if not (current_user.is_admin and _allow_admin_prefix_lookup()):
        return None

    min_prefix_len = _env_int("JOB_API_ADMIN_PREFIX_MIN_LENGTH", 12, minimum=4)
    if len(requested_job_id) < min_prefix_len:
        return None

    scan_limit = max(100, min(5000, _env_int("JOB_API_JOB_LOOKUP_SCAN_LIMIT", 2000, minimum=1)))
    rows = kernel.list_jobs(limit=scan_limit)
    matches = [
        row
        for row in rows
        if str(row.get("job_id") or "").startswith(requested_job_id) and _job_is_visible(row, current_user)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Job prefix is ambiguous; provide the full job_id")
    return matches[0]


# ═══════════════════════════════════════════════════════════════════════════════
# ── Planning Engine ────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class PlanRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    context: str = Field(default="")
    plan_id: str | None = None


class PlanExecuteRequest(BaseModel):
    max_steps: int = Field(default=50, ge=1, le=200)
    max_workers: int = Field(default=4, ge=1, le=16)


@router.post("/api/plans/decompose", summary="Decompose a goal into a task graph (no execution)")
def decompose_plan(req: PlanRequest):
    """
    Run AI goal decomposition and return the task graph.
    Does **not** execute tasks — use POST /api/plans/run or POST /api/plans to also execute.
    """
    k = _kernel()
    try:
        plan = k.plan_goal(goal=req.goal, context=req.context, plan_id=req.plan_id)
    except Exception as exc:
        logger.error("plan decompose failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"success": True, "data": plan}


@router.post("/api/plans", summary="Decompose + execute a goal autonomously", status_code=202)
def plan_and_execute(req: PlanRequest, max_steps: int = 50, max_workers: int = 4):
    """
    Full autonomous loop: decompose goal → execute task graph.
    Returns the execution result dict (status, completed, failed, elapsed_seconds).
    """
    k = _kernel()
    try:
        result = k.plan_and_execute(
            goal=req.goal,
            context=req.context,
            max_steps=max_steps,
            max_workers=max_workers,
        )
    except Exception as exc:
        logger.error("plan_and_execute failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "data": result}


@router.get("/api/plans", summary="List all saved plans")
def list_plans():
    k = _kernel()
    return {"success": True, "data": k.list_plans()}


@router.post("/api/plans/{plan_id}/run", summary="Execute a saved plan by ID")
def run_saved_plan(plan_id: str, req: PlanExecuteRequest | None = None):
    """Execute a plan that was previously decomposed and saved to disk."""
    k = _kernel()
    opts = req or PlanExecuteRequest()
    result = k.execute_plan(plan_id, max_steps=opts.max_steps, max_workers=opts.max_workers)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return {"success": True, "data": result}


@router.post("/api/plans/{plan_id}/resume", summary="Resume a saved plan (skip completed tasks)")
def resume_plan(plan_id: str, req: PlanExecuteRequest | None = None):
    """Resume execution of a partially-completed plan."""
    k = _kernel()
    opts = req or PlanExecuteRequest()
    result = k.resume_plan(plan_id, max_steps=opts.max_steps, max_workers=opts.max_workers)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found.")
    return {"success": True, "data": result}


# ═══════════════════════════════════════════════════════════════════════════════
# ── Job Scheduler ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class JobRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    agent_name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    task: str = Field(..., min_length=1, max_length=20_000)
    priority: int = Field(default=50, ge=0, le=100)
    run_at_iso: str | None = Field(
        default=None,
        min_length=20,
        max_length=64,
        description="ISO-8601 UTC datetime, e.g. 2026-03-18T09:00:00Z",
    )
    interval_sec: float = Field(default=0.0, ge=0.0, le=2_592_000.0)
    max_retries: int = Field(default=1, ge=0, le=10)


@router.post("/api/jobs", summary="Schedule an agent job", status_code=201)
def schedule_job(
    req: JobRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    Enqueue an agent task immediately, at a specific time, or on a recurring interval.

    - Set `run_at_iso` to schedule in the future (ISO-8601 UTC).
    - Set `interval_sec > 0` to create a recurring job.
    - `priority` 0 = highest, 100 = lowest.
    """
    tenant_id = _tenant_id_for_user(current_user)
    source_ip = _request_ip(request)

    enforce_job_api_rate_limit(
        current_user,
        bucket="write",
        tenant_id=tenant_id,
        source_ip=source_ip,
    )
    enforce_job_create_quota(db, current_user)
    enforce_job_submission_abuse_controls(
        current_user,
        fingerprint=_scheduler_job_fingerprint(req),
        tenant_id=tenant_id,
        source_ip=source_ip,
    )

    k = _kernel()
    run_at = None
    if req.run_at_iso:
        try:
            run_at = datetime.fromisoformat(req.run_at_iso.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid run_at_iso format: '{req.run_at_iso}'")

        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        run_at = run_at.astimezone(timezone.utc)

        now_utc = datetime.now(timezone.utc)
        max_schedule_ahead_seconds = _env_int("JOB_API_MAX_SCHEDULE_AHEAD_SECONDS", 15_552_000, minimum=60)
        if run_at < now_utc - timedelta(seconds=5):
            raise HTTPException(status_code=422, detail="run_at_iso must be in the future")
        if run_at > now_utc + timedelta(seconds=max_schedule_ahead_seconds):
            raise HTTPException(
                status_code=422,
                detail=(
                    "run_at_iso is too far in the future "
                    f"(max {max_schedule_ahead_seconds} seconds ahead)"
                ),
            )

    max_interval_seconds = _env_int("JOB_API_MAX_INTERVAL_SECONDS", 2_592_000, minimum=0)
    if max_interval_seconds > 0 and req.interval_sec > float(max_interval_seconds):
        raise HTTPException(
            status_code=422,
            detail=f"interval_sec exceeds max allowed value of {max_interval_seconds}",
        )

    try:
        job_id = k.schedule_job(
            name=req.name,
            agent_name=req.agent_name,
            task=req.task,
            priority=req.priority,
            run_at=run_at,
            interval_sec=req.interval_sec,
            max_retries=req.max_retries,
            owner_user_id=current_user.id,
            owner_username=current_user.username,
            owner_tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("schedule_job failed: %s", exc)
        _audit_job_activity(
            db,
            current_user=current_user,
            action="scheduler_job_create_rejected",
            detail={
                "name": req.name,
                "agent_name": req.agent_name,
                "reason": str(exc),
                "tenant_id": tenant_id,
            },
            source_ip=source_ip,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        record_job_create_usage(
            db,
            current_user=current_user,
            source="scheduler_api",
            job_id=job_id,
        )
    except Exception as exc:
        logger.warning("Failed to record scheduler usage for %s: %s", job_id, exc)

    _audit_job_activity(
        db,
        current_user=current_user,
        action="scheduler_job_created",
        detail={
            "job_id": job_id,
            "name": req.name,
            "agent_name": req.agent_name,
            "tenant_id": tenant_id,
        },
        source_ip=source_ip,
    )

    return {"success": True, "data": {"job_id": job_id}}


@router.get("/api/jobs", summary="List all jobs")
def list_jobs(
    status: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Return all jobs, optionally filtered by status (pending/running/completed/failed/cancelled)."""
    tenant_id = _tenant_id_for_user(current_user)
    source_ip = _request_ip(request)
    enforce_job_api_rate_limit(
        current_user,
        bucket="read",
        tenant_id=tenant_id,
        source_ip=source_ip,
    )

    k = _kernel()
    normalized_status = _normalize_job_status_filter(status)
    safe_limit = int(limit)
    jobs = k.list_jobs(status=normalized_status, limit=safe_limit)
    visible_jobs = jobs if current_user.is_admin else [row for row in jobs if _job_is_visible(row, current_user)]
    stats = k.scheduler_stats() if current_user.is_admin else _job_stats_for_rows(visible_jobs)
    _audit_job_activity(
        db,
        current_user=current_user,
        action="scheduler_jobs_list",
        detail={
            "status": normalized_status,
            "requested_limit": int(limit),
            "effective_limit": safe_limit,
            "returned": len(visible_jobs),
            "tenant_id": tenant_id,
        },
        source_ip=source_ip,
    )
    return {"success": True, "data": visible_jobs, "stats": stats}


@router.get("/api/jobs/{job_id}", summary="Get a job by ID")
def get_job(
    job_id: str = Path(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]{7,127}$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    tenant_id = _tenant_id_for_user(current_user)
    source_ip = _request_ip(request)
    enforce_job_api_rate_limit(
        current_user,
        bucket="read",
        tenant_id=tenant_id,
        source_ip=source_ip,
    )

    k = _kernel()
    requested_job_id = _validated_job_lookup_id(job_id)
    row = _lookup_job_for_user(
        kernel=k,
        requested_job_id=requested_job_id,
        current_user=current_user,
    )
    if row is None:
        _audit_job_activity(
            db,
            current_user=current_user,
            action="scheduler_job_get_denied",
            detail={"job_id": requested_job_id, "tenant_id": tenant_id},
            source_ip=source_ip,
        )
        raise HTTPException(status_code=404, detail=f"Job '{requested_job_id}' not found.")

    _audit_job_activity(
        db,
        current_user=current_user,
        action="scheduler_job_get",
        detail={"job_id": row.get("job_id"), "tenant_id": tenant_id},
        source_ip=source_ip,
    )
    return {"success": True, "data": row}


@router.delete("/api/jobs/{job_id}", summary="Cancel a pending job")
def cancel_job(
    job_id: str = Path(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9:_-]{7,127}$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    tenant_id = _tenant_id_for_user(current_user)
    source_ip = _request_ip(request)
    enforce_job_api_rate_limit(
        current_user,
        bucket="write",
        tenant_id=tenant_id,
        source_ip=source_ip,
    )

    k = _kernel()
    requested_job_id = _validated_job_lookup_id(job_id)
    row = _lookup_job_for_user(
        kernel=k,
        requested_job_id=requested_job_id,
        current_user=current_user,
    )
    if row is None:
        _audit_job_activity(
            db,
            current_user=current_user,
            action="scheduler_job_cancel_denied",
            detail={"job_id": requested_job_id, "tenant_id": tenant_id},
            source_ip=source_ip,
        )
        raise HTTPException(status_code=404, detail=f"Job '{requested_job_id}' not found.")

    full_id = str(row.get("job_id") or "")
    if not full_id:
        raise HTTPException(status_code=404, detail=f"Job '{requested_job_id}' not found.")

    ok = k.cancel_job(full_id)
    if not ok:
        _audit_job_activity(
            db,
            current_user=current_user,
            action="scheduler_job_cancel_conflict",
            detail={"job_id": full_id, "tenant_id": tenant_id},
            source_ip=source_ip,
        )
        raise HTTPException(status_code=409, detail="Job is not in a cancellable state.")

    _audit_job_activity(
        db,
        current_user=current_user,
        action="scheduler_job_cancelled",
        detail={"job_id": full_id, "tenant_id": tenant_id},
        source_ip=source_ip,
    )
    return {"success": True, "message": f"Job '{full_id[:12]}' cancelled."}


@router.get("/api/jobs/stats/summary", summary="Job queue statistics")
def job_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    tenant_id = _tenant_id_for_user(current_user)
    source_ip = _request_ip(request)
    enforce_job_api_rate_limit(
        current_user,
        bucket="read",
        tenant_id=tenant_id,
        source_ip=source_ip,
    )

    k = _kernel()
    if current_user.is_admin:
        payload = {"success": True, "data": k.scheduler_stats()}
        _audit_job_activity(
            db,
            current_user=current_user,
            action="scheduler_job_stats",
            detail={"scope": "admin"},
            source_ip=source_ip,
        )
        return payload

    scan_limit = max(100, min(5000, int(os.getenv("JOB_API_JOB_LOOKUP_SCAN_LIMIT", "2000"))))
    jobs = [row for row in k.list_jobs(limit=scan_limit) if _job_is_visible(row, current_user)]
    payload = {"success": True, "data": _job_stats_for_rows(jobs)}
    _audit_job_activity(
        db,
        current_user=current_user,
        action="scheduler_job_stats",
        detail={"scope": "tenant", "total": len(jobs), "tenant_id": tenant_id},
        source_ip=source_ip,
    )
    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# ── Risk Assessor ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class RiskRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1)
    context: str = Field(default="")


class ToolRiskRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=100)
    tool_name: str = Field(..., min_length=1, max_length=100)
    tool_kwargs: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/risk/assess", summary="Assess the risk of an agent action")
def assess_risk(req: RiskRequest):
    """
    Multi-dimensional risk scoring across:
      financial | reputation | security | compliance | operational

    Returns score (0–10), level (LOW/MEDIUM/HIGH), recommendation (PASS/WARN/BLOCK).
    BLOCK means the action should not proceed without human override.
    """
    k = _kernel()
    try:
        report = k.assess_risk(
            agent_name=req.agent_name,
            action=req.action,
            context=req.context,
        )
    except Exception as exc:
        logger.error("risk assessment failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "data": report}


@router.post("/api/risk/assess-tool", summary="Assess the risk of a specific tool call")
def assess_tool_risk(req: ToolRiskRequest):
    k = _kernel()
    try:
        report = k.assess_tool_risk(
            agent_name=req.agent_name,
            tool_name=req.tool_name,
            tool_kwargs=req.tool_kwargs,
        )
    except Exception as exc:
        logger.error("tool risk assessment failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "data": report}


@router.get("/api/risk/history", summary="Recent risk assessment history")
def risk_history(limit: int = 50):
    k = _kernel()
    return {"success": True, "data": k.risk_history(limit=limit)}


# ═══════════════════════════════════════════════════════════════════════════════
# ── Agent Lifecycle ────────────────────────────────────────════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/lifecycle", summary="Lifecycle summary for all agents")
def lifecycle_summary():
    k = _kernel()
    return {"success": True, "data": k.lifecycle_summary()}


@router.get("/api/lifecycle/capabilities", summary="Capability profiles for all agents")
def all_capabilities():
    k = _kernel()
    return {"success": True, "data": k.all_capabilities()}


@router.get("/api/lifecycle/find", summary="Find the best agent for a task")
def find_best_agent(task: str):
    """
    Semantically score all warm/idle agents and return the best match.
    Returns `{"agent": "<name>"}` or `{"agent": null}` if none found.
    """
    k = _kernel()
    best = k.find_best_agent(task)
    return {"success": True, "data": {"agent": best}}


@router.get("/api/lifecycle/{agent_name}", summary="Lifecycle state and capabilities for one agent")
def agent_lifecycle(agent_name: str):
    k = _kernel()
    state = k.lifecycle_state(agent_name)
    caps = k.discover_capabilities(agent_name)
    return {"success": True, "data": {"name": agent_name, "state": state, "capabilities": caps}}


@router.patch("/api/lifecycle/{agent_name}/activate", summary="Mark agent as warm (active)")
def activate_agent(agent_name: str):
    k = _kernel()
    new_state = k.lifecycle_activate(agent_name)
    return {"success": True, "data": {"name": agent_name, "state": new_state}}


@router.patch("/api/lifecycle/{agent_name}/deactivate", summary="Move agent to idle")
def deactivate_agent(agent_name: str):
    k = _kernel()
    new_state = k.lifecycle_deactivate(agent_name)
    return {"success": True, "data": {"name": agent_name, "state": new_state}}


@router.patch("/api/lifecycle/{agent_name}/retire", summary="Permanently retire an agent")
def retire_agent(agent_name: str, reason: str = ""):
    k = _kernel()
    k.lifecycle_retire(agent_name, reason=reason)
    return {"success": True, "message": f"Agent '{agent_name}' retired."}


@router.post("/api/lifecycle/{agent_name}/specialize", summary="Auto-specialize based on task history")
def auto_specialize(agent_name: str):
    """
    Ask the AI to suggest new skills and tools for this agent based on its
    performance history, then apply them automatically.
    """
    k = _kernel()
    try:
        result = k.auto_specialize(agent_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "data": result}


@router.post("/api/lifecycle/{agent_name}/compose-skills", summary="Dynamically add skills to a running agent")
def compose_skills(agent_name: str, skills: list[str]):
    k = _kernel()
    updated = k.compose_skills(agent_name, skills)
    return {"success": True, "data": {"name": agent_name, "skills": updated}}


# ═══════════════════════════════════════════════════════════════════════════════
# ── Business Growth Engine ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

class CampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    channel: str = Field(..., min_length=1, max_length=60)
    cta: str = Field(default="Book a demo", max_length=200)
    target_stage: str = Field(default="lead", max_length=40)
    cadence_hours: float = Field(default=24.0, gt=0.0, le=720.0)
    enabled: bool = Field(default=True)


class LeadPayload(BaseModel):
    lead_id: str | None = None
    external_id: str | None = None
    email: str | None = None
    name: str = ""
    company: str = ""
    stage: str = "lead"
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class LeadCaptureRequest(BaseModel):
    source: str = Field(default="manual", min_length=1, max_length=60)
    leads: list[LeadPayload] = Field(..., min_length=1, max_length=1000)


class MarketingLoopRequest(BaseModel):
    max_contacts: int = Field(default=25, ge=1, le=2000)


class ConversionRequest(BaseModel):
    lead_id: str = Field(..., min_length=1, max_length=80)
    event_type: str = Field(..., min_length=1, max_length=80)
    value: float = Field(default=0.0)
    currency: str = Field(default="USD", min_length=3, max_length=6)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RevenueLoopRequest(BaseModel):
    min_new_leads: int = Field(default=20, ge=1, le=100000)
    min_lead_to_customer_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    max_churn_rate: float = Field(default=0.20, ge=0.0, le=1.0)


@router.post("/api/business/campaigns", summary="Register a marketing automation campaign", status_code=201)
def business_create_campaign(req: CampaignRequest):
    k = _kernel()
    try:
        campaign = k.business_register_campaign(
            name=req.name,
            channel=req.channel,
            cta=req.cta,
            target_stage=req.target_stage,
            cadence_hours=req.cadence_hours,
            enabled=req.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("business_create_campaign failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "data": campaign}


@router.post("/api/business/leads", summary="Ingest leads from acquisition channels")
def business_capture_leads(req: LeadCaptureRequest):
    k = _kernel()
    result = k.business_capture_leads(
        leads=[item.model_dump() for item in req.leads],
        source=req.source,
    )
    return {"success": True, "data": result}


@router.post("/api/business/marketing/run", summary="Run one marketing automation cycle")
def business_run_marketing(req: MarketingLoopRequest):
    k = _kernel()
    result = k.business_run_marketing_loop(max_contacts=req.max_contacts)
    return {"success": True, "data": result}


@router.post("/api/business/conversions", summary="Track a conversion event")
def business_track_conversion(req: ConversionRequest):
    k = _kernel()
    try:
        out = k.business_track_conversion(
            lead_id=req.lead_id,
            event_type=req.event_type,
            value=req.value,
            currency=req.currency,
            metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("business_track_conversion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"success": True, "data": out}


@router.get("/api/business/lifecycle", summary="List customer lifecycle records")
def business_lifecycle(stage: str | None = None, limit: int = 200):
    k = _kernel()
    data = k.business_customer_lifecycle(stage=stage, limit=limit)
    return {"success": True, "data": data}


@router.get("/api/business/metrics", summary="Get lead funnel and revenue metrics")
def business_metrics():
    k = _kernel()
    return {"success": True, "data": k.business_metrics()}


@router.get("/api/business/actions", summary="List open autonomous revenue actions")
def business_actions(limit: int = 100):
    k = _kernel()
    return {"success": True, "data": k.business_open_actions(limit=limit)}


@router.post("/api/business/revenue/run", summary="Run revenue optimization loop")
def business_run_revenue_loop(req: RevenueLoopRequest):
    k = _kernel()
    result = k.business_revenue_loop(
        min_new_leads=req.min_new_leads,
        min_lead_to_customer_rate=req.min_lead_to_customer_rate,
        max_churn_rate=req.max_churn_rate,
    )
    return {"success": True, "data": result}
