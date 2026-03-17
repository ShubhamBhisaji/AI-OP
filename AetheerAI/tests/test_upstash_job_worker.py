"""Tests for worker concurrency behavior in workers/upstash_job_worker.py."""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workers import upstash_job_worker


class _FakeQueue:
    queue_name = "job_queue"

    def __init__(self, payloads, *, interrupt_when_empty: bool = True, empty_polls_before_interrupt: int = 3):
        self._payloads = list(payloads)
        self._interrupt_when_empty = interrupt_when_empty
        self._empty_polls_before_interrupt = max(1, int(empty_polls_before_interrupt))
        self._empty_polls = 0

    def blocking_pop(self, timeout_seconds=0):
        del timeout_seconds
        if self._payloads:
            self._empty_polls = 0
            return self._payloads.pop(0)
        if self._interrupt_when_empty:
            self._empty_polls += 1
            if self._empty_polls >= self._empty_polls_before_interrupt:
                raise KeyboardInterrupt()
        return None


class _FakeStore:
    def __init__(self):
        self.rows = {}
        self.running = []
        self.completed = []
        self.failed = []
        self._lock = threading.Lock()

    def get_job(self, job_id):
        with self._lock:
            return dict(self.rows[job_id]) if job_id in self.rows else None

    def create_job(self, *, job_id, task_type, task_payload, metadata):
        with self._lock:
            row = {
                "id": job_id,
                "status": "queued",
                "task_type": task_type,
                "task_payload": dict(task_payload),
                "metadata": dict(metadata or {}),
            }
            self.rows[job_id] = row
            return dict(row)

    def list_stale_running_jobs(self, *, timeout_seconds, limit=100):
        del timeout_seconds, limit
        return []

    def mark_running(self, job_id, *, retry_count=None, max_retries=None):
        with self._lock:
            row = self.rows.setdefault(job_id, {"id": job_id, "metadata": {}})
            row["status"] = "running"
            metadata = dict(row.get("metadata") or {})
            if retry_count is not None:
                metadata["retry_count"] = int(retry_count)
            if max_retries is not None:
                metadata["max_retries"] = int(max_retries)
            row["metadata"] = metadata
            self.running.append(job_id)

    def mark_completed(self, job_id, result):
        with self._lock:
            row = self.rows.setdefault(job_id, {"id": job_id, "metadata": {}})
            row["status"] = "completed"
            row["result"] = result
            self.completed.append((job_id, result))

    def mark_failed(self, job_id, error_message):
        with self._lock:
            row = self.rows.setdefault(job_id, {"id": job_id, "metadata": {}})
            row["status"] = "failed"
            row["error"] = str(error_message)
            self.failed.append((job_id, str(error_message)))

    def mark_requeued_for_retry(self, job_id, *, error_message, retry_count, max_retries, reason):
        with self._lock:
            row = self.rows.setdefault(job_id, {"id": job_id, "metadata": {}})
            row["status"] = "queued"
            row["error"] = str(error_message)
            metadata = dict(row.get("metadata") or {})
            metadata["retry_count"] = int(retry_count)
            metadata["max_retries"] = int(max_retries)
            metadata["last_failure_reason"] = str(reason)
            row["metadata"] = metadata

    def mark_dead_lettered(self, job_id, *, error_message, retry_count, max_retries, reason, dlq_queue):
        with self._lock:
            row = self.rows.setdefault(job_id, {"id": job_id, "metadata": {}})
            row["status"] = "failed"
            row["error"] = str(error_message)
            metadata = dict(row.get("metadata") or {})
            metadata["retry_count"] = int(retry_count)
            metadata["max_retries"] = int(max_retries)
            metadata["dead_letter_reason"] = str(reason)
            metadata["dead_letter_queue"] = str(dlq_queue)
            row["metadata"] = metadata


class _TrackingRunner:
    lock = threading.Lock()
    active = 0
    peak = 0

    @classmethod
    def reset(cls):
        with cls.lock:
            cls.active = 0
            cls.peak = 0

    def execute(self, *, task_type, task_data):
        del task_type
        cls = type(self)
        with cls.lock:
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
        try:
            time.sleep(0.05)
            return {"ok": True, "payload": dict(task_data)}
        finally:
            with cls.lock:
                cls.active -= 1


class WorkerConcurrencyTests(unittest.TestCase):
    def test_run_worker_processes_jobs_with_bounded_concurrency(self):
        _TrackingRunner.reset()
        payloads = [
            {
                "jobId": f"job-{idx}",
                "taskType": "chat",
                "task": {"message": f"hello-{idx}"},
            }
            for idx in range(6)
        ]
        fake_queue = _FakeQueue(payloads, interrupt_when_empty=True)
        fake_store = _FakeStore()

        with patch.object(upstash_job_worker, "UpstashRedisQueue", return_value=fake_queue), patch.object(
            upstash_job_worker, "SupabaseJobStore", return_value=fake_store
        ), patch.object(upstash_job_worker, "AIJobRunner", _TrackingRunner):
            upstash_job_worker.run_worker(
                pop_timeout=1,
                idle_sleep=0.001,
                run_once=False,
                max_concurrency=3,
                sandbox_enabled=False,
            )

        completed_ids = {job_id for job_id, _ in fake_store.completed}
        failed_ids = {job_id for job_id, _ in fake_store.failed}
        self.assertEqual(len(completed_ids | failed_ids), 6)
        self.assertGreaterEqual(len(completed_ids), 1)
        self.assertGreaterEqual(_TrackingRunner.peak, 2)
        self.assertLessEqual(_TrackingRunner.peak, 3)

    def test_run_worker_once_submits_only_one_job(self):
        _TrackingRunner.reset()
        payloads = [
            {
                "jobId": f"job-{idx}",
                "taskType": "chat",
                "task": {"message": f"hello-{idx}"},
            }
            for idx in range(3)
        ]
        fake_queue = _FakeQueue(payloads, interrupt_when_empty=False)
        fake_store = _FakeStore()

        with patch.object(upstash_job_worker, "UpstashRedisQueue", return_value=fake_queue), patch.object(
            upstash_job_worker, "SupabaseJobStore", return_value=fake_store
        ), patch.object(upstash_job_worker, "AIJobRunner", _TrackingRunner):
            upstash_job_worker.run_worker(
                pop_timeout=1,
                idle_sleep=0.001,
                run_once=True,
                max_concurrency=4,
                sandbox_enabled=False,
            )

        self.assertEqual(len(fake_store.completed) + len(fake_store.failed), 1)

    def test_parse_args_reads_max_concurrency_from_env(self):
        with patch.object(sys, "argv", ["upstash_job_worker.py"]), patch.dict(
            os.environ,
            {"AETHEER_WORKER_MAX_CONCURRENCY": "5"},
            clear=False,
        ):
            args = upstash_job_worker._parse_args()

        self.assertEqual(args.max_concurrency, 5)


if __name__ == "__main__":
    unittest.main()
