import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.base_agent import BaseAgent
from core.workflow_engine import WorkflowEngine, WorkflowFeedback, HITLAction


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
    def __init__(self, delay=0.0, text="ok"):
        self.delay = delay
        self.text = text

    def chat(self, messages, **kwargs):
        return self.text

    async def async_chat(self, messages, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.text


class WorkflowAsyncRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_pipeline_async_with_async_hitl_callback(self):
        a1 = BaseAgent(name="a1", role="dev", tools=[])
        a2 = BaseAgent(name="a2", role="qa", tools=[])

        calls = {"count": 0}

        async def approve_cb(_checkpoint):
            calls["count"] += 1
            return WorkflowFeedback(action=HITLAction.APPROVE)

        engine = WorkflowEngine(
            registry=None,
            ai_adapter=_DummyAI(text="done"),
            memory=_DummyMemory(),
            tool_manager=None,
            hitl_mode=True,
            feedback_callback_async=approve_cb,
        )

        result = await engine.run_pipeline_async([a1, a2], "ship feature")
        self.assertEqual(result, "done")
        self.assertEqual(calls["count"], 2)

    async def test_run_broadcast_async_timeout_and_cancellation(self):
        a1 = BaseAgent(name="a1", role="dev", tools=[])
        a2 = BaseAgent(name="a2", role="qa", tools=[])

        engine = WorkflowEngine(
            registry=None,
            ai_adapter=_DummyAI(delay=0.2, text="slow"),
            memory=_DummyMemory(),
            tool_manager=None,
            hitl_mode=False,
        )

        results = await engine.run_broadcast_async(
            [a1, a2],
            "long task",
            timeout_seconds=0.01,
            max_parallel=1,
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(r, TimeoutError) for r in results))


if __name__ == "__main__":
    unittest.main()
