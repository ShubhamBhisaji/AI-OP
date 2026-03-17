"""Tests for core/job_executor.py."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.job_executor import (  # noqa: E402
    DistributedHTTPJobExecutor,
    LocalJobExecutor,
    build_job_executor,
)


class _DummyResponse:
    def __init__(self, payload: str):
        self._payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class TestLocalJobExecutor(unittest.TestCase):
    def test_local_executor_delegates(self):
        calls = []

        def runner(agent_name: str, task: str) -> str:
            calls.append((agent_name, task))
            return "ok"

        executor = LocalJobExecutor(runner=runner)
        out = executor.execute("analyst", "summarize")

        self.assertEqual(out, "ok")
        self.assertEqual(calls, [("analyst", "summarize")])
        self.assertEqual(executor.info()["mode"], "local")


class TestDistributedHTTPJobExecutor(unittest.TestCase):
    def test_distributed_executor_parses_result_payload(self):
        body = json.dumps({"success": True, "data": {"result": "remote-ok"}})

        with patch("core.job_executor.urlopen", return_value=_DummyResponse(body)):
            executor = DistributedHTTPJobExecutor(endpoint="http://worker/execute")
            out = executor.execute("researcher", "find sources")

        self.assertEqual(out, "remote-ok")

    def test_distributed_executor_falls_back_to_local_runner(self):
        def local_runner(agent_name: str, task: str) -> str:
            return f"local:{agent_name}:{task}"

        with patch("core.job_executor.urlopen", side_effect=OSError("network down")):
            executor = DistributedHTTPJobExecutor(
                endpoint="http://worker/execute",
                local_fallback=local_runner,
            )
            out = executor.execute("dev", "ship")

        self.assertEqual(out, "local:dev:ship")


class TestBuildJobExecutor(unittest.TestCase):
    def test_build_defaults_to_local(self):
        executor = build_job_executor(lambda a, t: "ok", env={})
        self.assertEqual(executor.info()["mode"], "local")

    def test_build_uses_distributed_when_endpoint_set(self):
        env = {
            "AETHEERAI_DISTRIBUTED_EXECUTOR_URL": "http://worker/execute",
            "AETHEERAI_DISTRIBUTED_EXECUTOR_TIMEOUT_SEC": "12",
            "AETHEERAI_DISTRIBUTED_EXECUTOR_FALLBACK_LOCAL": "0",
        }
        executor = build_job_executor(lambda a, t: "ok", env=env)
        info = executor.info()

        self.assertEqual(info["mode"], "distributed")
        self.assertEqual(info["transport"], "http")
        self.assertEqual(info["timeout_seconds"], 12.0)
        self.assertFalse(info["fallback_enabled"])


if __name__ == "__main__":
    unittest.main()
