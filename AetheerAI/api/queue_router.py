"""Queue API routes for async job creation and status polling."""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.async_jobs import SupabaseJobStore, build_queue_payload
from api.auth import get_current_user
from api.database import ActivityLog, User, get_db
from api.job_security import (
    enforce_job_api_rate_limit,
    enforce_job_create_quota,
    enforce_job_submission_abuse_controls,
    record_job_create_usage,
)
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


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, value)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _json_size_bytes(value: Any) -> int:
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Queue payload must be JSON-serializable") from exc
    return len(encoded.encode("utf-8"))


def _enforce_payload_size_limits_for_values(task_data: dict[str, Any], metadata: dict[str, Any]) -> None:
    max_task_bytes = _env_int("JOB_API_MAX_TASK_PAYLOAD_BYTES", 262_144, minimum=64)
    max_metadata_bytes = _env_int("JOB_API_MAX_METADATA_BYTES", 65_536, minimum=64)

    task_size = _json_size_bytes(task_data)
    if task_size > max_task_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"task_data exceeds {max_task_bytes} bytes (got {task_size})",
        )

    metadata_size = _json_size_bytes(metadata)
    if metadata_size > max_metadata_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"metadata exceeds {max_metadata_bytes} bytes (got {metadata_size})",
        )


def _enforce_payload_size_limits(req: "QueueJobRequest") -> None:
    _enforce_payload_size_limits_for_values(dict(req.task_data), dict(req.metadata))


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


def _owner_tenant_id_from_row(row: dict[str, Any]) -> str | None:
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None

    tenant_id = str(metadata.get("owner_tenant_id") or "").strip().lower()
    return tenant_id or None


def _tenant_id_for_user(current_user: User) -> str:
    prefix = (os.getenv("JOB_API_TENANT_PREFIX") or "user").strip().lower() or "user"
    return f"{prefix}:{int(current_user.id)}"


def _row_visible_to_user(row: dict[str, Any], current_user: User) -> bool:
    if current_user.is_admin:
        return True

    owner_user_id = _owner_user_id_from_row(row)
    if owner_user_id is None or owner_user_id != int(current_user.id):
        return False

    owner_tenant_id = _owner_tenant_id_from_row(row)
    if owner_tenant_id is None:
        return True
    return owner_tenant_id == _tenant_id_for_user(current_user)


def _request_ip(request: Request | None) -> str | None:
    if request is None:
        return None

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or None

    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host).strip() if host else None


def _queue_job_fingerprint(req: "QueueJobRequest", *, priority: str) -> str:
    payload = {
        "task_type": str(req.task_type or "").strip().lower(),
        "task_data": req.task_data,
        "metadata": req.metadata,
        "priority": str(priority or "normal"),
        "stream_results": bool(req.stream_results),
        "max_retries": req.max_retries,
        "max_runtime_seconds": req.max_runtime_seconds,
        "max_memory_mb": req.max_memory_mb,
        "max_cpu_seconds": req.max_cpu_seconds,
        "max_cost_usd": req.max_cost_usd,
        "enforce_monthly_budget": req.enforce_monthly_budget,
    }
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Queue payload must be JSON-serializable") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _audit_queue_activity(
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
                action=str(action or "queue_event")[:128],
                detail=dict(detail or {}),
                ip_address=source_ip,
            )
        )
        db.commit()
    except Exception as exc:
        logger.warning("Queue audit logging failed for action=%s: %s", action, exc)


def _queue_name_for_priority(queue: UpstashRedisQueue, priority: str) -> str:
    resolver = getattr(queue, "queue_name_for_priority", None)
    if callable(resolver):
        try:
            return str(resolver(priority))
        except Exception:
            pass
    return str(getattr(queue, "queue_name", "job_queue"))


def _queue_depth_or_zero(queue: UpstashRedisQueue, queue_name: str) -> int:
    try:
        return int(queue.queue_depth(queue_name=queue_name))
    except Exception:
        return 0


