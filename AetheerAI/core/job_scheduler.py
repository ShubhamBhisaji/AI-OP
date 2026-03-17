"""
JobScheduler — Persistent, priority-based job queue for AetheerAI.

Closes the gaps:
  ❌ Parallel task orchestration   → thread-pool execution of independent jobs
    ❌ Distributed execution          → pluggable executor transport (local or remote)
  ❌ Persistent job queues          → jobs survive process restarts
  ❌ Scheduling                     → run-at, interval, and immediate scheduling

Job Lifecycle
-------------
  pending   → queued, waiting for a worker slot
  running   → currently executing on a worker thread
  completed → finished successfully
  failed    → raised an exception; stored with error detail
  cancelled → cancelled before execution began

Scheduling Modes
----------------
  immediate  — enqueue now (default)
  at_time    — run at a specific UTC datetime
  interval   — repeat every N seconds (recurring jobs)

Storage
-------
  Jobs are serialised to workspace/jobs/job_store.json after every state change.
  On startup, pending jobs are re-queued; running jobs are moved back to pending
  (they were interrupted mid-flight and need to re-run).

Security
--------
  - Job callables are never serialised; the job_store only holds metadata.
  - Agent/task strings are length-capped before storage to prevent bloat.
  - Max concurrent workers is configurable (default 4) to bound resource use.
"""

from __future__ import annotations

import heapq
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_JOB_STORE = Path(__file__).parent.parent / "workspace" / "jobs" / "job_store.json"
_JOB_STORE.parent.mkdir(parents=True, exist_ok=True)

_MAX_WORKERS: int = 4
_MAX_TASK_LEN: int = 2_000   # characters stored in job description
_MAX_RESULT_LEN: int = 4_000


# ── Job record ─────────────────────────────────────────────────────────────

