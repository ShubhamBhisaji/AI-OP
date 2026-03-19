"""Tests for the AutonomousGoalLoop (GAP 2)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.autonomous_loop import (
    AutonomousGoalLoop,
    LoopConfig,
    LoopMetrics,
    LoopState,
)
from core.goal_manager import GoalManager, GoalState, TaskState


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def goal_manager(tmp_path):
    return GoalManager(agent_name="test_bot", persist_path=tmp_path / "goals.json")


@pytest.fixture
def execute_fn():
    """Simple execute function that returns a result."""
    def fn(description: str, context: dict) -> str:
        return f"Executed: {description}"
    return fn


@pytest.fixture
def failing_execute_fn():
    """Execute function that always fails."""
    def fn(description: str, context: dict) -> str:
        raise RuntimeError(f"Task failed: {description}")
    return fn


@pytest.fixture
def loop(goal_manager, execute_fn):
    return AutonomousGoalLoop(
        agent_name="test_bot",
        goal_manager=goal_manager,
        execute_fn=execute_fn,
        config=LoopConfig(tick_interval_seconds=0.1, idle_backoff_seconds=0.1),
    )


# ── Tick execution ───────────────────────────────────────────────────────────

class TestTickExecution:
    def test_tick_no_work(self, loop):
        result = loop.tick()
        assert result["task_executed"] is False
        assert result.get("status") == "no_work"

    def test_tick_executes_task(self, loop, goal_manager):
        goal_id = goal_manager.add_goal("Test goal")
        goal_manager.add_task(goal_id, "Do something")
        goal_manager.start_goal(goal_id)

        result = loop.tick()
        assert result["task_executed"] is True
        assert result["success"] is True
        assert "Executed" in result["result"]

    def test_tick_records_metrics(self, loop, goal_manager):
        goal_id = goal_manager.add_goal("Test goal")
        goal_manager.add_task(goal_id, "Do something")
        goal_manager.start_goal(goal_id)

        loop.tick()
        status = loop.status()
        assert status["metrics"]["tasks_executed"] == 1
        assert status["metrics"]["tasks_succeeded"] == 1

    def test_tick_handles_failure(self, goal_manager, failing_execute_fn):
        loop = AutonomousGoalLoop(
            agent_name="test_bot",
            goal_manager=goal_manager,
            execute_fn=failing_execute_fn,
            config=LoopConfig(max_consecutive_failures=3),
        )
        goal_id = goal_manager.add_goal("Test goal")
        goal_manager.add_task(goal_id, "Failing task")
        goal_manager.start_goal(goal_id)

        result = loop.tick()
        assert result["task_executed"] is True
        assert result["success"] is False
        assert "error" in result

    def test_auto_pause_on_consecutive_failures(self, goal_manager, failing_execute_fn):
        loop = AutonomousGoalLoop(
            agent_name="test_bot",
            goal_manager=goal_manager,
            execute_fn=failing_execute_fn,
            config=LoopConfig(max_consecutive_failures=2),
        )
        goal_id = goal_manager.add_goal("Test goal")
        for i in range(3):
            goal_manager.add_task(goal_id, f"Failing task {i}")
        goal_manager.start_goal(goal_id)

        # First tick — retrying task
        loop.tick()
        # Second tick — should auto-pause
        loop._state = LoopState.RUNNING  # Simulate running state
        loop.tick()
        assert loop.state == LoopState.PAUSED


# ── Lifecycle ────────────────────────────────────────────────────────────────

class TestLifecycle:
    def test_start_stop(self, loop):
        assert loop.state == LoopState.IDLE
        loop.start()
        assert loop.state == LoopState.RUNNING
        time.sleep(0.2)
        loop.stop()
        assert loop.state == LoopState.STOPPED

    def test_pause_resume(self, loop):
        loop.start()
        assert loop.pause() is True
        assert loop.state == LoopState.PAUSED
        assert loop.resume() is True
        assert loop.state == LoopState.RUNNING
        loop.stop()

    def test_cannot_start_twice(self, loop):
        loop.start()
        assert loop.start() is False
        loop.stop()

    def test_cannot_pause_when_idle(self, loop):
        assert loop.pause() is False


# ── Status and introspection ─────────────────────────────────────────────────

class TestStatus:
    def test_status_report(self, loop):
        status = loop.status()
        assert status["agent_name"] == "test_bot"
        assert "metrics" in status
        assert "config" in status

    def test_event_log(self, loop, goal_manager):
        goal_id = goal_manager.add_goal("Test goal")
        goal_manager.add_task(goal_id, "Task 1")
        goal_manager.start_goal(goal_id)
        loop.tick()
        events = loop.event_log(limit=10)
        assert len(events) > 0

    def test_metrics_tracking(self, loop, goal_manager):
        goal_id = goal_manager.add_goal("Test goal")
        goal_manager.add_task(goal_id, "Task 1")
        goal_manager.add_task(goal_id, "Task 2")
        goal_manager.start_goal(goal_id)

        loop.tick()
        loop.tick()

        status = loop.status()
        assert status["metrics"]["tasks_executed"] == 2


# ── Memory integration ──────────────────────────────────────────────────────

class TestMemoryIntegration:
    def test_remembers_tasks(self, goal_manager, execute_fn):
        memory = MagicMock()
        loop = AutonomousGoalLoop(
            agent_name="test_bot",
            goal_manager=goal_manager,
            execute_fn=execute_fn,
            memory=memory,
            config=LoopConfig(tick_interval_seconds=0.1),
        )
        goal_id = goal_manager.add_goal("Test")
        goal_manager.add_task(goal_id, "Do X")
        goal_manager.start_goal(goal_id)

        loop.tick()
        memory.remember_task.assert_called_once()

    def test_remembers_failures(self, goal_manager, failing_execute_fn):
        memory = MagicMock()
        loop = AutonomousGoalLoop(
            agent_name="test_bot",
            goal_manager=goal_manager,
            execute_fn=failing_execute_fn,
            memory=memory,
            config=LoopConfig(max_consecutive_failures=10),
        )
        goal_id = goal_manager.add_goal("Test")
        goal_manager.add_task(goal_id, "Fail X")
        goal_manager.start_goal(goal_id)

        loop.tick()
        memory.remember_task.assert_called_once()
        call_kwargs = memory.remember_task.call_args[1]
        assert call_kwargs["success"] is False


# ── Evaluation ───────────────────────────────────────────────────────────────

class TestEvaluation:
    def test_evaluator_called(self, goal_manager, execute_fn):
        evaluator = MagicMock(return_value={"quality": 0.9, "notes": "Good"})
        loop = AutonomousGoalLoop(
            agent_name="test_bot",
            goal_manager=goal_manager,
            execute_fn=execute_fn,
            evaluate_fn=evaluator,
        )
        goal_id = goal_manager.add_goal("Test")
        goal_manager.add_task(goal_id, "Evaluate me")
        goal_manager.start_goal(goal_id)

        result = loop.tick()
        evaluator.assert_called_once()
        assert "evaluation" in result