def _governance_limits_snapshot() -> dict[str, Any]:
    default_runtime_seconds = _env_int(
        "AETHEER_JOB_MAX_RUNTIME_SECONDS",
        _env_int("MAX_RUNTIME_SECONDS", 600, minimum=1),
        minimum=1,
    )
    hard_runtime_seconds = _env_int(
        "AETHEER_JOB_RUNTIME_CAP_SECONDS",
        default_runtime_seconds,
        minimum=1,
    )
    default_runtime_seconds = min(default_runtime_seconds, hard_runtime_seconds)

    default_memory_mb = _env_int("AETHEER_JOB_MAX_MEMORY_MB", 1024, minimum=0)
    hard_memory_mb = _env_int("AETHEER_JOB_MEMORY_CAP_MB", default_memory_mb, minimum=0)
    if hard_memory_mb > 0:
        default_memory_mb = min(default_memory_mb, hard_memory_mb)

    default_cpu_seconds = _env_int("AETHEER_JOB_MAX_CPU_SECONDS", 300, minimum=0)
    hard_cpu_seconds = _env_int("AETHEER_JOB_CPU_CAP_SECONDS", default_cpu_seconds, minimum=0)
    if hard_cpu_seconds > 0:
        default_cpu_seconds = min(default_cpu_seconds, hard_cpu_seconds)

    default_cost_usd = _env_float(
        "AETHEER_JOB_DEFAULT_MAX_COST_USD",
        _env_float(
            "AETHEER_JOB_MAX_COST_USD",
            _env_float("MAX_COST_USD", 10.0, minimum=0.0),
            minimum=0.0,
        ),
        minimum=0.0,
    )
    hard_cost_usd = _env_float(
        "AETHEER_JOB_HARD_MAX_COST_USD",
        default_cost_usd if default_cost_usd > 0 else 0.0,
        minimum=0.0,
    )
    if hard_cost_usd > 0:
        default_cost_usd = min(default_cost_usd, hard_cost_usd)

    return {
        "default_max_runtime_seconds": default_runtime_seconds,
        "hard_max_runtime_seconds": hard_runtime_seconds,
        "default_max_memory_mb": default_memory_mb,
        "hard_max_memory_mb": hard_memory_mb,
        "default_max_cpu_seconds": default_cpu_seconds,
        "hard_max_cpu_seconds": hard_cpu_seconds,
        "default_max_cost_usd": default_cost_usd,
        "hard_max_cost_usd": hard_cost_usd,
        "default_enforce_monthly_budget": _env_bool("AETHEER_JOB_BUDGET_ENFORCE_MONTHLY", True),
        "allow_budget_opt_out": _env_bool("AETHEER_QUEUE_ALLOW_BUDGET_OPT_OUT", False),
        "allow_non_admin_high_priority": _env_bool("AETHEER_QUEUE_ALLOW_NON_ADMIN_HIGH_PRIORITY", True),
        "high_priority_depth_limit": _env_int("AETHEER_QUEUE_HIGH_PRIORITY_DEPTH_LIMIT", 0, minimum=0),
    }


