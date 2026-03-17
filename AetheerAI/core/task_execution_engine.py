"""Task execution engine for autonomous workflows.

Supports:
- Sequential or parallel batch execution
- Retry with bounded attempts
- Per-task status tracking and timestamps
- Lightweight event logs suitable for API monitoring
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


TaskRunner = Callable[[], str]


@dataclass
class ExecutionRecord:
    task_id: str
    title: str
    status: str = "pending"
    attempts: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    result: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "status": self.status,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": (
                round(self.finished_at - self.started_at, 3)
                if self.started_at is not None and self.finished_at is not None
                else None
            ),
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class ExecutionTask:
    title: str
    runner: TaskRunner
    task_id: str = ""
    max_retries: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskExecutionEngine:
    """Runs workflow tasks with retry semantics and status observability."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def execute_batch(
        self,
        tasks: list[ExecutionTask],
        *,
        mode: str = "sequential",
        max_workers: int = 4,
    ) -> list[ExecutionRecord]:
        """Execute a batch of tasks in sequential or parallel mode."""
        if mode not in {"sequential", "parallel"}:
            raise ValueError("mode must be either 'sequential' or 'parallel'.")

        if mode == "parallel":
            return self._execute_parallel(tasks, max_workers=max_workers)
        return [self._run_task(task) for task in tasks]

    def _execute_parallel(self, tasks: list[ExecutionTask], max_workers: int) -> list[ExecutionRecord]:
        if not tasks:
            return []

        workers = max(1, min(max_workers, len(tasks)))
        results: list[ExecutionRecord] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(self._run_task, task): task for task in tasks}
            for future in as_completed(future_map):
                record = future.result()
                results.append(record)

        return results

    def _run_task(self, task: ExecutionTask) -> ExecutionRecord:
        task_id = task.task_id or uuid.uuid4().hex
        record = ExecutionRecord(task_id=task_id, title=task.title, metadata=dict(task.metadata or {}))
        self._upsert_record(record)

        for attempt in range(1, max(1, task.max_retries) + 1):
            record.attempts = attempt
            record.started_at = record.started_at or time.time()
            record.status = "running"
            self._emit("task_started", task_id=task_id, attempt=attempt, title=task.title)
            self._upsert_record(record)

            try:
                result = task.runner()
                record.result = str(result)
                record.error = ""
                record.status = "completed"
                record.finished_at = time.time()
                self._emit("task_completed", task_id=task_id, attempt=attempt)
                self._upsert_record(record)
                return record
            except Exception as exc:
                record.error = str(exc)
                record.status = "retrying" if attempt < max(1, task.max_retries) else "failed"
                self._emit(
                    "task_failed",
                    task_id=task_id,
                    attempt=attempt,
                    error=str(exc),
                    will_retry=attempt < max(1, task.max_retries),
                )
                logger.warning(
                    "TaskExecutionEngine: task '%s' failed on attempt %d/%d: %s",
                    task.title,
                    attempt,
                    max(1, task.max_retries),
                    exc,
                )
                if attempt >= max(1, task.max_retries):
                    record.finished_at = time.time()
                    record.status = "failed"
                    self._upsert_record(record)
                    return record

        record.status = "failed"
        record.finished_at = time.time()
        self._upsert_record(record)
        return record

    def get_record(self, task_id: str) -> ExecutionRecord | None:
        with self._lock:
            return self._records.get(task_id)

    def list_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [record.to_dict() for record in self._records.values()]

    def get_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            if limit <= 0:
                return []
            return list(self._events[-limit:])

    def _upsert_record(self, record: ExecutionRecord) -> None:
        with self._lock:
            self._records[record.task_id] = record

    def _emit(self, event: str, **payload: Any) -> None:
        envelope = {
            "event": event,
            "timestamp": time.time(),
            **payload,
        }
        with self._lock:
            self._events.append(envelope)
            if len(self._events) > 5_000:
                self._events = self._events[-5_000:]
