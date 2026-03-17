"""product_router.py — admin controls, billing/subscriptions, audit, and usage tracking."""

from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.auth import get_current_user, get_optional_user, require_admin
from api.database import (
    ActivityLog,
    BillingInvoice,
    BillingPlan,
    Prediction,
    Subscription,
    UsageEvent,
    User,
    get_db,
)

router = APIRouter(tags=["Admin", "Billing", "Usage"])


def _utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _period_end(start: datetime.datetime, interval: str) -> datetime.datetime:
    if interval == "yearly":
        return start + datetime.timedelta(days=365)
    return start + datetime.timedelta(days=30)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _append_activity(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    detail: dict[str, Any],
    request: Request,
) -> None:
    db.add(
        ActivityLog(
            user_id=user_id,
            action=action,
            detail=detail,
            ip_address=_client_ip(request),
        )
    )


class AdminUserUpdateRequest(BaseModel):
    email: str | None = Field(default=None, min_length=5, max_length=200)
    is_admin: bool | None = None
    is_active: bool | None = None


class BillingPlanRequest(BaseModel):
    code: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    interval: str = Field(default="monthly", pattern=r"^(monthly|yearly)$")
    price_usd: float = Field(default=0.0, ge=0.0)
    token_quota: int | None = Field(default=None, ge=0)
    features: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class SubscribeRequest(BaseModel):
    plan_code: str = Field(..., min_length=2, max_length=64)


class CancelSubscriptionRequest(BaseModel):
    immediate: bool = False


class InvoiceStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern=r"^(open|paid|void)$")


class UsageEventRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=64)
    metric_name: str = Field(..., min_length=1, max_length=64)
    quantity: float = Field(default=1.0, gt=0.0)
    unit: str = Field(default="count", min_length=1, max_length=32)
    meta: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/admin/users")
def admin_list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    search: str | None = Query(default=None),
    include_inactive: bool = Query(default=True),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    q = db.query(User)
    if search:
        like = f"%{search}%"
        q = q.filter((User.username.ilike(like)) | (User.email.ilike(like)))
    if not include_inactive:
        q = q.filter(User.is_active == True)

    total = q.count()
    rows = q.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
    admin_users = db.query(func.count(User.id)).filter(User.is_admin == True, User.is_active == True).scalar() or 0

    return {
        "success": True,
        "data": {
            "items": [u.to_dict() for u in rows],
            "total": total,
            "skip": skip,
            "limit": limit,
            "stats": {
                "active_users": int(active_users),
                "admin_users": int(admin_users),
                "requested_by": admin.username,
            },
        },
    }


@router.patch("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    req: AdminUserUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.email and req.email != user.email:
        exists = db.query(User).filter(User.email == req.email, User.id != user.id).first()
        if exists:
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = req.email

    if req.is_admin is not None and req.is_admin != user.is_admin:
        if not req.is_admin and user.is_admin:
            other_active_admins = (
                db.query(func.count(User.id))
                .filter(User.id != user.id, User.is_admin == True, User.is_active == True)
                .scalar()
                or 0
            )
            if other_active_admins == 0:
                raise HTTPException(status_code=400, detail="Cannot remove the last active admin")
        user.is_admin = req.is_admin

    if req.is_active is not None and req.is_active != user.is_active:
        if not req.is_active and user.is_admin:
            other_active_admins = (
                db.query(func.count(User.id))
                .filter(User.id != user.id, User.is_admin == True, User.is_active == True)
                .scalar()
                or 0
            )
            if other_active_admins == 0:
                raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
        user.is_active = req.is_active

    _append_activity(
        db,
        user_id=admin.id,
        action="admin_update_user",
        detail={"target_user_id": user.id, "is_admin": user.is_admin, "is_active": user.is_active},
        request=request,
    )
    db.commit()
    db.refresh(user)

    return {"success": True, "data": user.to_dict()}


@router.get("/api/admin/audit-logs")
def admin_audit_logs(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=2000),
    action: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    since_hours: int = Query(default=0, ge=0, le=24 * 365),
):
    q = db.query(ActivityLog)
    if action:
        q = q.filter(ActivityLog.action == action)
    if user_id is not None:
        q = q.filter(ActivityLog.user_id == user_id)
    if since_hours > 0:
        q = q.filter(ActivityLog.created_at >= (_utcnow() - datetime.timedelta(hours=since_hours)))

    total = q.count()
    rows = q.order_by(ActivityLog.created_at.desc()).limit(limit).all()

    return {
        "success": True,
        "data": {
            "items": [r.to_dict() for r in rows],
            "total": total,
            "limit": limit,
            "requested_by": admin.username,
        },
    }