def _resolve_priority_policy(
    *,
    queue: UpstashRedisQueue,
    current_user: User,
    requested_priority: str,
    governance: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    requested = _normalize_priority(requested_priority)
    effective = requested
    reason = "accepted"

    high_queue_name = _queue_name_for_priority(queue, "high")
    high_queue_depth = _queue_depth_or_zero(queue, high_queue_name)
    high_depth_limit = _safe_int(governance.get("high_priority_depth_limit"), 0)

    if requested == "high" and not current_user.is_admin:
        if not bool(governance.get("allow_non_admin_high_priority", True)):
            effective = "normal"
            reason = "high_priority_requires_admin"
        elif high_depth_limit > 0 and high_queue_depth >= high_depth_limit:
            effective = "normal"
            reason = "high_priority_backpressure"

    return effective, {
        "requested": requested,
        "effective": effective,
        "reason": reason,
        "high_queue_name": high_queue_name,
        "high_queue_depth": high_queue_depth,
        "high_priority_depth_limit": high_depth_limit,
    }


def _resolve_job_governance(
    req: "QueueJobRequest",
    *,
    current_user: User,
    queue: UpstashRedisQueue,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    governance = _governance_limits_snapshot()
    task_data = dict(req.task_data)

    effective_priority, priority_policy = _resolve_priority_policy(
        queue=queue,
        current_user=current_user,
        requested_priority=req.priority,
        governance=governance,
    )

    runtime_raw = req.max_runtime_seconds if req.max_runtime_seconds is not None else task_data.get("max_runtime_seconds")
    memory_raw = req.max_memory_mb if req.max_memory_mb is not None else task_data.get("max_memory_mb")
    cpu_raw = req.max_cpu_seconds if req.max_cpu_seconds is not None else task_data.get("max_cpu_seconds")

    if req.max_cost_usd is not None:
        cost_raw: Any = req.max_cost_usd
    elif "max_cost_usd" in task_data:
        cost_raw = task_data.get("max_cost_usd")
    elif "budget_usd" in task_data:
        cost_raw = task_data.get("budget_usd")
    else:
        cost_raw = None

    max_runtime_seconds = max(1, _safe_int(runtime_raw, _safe_int(governance.get("default_max_runtime_seconds"), 600)))
    hard_runtime_seconds = _safe_int(governance.get("hard_max_runtime_seconds"), max_runtime_seconds)
    if hard_runtime_seconds > 0 and max_runtime_seconds > hard_runtime_seconds:
        raise HTTPException(
            status_code=422,
            detail=(
                f"max_runtime_seconds exceeds hard cap of {hard_runtime_seconds} "
                f"(got {max_runtime_seconds})"
            ),
        )

    max_memory_mb = max(0, _safe_int(memory_raw, _safe_int(governance.get("default_max_memory_mb"), 1024)))
    hard_memory_mb = _safe_int(governance.get("hard_max_memory_mb"), max_memory_mb)
    if hard_memory_mb > 0 and max_memory_mb > hard_memory_mb:
        raise HTTPException(
            status_code=422,
            detail=f"max_memory_mb exceeds hard cap of {hard_memory_mb} (got {max_memory_mb})",
        )

    max_cpu_seconds = max(0, _safe_int(cpu_raw, _safe_int(governance.get("default_max_cpu_seconds"), 300)))
    hard_cpu_seconds = _safe_int(governance.get("hard_max_cpu_seconds"), max_cpu_seconds)
    if hard_cpu_seconds > 0 and max_cpu_seconds > hard_cpu_seconds:
        raise HTTPException(
            status_code=422,
            detail=f"max_cpu_seconds exceeds hard cap of {hard_cpu_seconds} (got {max_cpu_seconds})",
        )

    max_cost_usd = max(0.0, _safe_float(cost_raw, _safe_float(governance.get("default_max_cost_usd"), 0.0)))
    hard_cost_usd = _safe_float(governance.get("hard_max_cost_usd"), 0.0)
    if hard_cost_usd > 0 and max_cost_usd > hard_cost_usd:
        raise HTTPException(
            status_code=422,
            detail=f"max_cost_usd exceeds hard cap of {hard_cost_usd:.6f} (got {max_cost_usd:.6f})",
        )

    requested_enforce_monthly = req.enforce_monthly_budget
    if requested_enforce_monthly is None and "enforce_monthly_budget" in task_data:
        requested_enforce_monthly = _coerce_bool(
            task_data.get("enforce_monthly_budget"),
            bool(governance.get("default_enforce_monthly_budget", True)),
        )

    if requested_enforce_monthly is None:
        enforce_monthly_budget = bool(governance.get("default_enforce_monthly_budget", True))
    else:
        enforce_monthly_budget = bool(requested_enforce_monthly)

    monthly_budget_reason = "accepted"
    if (
        not enforce_monthly_budget
        and not current_user.is_admin
        and not bool(governance.get("allow_budget_opt_out", False))
    ):
        enforce_monthly_budget = True
        monthly_budget_reason = "monthly_budget_opt_out_not_allowed"

    task_data["max_runtime_seconds"] = max_runtime_seconds
    task_data["max_memory_mb"] = max_memory_mb
    task_data["max_cpu_seconds"] = max_cpu_seconds
    task_data["max_cost_usd"] = round(max_cost_usd, 6)
    task_data["enforce_monthly_budget"] = bool(enforce_monthly_budget)

    policy = {
        "resource_limits": {
            "max_runtime_seconds": max_runtime_seconds,
            "max_memory_mb": max_memory_mb,
            "max_cpu_seconds": max_cpu_seconds,
        },
        "cost_protection": {
            "max_cost_usd": round(max_cost_usd, 6),
            "hard_max_cost_usd": round(hard_cost_usd, 6),
            "enforce_monthly_budget": bool(enforce_monthly_budget),
            "enforce_monthly_budget_reason": monthly_budget_reason,
        },
        "priority": priority_policy,
    }
    return task_data, effective_priority, policy


def _priority_queue_names(queue: UpstashRedisQueue) -> tuple[str, ...]:
    names: list[str] = []
    for raw_name in getattr(queue, "priority_queue_names", (getattr(queue, "queue_name", "job_queue"),)):
        name = str(raw_name).strip()
        if name and name not in names:
            names.append(name)

    if names:
        return tuple(names)
    return (str(getattr(queue, "queue_name", "job_queue")),)


def _queue_depth_snapshot(queue: UpstashRedisQueue, queue_names: tuple[str, ...]) -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for queue_name in queue_names:
        snapshot[queue_name] = _queue_depth_or_zero(queue, queue_name)
    return snapshot


def _enforce_queue_backpressure(
    queue: UpstashRedisQueue,
    *,
    priority: str,
    queue_name: str,
) -> None:
    max_depth_total = _env_int("AETHEER_QUEUE_MAX_DEPTH_TOTAL", 0, minimum=0)
    max_depth_high = _env_int("AETHEER_QUEUE_MAX_DEPTH_HIGH", 0, minimum=0)
    max_depth_normal = _env_int("AETHEER_QUEUE_MAX_DEPTH_NORMAL", 0, minimum=0)
    max_depth_low = _env_int("AETHEER_QUEUE_MAX_DEPTH_LOW", 0, minimum=0)
    if max_depth_total <= 0 and max_depth_high <= 0 and max_depth_normal <= 0 and max_depth_low <= 0:
        return

    allow_high_priority_bypass = _env_bool("AETHEER_QUEUE_OVERLOAD_ALLOW_HIGH_PRIORITY", default=True)
    bypass_for_priority = allow_high_priority_bypass and priority == "high"
    retry_after_seconds = _env_int("AETHEER_QUEUE_OVERLOAD_RETRY_AFTER_SECONDS", 5, minimum=1)

    queue_names = _priority_queue_names(queue)
    depth_snapshot = _queue_depth_snapshot(queue, queue_names)
    queue_depth_total = sum(depth_snapshot.values())
    priority_queue_depth = depth_snapshot.get(queue_name, _queue_depth_or_zero(queue, queue_name))
    max_depth_for_priority = {
        "high": max_depth_high,
        "normal": max_depth_normal,
        "low": max_depth_low,
    }.get(priority, max_depth_normal)

    if max_depth_total > 0 and queue_depth_total >= max_depth_total and not bypass_for_priority:
        raise HTTPException(
            status_code=429,
            detail=(
                "Queue is currently overloaded. "
                f"total_depth={queue_depth_total} limit={max_depth_total}; retry in {retry_after_seconds}s"
            ),
            headers={"Retry-After": str(retry_after_seconds)},
        )

    if max_depth_for_priority > 0 and priority_queue_depth >= max_depth_for_priority and not bypass_for_priority:
        raise HTTPException(
            status_code=429,
            detail=(
                "Priority queue is currently overloaded. "
                f"priority={priority} depth={priority_queue_depth} limit={max_depth_for_priority}; "
                f"retry in {retry_after_seconds}s"
            ),
            headers={"Retry-After": str(retry_after_seconds)},
        )


def _stable_job_id(owner_user_id: int, idempotency_key: str) -> str:
    token = str(idempotency_key or "").strip()
    seed = f"queue-job:{int(owner_user_id)}:{token}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


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
        max_length=120,
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
        le=25,
        description="Optional retry budget for worker retry/dead-letter flow.",
    )
    max_runtime_seconds: int | None = Field(
        default=None,
        ge=5,
        le=7_200,
        description="Optional hard runtime cap per job attempt enforced by worker sandbox.",
    )
    max_memory_mb: int | None = Field(
        default=None,
        ge=0,
        le=262_144,
        description="Optional per-job memory cap in MB (0 disables memory cap).",
    )
    max_cpu_seconds: int | None = Field(
        default=None,
        ge=0,
        le=86_400,
        description="Optional per-job CPU time cap in seconds (0 disables CPU cap).",
    )
    max_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        le=10_000.0,
        description="Optional per-job budget limit in USD.",
    )
    enforce_monthly_budget: bool | None = Field(
        default=None,
        description="Optional override for monthly budget enforcement (subject to policy).",
    )
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="Optional dedupe token. Reusing the same key returns the same job for the same user.",
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
                "max_runtime_seconds": 900,
                "max_memory_mb": 1024,
                "max_cpu_seconds": 300,
                "max_cost_usd": 10.0,
                "enforce_monthly_budget": True,
                "idempotency_key": "req_20260318_launch_plan_001",
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


