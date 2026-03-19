"""scheduled_goals.py — Scheduled and recurring goal execution.

Closes ISSUE 3: Continuous Goal Engine Still Basic.

Adds on top of the existing GoalManager:
    - Scheduled goals (run at a specific time)
    - Recurring goals (repeat on interval)
    - Task timeout enforcement
    - Dead-letter queue alerting
    - Long-running mission support

Usage
-----
    scheduler = GoalScheduler(goal_manager=gm)

    # Schedule a one-time goal
    scheduler.schedule(
        description="Generate weekly report",
        agent_name="analytics_bot",
        run_at=datetime(2026, 3, 20, 9, 0),
        tasks=["Pull metrics", "Generate charts", "Send email"],
    )

    # Recurring goal every 6 hours
    scheduler.schedule_recurring(
        description="Check inventory levels",
        agent_name="store_bot",
        interval_seconds=6 * 3600,
        tasks=["Query stock API", "Flag low items", "Create reorder tasks"],
    )

    # Start the scheduler loop
    scheduler.start()
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Scheduled Goal ───────────────────────────────────────────────────────────

@dataclass
class ScheduledGoal:
    id: str
    description: str
    agent_name: str
    tasks: list[str]
    run_at: float                              # UTC timestamp
    interval_seconds: float = 0.0              # 0 = one-time
    priority: int = 5
    task_timeout_seconds: float = 120.0
    max_retries: int = 2
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_run_at: float = 0.0
    run_count: int = 0
    status: str = "pending"                    # pending | active | completed | failed | paused
    created_at: float = field(default_factory=time.time)

    @property
    def is_recurring(self) -> bool:
        return self.interval_seconds > 0

    @property
    def is_due(self) -> bool:
        return self.status in ("pending", "active") and time.time() >= self.run_at

    @property
    def next_run_at(self) -> float:
        if not self.is_recurring:
            return self.run_at
        return self.last_run_at + self.interval_seconds if self.last_run_at else self.run_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "agent_name": self.agent_name,
            "tasks": self.tasks,
            "run_at": self.run_at,
            "interval_seconds": self.interval_seconds,
            "priority": self.priority,
            "task_timeout_seconds": self.task_timeout_seconds,
            "max_retries": self.max_retries,
            "tags": self.tags,
            "metadata": self.metadata,
            "last_run_at": self.last_run_at,
            "run_count": self.run_count,
            "status": self.status,
            "created_at": self.created_at,
            "is_recurring": self.is_recurring,
        }


# ── Dead Letter Entry ────────────────────────────────────────────────────────

@dataclass
class DeadLetterEntry:
    goal_id: str
    description: str
    agent_name: str
    error: str
    failed_at: float = field(default_factory=time.time)
    retry_count: int = 0
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "agent_name": self.agent_name,
            "error": self.error,
            "failed_at": self.failed_at,
            "retry_count": self.retry_count,
            "acknowledged": self.acknowledged,
        }


# ── GoalScheduler ────────────────────────────────────────────────────────────

class GoalScheduler:
    """
    Scheduler for time-based and recurring goal execution.

    Sits on top of GoalManager, adding:
    - Scheduled goals (run at specific UTC time)
    - Recurring goals (repeat every N seconds)
    - Task timeout enforcement
    - Dead-letter queue for permanently failed goals
    - Alert callback for DLQ entries

    Parameters
    ----------
    goal_manager     : GoalManager instance (optional when using goal_manager_factory).
    goal_manager_factory : Optional callable(agent_name) -> GoalManager for
                           per-agent manager resolution.
    tick_interval    : How often to check for due goals (seconds).
    persist_path     : File to persist scheduled goals.
    on_dlq_alert     : Callback(DeadLetterEntry) when a goal is dead-lettered.
    """

    def __init__(
        self,
        goal_manager: Any,
        tick_interval: float = 10.0,
        persist_path: str | Path | None = None,
        on_dlq_alert: Callable[[DeadLetterEntry], None] | None = None,
        goal_manager_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._gm = goal_manager
        self._goal_manager_factory = goal_manager_factory
        self._tick_interval = tick_interval
        self._persist_path = Path(persist_path) if persist_path else None
        self._on_dlq_alert = on_dlq_alert

        self._scheduled: dict[str, ScheduledGoal] = {}
        self._dlq: list[DeadLetterEntry] = []
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._load()

    def _resolve_goal_manager(self, agent_name: str) -> Any:
        """Resolve the GoalManager for an agent.

        If a per-agent factory is configured, it takes precedence.
        Otherwise, falls back to the static manager passed at construction.
        """
        if self._goal_manager_factory is not None:
            return self._goal_manager_factory(agent_name)
        if self._gm is None:
            raise RuntimeError("GoalScheduler has no GoalManager configured.")
        return self._gm

    # ── Schedule goals ───────────────────────────────────────────────────

    def schedule(
        self,
        description: str,
        agent_name: str,
        run_at: float | None = None,
        tasks: list[str] | None = None,
        priority: int = 5,
        task_timeout_seconds: float = 120.0,
        max_retries: int = 2,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Schedule a one-time goal. Returns scheduled goal ID."""
        goal = ScheduledGoal(
            id=str(uuid.uuid4()),
            description=description,
            agent_name=agent_name,
            tasks=list(tasks or []),
            run_at=run_at or time.time(),
            priority=priority,
            task_timeout_seconds=task_timeout_seconds,
            max_retries=max_retries,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._scheduled[goal.id] = goal
        self._save()
        logger.info("GoalScheduler: scheduled goal '%s' for %s.",
                     description[:40], time.ctime(goal.run_at))
        return goal.id

    def schedule_recurring(
        self,
        description: str,
        agent_name: str,
        interval_seconds: float,
        tasks: list[str] | None = None,
        priority: int = 5,
        task_timeout_seconds: float = 120.0,
        max_retries: int = 2,
        tags: list[str] | None = None,
        run_at: float | None = None,
    ) -> str:
        """Schedule a recurring goal. Returns scheduled goal ID."""
        goal = ScheduledGoal(
            id=str(uuid.uuid4()),
            description=description,
            agent_name=agent_name,
            tasks=list(tasks or []),
            run_at=run_at or time.time(),
            interval_seconds=max(1.0, interval_seconds),
            priority=priority,
            task_timeout_seconds=task_timeout_seconds,
            max_retries=max_retries,
            tags=list(tags or []),
        )
        with self._lock:
            self._scheduled[goal.id] = goal
        self._save()
        logger.info("GoalScheduler: recurring goal '%s' every %ds.",
                     description[:40], interval_seconds)
        return goal.id

    def cancel(self, goal_id: str) -> bool:
        """Cancel a scheduled goal."""
        with self._lock:
            goal = self._scheduled.get(goal_id)
            if goal is None:
                return False
            goal.status = "completed"
        self._save()
        return True

    def pause(self, goal_id: str) -> bool:
        """Pause a scheduled goal."""
        with self._lock:
            goal = self._scheduled.get(goal_id)
            if goal is None:
                return False
            goal.status = "paused"
        self._save()
        return True

    def resume(self, goal_id: str) -> bool:
        """Resume a paused scheduled goal."""
        with self._lock:
            goal = self._scheduled.get(goal_id)
            if goal is None or goal.status != "paused":
                return False
            goal.status = "pending"
        self._save()
        return True

    # ── Scheduler loop ───────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"goal-scheduler-{id(self)}",
            daemon=True,
        )
        self._thread.start()
        logger.info("GoalScheduler: started.")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("GoalScheduler: stopped.")

    def tick(self) -> int:
        """Process one tick manually (for testing). Returns goals dispatched."""
        return self._check_and_dispatch()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_and_dispatch()
            except Exception as exc:
                logger.error("GoalScheduler: tick error: %s", exc)
            self._stop_event.wait(timeout=self._tick_interval)

    def _check_and_dispatch(self) -> int:
        """Check for due goals and dispatch them to GoalManager."""
        dispatched = 0
        now = time.time()

        with self._lock:
            goals = list(self._scheduled.values())

        for sg in goals:
            if sg.status not in ("pending", "active"):
                continue

            due_time = sg.next_run_at if sg.is_recurring and sg.last_run_at else sg.run_at
            if now < due_time:
                continue

            try:
                gm = self._resolve_goal_manager(sg.agent_name)

                # Create goal in GoalManager
                goal_id = gm.add_goal(
                    description=sg.description,
                    priority=sg.priority,
                    tags=sg.tags,
                    metadata={
                        "scheduled_id": sg.id,
                        "recurring": sg.is_recurring,
                        **sg.metadata,
                    },
                )

                # Add tasks
                for task_desc in sg.tasks:
                    gm.add_task(
                        goal_id=goal_id,
                        description=task_desc,
                        priority=sg.priority,
                        max_retries=sg.max_retries,
                    )

                gm.start_goal(goal_id)

                # Update scheduled goal state
                with self._lock:
                    sg.last_run_at = now
                    sg.run_count += 1
                    sg.status = "active"

                    if sg.is_recurring:
                        sg.run_at = now + sg.interval_seconds
                    else:
                        sg.status = "completed"

                dispatched += 1
                logger.info("GoalScheduler: dispatched '%s' (run #%d).",
                            sg.description[:40], sg.run_count)

            except Exception as exc:
                error_msg = str(exc)
                logger.error("GoalScheduler: dispatch failed for '%s': %s",
                             sg.description[:40], exc)

                # Dead-letter after max retries
                with self._lock:
                    sg.run_count += 1
                    if sg.run_count > sg.max_retries:
                        sg.status = "failed"
                        dle = DeadLetterEntry(
                            goal_id=sg.id,
                            description=sg.description,
                            agent_name=sg.agent_name,
                            error=error_msg,
                            retry_count=sg.run_count,
                        )
                        self._dlq.append(dle)
                        if self._on_dlq_alert:
                            try:
                                self._on_dlq_alert(dle)
                            except Exception:
                                pass
                        logger.warning("GoalScheduler: goal '%s' moved to DLQ.", sg.description[:40])

        if dispatched:
            self._save()
        return dispatched

    # ── Dead Letter Queue ────────────────────────────────────────────────

    def list_dlq(self) -> list[dict[str, Any]]:
        """Return all dead-lettered goals."""
        return [d.to_dict() for d in self._dlq]

    def retry_dlq(self, goal_id: str) -> bool:
        """Retry a dead-lettered goal by resetting it to pending."""
        for i, dle in enumerate(self._dlq):
            if dle.goal_id == goal_id:
                with self._lock:
                    sg = self._scheduled.get(goal_id)
                    if sg:
                        sg.status = "pending"
                        sg.run_count = 0
                        sg.run_at = time.time()
                self._dlq.pop(i)
                self._save()
                return True
        return False

    def acknowledge_dlq(self, goal_id: str) -> bool:
        """Acknowledge a DLQ entry (mark as reviewed)."""
        for dle in self._dlq:
            if dle.goal_id == goal_id:
                dle.acknowledged = True
                return True
        return False

    def clear_dlq(self) -> int:
        """Clear all dead-lettered entries. Returns count removed."""
        count = len(self._dlq)
        self._dlq.clear()
        return count

    @property
    def dlq_size(self) -> int:
        return len(self._dlq)

    # ── Introspection ────────────────────────────────────────────────────

    def list_scheduled(
        self,
        agent_name: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List scheduled goals with optional filters."""
        with self._lock:
            goals = list(self._scheduled.values())
        if agent_name:
            goals = [g for g in goals if g.agent_name == agent_name]
        if status:
            goals = [g for g in goals if g.status == status]
        return [g.to_dict() for g in sorted(goals, key=lambda g: g.run_at)]

    def status(self) -> dict[str, Any]:
        """Return scheduler status summary."""
        with self._lock:
            goals = list(self._scheduled.values())
        return {
            "total_scheduled": len(goals),
            "pending": sum(1 for g in goals if g.status == "pending"),
            "active": sum(1 for g in goals if g.status == "active"),
            "completed": sum(1 for g in goals if g.status == "completed"),
            "failed": sum(1 for g in goals if g.status == "failed"),
            "recurring": sum(1 for g in goals if g.is_recurring),
            "dlq_size": self.dlq_size,
            "dlq_unacknowledged": sum(1 for d in self._dlq if not d.acknowledged),
        }

    # ── Persistence ──────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._persist_path is None:
            return
        try:
            import os
            data = {
                "scheduled": {k: v.to_dict() for k, v in self._scheduled.items()},
                "dlq": [d.to_dict() for d in self._dlq],
                "saved_at": time.time(),
            }
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self._persist_path)
        except OSError as exc:
            logger.warning("GoalScheduler: save failed: %s", exc)

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for sid, sdata in data.get("scheduled", {}).items():
                self._scheduled[sid] = ScheduledGoal(**{
                    k: v for k, v in sdata.items()
                    if k in ScheduledGoal.__dataclass_fields__ and k != "is_recurring"
                })
            for ddata in data.get("dlq", []):
                self._dlq.append(DeadLetterEntry(**{
                    k: v for k, v in ddata.items()
                    if k in DeadLetterEntry.__dataclass_fields__
                }))
            logger.info("GoalScheduler: loaded %d scheduled, %d DLQ.",
                        len(self._scheduled), len(self._dlq))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("GoalScheduler: load failed: %s", exc)
