"""
Tests for core/job_scheduler.py

Covers:
  - Immediate job enqueue and execution
  - Priority ordering (lower number executes first)
  - Future scheduling (run_at in the past triggers immediately)
  - Recurring interval job (re-enqueues after completion)
  - Retry-with-backoff on failure
  - Permanent failure after max_retries exhausted
  - Job cancellation
  - Persistence: load from store
  - Scheduler stats
"""

import json
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.job_scheduler import JobScheduler, JobRecord


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_scheduler(tmp_dir: Path, executor_fn=None) -> JobScheduler:
    """Create a scheduler with a temp store and synthetic executor."""
    if executor_fn is None:
        def executor_fn(agent_name: str, task: str) -> str:
            return f"done:{agent_name}:{task}"
    store = tmp_dir / "job_store.json"
    return JobScheduler(executor_fn=executor_fn, max_workers=2, store_path=store)


def _wait_for(condition, timeout: float = 5.0, interval: float = 0.05) -> bool:
    """Poll a condition function until it returns True or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


# ── Test cases ─────────────────────────────────────────────────────────────────

class TestJobSchedulerImmediate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_immediate_job_completes(self):
        results = []
        def executor(agent, task):
            results.append((agent, task))
            return "ok"

        s = _make_scheduler(self._tmpdir, executor)
        s.start()
        try:
            jid = s.schedule(name="test", agent_name="alice", task="do something")
            ran = _wait_for(lambda: s.status(jid)["status"] == "completed")
            self.assertTrue(ran, "Job did not complete within timeout")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0], ("alice", "do something"))
        finally:
            s.stop(wait=True)

    def test_result_stored(self):
        s = _make_scheduler(self._tmpdir)
        s.start()
        try:
            jid = s.schedule(name="r", agent_name="bob", task="compute")
            _wait_for(lambda: s.status(jid)["status"] == "completed")
            rec = s.status(jid)
            self.assertIn("done:bob:compute", rec["result"])
        finally:
            s.stop(wait=True)

    def test_multiple_jobs_all_complete(self):
        s = _make_scheduler(self._tmpdir)
        s.start()
        try:
            ids = [s.schedule(name=f"j{i}", agent_name="a", task=f"t{i}") for i in range(5)]
            done = _wait_for(lambda: all(s.status(j)["status"] == "completed" for j in ids))
            self.assertTrue(done, "Not all jobs completed")
        finally:
            s.stop(wait=True)


class TestJobSchedulerPriority(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_lower_priority_number_runs_first(self):
        """When two jobs are queued, priority=0 should complete before priority=99."""
        order = []
        gate = threading.Event()

        def executor(agent, task):
            order.append(agent)
            return "ok"

        # Use 1 worker so only one job runs at a time
        store = self._tmpdir / "store.json"
        s = JobScheduler(executor_fn=executor, max_workers=1, store_path=store)
        # Don't start yet so both jobs are queued before execution begins
        jid_low  = s.schedule(name="high-prio", agent_name="FIRST",  task="x", priority=0)
        jid_high = s.schedule(name="low-prio",  agent_name="SECOND", task="x", priority=99)
        s.start()
        try:
            _wait_for(lambda: len(order) == 2)
            self.assertEqual(order[0], "FIRST", f"Expected FIRST, got {order}")
        finally:
            s.stop(wait=True)


class TestJobSchedulerFutureAndInterval(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_past_run_at_executes_immediately(self):
        s = _make_scheduler(self._tmpdir)
        s.start()
        try:
            past = time.time() - 10  # 10 seconds in the past
            jid = s.schedule(name="past", agent_name="a", task="t", run_at=past)
            done = _wait_for(lambda: s.status(jid)["status"] == "completed")
            self.assertTrue(done)
        finally:
            s.stop(wait=True)

    def test_interval_job_reruns(self):
        """An interval job should create a new pending job after completion."""
        counts = {"n": 0}
        def executor(agent, task):
            counts["n"] += 1
            return "ok"

        store = self._tmpdir / "store.json"
        s = JobScheduler(executor_fn=executor, max_workers=1, store_path=store)
        s.start()
        try:
            s.schedule(name="recur", agent_name="a", task="t", interval_sec=0.2)
            # Wait for at least 2 completions (original + 1 re-run)
            ran_twice = _wait_for(lambda: counts["n"] >= 2, timeout=8)
            self.assertTrue(ran_twice, f"Interval job only ran {counts['n']} time(s)")
        finally:
            s.stop(wait=True)


class TestJobSchedulerFailureAndRetry(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_job_retries_then_fails(self):
        attempt_count = {"n": 0}
        def bad_executor(agent, task):
            attempt_count["n"] += 1
            raise RuntimeError("simulated failure")

        s = _make_scheduler(self._tmpdir, bad_executor)
        s.start()
        try:
            jid = s.schedule(name="bad", agent_name="a", task="t", max_retries=2)
            # max_retries=2 means 3 total attempts before permanent failure
            failed = _wait_for(lambda: s.status(jid) and s.status(jid)["status"] == "failed", timeout=15)
            self.assertTrue(failed, f"Job status: {s.status(jid)}")
            self.assertEqual(attempt_count["n"], 3)
        finally:
            s.stop(wait=True)

    def test_job_succeeds_on_retry(self):
        call_n = {"n": 0}
        def flaky_executor(agent, task):
            call_n["n"] += 1
            if call_n["n"] < 2:
                raise RuntimeError("transient error")
            return "recovered"

        s = _make_scheduler(self._tmpdir, flaky_executor)
        s.start()
        try:
            jid = s.schedule(name="flaky", agent_name="a", task="t", max_retries=2)
            done = _wait_for(lambda: s.status(jid) and s.status(jid)["status"] == "completed", timeout=15)
            self.assertTrue(done)
            self.assertIn("recovered", s.status(jid)["result"])
        finally:
            s.stop(wait=True)


class TestJobSchedulerCancellation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_cancel_pending_job(self):
        # Schedule far in the future so it stays pending
        store = self._tmpdir / "store.json"
        s = JobScheduler(executor_fn=lambda a, t: "ok", max_workers=1, store_path=store)
        s.start()
        try:
            far_future = time.time() + 9999
            jid = s.schedule(name="future", agent_name="a", task="t", run_at=far_future)
            self.assertEqual(s.status(jid)["status"], "pending")
            ok = s.cancel(jid)
            self.assertTrue(ok)
            self.assertEqual(s.status(jid)["status"], "cancelled")
        finally:
            s.stop(wait=True)

    def test_cancel_nonexistent_returns_false(self):
        store = self._tmpdir / "store.json"
        s = JobScheduler(executor_fn=lambda a, t: "ok", max_workers=1, store_path=store)
        s.start()
        try:
            ok = s.cancel("nonexistent-job-id")
            self.assertFalse(ok)
        finally:
            s.stop(wait=True)


class TestJobSchedulerPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_store_written_after_schedule(self):
        store_path = self._tmpdir / "job_store.json"
        s = _make_scheduler(self._tmpdir)
        s.start()
        try:
            s.schedule(name="persist_test", agent_name="a", task="t")
            time.sleep(0.3)
            self.assertTrue(store_path.exists(), "Store file not created")
            data = json.loads(store_path.read_text())
            self.assertIn("jobs", data)
            self.assertGreater(len(data["jobs"]), 0)
        finally:
            s.stop(wait=True)

    def test_pending_jobs_reloaded_on_restart(self):
        store_path = self._tmpdir / "job_store.json"
        executed = {"ran": False}

        def executor(agent, task):
            executed["ran"] = True
            return "ok"

        # Phase 1: schedule a future job (won't run yet)
        far_future = time.time() + 9999
        s1 = JobScheduler(executor_fn=executor, max_workers=1, store_path=store_path)
        jid = s1.schedule(name="reload_test", agent_name="a", task="t", run_at=far_future)
        s1.stop(wait=False)

        # Phase 2: reload — job should still be pending
        s2 = JobScheduler(executor_fn=executor, max_workers=1, store_path=store_path)
        self.assertIsNotNone(s2.status(jid), "Job not reloaded from store")
        self.assertEqual(s2.status(jid)["status"], "pending")
        s2.stop(wait=False)


class TestJobSchedulerStats(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_stats_reflect_completed_jobs(self):
        s = _make_scheduler(self._tmpdir)
        s.start()
        try:
            jids = [s.schedule(name=f"s{i}", agent_name="a", task="t") for i in range(3)]
            _wait_for(lambda: all(s.status(j)["status"] == "completed" for j in jids))
            stats = s.stats()
            self.assertEqual(stats["by_status"].get("completed", 0), 3)
        finally:
            s.stop(wait=True)

    def test_list_jobs_filter_by_status(self):
        store = self._tmpdir / "store.json"
        far = time.time() + 9999
        s = JobScheduler(executor_fn=lambda a, t: "ok", max_workers=1, store_path=store)
        s.start()
        try:
            s.schedule(name="pending_job", agent_name="a", task="t", run_at=far)
            jid2 = s.schedule(name="immediate", agent_name="a", task="t")
            _wait_for(lambda: s.status(jid2)["status"] == "completed")
            pending = s.list_jobs(status_filter="pending")
            completed = s.list_jobs(status_filter="completed")
            self.assertEqual(len(pending), 1)
            self.assertGreaterEqual(len(completed), 1)
        finally:
            s.stop(wait=True)


if __name__ == "__main__":
    unittest.main()
