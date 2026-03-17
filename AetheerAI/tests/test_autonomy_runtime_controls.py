import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.base_agent import BaseAgent
from agents.ceo_agent import CEOAgent, TaskRecord
from core.aetheerai_kernel import AetheerAiKernel
from core.governance_layer import GovernanceContext
from core.workflow_engine import WorkflowEngine


class _DummyMemory:
    def __init__(self):
        self._store = {}

    def save(self, key, value, namespace="global"):
        self._store[(namespace, key)] = value

    def load(self, key, default=None, namespace="global"):
        return self._store.get((namespace, key), default)

    def append(self, key, value, namespace="global"):
        cur = self._store.get((namespace, key), [])
        if not isinstance(cur, list):
            cur = [cur]
        cur.append(value)
        self._store[(namespace, key)] = cur


class _DummyAI:
    def __init__(self):
        self.calls = 0
        self.provider = "openai"
        self.model = "gpt-4o"
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._session_usage = {"total_tokens": 0}

    @property
    def total_tokens(self):
        return self._session_usage.get("total_tokens", 0)

    def chat(self, messages, **kwargs):
        self.calls += 1
        return "ok"


class _DummyDecision:
    def __init__(self, outcome: str, reasoning: str = "", violated_rule: str | None = None):
        self.outcome = SimpleNamespace(value=outcome)
        self.reasoning = reasoning
        self.violated_rule = violated_rule


class _BlockingPriorityController:
    def evaluate(self, agent_name: str, action_summary: str):
        return _DummyDecision("block", "Destructive action denied", "security_first")


class _BlockingFinOps:
    @staticmethod
    def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        return 5.0

    def can_spend(self, estimated_cost: float) -> bool:
        return False

    def status(self) -> dict:
        return {"remaining_usd": 0.0}


class WorkflowRuntimeControlTests(unittest.TestCase):
    def setUp(self):
        self.ai = _DummyAI()
        self.engine = WorkflowEngine(
            registry=None,
            ai_adapter=self.ai,
            memory=_DummyMemory(),
            tool_manager=None,
            hitl_mode=False,
        )
        self.agent = BaseAgent(name="ops", role="operations", tools=[])

    def test_policy_gate_blocks_execution_before_ai_call(self):
        self.engine.priority_controller = _BlockingPriorityController()

        result = self.engine.execute(self.agent, "Delete production data")

        self.assertTrue(str(result).startswith("POLICY_BLOCKED:"))
        self.assertEqual(self.ai.calls, 0, "AI call should not occur when policy blocks action")

    def test_budget_gate_blocks_execution_before_ai_call(self):
        self.engine.finops_controller = _BlockingFinOps()

        result = self.engine.execute(self.agent, "Run expensive analysis")

        self.assertTrue(str(result).startswith("BUDGET_BLOCKED:"))
        self.assertEqual(self.ai.calls, 0, "AI call should not occur when budget is exhausted")


class CEOPriorityAndResourceTests(unittest.TestCase):
    def _ceo(self) -> CEOAgent:
        kernel = SimpleNamespace(
            ai_adapter=_DummyAI(),
            workflow_engine=object(),
            registry=SimpleNamespace(get=lambda _name: None),
            factory=SimpleNamespace(),
            memory=_DummyMemory(),
            lifecycle=None,
        )
        return CEOAgent(kernel=kernel)

    def test_runnable_tasks_prioritize_critical_first(self):
        ceo = self._ceo()
        tasks = [
            TaskRecord(index=0, title="low", description="", agent_type="operations", priority="low", depends_on=[], require_approval=False),
            TaskRecord(index=1, title="critical", description="", agent_type="operations", priority="critical", depends_on=[], require_approval=False),
            TaskRecord(index=2, title="high", description="", agent_type="operations", priority="high", depends_on=[], require_approval=False),
            TaskRecord(index=3, title="medium", description="", agent_type="operations", priority="medium", depends_on=[], require_approval=False),
        ]

        ordered = ceo._runnable_tasks(tasks)

        self.assertEqual([task.title for task in ordered], ["critical", "high", "medium", "low"])

    def test_strategy_reduces_workers_under_budget_pressure(self):
        ceo = self._ceo()
        ctx = GovernanceContext(
            workflow_id="wf",
            max_runtime_seconds=600,
            max_budget_usd=1.0,
        )
        ctx.spent_usd = 0.9

        mode, workers = ceo._select_execution_strategy(
            runnable_count=5,
            parallel=True,
            offline_local_enabled=False,
            governance_ctx=ctx,
        )

        self.assertEqual(mode, "sequential")
        self.assertEqual(workers, 1)


class KernelLifecycleWrapperTests(unittest.TestCase):
    def test_lifecycle_record_uses_correct_argument_names(self):
        calls = {}

        class _Lifecycle:
            def record_performance(self, agent_name, **kwargs):
                calls["agent_name"] = agent_name
                calls.update(kwargs)

        kernel = object.__new__(AetheerAiKernel)
        kernel.lifecycle = _Lifecycle()

        kernel.lifecycle_record("agent-1", success=True, duration_ms=2500, task="deploy")

        self.assertEqual(calls["agent_name"], "agent-1")
        self.assertEqual(calls["task_type"], "deploy")
        self.assertAlmostEqual(calls["duration_sec"], 2.5, places=3)
        self.assertTrue(calls["success"])

    def test_lifecycle_list_flattens_by_state(self):
        class _Lifecycle:
            def summary(self):
                return {
                    "by_state": {
                        "warm": ["a", "b"],
                        "idle": ["c"],
                        "cold": [],
                        "retired": ["d"],
                    }
                }

            def list_by_state(self, state):
                return [state]

        kernel = object.__new__(AetheerAiKernel)
        kernel.lifecycle = _Lifecycle()

        all_names = kernel.lifecycle_list()
        warm = kernel.lifecycle_list("warm")

        self.assertEqual(all_names, ["a", "b", "c", "d"])
        self.assertEqual(warm, ["warm"])


if __name__ == "__main__":
    unittest.main()
