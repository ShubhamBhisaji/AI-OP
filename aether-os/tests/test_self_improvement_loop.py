import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.eval_runner import EvalRunner
from core.self_improve import SelfImproveCoordinator


class SelfImproveLoopTests(unittest.TestCase):
    def test_eval_runner_computes_pass_rate(self):
        runner = EvalRunner()
        cases = [
            {"id": "1", "prompt": "hello", "expected_contains": "world"},
            {"id": "2", "prompt": "ping", "expected_contains": "pong"},
        ]

        def run_fn(prompt: str) -> str:
            return {"hello": "hello world", "ping": "timeout"}.get(prompt, "")

        result = runner.run_cases(cases, run_fn=run_fn)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 1)

    def test_self_improver_clusters_failures(self):
        coord = SelfImproveCoordinator()
        cases = [
            {"id": "ok", "prompt": "a", "expected_contains": "alpha"},
            {"id": "bad", "prompt": "b", "expected_contains": "beta"},
        ]

        def run_fn(prompt: str) -> str:
            return "alpha" if prompt == "a" else "gamma"

        report = coord.run_once(cases, run_fn=run_fn)
        self.assertIn("eval_summary", report)
        self.assertIn("failure_clusters", report)
        self.assertGreaterEqual(len(report["recommendations"]), 1)
        self.assertEqual(report["eval_summary"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
