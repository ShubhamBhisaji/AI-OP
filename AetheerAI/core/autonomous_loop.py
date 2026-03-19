"""autonomous_loop.py — Continuous autonomous goal execution engine.

Closes GAP 2: Goal / Task Engine Is Weak.

Transforms agents from reactive tools into continuous autonomous workers
by implementing the core loop:

    Check Goals → Plan Actions → Execute → Evaluate → Repeat

The AutonomousGoalLoop runs as a background thread (or can be driven
manually via tick()) and continuously:

    1. Checks the GoalManager for pending/active goals and next actions
    2. Plans: selects the highest-priority actionable task
    3. Executes: dispatches the task to the agent's execute callback
    4. Evaluates: records success/failure, updates goal progress
    5. Repeats: sleeps briefly, then loops

The loop is stoppable, pausable, and observable.  It integrates with the
existing GoalManager, MemoryManager, and GovernanceLayer.

Usage
-----
    loop = AutonomousGoalLoop(
        agent_name="store_bot",
        goal_manager=goal_manager,
        execute_fn=agent.execute_task,
    )
    loop.start()       # background thread
    loop.pause()       # pause without stopping
    loop.resume()      # resume from pause
    loop.stop()        # graceful shutdown
    loop.status()      # introspection dict
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Loop state ────────────────────────────────────────────────────────────────

class LoopState(str, Enum):
    IDLE     = "idle"
    RUNNING  = "running"
    PAUSED   = "paused"
    STOPPING = "stopping"
    STOPPED  = "stopped"
    ERROR    = "error"


@dataclass
class LoopMetrics:
    """Runtime metrics for the autonomous loop."""
    ticks: int = 0
    tasks_executed: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    goals_completed: int = 0
    goals_failed: int = 0
    errors: int = 0
    last_tick_at: float = 0.0
    last_task_at: float = 0.0
    last_error: str = ""
    started_at: float = 0.0
    total_execution_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticks": self.ticks,
            "tasks_executed": self.tasks_executed,
            "tasks_succeeded": self.tasks_succeeded,
            "tasks_failed": self.tasks_failed,
            "goals_completed": self.goals_completed,
            "goals_failed": self.goals_failed,
            "errors": self.errors,
            "last_tick_at": self.last_tick_at,
            "last_task_at": self.last_task_at,
            "last_error": self.last_error,
            "started_at": self.started_at,
            "avg_execution_ms": round(
                self.total_execution_ms / max(1, self.tasks_executed), 2
            ),
        }


@dataclass
class LoopConfig:
    """Configuration for the autonomous loop."""
    tick_interval_seconds: float = 5.0        # Time between loop ticks
    max_consecutive_failures: int = 5         # Pause after N consecutive failures
    max_tasks_per_tick: int = 1               # Tasks to execute per tick
    idle_backoff_seconds: float = 15.0        # Extra sleep when no work available
    max_runtime_seconds: float = 0.0          # 0 = unlimited
    evaluation_enabled: bool = True           # Run post-execution evaluation


# ── Execute callback type ────────────────────────────────────────────────────

ExecuteFn = Callable[[str, dict[str, Any]], str]
"""
Signature: (task_description, context) -> result_string

The autonomous loop calls this function to dispatch tasks to the agent.
The function should:
  - Execute the task described by task_description
  - Return a string result (even if brief)
  - Raise an exception if the task fails
"""

EvaluateFn = Callable[[str, str, bool], dict[str, Any]]
"""
Signature: (task_description, result, success) -> evaluation_dict

Optional post-execution evaluator. Returns a dict with at minimum:
  - "quality": float (0.0 - 1.0)
  - "notes": str