@router.get("/api/billing/plans")
def list_billing_plans(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
    include_inactive: bool = Query(default=False),
):
    if include_inactive and (not current_user or not current_user.is_admin):
        raise HTTPException(status_code=403, detail="Admin access required for inactive plans")

    q = db.query(BillingPlan)
    if not include_inactive:
        q = q.filter(BillingPlan.is_active == True)

    rows = q.order_by(BillingPlan.price_usd.asc(), BillingPlan.created_at.asc()).all()
    return {"success": True, "data": [r.to_dict() for r in rows]}


@router.post("/api/admin/billing/plans")
def upsert_billing_plan(
    req: BillingPlanRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    code = req.code.strip().lower()
    row = db.query(BillingPlan).filter(BillingPlan.code == code).first()
    created = row is None

    if row is None:
        row = BillingPlan(code=code, name=req.name)
        db.add(row)

    row.name = req.name
    row.interval = req.interval
    row.price_usd = req.price_usd
    row.token_quota = req.token_quota
    row.features = req.features
    row.is_active = req.is_active

    _append_activity(
        db,
        user_id=admin.id,
        action="billing_plan_upsert",
        detail={"code": code, "created": created},
        request=request,
    )

    db.commit()
    db.refresh(row)

    return {"success": True, "data": {"created": created, "plan": row.to_dict()}}


@router.post("/api/billing/subscription/me")
def subscribe_me(
    req: SubscribeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = (
        db.query(BillingPlan)
        .filter(BillingPlan.code == req.plan_code.strip().lower(), BillingPlan.is_active == True)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Billing plan not found")

    now = _utcnow()

    existing = (
        db.query(Subscription)
        .filter(Subscription.user_id == current_user.id, Subscription.status == "active")
        .all()
    )
    for sub in existing:
        sub.status = "cancelled"
        sub.cancel_at_period_end = False

    sub = Subscription(
        user_id=current_user.id,
        plan_id=plan.id,
        status="active",
        current_period_start=now,
        current_period_end=_period_end(now, plan.interval),
        cancel_at_period_end=False,
    )
    db.add(sub)
    db.flush()

    is_free = plan.price_usd <= 0.0
    invoice = BillingInvoice(
        subscription_id=sub.id,
        user_id=current_user.id,
        amount_usd=plan.price_usd,
        currency="USD",
        status="paid" if is_free else "open",
        period_start=sub.current_period_start,
        period_end=sub.current_period_end,
        due_at=now if is_free else (now + datetime.timedelta(days=7)),
        paid_at=now if is_free else None,
        meta={"plan_code": plan.code, "plan_name": plan.name},
    )
    db.add(invoice)

    _append_activity(
        db,
        user_id=current_user.id,
        action="billing_subscribe",
        detail={"plan_code": plan.code, "subscription_id": sub.id},
        request=request,
    )

    db.commit()
    db.refresh(sub)
    db.refresh(invoice)

    return {
        "success": True,
        "data": {
            "subscription": sub.to_dict(),
            "plan": plan.to_dict(),
            "invoice": invoice.to_dict(),
        },
    }


@router.get("/api/billing/subscription/me")
def my_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == current_user.id)
        .order_by(Subscription.created_at.desc())
        .first()
    )

    if sub is None:
        return {"success": True, "data": None}

    return {
        "success": True,
        "data": {
            "subscription": sub.to_dict(),
            "plan": sub.plan.to_dict() if sub.plan else None,
        },
    }


@router.post("/api/billing/subscription/me/cancel")
def cancel_my_subscription(
    req: CancelSubscriptionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == current_user.id, Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription found")

    if req.immediate:
        sub.status = "cancelled"
        sub.current_period_end = _utcnow()
        sub.cancel_at_period_end = False
    else:
        sub.cancel_at_period_end = True

    _append_activity(
        db,
        user_id=current_user.id,
        action="billing_cancel_subscription",
        detail={"subscription_id": sub.id, "immediate": req.immediate},
        request=request,
    )

    db.commit()
    db.refresh(sub)

    return {"success": True, "data": sub.to_dict()}


@router.get("/api/billing/invoices/me")
def my_invoices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    q = db.query(BillingInvoice).filter(BillingInvoice.user_id == current_user.id)
    if status:
        q = q.filter(BillingInvoice.status == status)

    rows = q.order_by(BillingInvoice.created_at.desc()).limit(limit).all()
    return {"success": True, "data": [r.to_dict() for r in rows]}


@router.get("/api/admin/billing/invoices")
def admin_invoices(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
):
    q = db.query(BillingInvoice)
    if status:
        q = q.filter(BillingInvoice.status == status)
    if user_id is not None:
        q = q.filter(BillingInvoice.user_id == user_id)

    rows = q.order_by(BillingInvoice.created_at.desc()).limit(limit).all()
    return {
        "success": True,
        "data": {
            "items": [r.to_dict() for r in rows],
            "requested_by": admin.username,
        },
    }


@router.patch("/api/admin/billing/invoices/{invoice_id}")
def admin_update_invoice_status(
    invoice_id: int,
    req: InvoiceStatusUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    invoice = db.query(BillingInvoice).filter(BillingInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    invoice.status = req.status
    invoice.paid_at = _utcnow() if req.status == "paid" else None

    _append_activity(
        db,
        user_id=admin.id,
        action="admin_update_invoice",
        detail={"invoice_id": invoice_id, "status": req.status},
        request=request,
    )

    db.commit()
    db.refresh(invoice)

    return {"success": True, "data": invoice.to_dict()}


@router.post("/api/usage/events")
def record_usage_event(
    req: UsageEventRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = UsageEvent(
        user_id=current_user.id,
        event_type=req.event_type,
        metric_name=req.metric_name,
        quantity=req.quantity,
        unit=req.unit,
        meta=req.meta,
    )
    db.add(event)

    _append_activity(
        db,
        user_id=current_user.id,
        action="usage_event",
        detail={"event_type": req.event_type, "metric_name": req.metric_name, "quantity": req.quantity},
        request=request,
    )

    db.commit()
    db.refresh(event)

    return {"success": True, "data": event.to_dict()}


@router.get("/api/usage/me")
def usage_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    since_hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
):
    cutoff = _utcnow() - datetime.timedelta(hours=since_hours)

    pred_q = db.query(Prediction).filter(Prediction.user_id == current_user.id, Prediction.created_at >= cutoff)
    pred_count, pred_tokens, pred_cost = (
        pred_q.with_entities(
            func.count(Prediction.id),
            func.coalesce(func.sum(Prediction.tokens_used), 0),
            func.coalesce(func.sum(Prediction.cost_usd), 0.0),
        ).first()
        or (0, 0, 0.0)
    )

    events_q = db.query(UsageEvent).filter(UsageEvent.user_id == current_user.id, UsageEvent.created_at >= cutoff)
    events_total = events_q.with_entities(func.coalesce(func.sum(UsageEvent.quantity), 0.0)).scalar() or 0.0
    by_metric_rows = (
        events_q.with_entities(UsageEvent.metric_name, func.coalesce(func.sum(UsageEvent.quantity), 0.0))
        .group_by(UsageEvent.metric_name)
        .all()
    )

    return {
        "success": True,
        "data": {
            "user_id": current_user.id,
            "since_hours": since_hours,
            "predictions": {
                "count": int(pred_count or 0),
                "tokens": int(pred_tokens or 0),
                "cost_usd": float(pred_cost or 0.0),
            },
            "events": {
                "quantity_total": float(events_total or 0.0),
                "by_metric": {name: float(total or 0.0) for name, total in by_metric_rows},
            },
        },
    }


@router.get("/api/admin/usage/summary")
def admin_usage_summary(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    since_hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    top_users: int = Query(default=20, ge=1, le=100),
):
    cutoff = _utcnow() - datetime.timedelta(hours=since_hours)

    pred_q = db.query(Prediction).filter(Prediction.created_at >= cutoff)
    pred_count, pred_tokens, pred_cost = (
        pred_q.with_entities(
            func.count(Prediction.id),
            func.coalesce(func.sum(Prediction.tokens_used), 0),
            func.coalesce(func.sum(Prediction.cost_usd), 0.0),
        ).first()
        or (0, 0, 0.0)
    )

    event_q = db.query(UsageEvent).filter(UsageEvent.created_at >= cutoff)
    events_total = event_q.with_entities(func.coalesce(func.sum(UsageEvent.quantity), 0.0)).scalar() or 0.0
    by_metric_rows = (
        event_q.with_entities(UsageEvent.metric_name, func.coalesce(func.sum(UsageEvent.quantity), 0.0))
        .group_by(UsageEvent.metric_name)
        .all()
    )

    top_rows = (
        db.query(
            User.id,
            User.username,
            func.count(Prediction.id).label("prediction_count"),
            func.coalesce(func.sum(Prediction.tokens_used), 0).label("tokens"),
            func.coalesce(func.sum(Prediction.cost_usd), 0.0).label("cost_usd"),
        )
        .join(Prediction, Prediction.user_id == User.id)
        .filter(Prediction.created_at >= cutoff)
        .group_by(User.id, User.username)
        .order_by(func.count(Prediction.id).desc())
        .limit(top_users)
        .all()
    )

    return {
        "success": True,
        "data": {
            "since_hours": since_hours,
            "requested_by": admin.username,
            "predictions": {
                "count": int(pred_count or 0),
                "tokens": int(pred_tokens or 0),
                "cost_usd": float(pred_cost or 0.0),
            },
            "events": {
                "quantity_total": float(events_total or 0.0),
                "by_metric": {name: float(total or 0.0) for name, total in by_metric_rows},
            },
            "top_users": [
                {
                    "user_id": int(r.id),
                    "username": r.username,
                    "prediction_count": int(r.prediction_count or 0),
                    "tokens": int(r.tokens or 0),
                    "cost_usd": float(r.cost_usd or 0.0),
                }
                for r in top_rows
            ],
        },
    }
