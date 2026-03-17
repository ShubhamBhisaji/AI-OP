"""Tests for graceful shutdown handling in the Upstash worker."""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workers import upstash_job_worker


class _NoopQueue:
    queue_name = "job_queue"

    def push_job(self, payload, queue_name=None, priority=None):  # pragma: no cover - defensive in case retries are hit.
        del payload, queue_name, priority
        return 1


class _ProcessStore:
    def __init__(self):
        self.running = []
        self.completed = []
        self.failed = []
        self.requeued = []
        self.dead_lettered = []

    def get_job(self, job_id):
        return {"id": job_id, "status": "queued", "metadata": {}}

    def create_job(self, **_kwargs):
        return {}

    def mark_running(self, job_id, retry_count=0, max_retries=0):
        self.running.append((job_id, retry_count, max_retries))

    def mark_completed(self, job_id, result):
        self.completed.append((job_id, result))

    def mark_failed(self, job_id, message):
        self.failed.append((job_id, message))

    def mark_requeued_for_retry(self, job_id, *, error_message, retry_count, max_retries, reason):
        self.requeued.append((job_id, error_message, retry_count, max_retries, reason))

    def mark_dead_lettered(self, job_id, *, error_message, retry_count, max_retries, reason, dlq_queue):
        self.dead_lettered.append((job_id, error_message, retry_count, max_retries, reason, dlq_queue))


class _InterruptingQueue:
    queue_name = "job_queue"

    def __init__(self):
        self.calls = 0

    def blocking_pop(self, timeout_seconds):
        self.calls += 1
        if self.calls == 1:
            return {"jobId": "job-1", "taskType": "goal", "task": {"goal": "Ship update"}}
        raise KeyboardInterrupt()


class _WorkerStore:
    def __init__(self):
        self.failed = []

    def mark_failed(self, job_id, message):
        self.failed.append((job_id, message))


class WorkerShutdownTests(unittest.TestCase):
    def test_process_job_payload_keyboard_interrupt_requeues_with_retry_budget(self):
        store = _ProcessStore()

        ok = upstash_job_worker._process_job_payload(
            payload={"jobId": "job-int", "taskType": "goal", "task": {"goal": "Handle interrupt"}},
            queue=_NoopQueue(),
            store=store,
            run_job=lambda _task_type, _task_data: (_ for _ in ()).throw(KeyboardInterrupt()),
            worker_id="test-worker",
            claim_lease_seconds=60,
            max_retries=1,
            retry_backoff_base_seconds=0.0,
            retry_backoff_max_seconds=0.0,
            dlq_queue_name="job_queue_dlq",
        )

        self.assertFalse(ok)
        self.assertEqual(store.running[0][0], "job-int")
        self.assertEqual(len(store.completed), 0)
        self.assertEqual(len(store.failed), 0)
        self.assertEqual(len(store.requeued), 1)
        self.assertEqual(store.requeued[0][0], "job-int")
        self.assertEqual(store.requeued[0][2], 1)
        self.assertEqual(store.requeued[0][3], 1)
        self.assertIn("interrupt", store.requeued[0][4])

    def test_run_worker_marks_inflight_job_failed_on_shutdown(self):
        queue = _InterruptingQueue()
        store = _WorkerStore()

        def _slow_process(**_kwargs):
            time.sleep(0.25)
            return False

        with patch.object(upstash_job_worker, "UpstashRedisQueue", return_value=queue), patch.object(
            upstash_job_worker, "SupabaseJobStore", return_value=store
        ), patch.object(upstash_job_worker, "_supported_shutdown_signals", return_value=()), patch.object(
            upstash_job_worker, "_recover_stale_running_jobs", return_value=0
        ), patch.object(upstash_job_worker, "_process_job_payload", side_effect=_slow_process):
            upstash_job_worker.run_worker(
                pop_timeout=1,
                idle_sleep=0.01,
                run_once=False,
                max_concurrency=2,
                shutdown_grace_seconds=0.0,
                max_retries=0,
                running_timeout_seconds=30,
                stale_scan_interval_seconds=60,
                stale_scan_batch_size=10,
                dlq_queue_name="job_queue_dlq",
            )

        self.assertGreaterEqual(len(store.failed), 1)
        self.assertEqual(store.failed[0][0], "job-1")
        self.assertIn("interrupt", store.failed[0][1].lower())

    def test_process_job_payload_skips_when_claim_not_acquired(self):
        class _ClaimRejectingStore:
            def get_job(self, job_id):
                return {
                    "id": job_id,
                    "status": "queued",
                    "task_type": "goal",
                    "task_payload": {"goal": "skip"},
                    "metadata": {},
                }

            def try_claim_job_execution(self, job_id, *, worker_id, lease_seconds, retry_count=None, max_retries=None):
                del job_id, worker_id, lease_seconds, retry_count, max_retries
                return False

            def append_stream_event(self, *_args, **_kwargs):
                return None

        called = []

        def _run_job(_task_type, _task_data):
            called.append(True)
            return {"ok": True}

        ok = upstash_job_worker._process_job_payload(
            payload={"jobId": "job-skip", "taskType": "goal", "task": {"goal": "skip"}},
            queue=_NoopQueue(),
            store=_ClaimRejectingStore(),
            run_job=_run_job,
            worker_id="test-worker",
            claim_lease_seconds=60,
            max_retries=1,
            retry_backoff_base_seconds=0.0,
            retry_backoff_max_seconds=0.0,
            dlq_queue_name="job_queue_dlq",
        )

        self.assertFalse(ok)
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
