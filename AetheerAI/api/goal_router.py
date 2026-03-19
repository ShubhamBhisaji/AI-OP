"""
goal_router.py — REST API for MissionControl goal/task orchestration.

Endpoints
---------
  POST   /api/missions                          Launch a goal + tasks for an agent
  GET    /api/missions/{agent_name}             List goals for an agent
  GET    /api/missions/{agent_name}/status      Full loop + goal/task status
  POST   /api/missions/{agent_name}/pause       Pause the agent's execution loop
  POST   /api/missions/{agent_name}/resume      Resume the agent's execution loop
  DELETE /api/missions/{agent_name}/goals/{goal_id}         Cancel a goal
  POST   /api/missions/{agent_name}/goals/{goal_id}/retry   Retry failed tasks
  GET    /api/missions/{agent_name}/goals/{goal_id}/tasks   List tasks for a goal

  GET    /api/schedules                         List scheduled / recurring goals
  POST   /api/schedules                         Schedule a one-time or recurring goal
  DELETE /api/schedules/{scheduled_id}          Cancel a scheduled goal

  GET    /api/missions/health                   Aggregate health across all agents
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth import get_current_user

logger = logging.getLogger("aetheer.api.goals")

router = APIRouter(prefix="/api", tags=["missions"])

_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_GOAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_MAX_TASKS_PER_LAUNCH = 50
_MAX_DESC_LEN = 2_000


def _kernel():
    from api.server import _get_kernel
    return _get_kernel()


def _mc():
    k = _kernel()
    mc = getattr(k, "mission_control", None)
    if mc is None:
        raise HTTPException(status_code=503, detail="MissionControl not initialised.")
    return mc


def _validate_agent_name(name: str) -> str:
    if not _AGENT_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="agent_name must be 1–64 alphanumeric/underscore/hyphen chars.",
        )
    return name


def _validate_goal_id(goal_id: str) -> str:
    if not _GOAL_ID_RE.match(goal_id):
        raise HTTPException(
            status_code=400,
            detail="goal_id format invalid.",
        )
    return goal_id


# ── Request / Response models ─────────────────────────────────────────────────

class TaskSpec(BaseModel):
    description: str = Field(..., min_length=1, max_length=_MAX_DESC_LEN)
    priority: int = Field(5, ge=1, le=10)
    depends_on: list[str] = Field(default_factory=list)
    run_after: float = Field(0.0, ge=0.0)
    max_retries: int = Field(2, ge=0, le=10)
    tags: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class LaunchMissionRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=64)
    goal: str = Field(..., min_length=1, max_length=_MAX_DESC_LEN)
    tasks: list[TaskSpec] = Field(default_factory=list)
    priority: int = Field(5, ge=1, le=10)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    max_retries_per_task: int = Field(2, ge=0, le=10)


class ScheduleGoalRequest(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=64)
    goal: str = Field(..., min_length=1, max_length=_MAX_DESC_LEN)
    tasks: list[str] = Field(default_factory=list)
    priority: int = Field(5, ge=1, le=10)
    max_retries: int = Field(2, ge=0, le=10)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # One-time: run_at as Unix timestamp (None = run now)
    run_at: float | None = None
    # Recurring: interval in seconds (None = one-time)
    interval_seconds: float | None = None


# ── Mission endpoints ─────────────────────────────────────────────────────────

@router.post(
    "/missions",
    summary="Launch a mission — create persistent goal + tasks and start worker loop",
    status_code=202,
)
def launch_mission(
    req: LaunchMissionRequest,
    current_user=Depends(get_current_user),
):
    """
    Creates a persistent, prioritized goal with one or more tasks and starts
    the continuous AutonomousGoalLoop for the specified agent.

    Tasks support dependency chains via ``depends_on``:
    - Use ``"task:0"`` to reference the first task in the same request.
    - Use a raw task UUID to reference a task from a previous mission.

    Tasks with a future ``run_after`` timestamp will not start until that time.
    """
    _validate_agent_name(req.agent_name)
    if len(req.tasks) > _MAX_TASKS_PER_LAUNCH:
        raise HTTPException(
            status_code=400,
            detail=f"Too many tasks (max {_MAX_TASKS_PER_LAUNCH} per launch).",
        )

    mc = _mc()
    task_dicts = [t.model_dump() for t in req.tasks]

    try:
        goal_id = mc.launch(
            agent_name=req.agent_name,
            goal=req.goal,
            tasks=task_dicts,
            priority=req.priority,
            tags=req.tags,
            metadata=req.metadata,
            max_retries_per_task=req.max_retries_per_task,
        )
    except Exception as exc:
        logger.error("launch_mission failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "goal_id": goal_id,
        "agent_name": req.agent_name,
        "tasks_queued": len(req.tasks),
        "status": "launched",
    }


@router.get("/missions/health", summary="Aggregate health across all agent loops")
def mission_health(current_user=Depends(get_current_user)):
    """Returns health status for every agent execution loop and the goal scheduler."""
    return _mc().health_check()


@router.get(
    "/missions/{agent_name}",
    summary="List goals for an agent",
)
def list_missions(
    agent_name: str,
    state: str | None = Query(None, description="Filter: pending|active|completed|failed|paused|cancelled"),
    current_user=Depends(get_current_user),
):
    _validate_agent_name(agent_name)
    try:
        return _mc().list_goals(agent_name, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/missions/{agent_name}/status",
    summary="Full loop + goal/task status snapshot for an agent",
)
def mission_status(agent_name: str, current_user=Depends(get_current_user)):
    _validate_agent_name(agent_name)
    return _mc().status(agent_name)


@router.post("/missions/{agent_name}/pause", summary="Pause agent execution loop")
def pause_mission(agent_name: str, current_user=Depends(get_current_user)):
    _validate_agent_name(agent_name)
    ok = _mc().pause(agent_name)
    return {"agent_name": agent_name, "paused": ok}


@router.post("/missions/{agent_name}/resume", summary="Resume agent execution loop")
def resume_mission(agent_name: str, current_user=Depends(get_current_user)):
    _validate_agent_name(agent_name)
    ok = _mc().resume(agent_name)
    return {"agent_name": agent_name, "resumed": ok}


@router.delete(
    "/missions/{agent_name}/goals/{goal_id}",
    summary="Cancel a goal and skip remaining tasks",
)
def cancel_goal(
    agent_name: str,
    goal_id: str,
    current_user=Depends(get_current_user),
):
    _validate_agent_name(agent_name)
    _validate_goal_id(goal_id)
    ok = _mc().cancel(agent_name, goal_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Goal not found or already terminal.")
    return {"agent_name": agent_name, "goal_id": goal_id, "cancelled": True}


@router.post(
    "/missions/{agent_name}/goals/{goal_id}/retry",
    summary="Reset all failed tasks in a goal back to pending",
)
def retry_failed_tasks(
    agent_name: str,
    goal_id: str,
    current_user=Depends(get_current_user),
):
    _validate_agent_name(agent_name)
    _validate_goal_id(goal_id)
    reset = _mc().retry_failed(agent_name, goal_id)
    return {"agent_name": agent_name, "goal_id": goal_id, "tasks_reset": reset}


@router.get(
    "/missions/{agent_name}/goals/{goal_id}/tasks",
    summary="List tasks for a specific goal",
)
def list_goal_tasks(
    agent_name: str,
    goal_id: str,
    state: str | None = Query(None, description="Filter: pending|active|retrying|completed|failed|skipped"),
    current_user=Depends(get_current_user),
):
    _validate_agent_name(agent_name)
    _validate_goal_id(goal_id)
    try:
        return _mc().list_tasks(agent_name, goal_id=goal_id, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── Schedule endpoints ────────────────────────────────────────────────────────

@router.get("/schedules", summary="List all scheduled / recurring goals")
def list_scheduled(current_user=Depends(get_current_user)):
    return _mc().list_scheduled_goals()


@router.post(
    "/schedules",
    summary="Schedule a one-time or recurring goal",
    status_code=201,
)
def schedule_goal(
    req: ScheduleGoalRequest,
    current_user=Depends(get_current_user),
):
    """
    Schedule a goal to run at a specific time or on a recurring interval.

    - ``run_at`` (Unix timestamp): when to trigger the goal (None = now).
    - ``interval_seconds``: if set, the goal repeats every N seconds.
    """
    _validate_agent_name(req.agent_name)
    mc = _mc()
    try:
        if req.interval_seconds and req.interval_seconds > 0:
            sid = mc.schedule_recurring(
                agent_name=req.agent_name,
                goal=req.goal,
                interval_seconds=req.interval_seconds,
                tasks=req.tasks,
                priority=req.priority,
                max_retries=req.max_retries,
                tags=req.tags,
                run_at=req.run_at,
            )
        else:
            sid = mc.schedule(
                agent_name=req.agent_name,
                goal=req.goal,
                tasks=req.tasks,
                run_at=req.run_at,
                priority=req.priority,
                max_retries=req.max_retries,
                tags=req.tags,
                metadata=req.metadata,
            )
    except Exception as exc:
        logger.error("schedule_goal failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "scheduled_id": sid,
        "agent_name": req.agent_name,
        "recurring": bool(req.interval_seconds),
        "run_at": req.run_at,
    }


@router.delete(
    "/schedules/{scheduled_id}",
    summary="Cancel a scheduled goal",
)
def cancel_scheduled(
    scheduled_id: str,
    current_user=Depends(get_current_user),
):
    ok = _mc().cancel_scheduled(scheduled_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Scheduled goal not found.")
    return {"scheduled_id": scheduled_id, "cancelled": True}
