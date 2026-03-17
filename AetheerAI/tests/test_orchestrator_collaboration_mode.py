"""Tests for Orchestrator collaboration auto-mode behavior."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.orchestrator import Orchestrator


class DummyAgent:
    def __init__(self, name: str, role: str = "research_agent") -> None:
        self.name = name
        self.role = role
        self.profile = {"skills": ["analysis"]}


class DummyRegistry:
    def __init__(self) -> None:
        self._agents = {
            "alpha": DummyAgent("alpha", "research_agent"),
            "beta": DummyAgent("beta", "developer_agent"),
        }

    def list_names(self) -> list[str]:
        return list(self._agents.keys())

    def get(self, name: str):
        return self._agents.get(name)


class DummyWorkflowEngine:
    def execute(self, agent, task: str) -> str:
        return f"{agent.name}:{task[:50]}"


class TestOrchestratorCollaborationMode(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DummyRegistry()
        self.workflow = DummyWorkflowEngine()

    def test_orchestrate_collaborate_mode_uses_runner(self):
        ai = MagicMock()
        ai.chat.return_value = (
            "MODE: collaborate\n"
            "AGENTS: alpha,beta\n"
            "REASON: requires teamwork"
        )

        calls: dict = {}

        def runner(*, goal: str, agent_names: list[str], rounds: int):
            calls["goal"] = goal
            calls["agent_names"] = agent_names
            calls["rounds"] = rounds
            return {
                "session_id": "sess-1",
                "team": agent_names,
                "turns": [],
                "final_synthesis": "team outcome",
            }

        orchestrator = Orchestrator(
            registry=self.registry,
            ai_adapter=ai,
            workflow_engine=self.workflow,
            collaboration_runner=runner,
        )

        out = orchestrator.orchestrate("ship feature")

        self.assertEqual(out["mode"], "collaborate")
        self.assertEqual(out["session"]["session_id"], "sess-1")
        self.assertEqual(out["summary"], "team outcome")
        self.assertEqual(calls["goal"], "ship feature")
        self.assertEqual(calls["agent_names"], ["alpha", "beta"])
        self.assertEqual(calls["rounds"], 2)

    def test_orchestrate_collaborate_without_runner_falls_back_to_broadcast(self):
        ai = MagicMock()
        ai.chat.return_value = (
            "MODE: collaborate\n"
            "AGENTS: alpha,beta\n"
            "REASON: requires teamwork"
        )

        orchestrator = Orchestrator(
            registry=self.registry,
            ai_adapter=ai,
            workflow_engine=self.workflow,
        )

        out = orchestrator.orchestrate("investigate issue")

        self.assertEqual(out["mode"], "broadcast")
        self.assertIn("results", out)
        self.assertEqual(len(out["results"]), 2)

    def test_orchestrate_collaborate_runner_error_falls_back_to_vote(self):
        ai = MagicMock()
        ai.chat.side_effect = [
            "MODE: collaborate\nAGENTS: alpha,beta\nREASON: teamwork",
            "consensus output",
        ]

        def bad_runner(**_kwargs):
            raise RuntimeError("boom")

        orchestrator = Orchestrator(
            registry=self.registry,
            ai_adapter=ai,
            workflow_engine=self.workflow,
            collaboration_runner=bad_runner,
        )

        out = orchestrator.orchestrate("triage outage")

        self.assertEqual(out["mode"], "vote")
        self.assertEqual(out.get("consensus"), "consensus output")
        self.assertIn("responses", out)


if __name__ == "__main__":
    unittest.main()
