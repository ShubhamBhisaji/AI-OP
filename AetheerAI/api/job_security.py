"""Security helpers for job-related API endpoints."""
from __future__ import annotations

import datetime
import os
import threading
import time
from collections import deque
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.database import BillingPlan, Subscription, UsageEvent, User

_RATE_LIMIT_WINDOW_SECONDS = 60.0
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_BUCKETS: dict[tuple[str, str, str], deque[float]] = {}

_ABUSE_LOCK = threading.Lock()
_ABUSE_DUPLICATE_BUCKETS: dict[tuple[str, str, str], deque[float]] = {}

_QUOTA_FEATURE_KEYS = (
    "job_api_monthly_quota",
    "jobs_monthly_quota",
    "job_create_monthly_quota",
)


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _coerce_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _normalized_scope_id(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    return text[:160]


def _normalize_rate_limit_bucket(bucket: str) -> str:
    return "write" if str(bucket or "").strip().lower() == "write" else "read"


def _rate_limit_for_bucket(bucket: str, *, scope: str = "user") -> int:
    if scope == "tenant":
        if bucket == "write":
            return max(0, _env_int("JOB_API_TENANT_WRITE_RATE_LIMIT_RPM", 90))
        return max(0, _env_int("JOB_API_TENANT_READ_RATE_LIMIT_RPM", 300))

    if scope == "ip":
        if bucket == "write":
            return max(0, _env_int("JOB_API_IP_WRITE_RATE_LIMIT_RPM", 60))
        return max(0, _env_int("JOB_API_IP_READ_RATE_LIMIT_RPM", 240))

    if bucket == "write":
        return max(0, _env_int("JOB_API_WRITE_RATE_LIMIT_RPM", 30))
    return max(0, _env_int("JOB_API_READ_RATE_LIMIT_RPM", 120))


def _enforce_rate_limit_key(*, scope: str, scope_id: str, bucket: str, rpm: int) -> None:
    if rpm <= 0:
        return

    now = time.time()
    key = (scope, scope_id, bucket)
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS

    with _RATE_LIMIT_LOCK:
        hits = _RATE_LIMIT_BUCKETS.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= rpm:
            retry_after = max(1, int(_RATE_LIMIT_WINDOW_SECONDS - (now - hits[0])))
            raise HTTPException(
                status_code=429,
                detail=f"Job API {bucket} rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)


def _plan_job_quota(plan: BillingPlan | None) -> int | None:
    if plan is None:
        return None
    features = plan.features if isinstance(plan.features, dict) else {}
    for key in _QUOTA_FEATURE_KEYS:
        quota = _coerce_non_negative_int(features.get(key))
        if quota is not None:
            return quota
    return None


def _active_subscription(db: Session, user_id: int, now: datetime.datetime) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            Subscription.current_period_end >= now,
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )


def _job_create_usage(
    db: Session,
    *,
    user_id: int,
    window_start: datetime.datetime,
    window_end: datetime.datetime | None,
) -> float:
    q = db.query(func.coalesce(func.sum(UsageEvent.quantity), 0.0)).filter(
        UsageEvent.user_id == user_id,
        UsageEvent.event_type == "job_api",
        UsageEvent.metric_name == "job_create",
        UsageEvent.created_at >= window_start,
    )
    if window_end is not None:
        q = q.filter(UsageEvent.created_at < window_end)
    return float(q.scalar() or 0.0)


def _resolved_quota_window(
    db: Session,
    *,
    user_id: int,
) -> tuple[int, datetime.datetime, datetime.datetime | None]:
    now = datetime.datetime.utcnow()
    default_quota = max(0, _env_int("JOB_API_DEFAULT_MONTHLY_QUOTA", 200))
    default_window_days = max(1, _env_int("JOB_API_DEFAULT_WINDOW_DAYS", 30))

    active_sub = _active_subscription(db, user_id, now)
    if active_sub is not None:
        quota = _plan_job_quota(active_sub.plan) if active_sub.plan is not None else None
        if quota is None:
            quota = default_quota

        window_start = active_sub.current_period_start or (now - datetime.timedelta(days=default_window_days))
        window_end = active_sub.current_period_end
        return quota, window_start, window_end

    return default_quota, now - datetime.timedelta(days=default_window_days), None


def enforce_job_api_rate_limit(
    current_user: User,
    *,
    bucket: str,
    tenant_id: str | None = None,
    source_ip: str | None = None,
) -> None:
    if current_user.is_admin:
        return

    normalized_bucket = _normalize_rate_limit_bucket(bucket)
    user_scope_id = str(int(current_user.id))
    _enforce_rate_limit_key(
        scope="user",
        scope_id=user_scope_id,
        bucket=normalized_bucket,
        rpm=_rate_limit_for_bucket(normalized_bucket, scope="user"),
    )

    tenant_scope_id = _normalized_scope_id(tenant_id)
    if tenant_scope_id:
        _enforce_rate_limit_key(
            scope="tenant",
            scope_id=tenant_scope_id,
            bucket=normalized_bucket,
            rpm=_rate_limit_for_bucket(normalized_bucket, scope="tenant"),
        )

    ip_scope_id = _normalized_scope_id(source_ip)
    if ip_scope_id:
        _enforce_rate_limit_key(
            scope="ip",
            scope_id=ip_scope_id,
            bucket=normalized_bucket,
            rpm=_rate_limit_for_bucket(normalized_bucket, scope="ip"),
        )


def enforce_job_submission_abuse_controls(
    current_user: User,
    *,
    fingerprint: str,
    tenant_id: str | None = None,
    source_ip: str | None = None,
) -> None:
    if current_user.is_admin:
        return

    normalized_fingerprint = _normalized_scope_id(fingerprint)
    if not normalized_fingerprint:
        return

    window_seconds = float(max(1, _env_int("JOB_API_DUPLICATE_WINDOW_SECONDS", 120)))
    max_hits = max(0, _env_int("JOB_API_DUPLICATE_MAX_PER_WINDOW", 5))
    if max_hits <= 0:
        return

    user_scope_id = str(int(current_user.id))
    scope_keys: list[tuple[str, str, str]] = [("user", user_scope_id, normalized_fingerprint)]

    tenant_scope_id = _normalized_scope_id(tenant_id)
    if tenant_scope_id:
        scope_keys.append(("tenant", tenant_scope_id, normalized_fingerprint))

    ip_scope_id = _normalized_scope_id(source_ip)
    if ip_scope_id:
        scope_keys.append(("ip", ip_scope_id, normalized_fingerprint))

    now = time.time()
    cutoff = now - window_seconds

    with _ABUSE_LOCK:
        for key in scope_keys:
            hits = _ABUSE_DUPLICATE_BUCKETS.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= max_hits:
                retry_after = max(1, int(window_seconds - (now - hits[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Duplicate job submission pattern detected",
                    headers={"Retry-After": str(retry_after)},
                )

        for key in scope_keys:
            _ABUSE_DUPLICATE_BUCKETS.setdefault(key, deque()).append(now)


def enforce_job_create_quota(db: Session, current_user: User) -> None:
    if current_user.is_admin:
        return

    quota, window_start, window_end = _resolved_quota_window(db, user_id=int(current_user.id))
    if quota <= 0:
        return

    consumed = _job_create_usage(
        db,
        user_id=int(current_user.id),
        window_start=window_start,
        window_end=window_end,
    )
    if consumed < float(quota):
        return

    if window_end is not None:
        reset_hint = f"Quota resets at {window_end.isoformat()}."
    else:
        reset_hint = "Quota resets as older events leave the rolling window."
    raise HTTPException(status_code=429, detail=f"Job create quota exceeded ({quota}). {reset_hint}")


def record_job_create_usage(
    db: Session,
    *,
    current_user: User,
    source: str,
    job_id: str,
) -> None:
    db.add(
        UsageEvent(
            user_id=current_user.id,
            event_type="job_api",
            metric_name="job_create",
            quantity=1.0,
            unit="count",
            meta={"source": source, "job_id": job_id},
        )
    )
    db.commit()


def _reset_job_rate_limit_state_for_tests() -> None:
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_BUCKETS.clear()
    with _ABUSE_LOCK:
        _ABUSE_DUPLICATE_BUCKETS.clear()