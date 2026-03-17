"""Queue API routes for async job creation and status polling."""
from __future__ import annotations

import datetime
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.async_jobs import SupabaseJobStore, build_queue_payload
from api.auth import get_current_user
from api.database import User, get_db
from api.job_security import enforce_job_api_rate_limit, enforce_job_create_quota, record_job_create_usage
from integrations.upstash_redis_queue import UpstashRedisQueue

logger = logging.getLogger("aetheer.api.queue")

router = APIRouter(tags=["Queue"])

_job_store: SupabaseJobStore | None = None
_queue_client: UpstashRedisQueue | None = None


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, value)


def _normalize_priority(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "urgent", "critical"}:
        return "high"
    if text in {"low", "background"}:
        return "low"
    return "normal"


def _get_job_store() -> SupabaseJobStore:
    global _job_store
    if _job_store is None:
        _job_store = SupabaseJobStore()
    return _job_store


def _get_queue_client() -> UpstashRedisQueue:
    global _queue_client
    if _queue_client is None:
        _queue_client = UpstashRedisQueue()
    return _queue_client


def _owner_user_id_from_row(row: dict[str, Any]) -> int | None:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw_owner = metadata.get("owner_user_id")
    try:
        return int(raw_owner)
    except (TypeError, ValueError):
        return None


def _queue_name_for_priority(queue: UpstashRedisQueue, priority: str) -> str:
    resolver = getattr(queue, "queue_name_for_priority", None)
    if callable(resolver):
        try:
            return str(resolver(priority))
        except Exception:
            pass
    return str(getattr(queue, "queue_name", "job_queue"))


def _append_queued_event(metadata: dict[str, Any], *, queue_name: str, priority: str) -> None:
    events = metadata.get("stream_events")
    stream_events = [evt for evt in events if isinstance(evt, dict)] if isinstance(events, list) else []
    stream_events.append(
        {
            "ts": _utc_now_iso(),
            "type": "queued",
            "status": "queued",
            "payload": {
                "queue": queue_name,
                "priority": priority,
            },
        }
    )
    max_events = _env_int("AETHEER_JOB_STREAM_MAX_EVENTS", 100, minimum=10)
    if len(stream_events) > max_events:
        stream_events = stream_events[-max_events:]

    metadata["stream_events"] = stream_events
    metadata["stream_event_count"] = len(stream_events)


class QueueJobRequest(BaseModel):
    task_type: str = Field(
        default="goal",
        min_length=1,
        description="Task discriminator consumed by the worker (for example: goal, agent_task, chat).",
    )
    task_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Task payload consumed by the worker. Must be JSON-serializable.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata for traceability (tenant/user/request tags).",
    )
    priority: str = Field(
        default="normal",
        description="Queue priority: high | normal | low.",
    )
    stream_results: bool = Field(
        default=True,
        description="When true, stream events are appended to metadata for polling endpoints.",
    )
    max_retries: int | None = Field(
        default=None,
        ge=0,
        description="Optional retry budget for worker retry/dead-letter flow.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "task_type": "goal",
                "task_data": {
                    "name": "Product launch plan",
                    "goal": "Research competitors and draft a GTM launch strategy",
                    "context": {"region": "US"},
                    "parallel": True,
                    "collaboration_mode": True,
                },
                "metadata": {
                    "requested_by": "user_123",
                    "source": "vercel-api",
                },
                "priority": "normal",
                "stream_results": True,
                "max_retries": 3,
            }
        }
    }


class QueueBatchJobRequest(BaseModel):
    jobs: list[QueueJobRequest] = Field(..., min_length=1, max_length=50)


class QueueJobStatusResponse(BaseModel):
    job_id: str
    status: str
    task_type: str | None = None
    task_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    result: Any = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class QueueJobEventsResponse(BaseModel):
    job_id: str
    total_events: int
    events: list[dict[str, Any]]