class QueueMetricsResponse(BaseModel):
    generated_at: str
    queue_depth_total: int
    queue_depth_by_name: dict[str, int]
    dlq_queue: str
    dlq_depth: int
    status_counts: dict[str, int]
    stale_running: int
    running_timeout_seconds: int
    latency_sample_size: int
    avg_queue_wait_ms: float
    p95_queue_wait_ms: float
    avg_execution_ms: float
    p95_execution_ms: float
    governance_limits: dict[str, Any]


class QueueDeadLetterRow(BaseModel):
    job_id: str
    task_type: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    retry_count: int
    max_retries: int
    dead_letter_reason: str | None = None
    dead_lettered_at: str | None = None
    owner_user_id: int | None = None
    owner_username: str | None = None
    error: str | None = None


class QueueDeadLetterResponse(BaseModel):
    generated_at: str
    total: int
    jobs: list[QueueDeadLetterRow]


def _escape_metric_label(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def collect_queue_metrics_snapshot() -> QueueMetricsResponse:
    queue = _get_queue_client()
    store = _get_job_store()
    queue_names = tuple(
        str(name)
        for name in getattr(queue, "priority_queue_names", (getattr(queue, "queue_name", "job_queue"),))
        if str(name).strip()
    )
    if not queue_names:
        queue_names = (str(getattr(queue, "queue_name", "job_queue")),)

    queue_depth_by_name: dict[str, int] = {}
    for name in queue_names:
        try:
            queue_depth_by_name[name] = int(queue.queue_depth(queue_name=name))
        except Exception as exc:
            logger.warning("Queue depth read failed for %s: %s", name, exc)
            queue_depth_by_name[name] = 0

    dlq_queue_name = (os.getenv("UPSTASH_REDIS_DLQ_NAME") or "job_queue_dlq").strip() or "job_queue_dlq"
    try:
        dlq_depth = int(queue.queue_depth(queue_name=dlq_queue_name))
    except Exception as exc:
        logger.warning("DLQ depth read failed for %s: %s", dlq_queue_name, exc)
        dlq_depth = 0

    status_counts_fn = getattr(store, "status_counts", None)
    if callable(status_counts_fn):
        try:
            status_counts = status_counts_fn()
        except Exception as exc:
            logger.warning("Status count query failed: %s", exc)
            status_counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
    else:
        status_counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}

    running_timeout_seconds = _env_int("AETHEER_JOB_RUNNING_TIMEOUT_SECONDS", 1800, minimum=30)
    stale_probe_limit = _env_int("AETHEER_STALE_SCAN_BATCH_SIZE", 50, minimum=1)
    try:
        stale_running = len(
            store.list_stale_running_jobs(
                timeout_seconds=running_timeout_seconds,
                limit=stale_probe_limit,
            )
        )
    except Exception as exc:
        logger.warning("Stale-running probe failed: %s", exc)
        stale_running = 0

    latency_metrics_fn = getattr(store, "latency_metrics", None)
    if callable(latency_metrics_fn):
        try:
            latency_metrics = latency_metrics_fn(
                sample_limit=_env_int("AETHEER_QUEUE_METRICS_SAMPLE_LIMIT", 500, minimum=10)
            )
        except Exception as exc:
            logger.warning("Latency metrics query failed: %s", exc)
            latency_metrics = {}
    else:
        latency_metrics = {}

    return QueueMetricsResponse(
        generated_at=_utc_now_iso(),
        queue_depth_total=sum(queue_depth_by_name.values()),
        queue_depth_by_name=queue_depth_by_name,
        dlq_queue=dlq_queue_name,
        dlq_depth=dlq_depth,
        status_counts=status_counts,
        stale_running=stale_running,
        running_timeout_seconds=running_timeout_seconds,
        latency_sample_size=int(latency_metrics.get("sample_size", 0) or 0),
        avg_queue_wait_ms=float(latency_metrics.get("avg_queue_wait_ms", 0.0) or 0.0),
        p95_queue_wait_ms=float(latency_metrics.get("p95_queue_wait_ms", 0.0) or 0.0),
        avg_execution_ms=float(latency_metrics.get("avg_execution_ms", 0.0) or 0.0),
        p95_execution_ms=float(latency_metrics.get("p95_execution_ms", 0.0) or 0.0),
        governance_limits=_governance_limits_snapshot(),
    )


