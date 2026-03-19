"""
mission_control.py — Unified Mission-Driven Orchestration for AetheerAI.

Closes BLOCKER 6: Task/Goal Orchestration Still Basic.

MissionControl is the single entry point that wires together every
goal-execution subsystem into one coherent "worker control plane":

    GoalManager       → persistent goals & task state machine
    AutonomousGoalLoop → continuous background execution per agent
    GoalScheduler     → time-based / recurring goal scheduling
    JobScheduler      → priority job queue (bridged for non-loop execution)
    SelfHealingDebugger → AI-powered failure recovery (via kernel)

Features delivered
------------------
  ✓ Persistent goals   — JSON-backed per-agent GoalManager instances
  ✓ Task queues        — AutonomousGoalLoop drains tasks continuously
  ✓ Scheduling         — GoalScheduler fires goals at specific times / intervals
  ✓ Retry logic        — GoalManager retry_count / max_retries + TaskState.RETRYING
  ✓ Failure recovery   — retry_failed_tasks() + auto-healing via SelfHealingDebugger
  ✓ Prioritization     — 1–10 goal & task priority enforced in next_actions()
  ✓ Dependency chains  — depends_on field gates task start on predecessors
  ✓ Health checks      — per-agent loop status + aggregate health summary

Usage
-----
    mc = MissionControl(scheduler=kernel.scheduler, execute_fn=kernel.run_agent)
    mc.start()

    # Launch a mission (creates persistent goal + tasks, starts background loop)
    goal_id = mc.launch(
        agent_name="store_bot",
        goal="Reduce cart abandonment by 10%",
        tasks=["Send recovery emails", "Update discount logic", "Analyse results"],
        priority=2,
    )

    # Scheduled mission — fires at a specific time
    mc.schedule(
        agent_name="analytics_bot",
        goal="Generate weekly KPI report",
        tasks=["Pull metrics", "Build charts", "Send email"],
        run_at=datetime(2026, 3, 21, 9, 0),
    )

    # Recurring mission — repeats every 6 hours
    mc.schedule_recurring(
        agent_name="ops_bot",
        goal="Monitor system health",
        tasks=["Ping services", "Check error rates", "Alert if degraded"],
        interval_seconds=6 * 3600,
    )

    # Introspection
    status = mc.status("store_bot")
    report = mc.health_check()

    # Control
    mc.pause("store_bot")
    mc.resume("store_bot")
    mc.cancel("store_bot", goal_id)
    mc.retry_failed("store_bot", goal_id)

    mc.stop()   # graceful global shutdown
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Workspace paths ──────────────────────────────────────────────────────────

_WORKSPACE = Path(__file__).parent.parent / "workspace"
_GOALS_DIR = _WORKSPACE / "goals"
_SCHED_DIR = _WORKSPACE / "scheduled_goals"

_GOALS_DIR.mkdir(parents=True, exist_ok=True)
_SCHED_DIR.mkdir(parents=True, exist_ok=True)

# Max loop idle backoff (prevents CPU spin when no work is available)
_IDLE_BACKOFF_SEC: float = 20.0
# Max consecutive task failures before a loop auto-pauses
_MAX_CONSECUTIVE_FAILURES: int = 5


# ── MissionControl ───────────────────────────────────────────────────────────

class MissionControl:
    """
    Central coordinator for persistent, mission-driven agent execution.

    Parameters
    ----------
    scheduler       : JobScheduler from kernel (used as fallback / bridge).
    execute_fn      : Callable(agent_name, task_description) -> result_str.
                      If None, tasks are queued into the JobScheduler only.
    governance      : Optional GovernanceLayer for risk checks.
    tick_interval   : Seconds between autonomous loop ticks (default 5).
    """

    def __init__(
        self,
        scheduler: Any | None = None,
        execute_fn: Callable[[str, str], Any] | None = None,
        governance: Any | None = None,
        tick_interval: float = 5.0,
    ) -> None:
        self._scheduler = scheduler
        self._execute_fn = execute_fn
        self._governance = governance
        self._tick_interval = tick_interval

        # Per-agent GoalManagers (keyed by agent_name)
        self._goal_managers: dict[str, Any] = {}
        # Per-agent AutonomousGoalLoops (keyed by agent_name)
        self._loops: dict[str, Any] = {}
        # Shared GoalScheduler
        self._goal_scheduler: Any | None = None

        # RLock prevents deadlocks when factory methods call each other while
        # holding the same coordination lock.
        self._lock = threading.RLock()
        self._started = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the GoalScheduler and all registered autonomous loops."""
        with self._lock:
            if self._started:
                return
            self._started = True

        # Start any pre-registered loops
        with self._lock:
            loops = list(self._loops.values())

        for loop in loops:
            try:
                loop.start()
            except Exception as exc:
                logger.warning("MissionControl: loop start error: %s", exc)

        # Start the shared GoalScheduler
        self._ensure_goal_scheduler()
        if self._goal_scheduler:
            self._goal_scheduler.start()

        logger.info("MissionControl: started (%d agent loops).", len(loops))

    def stop(self, timeout: float = 10.0) -> None:
        """Gracefully stop all loops and the GoalScheduler."""
        with self._lock:
            loops = list(self._loops.values())
            self._started = False

        for loop in loops:
            try:
                loop.stop(timeout=timeout)
            except Exception as exc:
                logger.warning("MissionControl: loop stop error: %s", exc)

        if self._goal_scheduler:
            try:
                self._goal_scheduler.stop()
            except Exception:
                pass

        logger.info("MissionControl: stopped.")

    # ── Goal manager factory ─────────────────────────────────────────────────

    def _goal_manager_for(self, agent_name: str) -> Any:
        """Return (or create) the persistent GoalManager for an agent."""
        with self._lock:
            if agent_name not in self._goal_managers:
                from core.goal_manager import GoalManager
                persist_path = _GOALS_DIR / f"{agent_name}.json"
                gm = GoalManager(agent_name=agent_name, persist_path=persist_path)
                self._goal_managers[agent_name] = gm
            return self._goal_managers[agent_name]

    def _loop_for(self, agent_name: str) -> Any:
        """Return (or create) the AutonomousGoalLoop for an agent."""
        with self._lock:
            if agent_name not in self._loops:
                self._loops[agent_name] = self._build_loop(agent_name)
            return self._loops[agent_name]

    def _build_loop(self, agent_name: str) -> Any:
        from core.autonomous_loop import AutonomousGoalLoop, LoopConfig

        gm = self._goal_manager_for(agent_name)

        def _execute(task_description: str, context: dict) -> str:
            if self._execute_fn:
                result = self._execute_fn(agent_name, task_description)
                return str(result) if result is not None else ""
            # Fallback: bridge to JobScheduler
            if self._scheduler:
                job_id = self._scheduler.schedule(
                    name=f"{agent_name}:{task_description[:40]}",
                    agent_name=agent_name,
                    task=task_description,
                    priority=50,
                )
                return f"[queued:{job_id}]"
            return "[no executor]"

        config = LoopConfig(
            tick_interval_seconds=self._tick_interval,
            idle_backoff_seconds=_IDLE_BACKOFF_SEC,
            max_consecutive_failures=_MAX_CONSECUTIVE_FAILURES,
        )
        return AutonomousGoalLoop(
            agent_name=agent_name,
            goal_manager=gm,
            execute_fn=_execute,
            governance=self._governance,
            config=config,
        )

    def _ensure_goal_scheduler(self) -> Any:
        """Lazy-init the shared GoalScheduler."""
        with self._lock:
            if self._goal_scheduler is None:
                try:
                    from core.scheduled_goals import GoalScheduler
                    persist_path = _SCHED_DIR / "scheduled_goals.json"
                    self._goal_scheduler = GoalScheduler(
                        goal_manager=None,
                        tick_interval=10.0,
                        persist_path=persist_path,
                        on_dlq_alert=self._on_dlq_alert,
                        goal_manager_factory=self._goal_manager_for_scheduler,
                    )
                except Exception as exc:
                    logger.warning("MissionControl: GoalScheduler init failed: %s", exc)
        return self._goal_scheduler

    def _goal_manager_for_scheduler(self, agent_name: str) -> Any:
        """GoalManager resolver used by GoalScheduler dispatch.

        Ensures an execution loop exists and is running for the agent when
        scheduled goals are emitted, so dispatched tasks are actually consumed.
        """
        gm = self._goal_manager_for(agent_name)
        if self._started:
            loop = self._loop_for(agent_name)
            from core.autonomous_loop import LoopState
            if hasattr(loop, "_state") and loop._state not in (
                LoopState.RUNNING,
                LoopState.STOPPING,
            ):
                loop.start()
        return gm

    def _on_dlq_alert(self, entry: Any) -> None:
        logger.error(
            "MissionControl: DEAD-LETTER — goal '%s' for agent '%s' failed permanently: %s",
            entry.description[:60], entry.agent_name, entry.error[:200],
        )

    # ── Core API ─────────────────────────────────────────────────────────────

    def launch(
        self,
        agent_name: str,
        goal: str,
        tasks: list[str | dict] | None = None,
        *,
        priority: int = 5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        max_retries_per_task: int = 2,
        auto_start_loop: bool = True,
    ) -> str:
        """
        Create a persistent goal with tasks and start the agent's execution loop.

        Parameters
        ----------
        agent_name         : Target agent (loop is created on demand).
        goal               : High-level goal description.
        tasks              : List of task descriptions (str) or dicts with keys:
                              - description (required)
                              - priority (1–10, optional)
                              - depends_on (list[str] of task_id, optional)
                              - run_after (UTC unix timestamp, optional)
                              - max_retries (optional)
                              - tags (list[str], optional)
                              - context (dict, optional)
        priority           : Goal priority 1 (highest) – 10 (lowest).
        tags               : Goal-level tags.
        metadata           : Arbitrary goal metadata.
        max_retries_per_task: Default retry budget for each task.
        auto_start_loop    : If True, start the AutonomousGoalLoop if not running.

        Returns
        -------
        str — goal_id of the created goal.
        """
        if not agent_name or not str(agent_name).strip():
            raise ValueError("agent_name is required.")
        if not goal or not str(goal).strip():
            raise ValueError("goal is required.")

        agent_name = str(agent_name).strip()
        goal = str(goal).strip()

        gm = self._goal_manager_for(agent_name)
        goal_id = gm.add_goal(
            description=goal,
            priority=max(1, min(10, priority)),
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )

        # Add tasks in order; track id of each for depends_on wiring
        task_id_map: dict[int, str] = {}  # index → task_id (for relative deps)
        items: list[str | dict] = list(tasks or [])
        for idx, item in enumerate(items):
            if isinstance(item, str):
                cfg: dict[str, Any] = {"description": item}
            else:
                cfg = dict(item)

            desc = str(cfg.get("description", "")).strip()
            if not desc:
                continue

            # Resolve symbolic "depends_on" — allows ["task:0", "task:1"] notation
            raw_deps: list[str] = list(cfg.get("depends_on") or [])
            resolved_deps: list[str] = []
            for dep in raw_deps:
                if str(dep).startswith("task:"):
                    try:
                        ref_idx = int(str(dep).split(":", 1)[1])
                    except (TypeError, ValueError):
                        continue
                    if ref_idx in task_id_map:
                        resolved_deps.append(task_id_map[ref_idx])
                elif dep:
                    resolved_deps.append(str(dep))

            tid = gm.add_task(
                goal_id=goal_id,
                description=desc,
                priority=int(cfg.get("priority", priority)),
                max_retries=int(cfg.get("max_retries", max_retries_per_task)),
                tags=list(cfg.get("tags") or []),
                context=dict(cfg.get("context") or {}),
                depends_on=resolved_deps,
                run_after=float(cfg.get("run_after") or 0.0),
            )
            task_id_map[idx] = tid

        logger.info(
            "MissionControl: launched goal '%s' for '%s' (id=%s, %d tasks).",
            goal[:60], agent_name, goal_id, len(task_id_map),
        )

        if auto_start_loop:
            loop = self._loop_for(agent_name)
            from core.autonomous_loop import LoopState
            if hasattr(loop, "_state") and loop._state not in (
                LoopState.RUNNING, LoopState.STOPPING
            ):
                loop.start()

        return goal_id

    def schedule(
        self,
        agent_name: str,
        goal: str,
        tasks: list[str] | None = None,
        *,
        run_at: float | datetime | None = None,
        priority: int = 5,
        max_retries: int = 2,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Schedule a one-time goal to run at a specific time.

        Returns the scheduled-goal ID.
        """
        sched = self._ensure_goal_scheduler()
        if sched is None:
            raise RuntimeError("GoalScheduler is unavailable.")

        ts: float | None = None
        if isinstance(run_at, datetime):
            ts = run_at.timestamp()
        elif run_at is not None:
            ts = float(run_at)

        return sched.schedule(
            description=goal,
            agent_name=agent_name,
            run_at=ts,
            tasks=list(tasks or []),
            priority=priority,
            max_retries=max_retries,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )

    def schedule_recurring(
        self,
        agent_name: str,
        goal: str,
        interval_seconds: float,
        tasks: list[str] | None = None,
        *,
        priority: int = 5,
        max_retries: int = 2,
        tags: list[str] | None = None,
        run_at: float | datetime | None = None,
    ) -> str:
        """Schedule a recurring goal that repeats every `interval_seconds`.

        Returns the scheduled-goal ID.
        """
        sched = self._ensure_goal_scheduler()
        if sched is None:
            raise RuntimeError("GoalScheduler is unavailable.")

        ts: float | None = None
        if isinstance(run_at, datetime):
            ts = run_at.timestamp()
        elif run_at is not None:
            ts = float(run_at)

        return sched.schedule_recurring(
            description=goal,
            agent_name=agent_name,
            interval_seconds=interval_seconds,
            tasks=list(tasks or []),
            priority=priority,
            max_retries=max_retries,
            tags=list(tags or []),
            run_at=ts,
        )

    # ── Flow control ─────────────────────────────────────────────────────────

    def pause(self, agent_name: str) -> bool:
        """Pause the execution loop for an agent (current task finishes first)."""
        loop = self._loops.get(agent_name)
        if loop is None:
            return False
        result = loop.pause()
        logger.info("MissionControl: paused loop for '%s'.", agent_name)
        return result

    def resume(self, agent_name: str) -> bool:
        """Resume a paused execution loop."""
        loop = self._loops.get(agent_name)
        if loop is None:
            return False
        result = loop.resume()
        logger.info("MissionControl: resumed loop for '%s'.", agent_name)
        return result

    def cancel(self, agent_name: str, goal_id: str) -> bool:
        """Cancel a goal and skip all its remaining tasks."""
        gm = self._goal_managers.get(agent_name)
        if gm is None:
            return False
        return gm.cancel_goal(goal_id)

    def retry_failed(self, agent_name: str, goal_id: str) -> int:
        """Reset all FAILED tasks in a goal to PENDING for re-execution.

        Returns the number of tasks reset.
        """
        gm = self._goal_managers.get(agent_name)
        if gm is None:
            return 0
        return gm.retry_failed_tasks(goal_id)

    def stop_agent(self, agent_name: str, timeout: float = 10.0) -> bool:
        """Stop the execution loop for a specific agent."""
        loop = self._loops.pop(agent_name, None)
        if loop is None:
            return False
        return loop.stop(timeout=timeout)

    # ── Introspection ────────────────────────────────────────────────────────

    def status(self, agent_name: str) -> dict[str, Any]:
        """Full status snapshot for an agent: loop state + goal/task summary."""
        gm = self._goal_managers.get(agent_name)
        loop = self._loops.get(agent_name)

        goal_report: dict[str, Any] = {}
        if gm:
            try:
                goal_report = gm.status_report()
            except Exception:
                pass

        loop_report: dict[str, Any] = {}
        if loop:
            try:
                loop_report = loop.status()
            except Exception:
                pass

        return {
            "agent_name": agent_name,
            "goal_summary": goal_report,
            "loop": loop_report,
            "has_goals": gm is not None,
            "has_loop": loop is not None,
        }

    def list_agents(self) -> list[str]:
        """Return all agent names tracked by MissionControl."""
        with self._lock:
            names = set(self._goal_managers.keys()) | set(self._loops.keys())
        return sorted(names)

    def list_goals(self, agent_name: str, state: str | None = None) -> list[dict[str, Any]]:
        """List goals for an agent, optionally filtered by state."""
        gm = self._goal_managers.get(agent_name)
        if gm is None:
            return []
        from core.goal_manager import GoalState
        gstate = GoalState(state) if state else None
        goals = gm.list_goals(state=gstate)
        return [g.to_dict() for g in goals]

    def list_tasks(self, agent_name: str, goal_id: str | None = None,
                   state: str | None = None) -> list[dict[str, Any]]:
        """List tasks for an agent, optionally filtered by goal and/or state."""
        gm = self._goal_managers.get(agent_name)
        if gm is None:
            return []
        from core.goal_manager import TaskState
        tstate = TaskState(state) if state else None
        tasks = gm.list_tasks(goal_id=goal_id, state=tstate)
        return [t.to_dict() for t in tasks]

    def health_check(self) -> dict[str, Any]:
        """Aggregate health report across all agents."""
        agents = self.list_agents()
        agent_reports: list[dict[str, Any]] = []
        overall_healthy = True

        for name in agents:
            s = self.status(name)
            loop_state = s.get("loop", {}).get("state", "unknown")
            healthy = loop_state in ("running", "idle", "paused", "stopped")
            if not healthy:
                overall_healthy = False
            agent_reports.append({
                "agent": name,
                "loop_state": loop_state,
                "healthy": healthy,
                "goals": s.get("goal_summary", {}).get("goals", {}),
            })

        sched_status: dict[str, Any] = {}
        if self._goal_scheduler:
            try:
                sched_status = self._goal_scheduler.status()
            except Exception:
                pass

        return {
            "healthy": overall_healthy,
            "agents": agent_reports,
            "scheduler": sched_status,
            "total_agents": len(agents),
            "checked_at": time.time(),
        }

    def list_scheduled_goals(self) -> list[dict[str, Any]]:
        """List all scheduled (time-based / recurring) goals."""
        sched = self._goal_scheduler
        if sched is None:
            return []
        try:
            with sched._lock:
                return [s.to_dict() for s in sched._scheduled.values()]
        except Exception:
            return []

    def cancel_scheduled(self, scheduled_id: str) -> bool:
        """Cancel a scheduled goal by its scheduled-goal ID."""
        sched = self._goal_scheduler
        if sched is None:
            return False
        return sched.cancel(scheduled_id)
