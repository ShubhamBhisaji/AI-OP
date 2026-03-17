import datetime
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from api import job_security as job_security
    from api.database import Base, BillingPlan, Subscription, UsageEvent, User
    _API_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    job_security = None
    Base = None
    BillingPlan = None
    Subscription = None
    UsageEvent = None
    User = None
    _API_IMPORT_ERROR = exc


@unittest.skipIf(_API_IMPORT_ERROR is not None, f"API module deps unavailable: {_API_IMPORT_ERROR}")
class JobApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(bind=engine)

        self._engine = engine
        self._db = SessionLocal()
        self._user = User(
            username="alice",
            email="alice@example.com",
            hashed_pw="hash",
            is_admin=False,
            is_active=True,
        )
        self._admin = User(
            username="root",
            email="root@example.com",
            hashed_pw="hash",
            is_admin=True,
            is_active=True,
        )
        self._user_two = User(
            username="charlie",
            email="charlie@example.com",
            hashed_pw="hash",
            is_admin=False,
            is_active=True,
        )
        self._db.add_all([self._user, self._admin, self._user_two])
        self._db.commit()
        self._db.refresh(self._user)
        self._db.refresh(self._admin)
        self._db.refresh(self._user_two)
        job_security._reset_job_rate_limit_state_for_tests()

    def tearDown(self) -> None:
        self._db.close()
        self._engine.dispose()
        job_security._reset_job_rate_limit_state_for_tests()

    def test_write_rate_limit_blocks_after_threshold(self):
        with patch.dict(os.environ, {"JOB_API_WRITE_RATE_LIMIT_RPM": "2"}, clear=False):
            job_security.enforce_job_api_rate_limit(self._user, bucket="write")
            job_security.enforce_job_api_rate_limit(self._user, bucket="write")
            with self.assertRaises(HTTPException) as ctx:
                job_security.enforce_job_api_rate_limit(self._user, bucket="write")

        self.assertEqual(ctx.exception.status_code, 429)

    def test_write_burst_limit_blocks_short_spikes(self):
        with patch.dict(
            os.environ,
            {
                "JOB_API_WRITE_RATE_LIMIT_RPM": "100",
                "JOB_API_WRITE_RATE_LIMIT_BURST": "2",
            },
            clear=False,
        ):
            job_security.enforce_job_api_rate_limit(self._user, bucket="write")
            job_security.enforce_job_api_rate_limit(self._user, bucket="write")
            with self.assertRaises(HTTPException) as ctx:
                job_security.enforce_job_api_rate_limit(self._user, bucket="write")

        self.assertEqual(ctx.exception.status_code, 429)

    def test_admin_bypasses_rate_limit(self):
        with patch.dict(os.environ, {"JOB_API_WRITE_RATE_LIMIT_RPM": "1"}, clear=False):
            for _ in range(4):
                job_security.enforce_job_api_rate_limit(self._admin, bucket="write")

    def test_tenant_scope_rate_limit_blocks_across_users(self):
        with patch.dict(
            os.environ,
            {
                "JOB_API_WRITE_RATE_LIMIT_RPM": "99",
                "JOB_API_TENANT_WRITE_RATE_LIMIT_RPM": "2",
            },
            clear=False,
        ):
            job_security.enforce_job_api_rate_limit(self._user, bucket="write", tenant_id="org:acme")
            job_security.enforce_job_api_rate_limit(self._user_two, bucket="write", tenant_id="org:acme")
            with self.assertRaises(HTTPException) as ctx:
                job_security.enforce_job_api_rate_limit(self._user, bucket="write", tenant_id="org:acme")

        self.assertEqual(ctx.exception.status_code, 429)

    def test_duplicate_submission_abuse_control_blocks(self):
        with patch.dict(
            os.environ,
            {
                "JOB_API_DUPLICATE_MAX_PER_WINDOW": "2",
                "JOB_API_DUPLICATE_WINDOW_SECONDS": "120",
            },
            clear=False,
        ):
            job_security.enforce_job_submission_abuse_controls(
                self._user,
                fingerprint="fp-abc",
                tenant_id="org:acme",
                source_ip="203.0.113.8",
            )
            job_security.enforce_job_submission_abuse_controls(
                self._user,
                fingerprint="fp-abc",
                tenant_id="org:acme",
                source_ip="203.0.113.8",
            )
            with self.assertRaises(HTTPException) as ctx:
                job_security.enforce_job_submission_abuse_controls(
                    self._user,
                    fingerprint="fp-abc",
                    tenant_id="org:acme",
                    source_ip="203.0.113.8",
                )

        self.assertEqual(ctx.exception.status_code, 429)

    def test_default_quota_enforced_without_subscription(self):
        now = datetime.datetime.utcnow()
        self._db.add(
            UsageEvent(
                user_id=self._user.id,
                event_type="job_api",
                metric_name="job_create",
                quantity=2.0,
                unit="count",
                meta={},
                created_at=now,
            )
        )
        self._db.commit()

        with patch.dict(
            os.environ,
            {
                "JOB_API_DEFAULT_MONTHLY_QUOTA": "2",
                "JOB_API_DEFAULT_WINDOW_DAYS": "30",
            },
            clear=False,
        ):
            with self.assertRaises(HTTPException) as ctx:
                job_security.enforce_job_create_quota(self._db, self._user)

        self.assertEqual(ctx.exception.status_code, 429)

    def test_plan_feature_quota_overrides_default(self):
        now = datetime.datetime.utcnow()
        plan = BillingPlan(
            code="starter",
            name="Starter",
            interval="monthly",
            price_usd=0.0,
            token_quota=None,
            features={"job_api_monthly_quota": 1},
            is_active=True,
        )
        self._db.add(plan)
        self._db.flush()

        sub = Subscription(
            user_id=self._user.id,
            plan_id=plan.id,
            status="active",
            current_period_start=now - datetime.timedelta(days=1),
            current_period_end=now + datetime.timedelta(days=29),
            cancel_at_period_end=False,
        )
        self._db.add(sub)
        self._db.add(
            UsageEvent(
                user_id=self._user.id,
                event_type="job_api",
                metric_name="job_create",
                quantity=1.0,
                unit="count",
                meta={"source": "scheduler_api"},
                created_at=now,
            )
        )
        self._db.commit()

        with patch.dict(os.environ, {"JOB_API_DEFAULT_MONTHLY_QUOTA": "100"}, clear=False):
            with self.assertRaises(HTTPException) as ctx:
                job_security.enforce_job_create_quota(self._db, self._user)

        self.assertEqual(ctx.exception.status_code, 429)

    def test_record_job_create_usage_writes_event(self):
        job_security.record_job_create_usage(
            self._db,
            current_user=self._user,
            source="queue_api",
            job_id="job-123",
        )

        row = (
            self._db.query(UsageEvent)
            .filter(
                UsageEvent.user_id == self._user.id,
                UsageEvent.event_type == "job_api",
                UsageEvent.metric_name == "job_create",
            )
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.unit, "count")
        self.assertEqual(float(row.quantity), 1.0)


if __name__ == "__main__":
    unittest.main()