def queue_metrics_prometheus_text(instance_id: str) -> str:
    escaped_instance = _escape_metric_label(instance_id)
    lines = [
        "# HELP aetheer_queue_metrics_scrape_success Whether queue metrics were collected successfully.",
        "# TYPE aetheer_queue_metrics_scrape_success gauge",
    ]

    try:
        metrics = collect_queue_metrics_snapshot()
    except Exception as exc:
        logger.warning("Queue metrics Prometheus export failed: %s", exc, exc_info=True)
        lines.append(f'aetheer_queue_metrics_scrape_success{{instance="{escaped_instance}"}} 0')
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            f'aetheer_queue_metrics_scrape_success{{instance="{escaped_instance}"}} 1',
            "# HELP aetheer_queue_depth_total Total active queue depth across all priority lanes.",
            "# TYPE aetheer_queue_depth_total gauge",
            f'aetheer_queue_depth_total{{instance="{escaped_instance}"}} {metrics.queue_depth_total}',
            "# HELP aetheer_queue_depth Queue depth by queue lane.",
            "# TYPE aetheer_queue_depth gauge",
        ]
    )
    for queue_name, depth in sorted(metrics.queue_depth_by_name.items()):
        escaped_queue = _escape_metric_label(queue_name)
        lines.append(
            f'aetheer_queue_depth{{instance="{escaped_instance}",queue="{escaped_queue}"}} {int(depth)}'
        )

    escaped_dlq = _escape_metric_label(metrics.dlq_queue)
    lines.extend(
        [
            "# HELP aetheer_queue_dlq_depth Dead-letter queue depth.",
            "# TYPE aetheer_queue_dlq_depth gauge",
            f'aetheer_queue_dlq_depth{{instance="{escaped_instance}",queue="{escaped_dlq}"}} {int(metrics.dlq_depth)}',
            "# HELP aetheer_queue_jobs_status_total Job counts by status in the persistent store.",
            "# TYPE aetheer_queue_jobs_status_total gauge",
        ]
    )
    for status, count in sorted(metrics.status_counts.items()):
        escaped_status = _escape_metric_label(status)
        lines.append(
            f'aetheer_queue_jobs_status_total{{instance="{escaped_instance}",status="{escaped_status}"}} {int(count)}'
        )

    lines.extend(
        [
            "# HELP aetheer_queue_stale_running Number of running jobs exceeding timeout thresholds.",
            "# TYPE aetheer_queue_stale_running gauge",
            f'aetheer_queue_stale_running{{instance="{escaped_instance}"}} {int(metrics.stale_running)}',
            "# HELP aetheer_queue_latency_sample_size Sample size used for queue latency calculations.",
            "# TYPE aetheer_queue_latency_sample_size gauge",
            f'aetheer_queue_latency_sample_size{{instance="{escaped_instance}"}} {int(metrics.latency_sample_size)}',
            "# HELP aetheer_queue_wait_ms_avg Average queue wait time in milliseconds.",
            "# TYPE aetheer_queue_wait_ms_avg gauge",
            f'aetheer_queue_wait_ms_avg{{instance="{escaped_instance}"}} {float(metrics.avg_queue_wait_ms)}',
            "# HELP aetheer_queue_wait_ms_p95 95th percentile queue wait time in milliseconds.",
            "# TYPE aetheer_queue_wait_ms_p95 gauge",
            f'aetheer_queue_wait_ms_p95{{instance="{escaped_instance}"}} {float(metrics.p95_queue_wait_ms)}',
            "# HELP aetheer_queue_execution_ms_avg Average worker execution time in milliseconds.",
            "# TYPE aetheer_queue_execution_ms_avg gauge",
            f'aetheer_queue_execution_ms_avg{{instance="{escaped_instance}"}} {float(metrics.avg_execution_ms)}',
            "# HELP aetheer_queue_execution_ms_p95 95th percentile worker execution time in milliseconds.",
            "# TYPE aetheer_queue_execution_ms_p95 gauge",
            f'aetheer_queue_execution_ms_p95{{instance="{escaped_instance}"}} {float(metrics.p95_execution_ms)}',
        ]
    )

    return "\n".join(lines) + "\n"