@dataclass
class JobRecord:
    job_id:       str
    name:         str
    agent_name:   str
    task:         str
    priority:     int          # lower = higher priority (heap ordering)
    status:       str          # pending | running | completed | failed | cancelled
    mode:         str          # immediate | at_time | interval
    run_at:       float        # Unix timestamp; 0.0 = now
    interval_sec: float        # 0.0 = not recurring
    created_at:   float        = field(default_factory=time.time)
    started_at:   float | None = None
    finished_at:  float | None = None
    result:       str          = ""
    error:        str          = ""
    attempts:     int          = 0
    max_retries:  int          = 1
    owner_user_id: int | None  = None
    owner_username: str        = ""
    # These are NOT persisted
    _callable:    Callable | None = field(default=None, repr=False, compare=False)

    # Heap ordering by (run_at, priority, job_id)
    def __lt__(self, other: "JobRecord") -> bool:
        return (self.run_at, self.priority) < (other.run_at, other.priority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id":       self.job_id,
            "name":         self.name,
            "agent_name":   self.agent_name,
            "task":         self.task[:_MAX_TASK_LEN],
            "priority":     self.priority,
            "status":       self.status,
            "mode":         self.mode,
            "run_at":       self.run_at,
            "interval_sec": self.interval_sec,
            "created_at":   self.created_at,
            "started_at":   self.started_at,
            "finished_at":  self.finished_at,
            "result":       self.result[:_MAX_RESULT_LEN],
            "error":        self.error[:500],
            "attempts":     self.attempts,
            "max_retries":  self.max_retries,
            "owner_user_id": self.owner_user_id,
            "owner_username": self.owner_username,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JobRecord":
        return cls(
            job_id=str(d.get("job_id", uuid.uuid4().hex)),
            name=str(d.get("name", "job")),
            agent_name=str(d.get("agent_name", "")),
            task=str(d.get("task", "")),
            priority=int(d.get("priority", 50)),
            status=str(d.get("status", "pending")),
            mode=str(d.get("mode", "immediate")),
            run_at=float(d.get("run_at", 0.0)),
            interval_sec=float(d.get("interval_sec", 0.0)),
            created_at=float(d.get("created_at", time.time())),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            result=str(d.get("result", "")),
            error=str(d.get("error", "")),
            attempts=int(d.get("attempts", 0)),
            max_retries=int(d.get("max_retries", 1)),
            owner_user_id=(
                int(d["owner_user_id"]) if d.get("owner_user_id") is not None else None
            ),
            owner_username=str(d.get("owner_username", "")),
        )

    def elapsed(self) -> float | None:
        if self.started_at and self.finished_at:
            return round(self.finished_at - self.started_at, 3)
        return None


# ── Scheduler ──────────────────────────────────────────────────────────────

class JobScheduler:
    """
    Persistent, priority-based job scheduler for AetheerAI.

    Usage
    -----
    scheduler = JobScheduler(executor_fn=kernel.run_agent)
    job_id = scheduler.schedule(name="daily_report", agent_name="analyst", task="Generate KPI report")
    scheduler.start()           # launches background worker thread
    scheduler.stop()            # graceful shutdown
    scheduler.status(job_id)    # dict with current state
    scheduler.list_jobs()       # all jobs metadata
    """

    def __init__(
        self,
        executor_fn: Callable[[str, str], Any],
        max_workers: int = _MAX_WORKERS,
        store_path: Path | str | None = None,
        executor_name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        executor_fn : Callable(agent_name, task) → result_str
                      Typically kernel.run_agent — called for every job.
        max_workers : Thread pool size (default 4).
        store_path  : Override default persistence path.
        """
        self._executor_fn = executor_fn
        self._executor_name = (
            executor_name
            or getattr(executor_fn, "__qualname__", None)
            or type(executor_fn).__name__
        )
        self._store_path = Path(store_path) if store_path else _JOB_STORE
        self._store_path.parent.mkdir(parents=True, exist_ok=True)

        self._heap: list[JobRecord] = []      # min-heap by (run_at, priority)
        self._jobs: dict[str, JobRecord] = {} # job_id → record (source of truth)
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="aether-job")
        self._active: dict[str, Future] = {}  # job_id → Future

        self._load_store()

    # ── Public API ────────────────────────────────────────────────────────

    def schedule(
        self,
        name: str,
        agent_name: str,
        task: str,
        *,
        priority: int = 50,
        run_at: float | datetime | None = None,
        interval_sec: float = 0.0,
        max_retries: int = 1,
        callable_fn: Callable | None = None,
        owner_user_id: int | None = None,
        owner_username: str | None = None,
    ) -> str:
        """
        Enqueue a job and return its job_id.

        Parameters
        ----------
        name        : Human-readable job label.
        agent_name  : Agent to dispatch (passed to executor_fn).
        task        : Task description for the agent.
        priority    : 0–100; lower = higher priority (default 50).
        run_at      : datetime or Unix timestamp; None = run immediately.
        interval_sec: If > 0, re-schedule this job every N seconds after completion.
        max_retries : How many times to retry on failure (default 1).
        callable_fn : Optional override for executor_fn just for this job.
        """
        now = time.time()
        if run_at is None:
            scheduled_ts = now
            mode = "immediate"
        elif isinstance(run_at, datetime):
            scheduled_ts = run_at.timestamp()
            mode = "at_time"
        else:
            scheduled_ts = float(run_at)
            mode = "at_time"

        if interval_sec > 0:
            mode = "interval"

        resolved_owner_id: int | None
        try:
            resolved_owner_id = int(owner_user_id) if owner_user_id is not None else None
        except (TypeError, ValueError):
            resolved_owner_id = None

        job = JobRecord(
            job_id=uuid.uuid4().hex,
            name=name,
            agent_name=agent_name,
            task=task[:_MAX_TASK_LEN],
            priority=int(max(0, min(100, priority))),
            status="pending",
            mode=mode,
            run_at=scheduled_ts,
            interval_sec=interval_sec,
            max_retries=max_retries,
            owner_user_id=resolved_owner_id,
            owner_username=str(owner_username or "")[:120],
            _callable=callable_fn,
        )

        with self._lock:
            self._jobs[job.job_id] = job
            heapq.heappush(self._heap, job)

        self._persist()
        logger.info(
            "JobScheduler: scheduled '%s' (id=%s, mode=%s, priority=%d)",
            name, job.job_id[:8], mode, priority,
        )
        return job.job_id

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending job. Returns True if found and cancelled."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status not in ("pending",):
                return False
            job.status = "cancelled"
            job.finished_at = time.time()

        self._persist()
        logger.info("JobScheduler: cancelled job %s ('%s').", job_id[:8], job.name)
        return True

    def status(self, job_id: str) -> dict[str, Any] | None:
        """Return the current state of a job as a dict, or None if not found."""
        with self._lock:
            job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(
        self,
        status_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Return metadata for all known jobs.

        Parameters
        ----------
        status_filter : If set, only return jobs with this status.
        limit         : Maximum records to return (most-recently created first).
        """
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda j: j.created_at,
                reverse=True,
            )
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]
        return [j.to_dict() for j in jobs[:limit]]

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status == "pending")

    def running_count(self) -> int:
        with self._lock:
            return len(self._active)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for j in self._jobs.values():
                counts[j.status] = counts.get(j.status, 0) + 1
        return {
            "total": len(self._jobs),
            "by_status": counts,
            "running": len(self._active),
            "executor": self._executor_name,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background scheduler loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            name="aether-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("JobScheduler: background loop started.")

    def stop(self, wait: bool = True, timeout: float = 10.0) -> None:
        """Gracefully stop the scheduler. Waits for running jobs if wait=True."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        if wait:
            self._pool.shutdown(wait=True, cancel_futures=False)
        logger.info("JobScheduler: stopped.")

    # ── Internal ──────────────────────────────────────────────────────────

    def _scheduler_loop(self) -> None:
        """Background loop: pop due jobs from heap, dispatch to thread pool."""
        while not self._stop_event.is_set():
            now = time.time()
            dispatched = 0
            with self._lock:
                while self._heap:
                    job = self._heap[0]
                    # Skip stale heap entries (cancelled or already dispatched)
                    actual = self._jobs.get(job.job_id)
                    if actual is None or actual.status != "pending":
                        heapq.heappop(self._heap)
                        continue
                    if actual.run_at > now:
                        break  # Next job is in the future
                    heapq.heappop(self._heap)
                    actual.status = "running"
                    actual.started_at = time.time()
                    actual.attempts += 1
                    future = self._pool.submit(self._run_job, actual)
                    self._active[actual.job_id] = future
                    dispatched += 1

            if dispatched:
                self._persist()
            time.sleep(0.5)

    def _run_job(self, job: JobRecord) -> None:
        """Execute a single job and update its state."""
        try:
            fn = job._callable or self._executor_fn
            result = fn(job.agent_name, job.task)
            with self._lock:
                job.status = "completed"
                job.result = str(result or "")[:_MAX_RESULT_LEN]
                job.finished_at = time.time()
                self._active.pop(job.job_id, None)

            logger.info(
                "JobScheduler: job '%s' (%s) completed in %.1fs.",
                job.name, job.job_id[:8], job.elapsed() or 0,
            )

            # Re-schedule if interval job
            if job.interval_sec > 0:
                self.schedule(
                    name=job.name,
                    agent_name=job.agent_name,
                    task=job.task,
                    priority=job.priority,
                    run_at=time.time() + job.interval_sec,
                    interval_sec=job.interval_sec,
                    max_retries=job.max_retries,
                    callable_fn=job._callable,
                )

        except Exception as exc:
            with self._lock:
                job.error = str(exc)[:500]
                self._active.pop(job.job_id, None)

                if job.attempts <= job.max_retries:
                    # Retry with exponential back-off
                    backoff = 2 ** (job.attempts - 1)
                    job.status = "pending"
                    job.run_at = time.time() + backoff
                    job.started_at = None
                    job.finished_at = None
                    heapq.heappush(self._heap, job)
                    logger.warning(
                        "JobScheduler: job '%s' failed (attempt %d/%d), retry in %ds: %s",
                        job.name, job.attempts, job.max_retries + 1, backoff, exc,
                    )
                else:
                    job.status = "failed"
                    job.finished_at = time.time()
                    logger.error(
                        "JobScheduler: job '%s' permanently failed after %d attempts: %s",
                        job.name, job.attempts, exc,
                    )

        self._persist()

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Serialise all job metadata to disk (atomic write)."""
        try:
            with self._persist_lock:
                with self._lock:
                    data = {"jobs": [j.to_dict() for j in self._jobs.values()]}

                # Use a unique temp file per flush to avoid cross-thread collisions,
                # especially on Windows where replace() can fail on shared temp names.
                tmp = self._store_path.parent / f"{self._store_path.stem}.{uuid.uuid4().hex}.tmp"
                tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp.replace(self._store_path)
        except Exception as exc:
            logger.warning("JobScheduler: failed to persist store: %s", exc)

    def _load_store(self) -> None:
        """Load jobs from disk on startup."""
        if not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            for d in raw.get("jobs", []):
                job = JobRecord.from_dict(d)
                # Jobs that were running when the process died need re-queueing
                if job.status == "running":
                    job.status = "pending"
                    job.started_at = None
                self._jobs[job.job_id] = job
                if job.status == "pending":
                    heapq.heappush(self._heap, job)
            logger.info(
                "JobScheduler: loaded %d jobs from store (%d pending).",
                len(self._jobs), self.pending_count(),
            )
        except Exception as exc:
            logger.warning("JobScheduler: could not load job store: %s", exc)
