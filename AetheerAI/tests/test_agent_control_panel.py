"""Tests for the AgentControlPanel (GAP 5)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.agent_control_panel import AgentControlPanel, ControlEvent


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_loop():
    loop = MagicMock()
    loop.pause.return_value = True
    loop.resume.return_value = True
    loop.stop.return_value = True
    loop.start.return_value = True
    type(loop).state = PropertyMock(return_value=MagicMock(value="running"))
    loop.status.return_value = {
        "state": "running",
        "metrics": {"ticks": 10, "tasks_executed": 5},
    }
    loop.event_log.return_value = [
        {"ts": time.time(), "event": "task_completed", "agent": "test_bot"},
    ]
    return loop


@pytest.fixture
def mock_goal_manager():
    gm = MagicMock()
    gm.status_report.return_value = {
        "goals": {"total": 2, "active": 1},
        "tasks": {"total": 5, "pending": 2},
    }
    gm.cancel_goal.return_value = True
    gm.pause_goal.return_value = True
    gm.fail_task.return_value = True
    gm.add_goal.return_value = "goal-123"
    gm.list_goals.return_value = []
    gm.list_tasks.return_value = []
    return gm


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.get_decisions.return_value = [{"id": "d1", "description": "Test"}]
    mem.get_work_history.return_value = [{"id": "w1", "description": "Work"}]
    mem.update_decision_outcome.return_value = True
    mem.status.return_value = {"decisions": 5, "work_items": 10}
    return mem


@pytest.fixture
def mock_guardrails():
    gc = MagicMock()
    gc.update_rules.return_value = None
    gc.rules = MagicMock()
    gc.rules.to_dict.return_value = {"max_transaction": 500}
    gc.status.return_value = {"rules": {}, "rate_counts": {}}
    return gc


@pytest.fixture
def panel(tmp_path, mock_loop, mock_goal_manager, mock_memory, mock_guardrails):
    p = AgentControlPanel(agent_name="test_bot", log_dir=tmp_path / "control")
    p.register_loop(mock_loop)
    p.register_goal_manager(mock_goal_manager)
    p.register_memory(mock_memory)
    p.register_guardrails(mock_guardrails)
    return p


# ── Pause / Resume / Stop ────────────────────────────────────────────────────

class TestAgentControl:
    def test_pause(self, panel, mock_loop):
        result = panel.pause(operator="admin")
        assert result["status"] == "paused"
        mock_loop.pause.assert_called_once()

    def test_resume(self, panel, mock_loop):
        result = panel.resume(operator="admin")
        assert result["status"] == "running"
        mock_loop.resume.assert_called_once()

    def test_stop(self, panel, mock_loop):
        result = panel.stop(operator="admin")
        assert result["status"] == "stopped"
        mock_loop.stop.assert_called_once()

    def test_pause_without_loop(self, tmp_path):
        panel = AgentControlPanel(agent_name="no_loop", log_dir=tmp_path)
        result = panel.pause()
        assert result["status"] == "error"


# ── Inspect ──────────────────────────────────────────────────────────────────

class TestInspect:
    def test_inspect_returns_all_sections(self, panel):
        result = panel.inspect()
        assert result["agent"] == "test_bot"
        assert result["loop"] is not None
        assert result["goals"] is not None
        assert len(result["recent_decisions"]) > 0
        assert len(result["recent_work"]) > 0

    def test_agent_state(self, panel):
        state = panel.agent_state()
        assert state == "running"


# ── Override ─────────────────────────────────────────────────────────────────

class TestOverride:
    def test_override_decision(self, panel):
        result = panel.override_decision("d1", "denied", operator="admin", reason="Too risky")
        assert result["status"] == "overridden"

    def test_override_nonexistent(self, panel, mock_memory):
        mock_memory.update_decision_outcome.return_value = False
        result = panel.override_decision("nonexistent", "denied")
        assert result["status"] == "error"


# ── Review Logs ──────────────────────────────────────────────────────────────

class TestReviewLogs:
    def test_review_logs(self, panel):
        panel.pause(operator="admin")
        logs = panel.review_logs(limit=10)
        assert len(logs) > 0
        assert logs[0]["source"] == "control_panel"

    def test_review_with_filter(self, panel):
        panel.pause()
        panel.resume()
        logs = panel.review_logs(event_type="pause")
        assert all(entry.get("action") == "pause" for entry in logs if entry.get("source") == "control_panel")


# ── Update Config ────────────────────────────────────────────────────────────

class TestUpdateConfig:
    def test_update_config(self, panel, mock_guardrails):
        result = panel.update_config({"max_transaction": 200}, operator="admin")
        assert result["status"] == "updated"
        mock_guardrails.update_rules.assert_called_with({"max_transaction": 200})

    def test_update_without_guardrails(self, tmp_path):
        panel = AgentControlPanel(agent_name="no_gc", log_dir=tmp_path)
        result = panel.update_config({"max_transaction": 200})
        assert result["status"] == "error"


# ── Goal management ─────────────────────────────────────────────────────────

class TestGoalManagement:
    def test_cancel_goal(self, panel, mock_goal_manager):
        result = panel.cancel_goal("goal-abc")
        assert result["status"] == "cancelled"
        mock_goal_manager.cancel_goal.assert_called_with("goal-abc")

    def test_pause_goal(self, panel, mock_goal_manager):
        result = panel.pause_goal("goal-xyz")
        assert result["status"] == "paused"


# ── Dashboard ────────────────────────────────────────────────────────────────

class TestDashboard:
    def test_dashboard(self, panel):
        dash = panel.dashboard()
        assert dash["agent"] == "test_bot"
        assert "activity" in dash
        assert "recent_logs" in dash
        assert "guardrail_rules" in dash
        assert dash["guardrail_rules"]["max_transaction"] == 500


# ── Event persistence ────────────────────────────────────────────────────────

class TestEventPersistence:
    def test_events_persist(self, tmp_path, mock_loop, mock_goal_manager):
        panel1 = AgentControlPanel(agent_name="persist_test", log_dir=tmp_path)
        panel1.register_loop(mock_loop)
        panel1.pause(operator="admin")
        panel1.resume(operator="admin")

        panel2 = AgentControlPanel(agent_name="persist_test", log_dir=tmp_path)
        assert len(panel2._events) == 2