def _enqueue_single_job(
    req: QueueJobRequest,
    *,
    current_user: User,
    db: Session,
    apply_rate_limit: bool,
    tenant_id: str,
    source_ip: str | None,
) -> dict[str, Any]:
    _enforce_payload_size_limits(req)

    resolved_tenant_id = str(tenant_id or _tenant_id_for_user(current_user)).strip().lower()

    if apply_rate_limit:
        enforce_job_api_rate_limit(
            current_user,
            bucket="write",
            tenant_id=resolved_tenant_id,
            source_ip=source_ip,
        )

    enforce_job_create_quota(db, current_user)

    store = _get_job_store()
    queue = _get_queue_client()
    task_data, priority, governance_policy = _resolve_job_governance(
        req,
        current_user=current_user,
        queue=queue,
    )
    queue_name = _queue_name_for_priority(queue, priority)
    governance_policy["priority"]["queue_name"] = queue_name

    idempotency_key = str(req.idempotency_key or "").strip()
    if not idempotency_key:
        enforce_job_submission_abuse_controls(
            current_user,
            fingerprint=_queue_job_fingerprint(req, priority=priority),
            tenant_id=resolved_tenant_id,
            source_ip=source_ip,
        )

    if idempotency_key:
        job_id = _stable_job_id(int(current_user.id), idempotency_key)
    else:
        job_id = str(uuid.uuid4())

    resolved_max_retries = req.max_retries
    if resolved_max_retries is None:
        resolved_max_retries = _env_int("AETHEER_JOB_MAX_RETRIES", 3, minimum=0)

    if idempotency_key:
        try:
            existing = store.get_job(job_id)
        except Exception as exc:
            logger.warning("Failed idempotency lookup for %s: %s", job_id, exc)
            existing = None

        if isinstance(existing, dict):
            return {
                "job_id": job_id,
                "status": str(existing.get("status") or "queued"),
                "queue": queue_name,
                "queue_depth": _queue_depth_or_zero(queue, queue_name),
                "priority": priority,
                "deduplicated": True,
            }

    _enforce_queue_backpressure(
        queue,
        priority=priority,
        queue_name=queue_name,
    )

    metadata = dict(req.metadata)
    metadata["owner_user_id"] = current_user.id
    metadata["owner_username"] = current_user.username
    metadata["owner_tenant_id"] = resolved_tenant_id
    metadata["priority"] = priority
    metadata["requested_priority"] = _normalize_priority(req.priority)
    metadata["retry_count"] = 0
    metadata["max_retries"] = int(resolved_max_retries)
    metadata["max_runtime_seconds"] = max(1, _safe_int(task_data.get("max_runtime_seconds"), 0))
    metadata["max_memory_mb"] = max(0, _safe_int(task_data.get("max_memory_mb"), 0))
    metadata["max_cpu_seconds"] = max(0, _safe_int(task_data.get("max_cpu_seconds"), 0))
    metadata["max_cost_usd"] = round(max(0.0, _safe_float(task_data.get("max_cost_usd"), 0.0)), 6)
    metadata["enforce_monthly_budget"] = bool(task_data.get("enforce_monthly_budget", True))
    metadata["governance"] = governance_policy
    metadata["stream_results"] = bool(req.stream_results)
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key
    if metadata["stream_results"]:
        _append_queued_event(metadata, queue_name=queue_name, priority=priority)

    _enforce_payload_size_limits_for_values(task_data, metadata)

    try:
        store.create_job(
            job_id=job_id,
            task_type=req.task_type,
            task_payload=task_data,
            metadata=metadata,
        )
    except Exception as exc:
        if idempotency_key:
            try:
                existing = store.get_job(job_id)
            except Exception:
                existing = None
            if isinstance(existing, dict):
                return {
                    "job_id": job_id,
                    "status": str(existing.get("status") or "queued"),
                    "queue": queue_name,
                    "queue_depth": _queue_depth_or_zero(queue, queue_name),
                    "priority": priority,
                    "deduplicated": True,
                }

        logger.error("Failed to create Supabase job row %s: %s", job_id, exc)
        raise HTTPException(status_code=502, detail="Failed to persist job in Supabase") from exc

    try:
        payload = build_queue_payload(
            job_id,
            req.task_type,
            task_data,
            priority=priority,
            retry_count=0,
            max_retries=int(resolved_max_retries),
        )
    except TypeError:
        payload = build_queue_payload(job_id, req.task_type, task_data)

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
        "deduplicated": False,
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
    request: Request = None,
):
    """
    Vercel-safe entrypoint:
      1) Insert job row in Supabase.
      2) Push payload to Upstash Redis list `job_queue`.
      3) Return job_id immediately.
    """
    tenant_id = _tenant_id_for_user(current_user)
    source_ip = _request_ip(request)

    try:
        data = _enqueue_single_job(
            req,
            current_user=current_user,
            db=db,
            apply_rate_limit=True,
            tenant_id=tenant_id,
            source_ip=source_ip,
        )
    except HTTPException as exc:
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_job_create_rejected",
            detail={
                "task_type": req.task_type,
                "reason": str(exc.detail),
                "status_code": int(exc.status_code),
                "tenant_id": tenant_id,
            },
            source_ip=source_ip,
        )
        raise

    _audit_queue_activity(
        db,
        current_user=current_user,
        action="queue_job_created",
        detail={
            "job_id": data.get("job_id"),
            "priority": data.get("priority"),
            "deduplicated": bool(data.get("deduplicated")),
            "tenant_id": tenant_id,
        },
        source_ip=source_ip,
    )
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

    max_batch_jobs = _env_int("JOB_API_MAX_BATCH_JOBS", 20, minimum=1)
    if len(req.jobs) > max_batch_jobs:
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_job_batch_rejected",
            detail={
                "reason": "batch_limit_exceeded",
                "submitted": len(req.jobs),
                "max_batch_jobs": max_batch_jobs,
                "tenant_id": tenant_id,
            },
            source_ip=source_ip,
        )
        raise HTTPException(status_code=413, detail=f"Batch exceeds max size {max_batch_jobs}")

    jobs: list[dict[str, Any]] = []
    for item in req.jobs:
        jobs.append(
            _enqueue_single_job(
                item,
                current_user=current_user,
                db=db,
                apply_rate_limit=False,
                tenant_id=tenant_id,
                source_ip=source_ip,
            )
        )

    _audit_queue_activity(
        db,
        current_user=current_user,
        action="queue_job_batch_created",
        detail={
            "submitted": len(jobs),
            "job_ids": [str(item.get("job_id")) for item in jobs],
            "tenant_id": tenant_id,
        },
        source_ip=source_ip,
    )

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
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Status polling endpoint for clients to track queued/running/completed/failed jobs."""
    tenant_id = _tenant_id_for_user(current_user)
    source_ip = _request_ip(request)
    enforce_job_api_rate_limit(
        current_user,
        bucket="read",
        tenant_id=tenant_id,
        source_ip=source_ip,
    )

    row = _get_job_store().get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if not _row_visible_to_user(row, current_user):
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_job_status_denied",
            detail={"job_id": job_id, "tenant_id": tenant_id},
            source_ip=source_ip,
        )
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

    if _env_bool("JOB_API_AUDIT_READS", default=True):
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_job_status_read",
            detail={
                "job_id": response_payload.job_id,
                "status": response_payload.status,
                "tenant_id": tenant_id,
            },
            source_ip=source_ip,
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

    row = _get_job_store().get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if not _row_visible_to_user(row, current_user):
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_job_events_denied",
            detail={"job_id": job_id, "tenant_id": tenant_id},
            source_ip=source_ip,
        )
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    events = metadata.get("stream_events") if isinstance(metadata.get("stream_events"), list) else []
    event_rows = [evt for evt in events if isinstance(evt, dict)]

    safe_limit = max(1, min(int(limit), 500))
    clipped = event_rows[-safe_limit:]
    response_payload = QueueJobEventsResponse(
        job_id=str(row.get("id") or row.get("job_id") or job_id),
        total_events=len(event_rows),
        events=clipped,
    )

    if _env_bool("JOB_API_AUDIT_READS", default=True):
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_job_events_read",
            detail={
                "job_id": response_payload.job_id,
                "returned": len(clipped),
                "total_events": response_payload.total_events,
                "tenant_id": tenant_id,
            },
            source_ip=source_ip,
        )

    return response_payload


@router.get(
    "/api/queue/metrics",
    summary="Queue operational metrics",
    response_model=QueueMetricsResponse,
)
def get_queue_metrics(
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
    if not current_user.is_admin:
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_metrics_denied",
            detail={"tenant_id": tenant_id},
            source_ip=source_ip,
        )
        raise HTTPException(status_code=403, detail="Admin access required")

    response_payload = collect_queue_metrics_snapshot()
    _audit_queue_activity(
        db,
        current_user=current_user,
        action="queue_metrics_read",
        detail={
            "queue_depth_total": response_payload.queue_depth_total,
            "dlq_depth": response_payload.dlq_depth,
        },
        source_ip=source_ip,
    )
    return response_payload


@router.get(
    "/api/queue/dlq/jobs",
    summary="List dead-lettered queue jobs",
    response_model=QueueDeadLetterResponse,
)
def list_dead_letter_queue_jobs(
    limit: int = 100,
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
    if not current_user.is_admin:
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_dlq_denied",
            detail={"tenant_id": tenant_id},
            source_ip=source_ip,
        )
        raise HTTPException(status_code=403, detail="Admin access required")

    safe_limit = max(1, min(int(limit), 500))
    store = _get_job_store()

    list_dlq_fn = getattr(store, "list_dead_lettered_jobs", None)
    if callable(list_dlq_fn):
        rows = list_dlq_fn(limit=safe_limit, scan_limit=max(200, safe_limit * 5))
    else:
        rows = []

    jobs: list[QueueDeadLetterRow] = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        owner_user_id: int | None
        try:
            owner_user_id = int(metadata.get("owner_user_id")) if metadata.get("owner_user_id") is not None else None
        except (TypeError, ValueError):
            owner_user_id = None

        jobs.append(
            QueueDeadLetterRow(
                job_id=str(row.get("id") or row.get("job_id") or ""),
                task_type=row.get("task_type"),
                created_at=row.get("created_at"),
                completed_at=row.get("completed_at"),
                retry_count=max(0, _safe_int(metadata.get("retry_count"), 0)),
                max_retries=max(0, _safe_int(metadata.get("max_retries"), 0)),
                dead_letter_reason=str(metadata.get("dead_letter_reason") or "") or None,
                dead_lettered_at=metadata.get("dead_lettered_at"),
                owner_user_id=owner_user_id,
                owner_username=str(metadata.get("owner_username") or "") or None,
                error=str(row.get("error") or "") or None,
            )
        )

    response_payload = QueueDeadLetterResponse(
        generated_at=_utc_now_iso(),
        total=len(jobs),
        jobs=jobs,
    )

    _audit_queue_activity(
        db,
        current_user=current_user,
        action="queue_dlq_read",
        detail={"returned": response_payload.total},
        source_ip=source_ip,
    )
    return response_payload


@router.delete(
    "/api/queue/jobs/cleanup",
    summary="Cleanup old completed/failed queue jobs",
)
def cleanup_old_queue_jobs(
    retention_hours: int = 24 * 7,
    limit: int = 500,
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

    if not current_user.is_admin:
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_cleanup_denied",
            detail={"tenant_id": tenant_id},
            source_ip=source_ip,
        )
        raise HTTPException(status_code=403, detail="Admin access required")

    store = _get_job_store()
    cleanup_fn = getattr(store, "cleanup_old_jobs", None)
    if not callable(cleanup_fn):
        response_payload = {"success": True, "data": {"deleted": 0, "retention_hours": retention_hours}}
        _audit_queue_activity(
            db,
            current_user=current_user,
            action="queue_cleanup",
            detail={"deleted": 0, "retention_hours": retention_hours, "limit": limit},
            source_ip=source_ip,
        )
        return response_payload

    deleted = cleanup_fn(retention_hours=max(1, int(retention_hours)), limit=max(1, int(limit)))
    response_payload = {
        "success": True,
        "data": {
            "deleted": int(deleted),
            "retention_hours": max(1, int(retention_hours)),
            "limit": max(1, int(limit)),
        },
    }

    _audit_queue_activity(
        db,
        current_user=current_user,
        action="queue_cleanup",
        detail={
            "deleted": int(deleted),
            "retention_hours": max(1, int(retention_hours)),
            "limit": max(1, int(limit)),
        },
        source_ip=source_ip,
    )
    return response_payload
