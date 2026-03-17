"""Tests for Upstash queue + Supabase async job flow helpers."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api.queue_router as queue_router
from api.async_jobs import SupabaseJobStore, build_queue_payload
from integrations.config import UpstashRedisConfig
from integrations.upstash_redis_queue import UpstashRedisQueue


class _FakeRedisClient:
    def __init__(self):
        self.items = []

    def lpush(self, key, value):
        self.items.insert(0, (key, value))
        return len(self.items)

    def brpop(self, key, timeout):
        del timeout
        keys = list(key) if isinstance(key, (list, tuple)) else [key]
        for target_key in keys:
            for idx in range(len(self.items) - 1, -1, -1):
                item_key, value = self.items[idx]
                if item_key == target_key:
                    self.items.pop(idx)
                    return target_key, value
        return None

    def rpop(self, key):
        for idx in range(len(self.items) - 1, -1, -1):
            item_key, value = self.items[idx]
            if item_key == key:
                self.items.pop(idx)
                return value
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
        return [dict(row)]

    def query_rows(self, *, table, select="*", filters=None, limit=None, order=None, use_service_role=False):
        filters = filters or {}
        rows = list(self.rows.values())

        for key, clause in filters.items():
            if not isinstance(clause, str):
                continue
            if key == "id" and clause.startswith("eq."):
                target = clause[3:]
                rows = [row for row in rows if str(row.get("id")) == target]
            elif key == "status" and clause.startswith("eq."):
                target = clause[3:]
                rows = [row for row in rows if str(row.get("status")) == target]
            elif key == "status" and clause.startswith("in.(") and clause.endswith(")"):
                values = {
                    item.strip()
                    for item in clause[4:-1].split(",")
                    if item.strip()
                }
                rows = [row for row in rows if str(row.get("status")) in values]
            elif key == "started_at" and clause.startswith("lt."):
                threshold = clause[3:]
                rows = [
                    row
                    for row in rows
                    if isinstance(row.get("started_at"), str) and str(row.get("started_at")) < threshold
                ]
            elif key == "completed_at" and clause.startswith("lt."):
                threshold = clause[3:]
                rows = [
                    row
                    for row in rows
                    if isinstance(row.get("completed_at"), str) and str(row.get("completed_at")) < threshold
                ]

        if order:
            reverse = str(order).endswith(".desc")
            field = str(order).split(".", 1)[0]
            rows = sorted(rows, key=lambda row: str(row.get(field) or ""), reverse=reverse)

        if limit is not None:
            rows = rows[: int(limit)]

        return [dict(row) for row in rows]

    def update_rows(self, *, table, values, filters, use_service_role=True):
        target = str(filters.get("id", "eq."))[3:]
        if target in self.rows:
            self.rows[target].update(dict(values))
            return [dict(self.rows[target])]
        return []

    def delete_rows(self, *, table, filters, use_service_role=True):
        target = str(filters.get("id", "eq."))[3:]
        if target in self.rows:
            row = dict(self.rows[target])
            del self.rows[target]
            return [row]
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

    def append_stream_event(self, job_id, *, event_type, status, payload=None):
        row = self.rows.get(job_id)
        if not row:
            return

        metadata = row.setdefault("metadata", {})
        events = metadata.setdefault("stream_events", [])
        events.append(
            {
                "type": event_type,
                "status": status,
                "payload": dict(payload or {}),
            }
        )
        metadata["stream_event_count"] = len(events)

    def cleanup_old_jobs(self, *, retention_hours, limit=500):
        del retention_hours
        to_delete = [
            job_id
            for job_id, row in self.rows.items()
            if str(row.get("status")) in {"completed", "failed"}
        ][: int(limit)]
        for job_id in to_delete:
            del self.rows[job_id]
        return len(to_delete)

    def get_job(self, job_id):
        return self.rows.get(job_id)


class _FakeQueue:
    queue_name = "job_queue"

    def __init__(self):
        self.payloads = []

    @staticmethod
    def normalize_priority(priority):
        return UpstashRedisQueue.normalize_priority(priority)

    def queue_name_for_priority(self, priority):
        normalized = self.normalize_priority(priority)
        if normalized == "high":
            return "job_queue:high"
        if normalized == "low":
            return "job_queue:low"
        return self.queue_name

    def push_job(self, payload, queue_name=None, priority=None):
        target = queue_name or self.queue_name_for_priority(priority)
        self.payloads.append((target, dict(payload)))
        return len(self.payloads)


class _FakeUser:
    def __init__(self, user_id: int, username: str, is_admin: bool = False):
        self.id = user_id
        self.username = username
        self.is_admin = is_admin


class _FakeDb:
    pass


class UpstashQueueTests(unittest.TestCase):
    def test_queue_roundtrip(self):
        q = UpstashRedisQueue(
            config=UpstashRedisConfig(
                redis_url="rediss://local-placeholder",
                queue_name="job_queue",
                pop_timeout_seconds=1,
                socket_timeout_seconds=1,
            ),
            client=_FakeRedisClient(),
        )
        depth = q.push_job({"jobId": "j1", "task": {"goal": "demo"}})
        popped = q.blocking_pop(timeout_seconds=1)

        self.assertEqual(depth, 1)
        self.assertEqual(popped["jobId"], "j1")
        self.assertEqual(q.queue_depth(), 0)

    def test_queue_named_push_and_depth(self):
        q = UpstashRedisQueue(
            config=UpstashRedisConfig(
                redis_url="rediss://local-placeholder",
                queue_name="job_queue",
                pop_timeout_seconds=1,
                socket_timeout_seconds=1,
            ),
            client=_FakeRedisClient(),
        )
        q.push_job({"jobId": "j-dlq", "task": {"goal": "demo"}}, queue_name="job_queue_dlq")

        self.assertEqual(q.queue_depth(queue_name="job_queue_dlq"), 1)
        self.assertEqual(q.queue_depth(), 0)

    def test_build_queue_payload_shape(self):
        payload = build_queue_payload("job-123", "goal", {"goal": "ship"}, priority="high", retry_count=2)
        self.assertEqual(payload["jobId"], "job-123")
        self.assertEqual(payload["taskType"], "goal")
        self.assertEqual(payload["task"]["goal"], "ship")
        self.assertEqual(payload["priority"], "high")
        self.assertEqual(payload["retryCount"], 2)
        self.assertIn("enqueuedAt", payload)

    def test_priority_queue_pushes_to_high_lane(self):
        q = UpstashRedisQueue(client=_FakeRedisClient())
        q.push_job({"jobId": "j-high", "task": {"goal": "urgent"}}, priority="high")

        self.assertEqual(q.queue_depth(queue_name=q.queue_name_for_priority("high")), 1)
        self.assertEqual(q.queue_depth(queue_name=q.queue_name_for_priority("normal")), 0)


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

    def test_retry_and_dead_letter_transitions(self):
        store = SupabaseJobStore(supabase=_FakeSupabaseClient(), table_name="ai_jobs", id_column="id")
        store.create_job(
            job_id="job-retry",
            task_type="goal",
            task_payload={"goal": "recover"},
            metadata={"max_retries": 2},
        )

        store.mark_running("job-retry", retry_count=0, max_retries=2)
        store.mark_requeued_for_retry(
            "job-retry",
            error_message="temporary failure",
            retry_count=1,
            max_retries=2,
            reason="execution_error",
        )

        row = store.get_job("job-retry")
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["metadata"]["retry_count"], 1)
        self.assertFalse(row["metadata"]["dead_lettered"])

        store.mark_dead_lettered(
            "job-retry",
            error_message="retries exhausted",
            retry_count=2,
            max_retries=2,
            reason="execution_error",
            dlq_queue="job_queue_dlq",
        )

        row = store.get_job("job-retry")
        self.assertEqual(row["status"], "failed")
        self.assertTrue(row["metadata"]["dead_lettered"])
        self.assertEqual(row["metadata"]["dead_letter_queue"], "job_queue_dlq")

    def test_list_stale_running_jobs(self):
        fake = _FakeSupabaseClient()
        store = SupabaseJobStore(supabase=fake, table_name="ai_jobs", id_column="id")

        store.create_job(
            job_id="job-stale",
            task_type="goal",
            task_payload={"goal": "stale"},
            metadata={},
        )
        store.mark_running("job-stale")
        fake.rows["job-stale"]["started_at"] = "2000-01-01T00:00:00+00:00"

        store.create_job(
            job_id="job-fresh",
            task_type="goal",
            task_payload={"goal": "fresh"},
            metadata={},
        )
        store.mark_running("job-fresh")
        fake.rows["job-fresh"]["started_at"] = "2999-01-01T00:00:00+00:00"

        stale = store.list_stale_running_jobs(timeout_seconds=30, limit=20)
        stale_ids = {str(row.get("id")) for row in stale}
        self.assertIn("job-stale", stale_ids)
        self.assertNotIn("job-fresh", stale_ids)

    def test_cleanup_old_jobs_removes_terminal_rows(self):
        fake = _FakeSupabaseClient()
        store = SupabaseJobStore(supabase=fake, table_name="ai_jobs", id_column="id")

        store.create_job(job_id="job-old-1", task_type="goal", task_payload={"goal": "a"}, metadata={})
        store.mark_completed("job-old-1", {"ok": True})
        fake.rows["job-old-1"]["completed_at"] = "2000-01-01T00:00:00+00:00"

        store.create_job(job_id="job-old-2", task_type="goal", task_payload={"goal": "b"}, metadata={})
        store.mark_failed("job-old-2", "boom")
        fake.rows["job-old-2"]["completed_at"] = "2000-01-01T00:00:00+00:00"

        store.create_job(job_id="job-fresh", task_type="goal", task_payload={"goal": "c"}, metadata={})
        store.mark_completed("job-fresh", {"ok": True})
        fake.rows["job-fresh"]["completed_at"] = "2999-01-01T00:00:00+00:00"

        deleted = store.cleanup_old_jobs(retention_hours=1, limit=10)

        self.assertEqual(deleted, 2)
        self.assertIsNone(store.get_job("job-old-1"))
        self.assertIsNone(store.get_job("job-old-2"))
        self.assertIsNotNone(store.get_job("job-fresh"))


class QueueRouterTests(unittest.TestCase):
    def setUp(self):
        self._prev_store = queue_router._job_store
        self._prev_queue = queue_router._queue_client

        self._prev_rate_limit = queue_router.enforce_job_api_rate_limit
        self._prev_create_quota = queue_router.enforce_job_create_quota
        self._prev_usage = queue_router.record_job_create_usage

        queue_router._job_store = _FakeStore()
        queue_router._queue_client = _FakeQueue()

        queue_router.enforce_job_api_rate_limit = lambda *_args, **_kwargs: None
        queue_router.enforce_job_create_quota = lambda *_args, **_kwargs: None
        queue_router.record_job_create_usage = lambda *_args, **_kwargs: None

    def tearDown(self):
        queue_router._job_store = self._prev_store
        queue_router._queue_client = self._prev_queue

        queue_router.enforce_job_api_rate_limit = self._prev_rate_limit
        queue_router.enforce_job_create_quota = self._prev_create_quota
        queue_router.record_job_create_usage = self._prev_usage

    def test_create_queue_job_returns_immediate_id(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "Launch campaign"},
            metadata={"source": "test"},
        )

        response = queue_router.create_queue_job(
            req,
            current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            db=_FakeDb(),
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["status"], "queued")
        self.assertEqual(response["data"]["queue"], "job_queue")
        self.assertIn("job_id", response["data"])

        row = queue_router._job_store.get_job(response["data"]["job_id"])
        self.assertEqual(row["metadata"]["owner_user_id"], 7)
        self.assertIn("max_retries", row["metadata"])

    def test_get_queue_job_status_reads_supabase_row(self):
        store = queue_router._job_store
        job_id = "job-status-1"
        store.create_job(
            job_id=job_id,
            task_type="goal",
            task_payload={"goal": "Check status"},
            metadata={"owner_user_id": 9},
        )

        status = queue_router.get_queue_job_status(
            job_id,
            current_user=_FakeUser(user_id=9, username="bob", is_admin=False),
        )

        self.assertEqual(status.job_id, job_id)
        self.assertEqual(status.status, "queued")
        self.assertEqual(status.task_type, "goal")

    def test_batch_enqueue_and_event_polling(self):
        req = queue_router.QueueBatchJobRequest(
            jobs=[
                queue_router.QueueJobRequest(
                    task_type="goal",
                    task_data={"goal": "first"},
                    priority="high",
                    stream_results=True,
                ),
                queue_router.QueueJobRequest(
                    task_type="chat",
                    task_data={"message": "hello"},
                    priority="low",
                ),
            ],
        )

        response = queue_router.create_queue_jobs_batch(
            req,
            current_user=_FakeUser(user_id=11, username="eve", is_admin=False),
            db=_FakeDb(),
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["submitted"], 2)

        first_job = response["data"]["jobs"][0]
        events = queue_router.get_queue_job_events(
            first_job["job_id"],
            current_user=_FakeUser(user_id=11, username="eve", is_admin=False),
        )

        self.assertGreaterEqual(events.total_events, 1)
        self.assertEqual(events.events[0]["type"], "queued")

    def test_cleanup_requires_admin(self):
        with self.assertRaises(queue_router.HTTPException):
            queue_router.cleanup_old_queue_jobs(
                current_user=_FakeUser(user_id=12, username="mallory", is_admin=False),
            )


if __name__ == "__main__":
    unittest.main()
