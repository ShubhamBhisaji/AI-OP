"""Tests for Upstash queue + Supabase async job flow helpers."""

import datetime
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
            row = self.rows[target]
            status_filter = str(filters.get("status") or "").strip()
            if status_filter.startswith("eq."):
                required = status_filter[3:]
                if str(row.get("status") or "") != required:
                    return []
            row.update(dict(values))
            return [dict(row)]
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

    def list_stale_running_jobs(self, *, timeout_seconds, limit=50):
        del timeout_seconds, limit
        return []

    def status_counts(self):
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0}
        for row in self.rows.values():
            status = str(row.get("status") or "")
            if status in counts:
                counts[status] += 1
        return counts

    def list_dead_lettered_jobs(self, *, limit=100, scan_limit=1000):
        del scan_limit
        rows = []
        for row in self.rows.values():
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if bool(metadata.get("dead_lettered")):
                rows.append(row)
        return rows[: int(limit)]

    def latency_metrics(self, *, sample_limit=500):
        del sample_limit
        return {
            "sample_size": len(self.rows),
            "avg_queue_wait_ms": 12.5,
            "p95_queue_wait_ms": 20.0,
            "avg_execution_ms": 45.0,
            "p95_execution_ms": 70.0,
        }


class _FakeQueue:
    queue_name = "job_queue"
    priority_queue_names = ("job_queue:high", "job_queue", "job_queue:low")

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

    def queue_depth(self, *, queue_name=None):
        target = queue_name or self.queue_name
        return sum(1 for lane, _payload in self.payloads if lane == target)


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

    def test_try_claim_job_execution_only_claims_queued_rows(self):
        store = SupabaseJobStore(supabase=_FakeSupabaseClient(), table_name="ai_jobs", id_column="id")
        store.create_job(
            job_id="job-claim",
            task_type="goal",
            task_payload={"goal": "claim"},
            metadata={},
        )

        first = store.try_claim_job_execution(
            "job-claim",
            worker_id="worker-a",
            lease_seconds=60,
            retry_count=0,
            max_retries=3,
        )
        second = store.try_claim_job_execution(
            "job-claim",
            worker_id="worker-b",
            lease_seconds=60,
            retry_count=0,
            max_retries=3,
        )

        self.assertTrue(first)
        self.assertFalse(second)
        row = store.get_job("job-claim")
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["metadata"]["execution_claim"]["worker_id"], "worker-a")

        store.mark_completed("job-claim", {"ok": True})
        completed_row = store.get_job("job-claim")
        self.assertIsNone(completed_row["metadata"].get("execution_claim"))

    def test_extend_execution_claim_refreshes_expiry_for_same_worker(self):
        store = SupabaseJobStore(supabase=_FakeSupabaseClient(), table_name="ai_jobs", id_column="id")
        store.create_job(
            job_id="job-heartbeat",
            task_type="goal",
            task_payload={"goal": "renew"},
            metadata={},
        )

        self.assertTrue(
            store.try_claim_job_execution(
                "job-heartbeat",
                worker_id="worker-a",
                lease_seconds=60,
                retry_count=0,
                max_retries=2,
            )
        )

        before = store.get_job("job-heartbeat")
        before_expiry = before["metadata"]["execution_claim"]["claim_expires_at"]

        with patch(
            "api.async_jobs._utc_now",
            return_value=datetime.datetime(2026, 3, 18, 0, 0, 30, tzinfo=datetime.timezone.utc),
        ):
            refreshed = store.extend_execution_claim(
                "job-heartbeat",
                worker_id="worker-a",
                lease_seconds=600,
            )

        self.assertTrue(refreshed)
        after = store.get_job("job-heartbeat")
        claim = after["metadata"]["execution_claim"]
        self.assertEqual(claim["worker_id"], "worker-a")
        self.assertGreater(claim["claim_expires_at"], before_expiry)
        self.assertGreaterEqual(int(claim.get("renewal_count") or 0), 1)

        rejected = store.extend_execution_claim(
            "job-heartbeat",
            worker_id="worker-b",
            lease_seconds=600,
        )
        self.assertFalse(rejected)


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
        self.assertIn("governance", row["metadata"])
        self.assertIn("resource_limits", row["metadata"]["governance"])
        self.assertIn("cost_protection", row["metadata"]["governance"])
        self.assertIn("priority", row["metadata"]["governance"])
        self.assertIn("max_memory_mb", row["task_payload"])
        self.assertIn("max_cpu_seconds", row["task_payload"])
        self.assertIn("max_cost_usd", row["task_payload"])

    def test_create_queue_job_rejects_resource_runtime_cap_exceeded(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "Cap check"},
            max_runtime_seconds=1200,
        )

        with patch.dict(
            os.environ,
            {
                "AETHEER_JOB_MAX_RUNTIME_SECONDS": "600",
                "AETHEER_JOB_RUNTIME_CAP_SECONDS": "600",
            },
            clear=False,
        ):
            with self.assertRaises(queue_router.HTTPException) as ctx:
                queue_router.create_queue_job(
                    req,
                    current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
                    db=_FakeDb(),
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("max_runtime_seconds", str(ctx.exception.detail))

    def test_create_queue_job_rejects_cost_cap_exceeded(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "Budget check"},
            max_cost_usd=25.0,
        )

        with patch.dict(
            os.environ,
            {
                "AETHEER_JOB_DEFAULT_MAX_COST_USD": "10",
                "AETHEER_JOB_HARD_MAX_COST_USD": "10",
            },
            clear=False,
        ):
            with self.assertRaises(queue_router.HTTPException) as ctx:
                queue_router.create_queue_job(
                    req,
                    current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
                    db=_FakeDb(),
                )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("max_cost_usd", str(ctx.exception.detail))

    def test_high_priority_demoted_when_high_lane_backpressured(self):
        queue_router._queue_client.payloads.append(("job_queue:high", {"jobId": "existing-high"}))
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "Needs fast lane"},
            priority="high",
        )

        with patch.dict(
            os.environ,
            {
                "AETHEER_QUEUE_HIGH_PRIORITY_DEPTH_LIMIT": "1",
                "AETHEER_QUEUE_ALLOW_NON_ADMIN_HIGH_PRIORITY": "1",
            },
            clear=False,
        ):
            response = queue_router.create_queue_job(
                req,
                current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
                db=_FakeDb(),
            )

        self.assertEqual(response["data"]["priority"], "normal")
        self.assertEqual(response["data"]["queue"], "job_queue")

        row = queue_router._job_store.get_job(response["data"]["job_id"])
        governance = row["metadata"]["governance"]["priority"]
        self.assertEqual(governance["requested"], "high")
        self.assertEqual(governance["effective"], "normal")
        self.assertEqual(governance["reason"], "high_priority_backpressure")

    def test_create_queue_job_idempotency_deduplicates_retries(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "Idempotent launch"},
            metadata={"source": "test"},
            idempotency_key="idem_launch_20260318",
        )

        first = queue_router.create_queue_job(
            req,
            current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            db=_FakeDb(),
        )
        second = queue_router.create_queue_job(
            req,
            current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            db=_FakeDb(),
        )

        self.assertEqual(first["data"]["job_id"], second["data"]["job_id"])
        self.assertFalse(first["data"]["deduplicated"])
        self.assertTrue(second["data"]["deduplicated"])
        self.assertEqual(len(queue_router._queue_client.payloads), 1)

    def test_create_queue_job_rejects_when_total_queue_depth_limit_reached(self):
        queue_router._queue_client.payloads.extend(
            [
                ("job_queue", {"jobId": "seed-1"}),
                ("job_queue:high", {"jobId": "seed-2"}),
            ]
        )

        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "overloaded"},
            priority="normal",
        )

        with patch.dict(
            os.environ,
            {
                "AETHEER_QUEUE_MAX_DEPTH_TOTAL": "1",
                "AETHEER_QUEUE_OVERLOAD_ALLOW_HIGH_PRIORITY": "0",
                "AETHEER_QUEUE_OVERLOAD_RETRY_AFTER_SECONDS": "7",
            },
            clear=False,
        ):
            with self.assertRaises(queue_router.HTTPException) as ctx:
                queue_router.create_queue_job(
                    req,
                    current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
                    db=_FakeDb(),
                )

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("overloaded", str(ctx.exception.detail).lower())
        self.assertEqual(len(queue_router._queue_client.payloads), 2)

    def test_high_priority_enqueue_can_bypass_total_overload_limit(self):
        queue_router._queue_client.payloads.extend(
            [
                ("job_queue", {"jobId": "seed-1"}),
                ("job_queue:low", {"jobId": "seed-2"}),
            ]
        )
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "urgent"},
            priority="high",
        )

        with patch.dict(
            os.environ,
            {
                "AETHEER_QUEUE_MAX_DEPTH_TOTAL": "1",
                "AETHEER_QUEUE_OVERLOAD_ALLOW_HIGH_PRIORITY": "1",
            },
            clear=False,
        ):
            response = queue_router.create_queue_job(
                req,
                current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
                db=_FakeDb(),
            )

        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["priority"], "high")

    def test_create_queue_job_propagates_runtime_timeout(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "Timed execution"},
            metadata={"source": "test"},
            max_runtime_seconds=123,
        )

        response = queue_router.create_queue_job(
            req,
            current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            db=_FakeDb(),
        )

        job_id = response["data"]["job_id"]
        row = queue_router._job_store.get_job(job_id)
        self.assertEqual(row["task_payload"]["max_runtime_seconds"], 123)
        self.assertEqual(row["metadata"]["max_runtime_seconds"], 123)

        queued_payload = queue_router._queue_client.payloads[-1][1]
        self.assertEqual(queued_payload["task"]["max_runtime_seconds"], 123)

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

    def test_create_queue_job_rejects_oversized_task_payload(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "x" * 5000},
            metadata={"source": "test"},
        )

        with patch.dict(os.environ, {"JOB_API_MAX_TASK_PAYLOAD_BYTES": "1024"}, clear=False):
            with self.assertRaises(queue_router.HTTPException) as ctx:
                queue_router.create_queue_job(
                    req,
                    current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
                    db=_FakeDb(),
                )

        self.assertEqual(ctx.exception.status_code, 413)

    def test_queue_metrics_requires_admin(self):
        with self.assertRaises(queue_router.HTTPException) as ctx:
            queue_router.get_queue_metrics(
                current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_queue_metrics_admin_returns_depth_and_counts(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "metrics"},
            metadata={"source": "test"},
            priority="high",
        )
        queue_router.create_queue_job(
            req,
            current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            db=_FakeDb(),
        )

        metrics = queue_router.get_queue_metrics(
            current_user=_FakeUser(user_id=1, username="admin", is_admin=True),
        )

        self.assertGreaterEqual(metrics.queue_depth_total, 1)
        self.assertIn("queued", metrics.status_counts)
        self.assertEqual(metrics.status_counts["queued"], 1)
        self.assertGreaterEqual(metrics.avg_queue_wait_ms, 0.0)
        self.assertGreaterEqual(metrics.avg_execution_ms, 0.0)
        self.assertIn("default_max_runtime_seconds", metrics.governance_limits)
        self.assertIn("hard_max_cost_usd", metrics.governance_limits)

    def test_collect_queue_metrics_snapshot_matches_route_shape(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "metrics-snapshot"},
            metadata={"source": "test"},
            priority="low",
        )
        queue_router.create_queue_job(
            req,
            current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            db=_FakeDb(),
        )

        snap = queue_router.collect_queue_metrics_snapshot()
        route_metrics = queue_router.get_queue_metrics(
            current_user=_FakeUser(user_id=1, username="admin", is_admin=True),
        )

        self.assertGreaterEqual(snap.queue_depth_total, 1)
        self.assertEqual(snap.queue_depth_total, route_metrics.queue_depth_total)
        self.assertEqual(snap.status_counts, route_metrics.status_counts)

    def test_queue_metrics_prometheus_export_contains_queue_series(self):
        req = queue_router.QueueJobRequest(
            task_type="goal",
            task_data={"goal": "metrics-prometheus"},
            metadata={"source": "test"},
            priority="high",
        )
        queue_router.create_queue_job(
            req,
            current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            db=_FakeDb(),
        )

        text = queue_router.queue_metrics_prometheus_text("node-a")
        self.assertIn("aetheer_queue_metrics_scrape_success", text)
        self.assertIn('aetheer_queue_depth_total{instance="node-a"}', text)
        self.assertIn("aetheer_queue_depth", text)
        self.assertIn("aetheer_queue_dlq_depth", text)
        self.assertIn("aetheer_queue_jobs_status_total", text)

    def test_queue_metrics_prometheus_export_handles_snapshot_failure(self):
        with patch.object(queue_router, "collect_queue_metrics_snapshot", side_effect=RuntimeError("boom")):
            text = queue_router.queue_metrics_prometheus_text("node-a")

        self.assertIn('aetheer_queue_metrics_scrape_success{instance="node-a"} 0', text)

    def test_list_dead_letter_queue_jobs_requires_admin(self):
        with self.assertRaises(queue_router.HTTPException) as ctx:
            queue_router.list_dead_letter_queue_jobs(
                current_user=_FakeUser(user_id=7, username="alice", is_admin=False),
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_list_dead_letter_queue_jobs_returns_failed_rows(self):
        store = queue_router._job_store
        store.create_job(
            job_id="job-dlq-1",
            task_type="goal",
            task_payload={"goal": "recover"},
            metadata={
                "owner_user_id": 7,
                "owner_username": "alice",
                "retry_count": 3,
                "max_retries": 3,
                "dead_lettered": True,
                "dead_letter_reason": "external_timeout",
                "dead_lettered_at": "2026-03-18T00:00:00+00:00",
            },
        )
        store.rows["job-dlq-1"]["status"] = "failed"
        store.rows["job-dlq-1"]["error"] = "Timed out"
        store.rows["job-dlq-1"]["completed_at"] = "2026-03-18T00:00:00+00:00"

        response = queue_router.list_dead_letter_queue_jobs(
            current_user=_FakeUser(user_id=1, username="admin", is_admin=True),
        )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.jobs[0].job_id, "job-dlq-1")
        self.assertEqual(response.jobs[0].dead_letter_reason, "external_timeout")


if __name__ == "__main__":
    unittest.main()