"""


# ── AutonomousGoalLoop ────────────────────────────────────────────────────────

class AutonomousGoalLoop:
    """
    Continuous autonomous goal execution engine.

    Runs a background loop: Check → Plan → Execute → Evaluate → Repeat.

    Parameters
    ----------
    agent_name    : Name of the agent this loop drives.
    goal_manager  : GoalManager instance for goal/task tracking.
    execute_fn    : Callback to dispatch tasks for execution.
    evaluate_fn   : Optional post-execution quality evaluator.
    memory        : Optional MemoryManager (ScopedMemory) for persisting loop state.
    governance    : Optional GovernanceLayer for safety checks.
    config        : LoopConfig with timing and limit settings.
    """

    def __init__(
        self,
        agent_name: str,
        goal_manager: Any,
        execute_fn: ExecuteFn,
        evaluate_fn: EvaluateFn | None = None,
        memory: Any = None,
        governance: Any = None,
        config: LoopConfig | None = None,
    ) -> None:
        self.agent_name = agent_name
        self._goal_manager = goal_manager
        self._execute_fn = execute_fn
        self._evaluate_fn = evaluate_fn
        self._memory = memory
        self._governance = governance
        self._config = config or LoopConfig()
        self._state = LoopState.IDLE
        self._metrics = LoopMetrics()
        self._consecutive_failures = 0
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._lock = threading.Lock()

        # Event log for observability
        self._event_log: list[dict[str, Any]] = []
        self._max_event_log = 200

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the autonomous loop in a background thread."""
        with self._lock:
            if self._state in (LoopState.RUNNING, LoopState.STOPPING):
                logger.warning("AutonomousLoop[%s]: already %s.", self.agent_name, self._state.value)
                return False

            self._state = LoopState.RUNNING
            self._stop_event.clear()
            self._pause_event.set()
            self._metrics.started_at = time.time()
            self._consecutive_failures = 0

        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"AutonomousLoop-{self.agent_name}",
            daemon=True,
        )
        self._thread.start()
        self._log_event("loop_started")
        logger.info("AutonomousLoop[%s]: started.", self.agent_name)
        return True

    def stop(self, timeout: float = 10.0) -> bool:
        """Gracefully stop the loop."""
        with self._lock:
            if self._state not in (LoopState.RUNNING, LoopState.PAUSED):
                return False
            self._state = LoopState.STOPPING

        self._stop_event.set()
        self._pause_event.set()  # Unblock if paused

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        with self._lock:
            self._state = LoopState.STOPPED

        self._log_event("loop_stopped")
        logger.info("AutonomousLoop[%s]: stopped.", self.agent_name)
        return True

    def pause(self) -> bool:
        """Pause the loop (finish current task, then wait)."""
        with self._lock:
            if self._state != LoopState.RUNNING:
                return False
            self._state = LoopState.PAUSED
            self._pause_event.clear()

        self._log_event("loop_paused")
        logger.info("AutonomousLoop[%s]: paused.", self.agent_name)
        return True

    def resume(self) -> bool:
        """Resume from paused state."""
        with self._lock:
            if self._state != LoopState.PAUSED:
                return False
            self._state = LoopState.RUNNING
            self._pause_event.set()

        self._log_event("loop_resumed")
        logger.info("AutonomousLoop[%s]: resumed.", self.agent_name)
        return True

    # ── Manual tick (for testing / non-threaded use) ─────────────────────────

    def tick(self) -> dict[str, Any]:
        """Run a single loop iteration manually. Returns tick result."""
        return self._execute_tick()

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Background thread entry point."""
        try:
            while not self._stop_event.is_set():
                # Wait if paused
                self._pause_event.wait(timeout=1.0)
                if self._stop_event.is_set():
                    break

                # Check runtime limit
                if self._config.max_runtime_seconds > 0:
                    elapsed = time.time() - self._metrics.started_at
                    if elapsed > self._config.max_runtime_seconds:
                        logger.info(
                            "AutonomousLoop[%s]: max runtime reached (%.0fs).",
                            self.agent_name, elapsed,
                        )
                        break

                # Execute one tick
                tick_result = self._execute_tick()

                # Back off if no work
                if not tick_result.get("task_executed"):
                    self._stop_event.wait(timeout=self._config.idle_backoff_seconds)
                else:
                    self._stop_event.wait(timeout=self._config.tick_interval_seconds)

        except Exception as exc:
            logger.error("AutonomousLoop[%s]: fatal error: %s", self.agent_name, exc)
            with self._lock:
                self._state = LoopState.ERROR
                self._metrics.last_error = str(exc)
            self._log_event("loop_error", {"error": str(exc)})

    def _execute_tick(self) -> dict[str, Any]:
        """Run one iteration of Check → Plan → Execute → Evaluate."""
        self._metrics.ticks += 1
        self._metrics.last_tick_at = time.time()
        result: dict[str, Any] = {"tick": self._metrics.ticks, "task_executed": False}

        # ── CHECK: Get next actions from GoalManager ──────────────────
        try:
            next_actions = self._goal_manager.next_actions(
                limit=self._config.max_tasks_per_tick
            )
        except Exception as exc:
            logger.warning("AutonomousLoop[%s]: goal check failed: %s", self.agent_name, exc)
            self._metrics.errors += 1
            result["error"] = str(exc)
            return result

        if not next_actions:
            result["status"] = "no_work"
            return result

        # ── PLAN: Select highest-priority task ────────────────────────
        action = next_actions[0]
        task_id = action["task_id"]
        description = action["description"]
        context = action.get("context", {})

        # ── Governance check ──────────────────────────────────────────
        if self._governance:
            try:
                from core.governance_layer import GovernanceContext
                gov_ctx = GovernanceContext(
                    workflow_id=f"autoloop-{self.agent_name}",
                    max_runtime_seconds=int(self._config.max_runtime_seconds),
                    max_budget_usd=0,
                )
                self._governance.check_limits(gov_ctx)
            except (TimeoutError, RuntimeError) as exc:
                logger.warning("AutonomousLoop[%s]: governance blocked: %s", self.agent_name, exc)
                result["blocked_by"] = "governance"
                result["error"] = str(exc)
                return result

        # ── EXECUTE ───────────────────────────────────────────────────
        self._goal_manager.start_task(task_id)
        result["task_executed"] = True
        result["task_id"] = task_id
        result["description"] = description

        start_time = time.time()
        try:
            task_result = self._execute_fn(description, context)
            elapsed_ms = (time.time() - start_time) * 1000

            self._goal_manager.complete_task(task_id, result=str(task_result)[:4000])
            self._metrics.tasks_executed += 1
            self._metrics.tasks_succeeded += 1
            self._metrics.last_task_at = time.time()
            self._metrics.total_execution_ms += elapsed_ms
            self._consecutive_failures = 0

            result["success"] = True
            result["result"] = str(task_result)[:500]
            result["elapsed_ms"] = round(elapsed_ms, 2)

            self._log_event("task_completed", {
                "task_id": task_id,
                "description": description[:100],
                "elapsed_ms": round(elapsed_ms, 2),
            })

            # ── EVALUATE ──────────────────────────────────────────────
            if self._config.evaluation_enabled and self._evaluate_fn:
                try:
                    evaluation = self._evaluate_fn(description, str(task_result), True)
                    result["evaluation"] = evaluation
                except Exception as eval_exc:
                    logger.debug("AutonomousLoop[%s]: evaluation failed: %s", self.agent_name, eval_exc)

            # Persist to memory
            if self._memory:
                try:
                    self._memory.remember_task(
                        task=description,
                        output=str(task_result)[:2000],
                        success=True,
                        metadata={"task_id": task_id, "elapsed_ms": round(elapsed_ms, 2)},
                    )
                except Exception:
                    pass

        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = str(exc)

            self._goal_manager.fail_task(task_id, error=error_msg[:1000])
            self._metrics.tasks_executed += 1
            self._metrics.tasks_failed += 1
            self._metrics.last_error = error_msg[:500]
            self._metrics.total_execution_ms += elapsed_ms
            self._consecutive_failures += 1

            result["success"] = False
            result["error"] = error_msg[:500]
            result["elapsed_ms"] = round(elapsed_ms, 2)

            self._log_event("task_failed", {
                "task_id": task_id,
                "description": description[:100],
                "error": error_msg[:200],
            })

            # Auto-pause on too many consecutive failures
            if self._consecutive_failures >= self._config.max_consecutive_failures:
                logger.warning(
                    "AutonomousLoop[%s]: %d consecutive failures — auto-pausing.",
                    self.agent_name, self._consecutive_failures,
                )
                self.pause()
                result["auto_paused"] = True

            # Persist failure to memory
            if self._memory:
                try:
                    self._memory.remember_task(
                        task=description,
                        output=error_msg[:2000],
                        success=False,
                        metadata={"task_id": task_id, "error": error_msg[:500]},
                    )
                except Exception:
                    pass

        # ── Check if goal completed ───────────────────────────────────
        goal_id = action.get("goal_id")
        if goal_id:
            goal = self._goal_manager.get_goal(goal_id)
            if goal:
                from core.goal_manager import GoalState
                if goal.state == GoalState.COMPLETED:
                    self._metrics.goals_completed += 1
                    self._log_event("goal_completed", {"goal_id": goal_id})
                elif goal.state == GoalState.FAILED:
                    self._metrics.goals_failed += 1
                    self._log_event("goal_failed", {"goal_id": goal_id})

        return result

    # ── Introspection ────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Full status snapshot of the autonomous loop."""
        with self._lock:
            state = self._state.value

        goal_status = {}
        try:
            goal_status = self._goal_manager.status_report()
        except Exception:
            pass

        return {
            "agent_name": self.agent_name,
            "state": state,
            "metrics": self._metrics.to_dict(),
            "config": {
                "tick_interval_seconds": self._config.tick_interval_seconds,
                "max_consecutive_failures": self._config.max_consecutive_failures,
                "max_tasks_per_tick": self._config.max_tasks_per_tick,
                "idle_backoff_seconds": self._config.idle_backoff_seconds,
                "max_runtime_seconds": self._config.max_runtime_seconds,
            },
            "consecutive_failures": self._consecutive_failures,
            "goal_status": goal_status,
            "recent_events": self._event_log[-20:],
        }

    @property
    def state(self) -> LoopState:
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state == LoopState.RUNNING

    def event_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._event_log[-max(1, min(limit, self._max_event_log)):]

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _log_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        entry = {
            "ts": time.time(),
            "event": event_type,
            "agent": self.agent_name,
            **(data or {}),
        }
        self._event_log.append(entry)
        if len(self._event_log) > self._max_event_log:
            self._event_log = self._event_log[-self._max_event_log:]

    def __repr__(self) -> str:
        return (
            f"AutonomousGoalLoop(agent={self.agent_name!r}, "
            f"state={self._state.value}, "
            f"ticks={self._metrics.ticks}, "
            f"tasks={self._metrics.tasks_executed})"
        )
