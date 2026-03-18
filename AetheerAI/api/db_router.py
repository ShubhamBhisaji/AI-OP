"""db_router.py — read access to persisted goal runs, tasks, and system logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.database import GoalRun, SystemLog, Task, get_db

router = APIRouter(prefix="/api/db", tags=["Database"])


def _request_user_id(request: Request) -> int | None:
    raw = getattr(request.state, "current_user_id", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _request_is_admin(request: Request) -> bool:
    return str(getattr(request.state, "api_role", "") or "").strip().lower() == "admin"


def _goal_query_for_request(db: Session, request: Request):
    q = db.query(GoalRun)
    if _request_is_admin(request):
        return q

    user_id = _request_user_id(request)
    if user_id is None:
        return q
    return q.filter(GoalRun.owner_user_id == user_id)


def _task_query_for_request(db: Session, request: Request):
    q = db.query(Task)
    if _request_is_admin(request):
        return q

    user_id = _request_user_id(request)
    if user_id is None:
        return q
    return q.filter(Task.owner_user_id == user_id)


@router.get("/goals")
def list_goal_runs(
    request: Request,
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None),
    search: str | None = Query(None),
):
    q = _goal_query_for_request(db, request)
    if status:
        q = q.filter(GoalRun.status == status)
    if search:
        like = f"%{search}%"
        q = q.filter((GoalRun.name.ilike(like)) | (GoalRun.goal.ilike(like)))

    total = q.count()
    rows = q.order_by(GoalRun.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "success": True,
        "data": {
            "items": [r.to_dict() for r in rows],
            "total": total,
            "skip": skip,
            "limit": limit,
        },
    }


@router.get("/goals/{goal_id}")
def get_goal_run(goal_id: str, request: Request, db: Session = Depends(get_db)):
    row = _goal_query_for_request(db, request).filter(GoalRun.id == goal_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Goal run not found")
    return {"success": True, "data": row.to_dict(include_tasks=True)}


@router.get("/tasks")
def list_tasks(
    request: Request,
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    goal_id: str | None = Query(None),
    status: str | None = Query(None),
    agent_type: str | None = Query(None),
):
    q = _task_query_for_request(db, request)
    if goal_id:
        q = q.filter(Task.goal_id == goal_id)
    if status:
        q = q.filter(Task.status == status)
    if agent_type:
        q = q.filter(Task.agent_type == agent_type)

    total = q.count()
    rows = q.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "success": True,
        "data": {
            "items": [r.to_dict() for r in rows],
            "total": total,
            "skip": skip,
            "limit": limit,
        },
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    row = _task_query_for_request(db, request).filter(Task.id == task_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "data": row.to_dict()}


@router.get("/logs")
def list_system_logs(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    level: str | None = Query(None),
    logger_name: str | None = Query(None),
):
    q = db.query(SystemLog)
    if level:
        q = q.filter(SystemLog.level == level.upper())
    if logger_name:
        q = q.filter(SystemLog.logger_name == logger_name)

    total = q.count()
    rows = q.order_by(SystemLog.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "success": True,
        "data": {
            "items": [r.to_dict() for r in rows],
            "total": total,
            "skip": skip,
            "limit": limit,
        },
    }


@router.get("/stats")
def db_stats(request: Request, db: Session = Depends(get_db)):
    goal_query = _goal_query_for_request(db, request)
    task_query = _task_query_for_request(db, request)

    goals_total = goal_query.with_entities(func.count(GoalRun.id)).scalar() or 0
    tasks_total = task_query.with_entities(func.count(Task.id)).scalar() or 0
    logs_total = db.query(func.count(SystemLog.id)).scalar() or 0

    running = goal_query.filter(GoalRun.status == "running").with_entities(func.count(GoalRun.id)).scalar() or 0
    completed = goal_query.filter(GoalRun.status == "completed").with_entities(func.count(GoalRun.id)).scalar() or 0
    failed = goal_query.filter(GoalRun.status == "failed").with_entities(func.count(GoalRun.id)).scalar() or 0

    task_completed = task_query.filter(Task.status == "completed").with_entities(func.count(Task.id)).scalar() or 0
    task_failed = task_query.filter(Task.status == "failed").with_entities(func.count(Task.id)).scalar() or 0

    return {
        "success": True,
        "data": {
            "goal_runs": {
                "total": int(goals_total),
                "running": int(running),
                "completed": int(completed),
                "failed": int(failed),
            },
            "tasks": {
                "total": int(tasks_total),
                "completed": int(task_completed),
                "failed": int(task_failed),
            },
            "system_logs": {
                "total": int(logs_total),
            },
        },
    }
