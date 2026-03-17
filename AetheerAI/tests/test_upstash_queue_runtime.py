"""Tests for Upstash queue + Supabase async job flow helpers."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import queue_router
from api.async_jobs import SupabaseJobStore, build_queue_payload
from integrations.upstash_redis_queue import UpstashRedisQueue


class _FakeRedisClient:
    def __init__(self):
        self.items = []

    def lpush(self, key, value):
        self.items.insert(0, (key, value))
        return len(self.items)

    def brpop(self, key, timeout):
        for idx in range(len(self.items) - 1, -1, -1):
            item_key, value = self.items[idx]
            if item_key == key:
                self.items.pop(idx)
                return key, value
        return None

    def llen(self, key):
        return sum(1 for item_key, _ in self.items if item_key == key)


class _FakeSupabaseClient:
    def __init__(self):
        self.rows = {}

    def insert_row(self, *, table, payload, use_service_role=True, upsert=False):
        row = dict(payload)
        row_id = str(row.get("id"))
        self.rows[row_id] = row
        return [row]

    def query_rows(self, *, table, select="*", filters=None, limit=None, order=None, use_service_role=False):
        filters = filters or {}
        target = str(filters.get("id", "eq."))[3:]
        row = self.rows.get(target)
        return [row] if row else []

    def update_rows(self, *, table, values, filters, use_service_role=True):
        target = str(filters.get("id", "eq."))[3:]
        if target in self.rows:
            self.rows[target].update(dict(values))
            return [dict(self.rows[target])]
        return []


class _FakeStore:
    def __init__(self):
        self.rows = {}

    def create_job(self, *, job_id, task_type, task_payload, metadata):
        self.rows[job_id] = {
            "id": job_id,
            "status": "queued",
            "task_type": task_type,
            "task_payload": dict(task_payload),
            "metadata": dict(metadata),
        }
        return self.rows[job_id]

    def mark_failed(self, job_id, error_message):
        if job_id in self.rows:
            self.rows[job_id]["status"] = "failed"
            self.rows[job_id]["error"] = error_message

    def get_job(self, job_id):
        return self.rows.get(job_id)


class _FakeQueue:
    queue_name = "job_queue"

    def __init__(self):
        self.payloads = []

    def push_job(self, payload):
        self.payloads.append(dict(payload))
        return len(self.payloads)


class UpstashQueueTests(unittest.TestCase):
    def test_queue_roundtrip(self):
        q = UpstashRedisQueue(client=_FakeRedisClient())
        depth = q.push_job({"jobId": "j1", "task": {"goal": "demo"}})
        popped = q.blocking_pop(timeout_seconds=1)

        self.assertEqual(depth, 1)
        self.assertEqual(popped["jobId"], "j1")
        self.assertEqual(q.queue_depth(), 0)

    def test_build_queue_payload_shape(self):
        payload = build_queue_payload("job-123", "goal", {"goal": "ship"})
        self.assertEqual(payload["jobId"], "job-123")
        self.assertEqual(payload["taskType"], "goal")
        self.assertEqual(payload["task"]["goal"], "ship")
        self.assertIn("enqueuedAt", payload)


class SupabaseJobStoreTests(unittest.TestCase):
    def test_status_transitions(self):
        store = SupabaseJobStore(supabase=_FakeSupabaseClient(), table_name="ai_jobs", id_column="id")

        store.create_job(
            job_id="job-1",
            task_type="goal",
            task_payload={"goal": "build"},
            metadata={"tenant": "acme"},
        )
        store.mark_running("job-1")
        store.mark_completed("job-1", {"ok": True})

        row = store.get_job("job-1")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["result"], {"ok": True})


class QueueRouterTests(unittest.TestCase):
    def setUp(self):
        self._prev_store = queue_router._job_store
        self._prev_queue = queue_router._queue_client
        queue_router._job_store = _FakeStore()
        queue_router._queue_client = _FakeQueue()

    def tearDown(self):
        queue_router._job_store = self._prev_store
        queue_router._queue_client = self._prev_queue

    def test_create_queue_job_returns_immediate_id(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "Launch campaign"},
            metadata={"source": "test"},
        )

        response = queue_router.create_queue_job(req)

        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["status"], "queued")
        self.assertEqual(response["data"]["queue"], "job_queue")
        self.assertIn("job_id", response["data"])

    def test_get_queue_job_status_reads_supabase_row(self):
        store = queue_router._job_store
        job_id = "job-status-1"
        store.create_job(
            job_id=job_id,
            task_type="goal",
            task_payload={"goal": "Check status"},
            metadata={},
        )

        status = queue_router.get_queue_job_status(job_id)

        self.assertEqual(status.job_id, job_id)
        self.assertEqual(status.status, "queued")
        self.assertEqual(status.task_type, "goal")


if __name__ == "__main__":
    unittest.main()
