"""goal_manager.py — Autonomous goal and task tracking engine.

Without a goal manager, an agent is a reactive tool — it answers prompts
and stops. The GoalManager turns an agent into an *autonomous worker*:

  - Goals are persistent, prioritised objectives the agent works toward.
  - Each goal decomposes into a queue of Tasks.
  - The manager tracks state transitions: pending → active → done/failed.
  - Failures are recorded with retry budgets and error context.
  - The manager surfaces "next actions" so orchestrators know what to do next.

Design
------
Goals are stored as dicts in memory and optionally persisted to a JSON file
in workspace/goals/<agent_name>.json.  This is intentionally simple so the
file can be inspected and edited by humans.

State machine:
    Goal: pending → active → completed | failed | paused | cancelled
    Task: pending → active → completed | failed | retrying

Usage
-----
gm = GoalManager(agent_name="store_bot")
goal_id = gm.add_goal("Reduce cart abandonment by 10%", priority=1)
task_id = gm.add_task(goal_id, "Send recovery emails to abandoned carts")
gm.start_task(task_id)
gm.complete_task(task_id, result="Sent 42 recovery emails.")
gm.complete_goal(goal_id)

# Orchestrator loop
next_actions = gm.next_actions(limit=3)
for action in next_actions:
    agent.execute_task(action["description"])
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── State enums ───────────────────────────────────────────────────────────────

class GoalState(str, Enum):
    PENDING    = "pending"
    ACTIVE     = "active"
    PAUSED     = "paused"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


class TaskState(str, Enum):
    PENDING   = "pending"
    ACTIVE    = "active"
    RETRYING  = "retrying"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Task:
    id: str
    goal_id: str
    description: str
    state: TaskState = TaskState.PENDING
    priority: int = 5          # 1 (highest) → 10 (lowest)
    result: str = ""
    error: str = ""
    retry_count: int = 0
    max_retries: int = 2
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    tags: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    # Task dependency chain: this task cannot start until all listed task IDs are COMPLETED.
    depends_on: list[str] = field(default_factory=list)
    # Scheduled start: task will not be queued until this UTC timestamp is reached (0 = immediate).
    run_after: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        _known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {k: v for k, v in data.items() if k in _known}
        data["state"] = TaskState(data.get("state", "pending"))
        data["tags"] = list(data.get("tags", []))
        data["context"] = dict(data.get("context", {}))
        data["depends_on"] = list(data.get("depends_on", []))
        return cls(**data)


@dataclass
class Goal:
    id: str
    description: str
    agent_name: str
    state: GoalState = GoalState.PENDING
    priority: int = 5          # 1 (highest) → 10 (lowest)
    tasks: list[str] = field(default_factory=list)   # task IDs (ordered)
    progress: float = 0.0      # 0.0 – 1.0
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Goal":
        data = dict(data)
        data["state"] = GoalState(data.get("state", "pending"))
        data["tasks"] = list(data.get("tasks", []))
        data["tags"] = list(data.get("tags", []))
        data["metadata"] = dict(data.get("metadata", {}))
        return cls(**data)


# ── GoalManager ───────────────────────────────────────────────────────────────

class GoalManager:
    """
    Autonomous goal and task tracking engine.

    Parameters
    ----------
    agent_name   : Owner agent name (used for persistence scoping).
    persist_path : Optional JSON file path for durable storage.
                   If None, goals live in memory only.
    """

    def __init__(
        self,
        agent_name: str,
        persist_path: str | Path | None = None,
    ) -> None:
        self.agent_name = agent_name
        self._persist_path = Path(persist_path) if persist_path else None
        self._goals: dict[str, Goal] = {}
        self._tasks: dict[str, Task] = {}
        self._load()

    # ── Goal management ───────────────────────────────────────────────────────

    def add_goal(
        self,
        description: str,
        priority: int = 5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a new goal. Returns the goal ID."""
        goal = Goal(
            id=str(uuid.uuid4()),
            description=description,
            agent_name=self.agent_name,
            priority=max(1, min(10, priority)),
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        self._goals[goal.id] = goal
        self._save()
        logger.info("GoalManager[%s]: added goal '%s' (id=%s).", self.agent_name, description[:60], goal.id)
        return goal.id

    def start_goal(self, goal_id: str) -> bool:
        goal = self._goals.get(goal_id)
        if goal is None:
            return False
        goal.state = GoalState.ACTIVE
        goal.started_at = time.time()
        self._save()
        return True

    def complete_goal(self, goal_id: str, result: str = "") -> bool:
        goal = self._goals.get(goal_id)
        if goal is None:
            return False
        goal.state = GoalState.COMPLETED
        goal.result = result
        goal.progress = 1.0
        goal.finished_at = time.time()
        self._save()
        logger.info("GoalManager[%s]: goal completed — %s", self.agent_name, goal.description[:60])
        return True

    def fail_goal(self, goal_id: str, error: str = "") -> bool:
        goal = self._goals.get(goal_id)
        if goal is None:
            return False
        goal.state = GoalState.FAILED
        goal.error = error
        goal.finished_at = time.time()
        self._save()
        logger.warning("GoalManager[%s]: goal failed — %s | %s", self.agent_name, goal.description[:60], error)
        return True

    def pause_goal(self, goal_id: str) -> bool:
        goal = self._goals.get(goal_id)
        if goal is None:
            return False
        goal.state = GoalState.PAUSED
        self._save()
        return True

    def cancel_goal(self, goal_id: str) -> bool:
        goal = self._goals.get(goal_id)
        if goal is None:
            return False
        goal.state = GoalState.CANCELLED
        goal.finished_at = time.time()
        # Cancel all pending tasks for this goal
        for task_id in goal.tasks:
            task = self._tasks.get(task_id)
            if task and task.state in (TaskState.PENDING, TaskState.RETRYING):
                task.state = TaskState.SKIPPED
        self._save()
        return True

    # ── Task management ───────────────────────────────────────────────────────

    def add_task(
        self,
        goal_id: str,
        description: str,
        priority: int = 5,
        max_retries: int = 2,
        tags: list[str] | None = None,
        context: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        run_after: float = 0.0,
    ) -> str:
        """Add a task to a goal. Returns the task ID.

        Parameters
        ----------
        depends_on : List of task IDs that must be COMPLETED before this task runs.
        run_after  : Unix timestamp; task will not start before this time (0 = immediate).
        """
        goal = self._goals.get(goal_id)
        if goal is None:
            raise ValueError(f"Goal '{goal_id}' not found.")

        task = Task(
            id=str(uuid.uuid4()),
            goal_id=goal_id,
            description=description,
            priority=max(1, min(10, priority)),
            max_retries=max_retries,
            tags=list(tags or []),
            context=dict(context or {}),
            depends_on=list(depends_on or []),
            run_after=max(0.0, float(run_after)),
        )
        self._tasks[task.id] = task
        goal.tasks.append(task.id)
        self._update_goal_progress(goal_id)
        self._save()
        return task.id

    def start_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.state = TaskState.ACTIVE
        task.started_at = time.time()
        # Auto-activate parent goal
        goal = self._goals.get(task.goal_id)
        if goal and goal.state == GoalState.PENDING:
            self.start_goal(goal.id)
        self._save()
        return True

    def complete_task(self, task_id: str, result: str = "") -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.state = TaskState.COMPLETED
        task.result = result
        task.finished_at = time.time()
        self._update_goal_progress(task.goal_id)
        self._save()
        return True

    def fail_task(self, task_id: str, error: str = "", retry: bool = True) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.error = error
        task.finished_at = time.time()

        if retry and task.retry_count < task.max_retries:
            task.retry_count += 1
            task.state = TaskState.RETRYING
            task.started_at = 0.0  # reset for retry
            logger.info(
                "GoalManager[%s]: task '%s' set to retry (%d/%d).",
                self.agent_name, task.description[:40], task.retry_count, task.max_retries,
            )
        else:
            task.state = TaskState.FAILED
            logger.warning(
                "GoalManager[%s]: task failed (no more retries) — %s | %s",
                self.agent_name, task.description[:40], error,
            )
            self._update_goal_progress(task.goal_id)

        self._save()
        return True

    # ── Next actions ──────────────────────────────────────────────────────────

    def next_actions(self, limit: int = 5) -> list[dict[str, Any]]:
        """
        Return the most important tasks the agent should work on next.

        Priority order:
        1. Retrying tasks (already started, need a retry)
        2. Pending tasks belonging to active goals (highest-priority first)
        3. Pending tasks from pending goals (to auto-activate the goal)

        Filters:
        - Tasks whose `depends_on` predecessors are not all COMPLETED are skipped.
        - Tasks whose `run_after` timestamp is in the future are skipped.
        """
        now = time.time()
        candidates: list[tuple[tuple, float, Task]] = []  # (sort_key, ts, task)

        for task in self._tasks.values():
            if task.state not in (TaskState.PENDING, TaskState.RETRYING):
                continue

            goal = self._goals.get(task.goal_id)
            if goal is None:
                continue
            if goal.state in (GoalState.COMPLETED, GoalState.FAILED, GoalState.CANCELLED, GoalState.PAUSED):
                continue

            # Scheduled-start gate: skip if not yet time
            if task.run_after > 0 and now < task.run_after:
                continue

            # Dependency gate: all predecessor tasks must be COMPLETED
            if task.depends_on:
                unmet = [
                    dep_id for dep_id in task.depends_on
                    if self._tasks.get(dep_id, Task(id="", goal_id="", description="")).state
                    != TaskState.COMPLETED
                ]
                if unmet:
                    continue

            urgency = 0 if task.state == TaskState.RETRYING else 1
            sort_key = (urgency, goal.priority, task.priority)
            candidates.append((sort_key, task.created_at, task))

        candidates.sort(key=lambda x: (x[0], x[1]))
        result: list[dict[str, Any]] = []

        for _key, _ts, task in candidates[:limit]:
            goal = self._goals.get(task.goal_id)
            result.append({
                "task_id": task.id,
                "goal_id": task.goal_id,
                "description": task.description,
                "goal_description": goal.description if goal else "",
                "priority": task.priority,
                "state": task.state.value,
                "retry_count": task.retry_count,
                "context": task.context,
                "depends_on": task.depends_on,
                "run_after": task.run_after,
            })

        return result

    def retry_failed_tasks(self, goal_id: str) -> int:
        """Reset all FAILED tasks in a goal back to PENDING for re-execution.

        Returns the number of tasks reset.
        """
        goal = self._goals.get(goal_id)
        if goal is None:
            return 0
        reset = 0
        for task_id in goal.tasks:
            task = self._tasks.get(task_id)
            if task and task.state == TaskState.FAILED:
                task.state = TaskState.PENDING
                task.retry_count = 0
                task.error = ""
                task.started_at = 0.0
                task.finished_at = 0.0
                reset += 1
        if reset:
            if goal.state == GoalState.FAILED:
                goal.state = GoalState.ACTIVE
            self._update_goal_progress(goal_id)
            self._save()
            logger.info(
                "GoalManager[%s]: reset %d failed tasks in goal '%s'.",
                self.agent_name, reset, goal_id,
            )
        return reset

    # ── Progress ──────────────────────────────────────────────────────────────

    def _update_goal_progress(self, goal_id: str) -> None:
        goal = self._goals.get(goal_id)
        if goal is None:
            return
        total = len(goal.tasks)
        if total == 0:
            return
        done = sum(
            1 for tid in goal.tasks
            if self._tasks.get(tid, Task(id="", goal_id="", description="")).state
            in (TaskState.COMPLETED, TaskState.SKIPPED)
        )
        goal.progress = round(done / total, 4)

        # Auto-complete goal when all tasks are done
        all_done = all(
            self._tasks.get(tid, Task(id="", goal_id="", description="")).state
            in (TaskState.COMPLETED, TaskState.SKIPPED, TaskState.FAILED)
            for tid in goal.tasks
        )
        if all_done and goal.state == GoalState.ACTIVE and goal.progress > 0:
            any_failed = any(
                self._tasks.get(tid, Task(id="", goal_id="", description="")).state == TaskState.FAILED
                for tid in goal.tasks
            )
            if any_failed:
                goal.state = GoalState.FAILED
                goal.finished_at = time.time()
            else:
                goal.state = GoalState.COMPLETED
                goal.progress = 1.0
                goal.finished_at = time.time()

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_goal(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_goals(
        self,
        state: GoalState | None = None,
    ) -> list[Goal]:
        goals = list(self._goals.values())
        if state is not None:
            goals = [g for g in goals if g.state == state]
        return sorted(goals, key=lambda g: (g.priority, g.created_at))

    def list_tasks(
        self,
        goal_id: str | None = None,
        state: TaskState | None = None,
    ) -> list[Task]:
        tasks = list(self._tasks.values())
        if goal_id:
            tasks = [t for t in tasks if t.goal_id == goal_id]
        if state is not None:
            tasks = [t for t in tasks if t.state == state]
        return sorted(tasks, key=lambda t: (t.priority, t.created_at))

    # ── Full status report ────────────────────────────────────────────────────

    def status_report(self) -> dict[str, Any]:
        goals = list(self._goals.values())
        tasks = list(self._tasks.values())

        def _count_goals(state: GoalState) -> int:
            return sum(1 for g in goals if g.state == state)

        def _count_tasks(state: TaskState) -> int:
            return sum(1 for t in tasks if t.state == state)

        return {
            "agent": self.agent_name,
            "goals": {
                "total": len(goals),
                "active": _count_goals(GoalState.ACTIVE),
                "pending": _count_goals(GoalState.PENDING),
                "completed": _count_goals(GoalState.COMPLETED),
                "failed": _count_goals(GoalState.FAILED),
                "paused": _count_goals(GoalState.PAUSED),
            },
            "tasks": {
                "total": len(tasks),
                "pending": _count_tasks(TaskState.PENDING),
                "active": _count_tasks(TaskState.ACTIVE),
                "retrying": _count_tasks(TaskState.RETRYING),
                "completed": _count_tasks(TaskState.COMPLETED),
                "failed": _count_tasks(TaskState.FAILED),
            },
            "next_actions": self.next_actions(limit=5),
            "active_goals": [
                {"id": g.id, "description": g.description, "progress": g.progress}
                for g in goals if g.state == GoalState.ACTIVE
            ],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "agent": self.agent_name,
                "saved_at": time.time(),
                "goals": {gid: g.to_dict() for gid, g in self._goals.items()},
                "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
            }
            tmp = self._persist_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            tmp.replace(self._persist_path)
        except OSError as exc:
            logger.warning("GoalManager: could not persist state: %s", exc)

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for gid, gdata in data.get("goals", {}).items():
                self._goals[gid] = Goal.from_dict(gdata)
            for tid, tdata in data.get("tasks", {}).items():
                self._tasks[tid] = Task.from_dict(tdata)
            logger.info(
                "GoalManager[%s]: loaded %d goals, %d tasks from disk.",
                self.agent_name, len(self._goals), len(self._tasks),
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("GoalManager: could not load persisted state: %s", exc)

    # ── Repr ─────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        active_goals = sum(1 for g in self._goals.values() if g.state == GoalState.ACTIVE)
        pending_tasks = sum(1 for t in self._tasks.values() if t.state == TaskState.PENDING)
        return (
            f"GoalManager(agent={self.agent_name!r}, "
            f"goals={len(self._goals)} [{active_goals} active], "
            f"tasks={len(self._tasks)} [{pending_tasks} pending])"
        )
