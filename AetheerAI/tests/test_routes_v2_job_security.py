import datetime
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from api import routes_v2
    _API_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    routes_v2 = None
    _API_IMPORT_ERROR = exc


class _FakeUser:
    def __init__(self, user_id: int, username: str, is_admin: bool = False):
        self.id = user_id
        self.username = username
        self.is_admin = is_admin


class _FakeKernel:
    def __init__(self, rows: list[dict]):
        self._rows = {str(row["job_id"]): dict(row) for row in rows}

    def schedule_job(self, **kwargs):
        job_id = "jobnew1234567890abcdef1234567890"
        self._rows[job_id] = {
            "job_id": job_id,
            "name": kwargs.get("name"),
            "agent_name": kwargs.get("agent_name"),
            "task": kwargs.get("task"),
            "status": "pending",
            "owner_user_id": kwargs.get("owner_user_id"),
            "owner_username": kwargs.get("owner_username"),
            "owner_tenant_id": kwargs.get("owner_tenant_id"),
        }
        return job_id

    def list_jobs(self, status=None, limit=100):
        rows = list(self._rows.values())
        if status:
            rows = [row for row in rows if str(row.get("status")) == str(status)]
        return rows[: int(limit)]

    def job_status(self, job_id):
        row = self._rows.get(str(job_id))
        return dict(row) if row else None

    def cancel_job(self, job_id):
        row = self._rows.get(str(job_id))
        if not row:
            return False
        if str(row.get("status") or "") not in {"pending", "running"}:
            return False
        row["status"] = "cancelled"
        return True

    @staticmethod
    def scheduler_stats():
        return {"total": 1}


class _FakeDb:
    pass


@unittest.skipIf(_API_IMPORT_ERROR is not None, f"API module deps unavailable: {_API_IMPORT_ERROR}")
class RoutesV2JobSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._user = _FakeUser(user_id=7, username="alice", is_admin=False)
        self._admin = _FakeUser(user_id=1, username="root", is_admin=True)
        self._job_id = "jobabc1234567890fedcba0987654321"
        self._kernel = _FakeKernel(
            [
                {
                    "job_id": self._job_id,
                    "name": "demo",
                    "agent_name": "researcher",
                    "task": "run",
                    "status": "pending",
                    "owner_user_id": 7,
                    "owner_username": "alice",
                    "owner_tenant_id": "user:7",
                }
            ]
        )

        self._patchers = [
            patch.object(routes_v2, "enforce_job_api_rate_limit", lambda *_a, **_k: None),
            patch.object(routes_v2, "enforce_job_create_quota", lambda *_a, **_k: None),
            patch.object(routes_v2, "enforce_job_submission_abuse_controls", lambda *_a, **_k: None),
            patch.object(routes_v2, "record_job_create_usage", lambda *_a, **_k: None),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()

    def test_list_jobs_rejects_invalid_status_filter(self):
        with patch.object(routes_v2, "_kernel", return_value=self._kernel):
            with self.assertRaises(HTTPException) as ctx:
                routes_v2.list_jobs(
                    status="unknown_status",
                    current_user=self._user,
                    db=_FakeDb(),
                )

        self.assertEqual(ctx.exception.status_code, 422)

    def test_get_job_requires_exact_id_for_non_admin(self):
        prefix = self._job_id[:12]

        with patch.dict(os.environ, {"JOB_API_ALLOW_ADMIN_PREFIX_LOOKUP": "0"}, clear=False):
            with patch.object(routes_v2, "_kernel", return_value=self._kernel):
                with self.assertRaises(HTTPException) as ctx:
                    routes_v2.get_job(prefix, current_user=self._user, db=_FakeDb())

                response = routes_v2.get_job(self._job_id, current_user=self._user, db=_FakeDb())

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(response["data"]["job_id"], self._job_id)

    def test_admin_prefix_lookup_requires_explicit_opt_in(self):
        prefix = self._job_id[:12]

        with patch.object(routes_v2, "_kernel", return_value=self._kernel):
            with self.assertRaises(HTTPException):
                routes_v2.get_job(prefix, current_user=self._admin, db=_FakeDb())

        with patch.dict(os.environ, {"JOB_API_ALLOW_ADMIN_PREFIX_LOOKUP": "1"}, clear=False):
            with patch.object(routes_v2, "_kernel", return_value=self._kernel):
                response = routes_v2.get_job(prefix, current_user=self._admin, db=_FakeDb())

        self.assertEqual(response["data"]["job_id"], self._job_id)

    def test_schedule_job_rejects_past_run_at(self):
        req = routes_v2.JobRequest(
            name="demo",
            agent_name="researcher",
            task="execute",
            run_at_iso="2020-01-01T00:00:00Z",
        )

        with patch.object(routes_v2, "_kernel", return_value=self._kernel):
            with self.assertRaises(HTTPException) as ctx:
                routes_v2.schedule_job(req, current_user=self._user, db=_FakeDb())

        self.assertEqual(ctx.exception.status_code, 422)

    def test_schedule_job_rejects_run_at_too_far_ahead(self):
        run_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
        req = routes_v2.JobRequest(
            name="demo",
            agent_name="researcher",
            task="execute",
            run_at_iso=run_at.isoformat().replace("+00:00", "Z"),
        )

        with patch.dict(os.environ, {"JOB_API_MAX_SCHEDULE_AHEAD_SECONDS": "60"}, clear=False):
            with patch.object(routes_v2, "_kernel", return_value=self._kernel):
                with self.assertRaises(HTTPException) as ctx:
                    routes_v2.schedule_job(req, current_user=self._user, db=_FakeDb())

        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
