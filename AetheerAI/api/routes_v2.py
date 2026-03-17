"""
routes_v2.py — REST API routes for AetheerAI v2 subsystems.

Adds endpoints for:
  /api/plans        — PlanningEngine (DAG goal decomposition + execution)
  /api/jobs         — JobScheduler  (persistent priority queue)
  /api/risk         — RiskAssessor  (multi-dimensional risk scoring)
  /api/lifecycle    — AgentLifecycleManager (warm/idle/cold/retired + capabilities)

Mount this router from api/server.py:
    from api.routes_v2 import router as v2_router
    app.include_router(v2_router)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("aetheer.api.v2")

router = APIRouter(tags=["v2"])

# ── Lazy kernel accessor (avoids import-time circular dependency) ─────────────

def _kernel():
    from api.server import _get_kernel
    return _get_kernel()


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
    agent_name: str = Field(..., min_length=1, max_length=100)
    task: str = Field(..., min_length=1)
    priority: int = Field(default=50, ge=0, le=100)
    run_at_iso: str | None = Field(default=None, description="ISO-8601 UTC datetime, e.g. 2026-03-18T09:00:00Z")
    interval_sec: float = Field(default=0.0, ge=0.0)
    max_retries: int = Field(default=1, ge=0, le=10)


@router.post("/api/jobs", summary="Schedule an agent job", status_code=201)
def schedule_job(req: JobRequest):
    """
    Enqueue an agent task immediately, at a specific time, or on a recurring interval.

    - Set `run_at_iso` to schedule in the future (ISO-8601 UTC).
    - Set `interval_sec > 0` to create a recurring job.
    - `priority` 0 = highest, 100 = lowest.
    """
    k = _kernel()
    run_at = None
    if req.run_at_iso:
        try:
            run_at = datetime.fromisoformat(req.run_at_iso.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid run_at_iso format: '{req.run_at_iso}'")

    try:
        job_id = k.schedule_job(
            name=req.name,
            agent_name=req.agent_name,
            task=req.task,
            priority=req.priority,
            run_at=run_at,
            interval_sec=req.interval_sec,
            max_retries=req.max_retries,
        )
    except Exception as exc:
        logger.error("schedule_job failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"success": True, "data": {"job_id": job_id}}


@router.get("/api/jobs", summary="List all jobs")
def list_jobs(status: str | None = None, limit: int = 100):
    """Return all jobs, optionally filtered by status (pending/running/completed/failed/cancelled)."""
    k = _kernel()
    jobs = k.list_jobs(status=status, limit=limit)
    stats = k.scheduler_stats()
    return {"success": True, "data": jobs, "stats": stats}


@router.get("/api/jobs/{job_id}", summary="Get a job by ID")
def get_job(job_id: str):
    k = _kernel()
    # Allow partial ID prefix match
    all_jobs = k.list_jobs(limit=5000)
    matches = [j for j in all_jobs if j["job_id"] == job_id or j["job_id"].startswith(job_id)]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"success": True, "data": matches[0]}


@router.delete("/api/jobs/{job_id}", summary="Cancel a pending job")
def cancel_job(job_id: str):
    k = _kernel()
    # Allow partial match
    all_jobs = k.list_jobs(limit=5000)
    matches = [j for j in all_jobs if j["job_id"] == job_id or j["job_id"].startswith(job_id)]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    full_id = matches[0]["job_id"]
    ok = k.cancel_job(full_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Job is not in a cancellable state.")
    return {"success": True, "message": f"Job '{full_id[:12]}' cancelled."}


@router.get("/api/jobs/stats/summary", summary="Job queue statistics")
def job_stats():
    k = _kernel()
    return {"success": True, "data": k.scheduler_stats()}


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
