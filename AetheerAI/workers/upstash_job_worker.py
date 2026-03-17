"""Persistent worker that consumes Upstash Redis jobs and updates Supabase status."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import datetime
import logging
import os
import random
import socket
import signal
import sys
import threading
import time
from typing import Any, Callable
import uuid

# Ensure project-local imports resolve when executed as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.ceo_agent import CEOAgent, ProjectResult
from api.async_jobs import SupabaseJobStore, build_queue_payload
from core.aetheerai_kernel import AetheerAiKernel
from core.env_loader import load_env
from integrations.upstash_redis_queue import UpstashRedisQueue
from utils.log_config import setup_logging

logger = logging.getLogger("aetheer.worker.upstash")


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _supported_shutdown_signals() -> tuple[int, ...]:
    values: list[int] = []
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        candidate = getattr(signal, name, None)
        if candidate is not None:
            values.append(int(candidate))
    return tuple(values)


def _signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except Exception:
        return str(signum)


def _interrupt_message(reason: str) -> str:
    detail = (reason or "shutdown").strip()
    return f"Worker interrupted before job completion ({detail}). Please retry this job."


def _mark_interrupted_job(store: SupabaseJobStore, job_id: str, reason: str) -> None:
    try:
        store.mark_failed(job_id, _interrupt_message(reason))
    except Exception as exc:
        logger.error("Could not persist interrupted status for %s: %s", job_id, exc, exc_info=True)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _coerce_int(value: Any, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _is_retryable_external_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True

    text = f"{type(exc).__name__}: {exc}".lower()
    retryable_hints = (
        "timeout",
        "timed out",
        "rate limit",
        "too many requests",
        "temporarily unavailable",
        "service unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "remote disconnected",
        "gateway timeout",
        "bad gateway",
        "429",
        "502",
        "503",
        "504",
    )
    return any(hint in text for hint in retryable_hints)


def _compute_backoff_seconds(attempt: int, *, base_seconds: float, max_seconds: float) -> float:
    capped_attempt = max(1, int(attempt))
    exp_delay = float(base_seconds) * (2 ** (capped_attempt - 1))
    jitter = random.uniform(0.0, float(base_seconds))
    return max(0.0, min(float(max_seconds), exp_delay + jitter))


def _append_stream_event_if_enabled(
    *,
    store: SupabaseJobStore,
    job_id: str,
    enabled: bool,
    event_type: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    if not enabled:
        return

    append_event = getattr(store, "append_stream_event", None)
    if not callable(append_event):
        return

    try:
        append_event(job_id, event_type=event_type, status=status, payload=payload)
    except Exception:
        logger.debug("Unable to append stream event %s for %s", event_type, job_id, exc_info=True)


def _blocking_pop_many_with_priority(
    queue: UpstashRedisQueue,
    *,
    timeout_seconds: int,
    batch_size: int,
    queue_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    pop_many = getattr(queue, "blocking_pop_many", None)
    if callable(pop_many):
        try:
            payloads = pop_many(
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                queue_names=queue_names,
            )
        except TypeError:
            payloads = pop_many(
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
            )

        return [payload for payload in payloads if isinstance(payload, dict)]

    try:
        payload = queue.blocking_pop(timeout_seconds=timeout_seconds, queue_names=queue_names)
    except TypeError:
        payload = queue.blocking_pop(timeout_seconds=timeout_seconds)

    if payload is None:
        return []
    return [payload] if isinstance(payload, dict) else []


def _queue_depth_snapshot(
    queue: UpstashRedisQueue,
    *,
    queue_names: tuple[str, ...],
    dlq_queue_name: str,
) -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for queue_name in queue_names:
        try:
            snapshot[queue_name] = int(queue.queue_depth(queue_name=queue_name))
        except Exception:
            logger.debug("Queue depth probe failed for %s", queue_name, exc_info=True)

    if dlq_queue_name and dlq_queue_name not in snapshot:
        try:
            snapshot[dlq_queue_name] = int(queue.queue_depth(queue_name=dlq_queue_name))
        except Exception:
            logger.debug("DLQ depth probe failed for %s", dlq_queue_name, exc_info=True)

    return snapshot


def _extract_retry_state(
    *,
    job_row: dict[str, Any] | None,
    queue_payload: dict[str, Any] | None,
    default_max_retries: int,
) -> tuple[int, int]:
    payload = queue_payload if isinstance(queue_payload, dict) else {}
    metadata = job_row.get("metadata") if isinstance(job_row, dict) and isinstance(job_row.get("metadata"), dict) else {}

    payload_retry = payload.get("retryCount")
    row_retry = metadata.get("retry_count")
    retry_count = _coerce_int(payload_retry if payload_retry is not None else row_retry, 0, minimum=0)

    payload_max = payload.get("maxRetries")
    row_max = metadata.get("max_retries")
    max_retries = _coerce_int(payload_max if payload_max is not None else row_max, default_max_retries, minimum=0)
    return retry_count, max_retries


def _extract_priority_and_stream(
    *,
    job_row: dict[str, Any] | None,
    queue_payload: dict[str, Any] | None,
) -> tuple[str, bool]:
    payload = queue_payload if isinstance(queue_payload, dict) else {}
    metadata = job_row.get("metadata") if isinstance(job_row, dict) and isinstance(job_row.get("metadata"), dict) else {}

    payload_priority = payload.get("priority")
    row_priority = metadata.get("priority")
    priority = UpstashRedisQueue.normalize_priority(payload_priority if payload_priority is not None else row_priority)
    stream_results = bool(metadata.get("stream_results", False))
    return priority, stream_results


def _requeue_or_dead_letter(
    *,
    queue: UpstashRedisQueue,
    store: SupabaseJobStore,
    job_id: str,
    task_type: str,
    task_data: dict[str, Any],
    retry_count: int,
    max_retries: int,
    error_message: str,
    reason: str,
    priority: str,
    retry_backoff_base_seconds: float,
    retry_backoff_max_seconds: float,
    dlq_queue_name: str,
) -> str:
    next_retry_count = retry_count + 1
    normalized_error = str(error_message or "Unknown worker error")

    if next_retry_count <= max_retries:
        backoff_seconds = _compute_backoff_seconds(
            next_retry_count,
            base_seconds=retry_backoff_base_seconds,
            max_seconds=retry_backoff_max_seconds,
        )
        retry_payload = build_queue_payload(job_id, task_type, task_data)
        retry_payload["priority"] = UpstashRedisQueue.normalize_priority(priority)
        retry_payload["retryCount"] = next_retry_count
        retry_payload["maxRetries"] = max_retries
        retry_payload["retryReason"] = reason
        retry_payload["lastError"] = normalized_error
        retry_payload["retryAt"] = _utc_now_iso()
        retry_payload["retryBackoffSeconds"] = round(backoff_seconds, 3)

        try:
            if backoff_seconds > 0:
                time.sleep(backoff_seconds)

            queue.push_job(retry_payload, priority=priority)
            store.mark_requeued_for_retry(
                job_id,
                error_message=normalized_error,
                retry_count=next_retry_count,
                max_retries=max_retries,
                reason=reason,
            )
            logger.warning(
                "Job %s requeued (retry %s/%s, reason=%s)",
                job_id,
                next_retry_count,
                max_retries,
                reason,
            )
            return "requeued"
        except Exception as exc:
            logger.error("Retry enqueue failed for %s: %s", job_id, exc, exc_info=True)
            try:
                store.mark_failed(job_id, f"Retry enqueue failed: {exc} | original: {normalized_error}")
            except Exception as update_exc:
                logger.error("Could not persist failed status for %s: %s", job_id, update_exc, exc_info=True)
            return "failed"

    dlq_payload = build_queue_payload(job_id, task_type, task_data)
    dlq_payload["priority"] = UpstashRedisQueue.normalize_priority(priority)
    dlq_payload["retryCount"] = retry_count
    dlq_payload["maxRetries"] = max_retries
    dlq_payload["deadLetterReason"] = reason
    dlq_payload["deadLetteredAt"] = _utc_now_iso()
    dlq_payload["lastError"] = normalized_error

    dlq_pushed = False
    try:
        queue.push_job(dlq_payload, queue_name=dlq_queue_name)
        dlq_pushed = True
    except Exception as dlq_exc:
        logger.error("DLQ publish failed for %s: %s", job_id, dlq_exc, exc_info=True)
        normalized_error = f"{normalized_error} | DLQ publish failed: {dlq_exc}"

    try:
        store.mark_dead_lettered(
            job_id,
            error_message=normalized_error,
            retry_count=retry_count,
            max_retries=max_retries,
            reason=reason,
            dlq_queue=dlq_queue_name,
        )
    except Exception as update_exc:
        logger.error("Could not persist dead-lettered status for %s: %s", job_id, update_exc, exc_info=True)
        try:
            store.mark_failed(job_id, normalized_error)
        except Exception:
            logger.error("Could not persist fallback failed status for %s", job_id, exc_info=True)

    if dlq_pushed:
        logger.error("Job %s exhausted retries and moved to DLQ '%s'", job_id, dlq_queue_name)
        return "dead-lettered"

    logger.error("Job %s exhausted retries but DLQ publish failed", job_id)
    return "failed"


def _recover_stale_running_jobs(
    *,
    queue: UpstashRedisQueue,
    store: SupabaseJobStore,
    max_retries: int,
    running_timeout_seconds: int,
    stale_scan_batch_size: int,
    dlq_queue_name: str,
) -> int:
    try:
        stale_rows = store.list_stale_running_jobs(
            timeout_seconds=running_timeout_seconds,
            limit=stale_scan_batch_size,
        )
    except Exception as exc:
        logger.error("Stale-running scan failed: %s", exc, exc_info=True)
        return 0

    recovered = 0
    for row in stale_rows:
        job_id = str(row.get("id") or "").strip()
        task_type = str(row.get("task_type") or "goal")
        task_data = row.get("task_payload")

        if not job_id or not isinstance(task_data, dict):
            logger.error("Skipping stale row with invalid payload: %s", row)
            continue

        retry_count, max_retries_for_job = _extract_retry_state(
            job_row=row,
            queue_payload=None,
            default_max_retries=max_retries,
        )
        priority, _ = _extract_priority_and_stream(job_row=row, queue_payload=None)
        started_at = str(row.get("started_at") or "unknown")
        timeout_error = (
            f"Job exceeded running timeout ({running_timeout_seconds}s). "
            f"Last started_at={started_at}."
        )

        _requeue_or_dead_letter(
            queue=queue,
            store=store,
            job_id=job_id,
            task_type=task_type,
            task_data=task_data,
            retry_count=retry_count,
            max_retries=max_retries_for_job,
            error_message=timeout_error,
            reason="running_timeout",
            priority=priority,
            retry_backoff_base_seconds=0.0,
            retry_backoff_max_seconds=0.0,
            dlq_queue_name=dlq_queue_name,
        )
        recovered += 1

    if recovered:
        logger.warning("Recovered %s stale running jobs", recovered)
    return recovered


def _resolve_ai_runtime() -> tuple[str, str]:
    provider = (
        (os.getenv("AETHEERAI_DEFAULT_PROVIDER") or "").strip().lower()
        or (os.getenv("AI_PROVIDER") or "").strip().lower()
        or "openai"
    )
    model = (
        (os.getenv("AETHEERAI_DEFAULT_MODEL") or "").strip()
        or (os.getenv("AI_MODEL") or "").strip()
        or "gpt-4o"
    )
    return provider, model


def _serialize_project_result(result: ProjectResult) -> dict[str, Any]:
    total = max(1, result.total_tasks)
    return {
        "workflow_id": result.workflow_id,
        "goal": result.goal,
        "status": result.status,
        "plan_summary": result.final_summary,
        "spent_usd": result.spent_usd,
        "progress": {
            "completed": result.completed_tasks,
            "failed": result.failed_tasks,
            "total": result.total_tasks,
            "percent": round((result.completed_tasks / total) * 100.0, 2),
        },
        "tasks": [
            {
                "task_id": t.task_id,
                "index": t.index,
                "title": t.title,
                "description": t.description,
                "agent_type": t.agent_type,
                "role_description": t.role_description,
                "priority": t.priority,
                "depends_on": t.depends_on,
                "require_approval": t.require_approval,
                "status": t.status,
                "result": t.result,
                "error": t.error,
                "attempts": t.attempts,
            }
            for t in result.tasks
        ],
        "elapsed_seconds": result.elapsed_seconds,
        "replanned": result.replanned,
        "events": result.events,
    }


class AIJobRunner:
    """Execute task payloads consumed from the queue."""

    def __init__(self) -> None:
        self._kernel: AetheerAiKernel | None = None
        self._ceo: CEOAgent | None = None

    def _kernel_instance(self) -> AetheerAiKernel:
        if self._kernel is None:
            provider, model = _resolve_ai_runtime()
            self._kernel = AetheerAiKernel(ai_provider=provider, model=model)
            logger.info("Worker kernel booted (provider=%s model=%s)", provider, model)
        return self._kernel

    def _ceo_instance(self) -> CEOAgent:
        if self._ceo is None:
            kernel = self._kernel_instance()
            self._ceo = CEOAgent(
                kernel,
                max_tasks=_env_int("MAX_TASKS_PER_PROJECT", 50, minimum=1),
                max_cost_usd=_env_float("MAX_COST_USD", 10.0, minimum=0.0),
                max_runtime_seconds=_env_int("MAX_RUNTIME_SECONDS", 600, minimum=10),
                max_retries=_env_int("MAX_RETRIES", 3, minimum=0),
            )
        return self._ceo

    def execute(self, *, task_type: str, task_data: dict[str, Any]) -> Any:
        normalized = (task_type or "").strip().lower()
        if not normalized:
            normalized = "goal"

        if normalized == "goal":
            return self._execute_goal(task_data)
        if normalized == "agent_task":
            return self._execute_agent_task(task_data)
        if normalized == "chat":
            return self._execute_chat(task_data)

        raise ValueError(f"Unsupported task_type '{task_type}'.")

    def _execute_goal(self, task_data: dict[str, Any]) -> dict[str, Any]:
        goal = str(task_data.get("goal") or "").strip()
        if not goal:
            raise ValueError("goal task requires task_data.goal")

        context = task_data.get("context") if isinstance(task_data.get("context"), dict) else {}
        parallel = bool(task_data.get("parallel", True))
        collaboration_mode = bool(task_data.get("collaboration_mode", False))
        offline_local_mode = bool(task_data.get("offline_local_mode", False))
        fast_mode_collaboration = bool(task_data.get("fast_mode_collaboration", False))

        result = self._ceo_instance().run(
            goal,
            context=context,
            parallel=parallel,
            collaboration_mode=collaboration_mode,
            offline_local_mode=offline_local_mode,
            fast_mode_collaboration=fast_mode_collaboration,
        )
        return _serialize_project_result(result)

    def _execute_agent_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        agent_name = str(task_data.get("agent_name") or "").strip()
        task = str(task_data.get("task") or "").strip()
        if not agent_name or not task:
            raise ValueError("agent_task requires task_data.agent_name and task_data.task")

        result = self._kernel_instance().run_agent(agent_name, task)
        return {
            "agent_name": agent_name,
            "task": task,
            "result": result,
        }

    def _execute_chat(self, task_data: dict[str, Any]) -> dict[str, Any]:
        message = str(task_data.get("message") or "").strip()
        if not message:
            raise ValueError("chat task requires task_data.message")

        history = task_data.get("history") if isinstance(task_data.get("history"), list) else []
        reply = self._kernel_instance().chat(message=message, history=history)
        return {
            "message": message,
            "reply": reply,
        }


def _process_job_payload(
    *,
    payload: dict[str, Any],
    queue: UpstashRedisQueue,
    store: SupabaseJobStore,
    run_job: Callable[[str, dict[str, Any]], Any],
    worker_id: str,
    claim_lease_seconds: int,
    max_retries: int,
    retry_backoff_base_seconds: float,
    retry_backoff_max_seconds: float,
    dlq_queue_name: str,
) -> bool:
    job_id = str(payload.get("jobId") or "").strip()
    task_type = str(payload.get("taskType") or "goal")
    task_data = payload.get("task")

    if not job_id or not isinstance(task_data, dict):
        logger.error("Invalid queue payload discarded: %s", payload)
        return False

    row: dict[str, Any] | None = None
    try:
        row = store.get_job(job_id)
    except Exception as exc:
        logger.warning("Failed to read job %s before execution: %s", job_id, exc)

    if row is None:
        logger.warning("Job row %s missing in Supabase; creating fallback row.", job_id)
        try:
            store.create_job(
                job_id=job_id,
                task_type=task_type,
                task_payload=task_data,
                metadata={
                    "source": "queue_worker_fallback",
                    "retry_count": _coerce_int(payload.get("retryCount"), 0, minimum=0),
                    "max_retries": _coerce_int(payload.get("maxRetries"), max_retries, minimum=0),
                },
            )
            row = store.get_job(job_id)
        except Exception as exc:
            logger.warning("Could not create fallback row for %s: %s", job_id, exc)

    if isinstance(row, dict):
        status = str(row.get("status") or "")
        if status in {"completed", "failed"}:
            logger.info("Skipping terminal job %s with status=%s", job_id, status)
            return False

    retry_count, max_retries_for_job = _extract_retry_state(
        job_row=row,
        queue_payload=payload,
        default_max_retries=max_retries,
    )
    priority, stream_results = _extract_priority_and_stream(
        job_row=row,
        queue_payload=payload,
    )

    claim_acquired = True
    claim_fn = getattr(store, "try_claim_job_execution", None)
    if callable(claim_fn):
        try:
            claim_acquired = bool(
                claim_fn(
                    job_id,
                    worker_id=worker_id,
                    lease_seconds=claim_lease_seconds,
                    retry_count=retry_count,
                    max_retries=max_retries_for_job,
                )
            )
        except Exception as exc:
            claim_acquired = False
            logger.warning("Failed to acquire execution claim for %s: %s", job_id, exc)
    else:
        try:
            store.mark_running(job_id, retry_count=retry_count, max_retries=max_retries_for_job)
        except Exception as exc:
            logger.warning("Failed to mark job %s running before execution: %s", job_id, exc)

    if not claim_acquired:
        logger.info("Skipping job %s because execution claim was not acquired", job_id)
        _append_stream_event_if_enabled(
            store=store,
            job_id=job_id,
            enabled=stream_results,
            event_type="duplicate_skipped",
            status=str((row or {}).get("status") or "queued"),
            payload={
                "reason": "execution_claim_not_acquired",
                "worker_id": worker_id,
            },
        )
        return False

    _append_stream_event_if_enabled(
        store=store,
        job_id=job_id,
        enabled=stream_results,
        event_type="running",
        status="running",
        payload={
            "retry_count": retry_count,
            "max_retries": max_retries_for_job,
            "priority": priority,
        },
    )

    try:
        result = run_job(task_type, task_data)
        store.mark_completed(job_id, result)
        _append_stream_event_if_enabled(
            store=store,
            job_id=job_id,
            enabled=stream_results,
            event_type="completed",
            status="completed",
            payload={
                "retry_count": retry_count,
            },
        )
        logger.info("Job %s completed", job_id)
        return True
    except KeyboardInterrupt:
        logger.warning("Job %s interrupted before completion", job_id)
        _mark_interrupted_job(store, job_id, "interrupt during execution")
        _append_stream_event_if_enabled(
            store=store,
            job_id=job_id,
            enabled=stream_results,
            event_type="interrupted",
            status="failed",
            payload={"reason": "interrupt during execution"},
        )
        return False
    except Exception as exc:
        logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
        if _is_retryable_external_error(exc):
            outcome = _requeue_or_dead_letter(
                queue=queue,
                store=store,
                job_id=job_id,
                task_type=task_type,
                task_data=task_data,
                retry_count=retry_count,
                max_retries=max_retries_for_job,
                error_message=str(exc),
                reason="external_api_failure",
                priority=priority,
                retry_backoff_base_seconds=retry_backoff_base_seconds,
                retry_backoff_max_seconds=retry_backoff_max_seconds,
                dlq_queue_name=dlq_queue_name,
            )
            _append_stream_event_if_enabled(
                store=store,
                job_id=job_id,
                enabled=stream_results,
                event_type=("retry_scheduled" if outcome == "requeued" else "dead_lettered"),
                status=("queued" if outcome == "requeued" else "failed"),
                payload={
                    "retry_count": retry_count + 1 if outcome == "requeued" else retry_count,
                    "max_retries": max_retries_for_job,
                    "reason": "external_api_failure",
                    "error": str(exc),
                },
            )
            return False

        try:
            store.mark_failed(job_id, str(exc))
        except Exception as update_exc:
            logger.error("Could not persist failed status for %s: %s", job_id, update_exc, exc_info=True)

        _append_stream_event_if_enabled(
            store=store,
            job_id=job_id,
            enabled=stream_results,
            event_type="failed",
            status="failed",
            payload={
                "reason": "non_retryable_execution_error",
                "error": str(exc),
            },
        )
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upstash Redis worker for AetheerAI async jobs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pop-timeout",
        type=int,
        default=_env_int("UPSTASH_REDIS_POP_TIMEOUT_SECONDS", 30, minimum=1),
        help="BRPOP timeout in seconds.",
    )
    parser.add_argument(
        "--idle-sleep",
        type=float,
        default=_env_float("AETHEER_WORKER_IDLE_SLEEP_SECONDS", 0.25, minimum=0.05),
        help="Sleep interval when no job is popped.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single job then exit.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=_env_int(
            "AETHEER_WORKER_MAX_CONCURRENCY",
            _env_int("AETHER_WORKER_MAX_CONCURRENCY", 1, minimum=1),
            minimum=1,
        ),
        help="Maximum number of jobs processed concurrently in this worker process.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_env_int("AETHEER_WORKER_BATCH_SIZE", 1, minimum=1),
        help="Maximum number of jobs popped in one queue read cycle.",
    )
    parser.add_argument(
        "--shutdown-grace-seconds",
        type=float,
        default=_env_float(
            "AETHEER_WORKER_SHUTDOWN_GRACE_SECONDS",
            _env_float("AETHER_WORKER_SHUTDOWN_GRACE_SECONDS", 15.0, minimum=0.0),
            minimum=0.0,
        ),
        help="Seconds to wait for in-flight jobs before force-marking them interrupted.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=_env_int("AETHEER_JOB_MAX_RETRIES", 3, minimum=0),
        help="Maximum retry count before a job is moved to DLQ.",
    )
    parser.add_argument(
        "--retry-backoff-base",
        type=float,
        default=_env_float("AETHEER_JOB_RETRY_BACKOFF_BASE_SECONDS", 1.0, minimum=0.0),
        help="Base seconds for exponential backoff on external API failures.",
    )
    parser.add_argument(
        "--retry-backoff-max",
        type=float,
        default=_env_float("AETHEER_JOB_RETRY_BACKOFF_MAX_SECONDS", 30.0, minimum=0.0),
        help="Maximum seconds for exponential backoff on external API failures.",
    )
    parser.add_argument(
        "--claim-lease-seconds",
        type=int,
        default=_env_int("AETHEER_JOB_CLAIM_LEASE_SECONDS", 1800, minimum=30),
        help="Execution claim lease duration used to avoid duplicate multi-worker execution.",
    )
    parser.add_argument(
        "--running-timeout",
        type=int,
        default=_env_int("AETHEER_JOB_RUNNING_TIMEOUT_SECONDS", 1800, minimum=30),
        help="Consider a running job stale after this many seconds.",
    )
    parser.add_argument(
        "--stale-scan-interval",
        type=int,
        default=_env_int("AETHEER_STALE_SCAN_INTERVAL_SECONDS", 30, minimum=5),
        help="Seconds between stale-running recovery scans.",
    )
    parser.add_argument(
        "--stale-scan-batch-size",
        type=int,
        default=_env_int("AETHEER_STALE_SCAN_BATCH_SIZE", 50, minimum=1),
        help="Maximum stale-running jobs recovered per scan.",
    )
    parser.add_argument(
        "--cleanup-interval-seconds",
        type=int,
        default=_env_int("AETHEER_JOB_CLEANUP_INTERVAL_SECONDS", 300, minimum=0),
        help="Seconds between cleanup sweeps for old terminal jobs (0 disables cleanup).",
    )
    parser.add_argument(
        "--metrics-log-interval-seconds",
        type=float,
        default=_env_float("AETHEER_WORKER_METRICS_LOG_INTERVAL_SECONDS", 30.0, minimum=0.0),
        help="Seconds between periodic queue/throughput telemetry logs (0 disables).",
    )
    parser.add_argument(
        "--retention-hours",
        type=int,
        default=_env_int("AETHEER_JOB_RETENTION_HOURS", 168, minimum=1),
        help="Retention window for completed/failed jobs before cleanup.",
    )
    parser.add_argument(
        "--dlq-queue",
        default=(os.getenv("UPSTASH_REDIS_DLQ_NAME") or "job_queue_dlq").strip() or "job_queue_dlq",
        help="Redis list name used for dead-lettered jobs.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Worker log level.",
    )
    return parser.parse_args()


def run_worker(
    *,
    pop_timeout: int,
    idle_sleep: float,
    run_once: bool,
    max_concurrency: int = 1,
    batch_size: int = 1,
    shutdown_grace_seconds: float = 15.0,
    max_retries: int = 3,
    retry_backoff_base_seconds: float = 1.0,
    retry_backoff_max_seconds: float = 30.0,
    claim_lease_seconds: int = 1800,
    running_timeout_seconds: int = 1800,
    stale_scan_interval_seconds: int = 30,
    stale_scan_batch_size: int = 50,
    cleanup_interval_seconds: int = 300,
    metrics_log_interval_seconds: float = 30.0,
    retention_hours: int = 168,
    dlq_queue_name: str = "job_queue_dlq",
) -> None:
    queue = UpstashRedisQueue()
    store = SupabaseJobStore()
    max_concurrency = max(1, int(max_concurrency))
    batch_size = max(1, int(batch_size))
    shutdown_grace_seconds = max(0.0, float(shutdown_grace_seconds))
    max_retries = max(0, int(max_retries))
    retry_backoff_base_seconds = max(0.0, float(retry_backoff_base_seconds))
    retry_backoff_max_seconds = max(retry_backoff_base_seconds, float(retry_backoff_max_seconds))
    claim_lease_seconds = max(30, int(claim_lease_seconds))
    running_timeout_seconds = max(30, int(running_timeout_seconds))
    stale_scan_interval_seconds = max(5, int(stale_scan_interval_seconds))
    stale_scan_batch_size = max(1, int(stale_scan_batch_size))
    cleanup_interval_seconds = max(0, int(cleanup_interval_seconds))
    metrics_log_interval_seconds = max(0.0, float(metrics_log_interval_seconds))
    retention_hours = max(1, int(retention_hours))
    dlq_queue_name = str(dlq_queue_name).strip() or "job_queue_dlq"
    priority_queue_names = tuple(
        str(name)
        for name in getattr(queue, "priority_queue_names", (queue.queue_name,))
        if str(name).strip()
    )
    if not priority_queue_names:
        priority_queue_names = (queue.queue_name,)
    runner_local = threading.local()
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    def _run_job(task_type: str, task_data: dict[str, Any]) -> Any:
        runner = getattr(runner_local, "runner", None)
        if runner is None:
            runner = AIJobRunner()
            runner_local.runner = runner
        return runner.execute(task_type=task_type, task_data=task_data)

    def _collect_done(
        inflight_jobs: dict[Future[bool], str], *, timeout: float
    ) -> tuple[dict[Future[bool], str], int]:
        if not inflight_jobs:
            return inflight_jobs, 0

        done, pending = wait(set(inflight_jobs), timeout=timeout, return_when=FIRST_COMPLETED)
        completed_successfully = 0
        for future in done:
            try:
                if future.result():
                    completed_successfully += 1
            except Exception:  # pragma: no cover - defensive; worker function catches expected failures.
                logger.exception("Unexpected unhandled exception in worker future")
        return {future: inflight_jobs[future] for future in pending}, completed_successfully

    shutdown_requested = False
    shutdown_reason = "interrupt"
    previous_handlers: dict[int, Any] = {}

    def _request_shutdown(reason: str) -> None:
        nonlocal shutdown_requested, shutdown_reason
        if shutdown_requested:
            return
        shutdown_requested = True
        shutdown_reason = reason
        logger.info("Worker shutdown requested: %s", reason)

    def _handle_signal(signum: int, _frame: Any) -> None:
        _request_shutdown(f"received {_signal_name(signum)}")
        raise KeyboardInterrupt()

    logger.info(
        (
            "Worker online: queues=%s pop_timeout=%ss max_concurrency=%s batch_size=%s "
            "run_once=%s shutdown_grace_seconds=%s max_retries=%s retry_backoff=%ss..%ss "
            "claim_lease=%ss timeout=%ss cleanup_interval=%ss metrics_interval=%ss retention=%sh dlq=%s worker_id=%s"
        ),
        ",".join(priority_queue_names),
        pop_timeout,
        max_concurrency,
        batch_size,
        run_once,
        shutdown_grace_seconds,
        max_retries,
        retry_backoff_base_seconds,
        retry_backoff_max_seconds,
        claim_lease_seconds,
        running_timeout_seconds,
        cleanup_interval_seconds,
        metrics_log_interval_seconds,
        retention_hours,
        dlq_queue_name,
        worker_id,
    )

    handled = 0
    submitted = 0
    inflight: dict[Future[bool], str] = {}
    next_stale_scan = time.monotonic()
    next_cleanup_scan = time.monotonic() if cleanup_interval_seconds > 0 else float("inf")
    next_metrics_log = time.monotonic() if metrics_log_interval_seconds > 0 else float("inf")
    pool = ThreadPoolExecutor(max_workers=max_concurrency, thread_name_prefix="upstash-job")
    try:
        for signum in _supported_shutdown_signals():
            try:
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, _handle_signal)
            except Exception:
                logger.debug("Unable to register shutdown handler for %s", _signal_name(signum))

        while not shutdown_requested:
            now = time.monotonic()
            if now >= next_stale_scan:
                _recover_stale_running_jobs(
                    queue=queue,
                    store=store,
                    max_retries=max_retries,
                    running_timeout_seconds=running_timeout_seconds,
                    stale_scan_batch_size=stale_scan_batch_size,
                    dlq_queue_name=dlq_queue_name,
                )
                next_stale_scan = now + stale_scan_interval_seconds

            if cleanup_interval_seconds > 0 and now >= next_cleanup_scan:
                cleanup_fn = getattr(store, "cleanup_old_jobs", None)
                if callable(cleanup_fn):
                    try:
                        deleted = cleanup_fn(retention_hours=retention_hours, limit=500)
                        if deleted:
                            logger.info("Cleanup removed %s terminal jobs older than %sh", deleted, retention_hours)
                    except Exception as cleanup_exc:
                        logger.warning("Periodic cleanup failed: %s", cleanup_exc, exc_info=True)
                next_cleanup_scan = now + cleanup_interval_seconds

            if metrics_log_interval_seconds > 0 and now >= next_metrics_log:
                depth_snapshot = _queue_depth_snapshot(
                    queue,
                    queue_names=priority_queue_names,
                    dlq_queue_name=dlq_queue_name,
                )
                active_queue_depth = sum(
                    depth_snapshot.get(queue_name, 0)
                    for queue_name in priority_queue_names
                    if queue_name in depth_snapshot
                )
                logger.info(
                    "Worker metrics: worker_id=%s submitted=%s completed=%s inflight=%s queue_depth=%s dlq_depth=%s",
                    worker_id,
                    submitted,
                    handled,
                    len(inflight),
                    active_queue_depth,
                    depth_snapshot.get(dlq_queue_name, 0),
                )
                next_metrics_log = now + metrics_log_interval_seconds

            inflight, completed_now = _collect_done(inflight, timeout=0)
            handled += completed_now

            if run_once and submitted >= 1:
                if not inflight:
                    logger.info("Processed one job; exiting due to --once.")
                    break
                inflight, completed_now = _collect_done(inflight, timeout=idle_sleep)
                handled += completed_now
                continue

            if len(inflight) >= max_concurrency:
                inflight, completed_now = _collect_done(inflight, timeout=idle_sleep)
                handled += completed_now
                continue

            available_slots = max_concurrency - len(inflight)
            target_batch_size = 1 if run_once else min(batch_size, available_slots)

            try:
                payloads = _blocking_pop_many_with_priority(
                    queue,
                    timeout_seconds=pop_timeout,
                    batch_size=target_batch_size,
                    queue_names=priority_queue_names,
                )
            except KeyboardInterrupt:
                _request_shutdown("interrupt while waiting for queued jobs")
                continue
            except Exception as exc:
                logger.error("Queue pop error: %s", exc, exc_info=True)
                time.sleep(min(5.0, idle_sleep * 2.0))
                continue

            if not payloads:
                if run_once and submitted == 0:
                    logger.info("No jobs available; exiting due to --once.")
                    break
                if not inflight:
                    time.sleep(idle_sleep)
                continue

            for payload in payloads:
                job_id = str(payload.get("jobId") or "").strip()
                task_data = payload.get("task")
                if not job_id or not isinstance(task_data, dict):
                    logger.error("Invalid queue payload discarded: %s", payload)
                    continue

                future = pool.submit(
                    _process_job_payload,
                    payload=payload,
                    queue=queue,
                    store=store,
                    run_job=_run_job,
                    worker_id=worker_id,
                    claim_lease_seconds=claim_lease_seconds,
                    max_retries=max_retries,
                    retry_backoff_base_seconds=retry_backoff_base_seconds,
                    retry_backoff_max_seconds=retry_backoff_max_seconds,
                    dlq_queue_name=dlq_queue_name,
                )
                inflight[future] = job_id
                submitted += 1

                if run_once and submitted >= 1:
                    break
    except KeyboardInterrupt:
        _request_shutdown("interrupt")
    finally:
        if shutdown_requested and inflight:
            logger.info("Shutdown started with %s in-flight job(s)", len(inflight))
            for job_id in sorted(set(inflight.values())):
                _mark_interrupted_job(store, job_id, shutdown_reason)

        if inflight and shutdown_grace_seconds > 0:
            done, pending = wait(set(inflight), timeout=shutdown_grace_seconds)
            for future in done:
                try:
                    if future.result():
                        handled += 1
                except Exception:
                    logger.exception("Unexpected unhandled exception while draining worker futures")
            inflight = {future: inflight[future] for future in pending}

        if inflight:
            for future in inflight:
                future.cancel()
            logger.warning(
                "Worker exiting with %s unfinished job(s): %s",
                len(inflight),
                ", ".join(sorted(set(inflight.values()))),
            )

        pool.shutdown(wait=False, cancel_futures=True)
        for signum, previous_handler in previous_handlers.items():
            try:
                signal.signal(signum, previous_handler)
            except Exception:
                pass

    logger.info("Worker stopped after submitting=%s and completed=%s successful jobs", submitted, handled)


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    load_env(env_path)

    args = _parse_args()
    setup_logging(level=str(args.log_level).upper())

    run_worker(
        pop_timeout=max(1, int(args.pop_timeout)),
        idle_sleep=max(0.05, float(args.idle_sleep)),
        run_once=bool(args.once),
        max_concurrency=max(1, int(args.max_concurrency)),
        batch_size=max(1, int(args.batch_size)),
        shutdown_grace_seconds=max(0.0, float(args.shutdown_grace_seconds)),
        max_retries=max(0, int(args.max_retries)),
        retry_backoff_base_seconds=max(0.0, float(args.retry_backoff_base)),
        retry_backoff_max_seconds=max(0.0, float(args.retry_backoff_max)),
        claim_lease_seconds=max(30, int(args.claim_lease_seconds)),
        running_timeout_seconds=max(30, int(args.running_timeout)),
        stale_scan_interval_seconds=max(5, int(args.stale_scan_interval)),
        stale_scan_batch_size=max(1, int(args.stale_scan_batch_size)),
        cleanup_interval_seconds=max(0, int(args.cleanup_interval_seconds)),
        metrics_log_interval_seconds=max(0.0, float(args.metrics_log_interval_seconds)),
        retention_hours=max(1, int(args.retention_hours)),
        dlq_queue_name=str(args.dlq_queue).strip() or "job_queue_dlq",
    )


if __name__ == "__main__":
    main()