def _enqueue_single_job(
    req: QueueJobRequest,
    *,
    current_user: User,
    db: Session,
    apply_rate_limit: bool,
) -> dict[str, Any]:
    if apply_rate_limit:
        enforce_job_api_rate_limit(current_user, bucket="write")

    enforce_job_create_quota(db, current_user)

    job_id = str(uuid.uuid4())
    store = _get_job_store()
    queue = _get_queue_client()
    priority = _normalize_priority(req.priority)
    queue_name = _queue_name_for_priority(queue, priority)

    resolved_max_retries = req.max_retries
    if resolved_max_retries is None:
        resolved_max_retries = _env_int("AETHEER_JOB_MAX_RETRIES", 3, minimum=0)

    metadata = dict(req.metadata)
    metadata["owner_user_id"] = current_user.id
    metadata["owner_username"] = current_user.username
    metadata["priority"] = priority
    metadata["retry_count"] = 0
    metadata["max_retries"] = int(resolved_max_retries)
    metadata["stream_results"] = bool(req.stream_results)
    if metadata["stream_results"]:
        _append_queued_event(metadata, queue_name=queue_name, priority=priority)

    try:
        store.create_job(
            job_id=job_id,
            task_type=req.task_type,
            task_payload=req.task_data,
            metadata=metadata,
        )
    except Exception as exc:
        logger.error("Failed to create Supabase job row %s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Failed to persist job in Supabase") from exc

    try:
        payload = build_queue_payload(
            job_id,
            req.task_type,
            req.task_data,
            priority=priority,
            retry_count=0,
            max_retries=int(resolved_max_retries),
        )
    except TypeError:
        payload = build_queue_payload(job_id, req.task_type, req.task_data)

    try:
        queue_depth = queue.push_job(payload, queue_name=queue_name)
    except TypeError:
        queue_depth = queue.push_job(payload)
    except Exception as exc:
        logger.error("Failed to push queue payload for job %s: %s", job_id, exc)
        try:
            store.mark_failed(job_id, f"Queue publish failed: {exc}")
        except Exception as update_exc:
            logger.warning("Unable to mark job %s as failed after queue error: %s", job_id, update_exc)
        raise HTTPException(status_code=502, detail="Failed to enqueue job in Upstash Redis") from exc

    try:
        record_job_create_usage(
            db,
            current_user=current_user,
            source="queue_api",
            job_id=job_id,
        )
    except Exception as exc:
        logger.warning("Failed to record queue job usage for %s: %s", job_id, exc)

    return {
        "job_id": job_id,
        "status": "queued",
        "queue": queue_name,
        "queue_depth": queue_depth,
        "priority": priority,
    }


@router.post(
    "/api/queue/jobs",
    summary="Create an async job",
    status_code=201,
)
def create_queue_job(
    req: QueueJobRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Vercel-safe entrypoint:
      1) Insert job row in Supabase.
      2) Push payload to Upstash Redis list `job_queue`.
      3) Return job_id immediately.
    """
    data = _enqueue_single_job(req, current_user=current_user, db=db, apply_rate_limit=True)
    return {"success": True, "data": data}


@router.post(
    "/api/queue/jobs/batch",
    summary="Create multiple async jobs",
    status_code=201,
)
def create_queue_jobs_batch(
    req: QueueBatchJobRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_job_api_rate_limit(current_user, bucket="write")

    jobs: list[dict[str, Any]] = []
    for item in req.jobs:
        jobs.append(_enqueue_single_job(item, current_user=current_user, db=db, apply_rate_limit=False))

    return {
        "success": True,
        "data": {
            "submitted": len(jobs),
            "jobs": jobs,
        },
    }


@router.get(
    "/api/queue/jobs/{job_id}",
    summary="Get async job status",
    response_model=QueueJobStatusResponse,
)
def get_queue_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    """Status polling endpoint for clients to track queued/running/completed/failed jobs."""
    enforce_job_api_rate_limit(current_user, bucket="read")

    row = _get_job_store().get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    owner_user_id = _owner_user_id_from_row(row)
    if not current_user.is_admin:
        # Return 404 to avoid leaking whether another user's job exists.
        if owner_user_id is None or owner_user_id != current_user.id:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    response_payload = QueueJobStatusResponse(
        job_id=str(row.get("id") or row.get("job_id") or job_id),
        status=str(row.get("status") or "unknown"),
        task_type=row.get("task_type"),
        task_payload=row.get("task_payload") if isinstance(row.get("task_payload"), dict) else None,
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else None,
        result=row.get("result"),
        error=row.get("error"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )
    return response_payload


@router.get(
    "/api/queue/jobs/{job_id}/events",
    summary="Poll queue job stream events",
    response_model=QueueJobEventsResponse,
)
def get_queue_job_events(
    job_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
):
    enforce_job_api_rate_limit(current_user, bucket="read")

    row = _get_job_store().get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    owner_user_id = _owner_user_id_from_row(row)
    if not current_user.is_admin:
        if owner_user_id is None or owner_user_id != current_user.id:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    events = metadata.get("stream_events") if isinstance(metadata.get("stream_events"), list) else []
    event_rows = [evt for evt in events if isinstance(evt, dict)]

    safe_limit = max(1, min(int(limit), 500))
    clipped = event_rows[-safe_limit:]
    return QueueJobEventsResponse(
        job_id=str(row.get("id") or row.get("job_id") or job_id),
        total_events=len(event_rows),
        events=clipped,
    )


@router.delete(
    "/api/queue/jobs/cleanup",
    summary="Cleanup old completed/failed queue jobs",
)
def cleanup_old_queue_jobs(
    retention_hours: int = 24 * 7,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
):
    enforce_job_api_rate_limit(current_user, bucket="write")

    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    store = _get_job_store()
    cleanup_fn = getattr(store, "cleanup_old_jobs", None)
    if not callable(cleanup_fn):
        return {"success": True, "data": {"deleted": 0, "retention_hours": retention_hours}}

    deleted = cleanup_fn(retention_hours=max(1, int(retention_hours)), limit=max(1, int(limit)))
    return {
        "success": True,
        "data": {
            "deleted": int(deleted),
            "retention_hours": max(1, int(retention_hours)),
            "limit": max(1, int(limit)),
        },
    }
