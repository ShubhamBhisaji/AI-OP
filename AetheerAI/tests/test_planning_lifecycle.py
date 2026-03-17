"""
Tests for:
- core/planning_engine.py
- factory/lifecycle_manager.py

Focuses on deterministic unit coverage:
- TaskGraph dependency scheduling and completion semantics
- PlanningEngine goal decomposition, JSON parsing, plan persistence, and execution
- AgentLifecycleManager state transitions, capabilities, smart dispatch, specialization, and persistence
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.planning_engine import PlanningEngine, TaskGraph, TaskNode
from factory.lifecycle_manager import AgentLifecycleManager


# ---------------------------------------------------------------------------
# Lightweight fakes
# ---------------------------------------------------------------------------

class DummyAgent:
    def __init__(self, profile: dict):
        self.profile = dict(profile)


class DummyRegistry:
    def __init__(self, profiles: dict[str, dict]):
        self._agents = {name: DummyAgent(p) for name, p in profiles.items()}

    def get(self, name: str):
        return self._agents.get(name)

    def list_agents(self) -> dict[str, dict]:
        return {name: dict(agent.profile) for name, agent in self._agents.items()}


class DummyWorkflowEngine:
    def execute(self, agent, task: str) -> str:
        role = agent.profile.get("role", "unknown") if agent else "none"
        return f"ok:{role}:{task[:40]}"


class FailingWorkflowEngine(DummyWorkflowEngine):
    def execute(self, agent, task: str) -> str:
        if "Primary" in task:
            return "error: simulated failure"
        return super().execute(agent, task)


class DummyGovernance:
    def check_limits(self, _ctx) -> None:
        return None


# ---------------------------------------------------------------------------
# TaskGraph tests
# ---------------------------------------------------------------------------

class TestTaskGraphBasics(unittest.TestCase):
    def test_ready_tasks_respect_dependencies(self):
        graph = TaskGraph(plan_id="p1", title="Demo", summary="demo plan")
        graph.add_task(TaskNode(id="t1", title="A", description="", agent_type="research_agent"))
        graph.add_task(TaskNode(id="t2", title="B", description="", agent_type="research_agent", depends_on=["t1"]))
        graph.add_task(TaskNode(id="t3", title="C", description="", agent_type="research_agent", depends_on=["t2"]))

        ready = [n.id for n in graph.ready_tasks()]
        self.assertEqual(ready, ["t1"])

        graph.update_task_status("t1", "completed", result="done")
        ready = [n.id for n in graph.ready_tasks()]
        self.assertEqual(ready, ["t2"])

        graph.update_task_status("t2", "completed", result="done")
        ready = [n.id for n in graph.ready_tasks()]
        self.assertEqual(ready, ["t3"])

    def test_is_complete_when_completed_or_skipped(self):
        graph = TaskGraph(plan_id="p2", title="Demo", summary="demo plan")
        graph.add_task(TaskNode(id="t1", title="A", description="", agent_type="research_agent"))
        graph.add_task(TaskNode(id="t2", title="B", description="", agent_type="research_agent"))

        self.assertFalse(graph.is_complete())
        graph.update_task_status("t1", "completed", result="ok")
        graph.update_task_status("t2", "skipped", error="blocked")
        self.assertTrue(graph.is_complete())


# ---------------------------------------------------------------------------
# PlanningEngine tests
# ---------------------------------------------------------------------------

class TestPlanningEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)

        profiles = {
            "researcher": {
                "role": "research_agent",
                "skills": ["research", "analysis"],
                "tools": ["search"],
                "permission_level": 2,
            },
            "developer": {
                "role": "developer_agent",
                "skills": ["python", "debugging"],
                "tools": ["code_runner"],
                "permission_level": 3,
            },
        }
        self.registry = DummyRegistry(profiles)

    def tearDown(self):
        self.tmp.cleanup()

    def _engine_with_ai_response(self, response_text: str) -> PlanningEngine:
        ai = MagicMock()
        ai.chat.return_value = response_text
        return PlanningEngine(
            workflow_engine=DummyWorkflowEngine(),
            registry=self.registry,
            ai_adapter=ai,
            governance=DummyGovernance(),
            self_healer=None,
            memory_manager=None,
        )

    def test_decompose_goal_builds_and_saves_graph(self):
        response = {
            "plan_title": "Launch Plan",
            "plan_summary": "Two-step plan",
            "tasks": [
                {
                    "id": "t1",
                    "title": "Research requirements",
                    "description": "Collect requirements",
                    "agent_type": "research_agent",
                    "depends_on": [],
                    "max_retries": 1,
                    "critical": True,
                },
                {
                    "id": "t2",
                    "title": "Implement feature",
                    "description": "Build implementation",
                    "agent_type": "developer_agent",
                    "depends_on": ["t1"],
                    "max_retries": 1,
                    "critical": True,
                },
            ],
        }
        engine = self._engine_with_ai_response(json.dumps(response))

        with patch.object(TaskGraph, "save", autospec=True, return_value=self.tmpdir / "plan_plan123.json") as save_mock:
            graph = engine.decompose_goal("Build feature X", plan_id="plan123")

        self.assertEqual(graph.plan_id, "plan123")
        self.assertEqual(graph.title, "Launch Plan")
        self.assertEqual(len(graph.all_tasks()), 2)
        save_mock.assert_called_once()

    def test_decompose_goal_accepts_markdown_fenced_json(self):
        fenced = """```json
{
  \"plan_title\": \"Fenced Plan\",
  \"plan_summary\": \"Valid inside fences\",
  \"tasks\": [
    {
      \"id\": \"t1\",
      \"title\": \"Research\",
      \"description\": \"Do research\",
      \"agent_type\": \"research_agent\",
      \"depends_on\": [],
      \"max_retries\": 1,
      \"critical\": true
    }
  ]
}
```"""
        engine = self._engine_with_ai_response(fenced)

        with patch.object(TaskGraph, "save", autospec=True, return_value=self.tmpdir / "plan_fenced1.json"):
            graph = engine.decompose_goal("Goal", plan_id="fenced1")

        self.assertEqual(graph.title, "Fenced Plan")
        self.assertEqual(len(graph.all_tasks()), 1)

    def test_execute_plan_runs_tasks_to_completion(self):
        engine = self._engine_with_ai_response("{}")
        graph = TaskGraph(plan_id="exec1", title="Run", summary="")
        graph.add_task(TaskNode(
            id="t1",
            title="Research",
            description="Read docs",
            agent_type="research_agent",
            depends_on=[],
            critical=True,
        ))
        graph.add_task(TaskNode(
            id="t2",
            title="Implement",
            description="Write code",
            agent_type="developer_agent",
            depends_on=["t1"],
            critical=True,
        ))

        with patch.object(TaskGraph, "save", autospec=True, return_value=self.tmpdir / "plan_exec1.json"):
            result = engine.execute_plan(graph, max_steps=10, max_workers=2)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["failed_tasks"], [])
        self.assertEqual(result["stats"].get("completed"), 2)
        self.assertTrue(graph.is_complete())

    def test_execute_plan_skips_tasks_blocked_by_failed_or_skipped_dependencies(self):
        ai = MagicMock()
        ai.chat.return_value = "{}"
        engine = PlanningEngine(
            workflow_engine=FailingWorkflowEngine(),
            registry=self.registry,
            ai_adapter=ai,
            governance=DummyGovernance(),
            self_healer=None,
            memory_manager=None,
        )
        graph = TaskGraph(plan_id="exec2", title="Fail chain", summary="")
        graph.add_task(TaskNode(
            id="t1",
            title="Primary",
            description="Fail here",
            agent_type="research_agent",
            depends_on=[],
            critical=False,
            max_retries=0,
        ))
        graph.add_task(TaskNode(
            id="t2",
            title="Secondary",
            description="Depends on t1",
            agent_type="developer_agent",
            depends_on=["t1"],
            critical=False,
        ))
        graph.add_task(TaskNode(
            id="t3",
            title="Tertiary",
            description="Depends on skipped t2",
            agent_type="developer_agent",
            depends_on=["t2"],
            critical=False,
        ))

        with patch.object(TaskGraph, "save", autospec=True, return_value=self.tmpdir / "plan_exec2.json"):
            result = engine.execute_plan(graph, max_steps=10, max_workers=2)

        statuses = {task["id"]: task["status"] for task in result["tasks"]}
        self.assertEqual(statuses["t1"], "failed")
        self.assertEqual(statuses["t2"], "skipped")
        self.assertEqual(statuses["t3"], "skipped")
        self.assertIn("t1", result["failed_tasks"])

    def test_build_graph_rejects_missing_tasks(self):
        engine = self._engine_with_ai_response("{}")
        with self.assertRaises(ValueError):
            engine._build_graph("p-missing", {"plan_title": "X", "tasks": []})


# ---------------------------------------------------------------------------
# AgentLifecycleManager tests
# ---------------------------------------------------------------------------

class TestLifecycleManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "lifecycle_store.json"

        profiles = {
            "researcher": {
                "role": "research_agent",
                "skills": ["market research"],
                "tools": ["search"],
                "permission_level": 2,
            },
            "developer": {
                "role": "developer_agent",
                "skills": ["python", "debugging"],
                "tools": ["code_runner"],
                "permission_level": 3,
            },
        }
        self.registry = DummyRegistry(profiles)

        # Prevent long-running background thread and isolate persistence path.
        self.p_store = patch("factory.lifecycle_manager._LIFECYCLE_STORE", self.store)
        self.p_decay = patch.object(AgentLifecycleManager, "_state_decay_loop", lambda self: None)
        self.p_store.start()
        self.p_decay.start()

    def tearDown(self):
        self.p_decay.stop()
        self.p_store.stop()
        self.tmp.cleanup()

    def _manager(self, ai=None) -> AgentLifecycleManager:
        return AgentLifecycleManager(registry=self.registry, ai_adapter=ai)

    def test_activate_deactivate_retire(self):
        mgr = self._manager()

        state = mgr.activate("researcher")
        self.assertEqual(state, "warm")

        state = mgr.deactivate("researcher")
        self.assertEqual(state, "idle")

        mgr.retire("researcher", reason="decommissioned")
        self.assertEqual(mgr.get_state("researcher"), "retired")

    def test_record_performance_updates_metrics(self):
        mgr = self._manager()

        mgr.record_performance("developer", task_type="build", success=True, duration_sec=2.0)
        mgr.record_performance("developer", task_type="test", success=False, duration_sec=4.0)

        cap = mgr.discover_capabilities("developer")
        perf = cap["performance"]

        self.assertEqual(perf["task_count"], 2)
        self.assertAlmostEqual(perf["success_rate"], 0.5, places=3)
        self.assertAlmostEqual(perf["avg_duration_sec"], 3.0, places=2)
        self.assertEqual(cap["state"], "warm")

    def test_compose_skills_reflected_in_capabilities(self):
        mgr = self._manager()

        updated = mgr.compose_skills("developer", ["incident response", "python"])

        self.assertIn("incident response", updated)
        cap = mgr.discover_capabilities("developer")
        self.assertIn("incident response", cap["skills"])

    def test_find_best_agent_keyword_match(self):
        mgr = self._manager()
        mgr.activate("researcher")
        mgr.activate("developer")
        mgr.record_performance("developer", task_type="coding", success=True, duration_sec=1.0)

        best = mgr.find_best_agent("Need python debugging with code runner support")

        self.assertEqual(best, "developer")

    def test_auto_specialize_applies_ai_suggestions(self):
        ai = MagicMock()
        ai.chat.return_value = json.dumps({
            "add_skills": ["incident response"],
            "add_tools": ["terminal_tool"],
            "reasoning": "Recent tasks show incident workflows.",
        })
        mgr = self._manager(ai=ai)

        out = mgr.auto_specialize("developer")

        self.assertIn("incident response", out.get("added_skills", []))
        self.assertIn("terminal_tool", out.get("added_tools", []))

        agent = self.registry.get("developer")
        self.assertIn("terminal_tool", agent.profile.get("tools", []))
        cap = mgr.discover_capabilities("developer")
        self.assertIn("incident response", cap.get("skills", []))

    def test_persistence_round_trip(self):
        mgr1 = self._manager()
        mgr1.activate("researcher")
        mgr1.compose_skills("researcher", ["competitive analysis"])
        mgr1.record_performance("researcher", task_type="analysis", success=True, duration_sec=1.5)

        self.assertTrue(self.store.exists(), "Expected lifecycle store to exist")

        mgr2 = self._manager()
        state = mgr2.get_state("researcher")
        cap = mgr2.discover_capabilities("researcher")

        self.assertEqual(state, "warm")
        self.assertIn("competitive analysis", cap["skills"])
        self.assertGreaterEqual(cap["performance"]["task_count"], 1)


if __name__ == "__main__":
    unittest.main()
