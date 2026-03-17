"""Queue API routes for async job creation and status polling."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.async_jobs import SupabaseJobStore, build_queue_payload
from integrations.upstash_redis_queue import UpstashRedisQueue

logger = logging.getLogger("aetheer.api.queue")

router = APIRouter(tags=["Queue"])

_job_store: SupabaseJobStore | None = None
_queue_client: UpstashRedisQueue | None = None


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
            }
        }
    }


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


@router.post(
    "/api/queue/jobs",
    summary="Create an async job",
    status_code=201,
)
def create_queue_job(req: QueueJobRequest):
    """
    Vercel-safe entrypoint:
      1) Insert job row in Supabase.
      2) Push payload to Upstash Redis list `job_queue`.
      3) Return job_id immediately.
    """
    job_id = str(uuid.uuid4())
    store = _get_job_store()
    queue = _get_queue_client()

    try:
        store.create_job(
            job_id=job_id,
            task_type=req.task_type,
            task_payload=req.task_data,
            metadata=req.metadata,
        )
    except Exception as exc:
        logger.error("Failed to create Supabase job row %s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Failed to persist job in Supabase") from exc

    payload = build_queue_payload(job_id, req.task_type, req.task_data)
    try:
        queue_depth = queue.push_job(payload)
    except Exception as exc:
        logger.error("Failed to push queue payload for job %s: %s", job_id, exc)
        try:
            store.mark_failed(job_id, f"Queue publish failed: {exc}")
        except Exception as update_exc:
            logger.warning("Unable to mark job %s as failed after queue error: %s", job_id, update_exc)
        raise HTTPException(status_code=502, detail="Failed to enqueue job in Upstash Redis") from exc

    return {
        "success": True,
        "data": {
            "job_id": job_id,
            "status": "queued",
            "queue": queue.queue_name,
            "queue_depth": queue_depth,
        },
    }


@router.get(
    "/api/queue/jobs/{job_id}",
    summary="Get async job status",
    response_model=QueueJobStatusResponse,
)
def get_queue_job_status(job_id: str):
    """Status polling endpoint for clients to track queued/running/completed/failed jobs."""
    row = _get_job_store().get_job(job_id)
    if row is None:
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
