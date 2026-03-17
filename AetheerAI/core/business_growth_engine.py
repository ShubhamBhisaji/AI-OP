"""
BusinessGrowthEngine — autonomous revenue operations for AetheerAI.

This module closes core business capability gaps:
  1) Lead acquisition system
  2) Marketing automation loop
  3) Conversion tracking
  4) Customer lifecycle management
  5) Autonomous revenue optimization actions
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GROWTH_STORE = Path(__file__).parent.parent / "registry" / "business_growth_store.json"

_STAGE_SEQUENCE = (
    "lead",
    "marketing_qualified",
    "sales_qualified",
    "trial",
    "customer",
    "retained",
    "churned",
)

_EVENT_TO_STAGE = {
    "lead_captured": "lead",
    "email_engaged": "marketing_qualified",
    "demo_booked": "sales_qualified",
    "trial_started": "trial",
    "purchase": "customer",
    "renewal": "retained",
    "churn": "churned",
}

_EVENT_SCORE = {
    "lead_captured": 3.0,
    "email_engaged": 5.0,
    "demo_booked": 8.0,
    "trial_started": 10.0,
    "purchase": 20.0,
    "renewal": 12.0,
    "churn": -25.0,
}


def _now() -> float:
    return time.time()


def _canonical_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _safe_stage(stage: str | None) -> str:
    normalized = (stage or "").strip().lower()
    if normalized in _STAGE_SEQUENCE:
        return normalized
    return "lead"


def _stage_rank(stage: str) -> int:
    try:
        return _STAGE_SEQUENCE.index(stage)
    except ValueError:
        return 0


@dataclass
class LeadRecord:
    lead_id: str
    source: str
    email: str = ""
    name: str = ""
    company: str = ""
    stage: str = "lead"
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    first_seen: float = field(default_factory=_now)
    last_touch: float | None = None
    touch_count: int = 0
    conversion_count: int = 0
    status: str = "new"
    customer_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead_id": self.lead_id,
            "source": self.source,
            "email": self.email,
            "name": self.name,
            "company": self.company,
            "stage": self.stage,
            "score": round(float(self.score), 3),
            "metadata": dict(self.metadata),
            "first_seen": self.first_seen,
            "last_touch": self.last_touch,
            "touch_count": self.touch_count,
            "conversion_count": self.conversion_count,
            "status": self.status,
            "customer_id": self.customer_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "LeadRecord":
        return cls(
            lead_id=str(raw.get("lead_id", uuid.uuid4().hex[:10])),
            source=str(raw.get("source", "manual")),
            email=_canonical_email(raw.get("email")),
            name=str(raw.get("name", "")),
            company=str(raw.get("company", "")),
            stage=_safe_stage(str(raw.get("stage", "lead"))),
            score=float(raw.get("score", 0.0)),
            metadata=dict(raw.get("metadata") or {}),
            first_seen=float(raw.get("first_seen", _now())),
            last_touch=(
                float(raw["last_touch"])
                if raw.get("last_touch") is not None
                else None
            ),
            touch_count=int(raw.get("touch_count", 0)),
            conversion_count=int(raw.get("conversion_count", 0)),
            status=str(raw.get("status", "new")),
            customer_id=(str(raw["customer_id"]) if raw.get("customer_id") else None),
        )


@dataclass
class CampaignRecord:
    campaign_id: str
    name: str
    channel: str
    cta: str
    target_stage: str = "lead"
    cadence_hours: float = 24.0
    enabled: bool = True
    created_at: float = field(default_factory=_now)
    sent_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "channel": self.channel,
            "cta": self.cta,
            "target_stage": self.target_stage,
            "cadence_hours": self.cadence_hours,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "sent_count": self.sent_count,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CampaignRecord":
        return cls(
            campaign_id=str(raw.get("campaign_id", uuid.uuid4().hex[:10])),
            name=str(raw.get("name", "Unnamed Campaign")),
            channel=str(raw.get("channel", "email")),
            cta=str(raw.get("cta", "Book a demo")),
            target_stage=_safe_stage(str(raw.get("target_stage", "lead"))),
            cadence_hours=float(raw.get("cadence_hours", 24.0)),
            enabled=bool(raw.get("enabled", True)),
            created_at=float(raw.get("created_at", _now())),
            sent_count=int(raw.get("sent_count", 0)),
        )


@dataclass
class ConversionEvent:
    event_id: str
    lead_id: str
    event_type: str
    value: float = 0.0
    currency: str = "USD"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "lead_id": self.lead_id,
            "event_type": self.event_type,
            "value": round(float(self.value), 2),
            "currency": self.currency,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ConversionEvent":
        return cls(
            event_id=str(raw.get("event_id", uuid.uuid4().hex[:10])),
            lead_id=str(raw.get("lead_id", "")),
            event_type=str(raw.get("event_type", "lead_captured")).strip().lower(),
            value=float(raw.get("value", 0.0)),
            currency=str(raw.get("currency", "USD")),
            metadata=dict(raw.get("metadata") or {}),
            timestamp=float(raw.get("timestamp", _now())),
        )


@dataclass
class CustomerRecord:
    customer_id: str
    lead_id: str
    stage: str = "customer"
    total_revenue: float = 0.0
    orders: int = 0
    renewals: int = 0
    churned_at: float | None = None
    last_event: str = ""
    last_event_at: float = field(default_factory=_now)
    health_score: float = 0.75

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "lead_id": self.lead_id,
            "stage": self.stage,
            "total_revenue": round(float(self.total_revenue), 2),
            "orders": self.orders,
            "renewals": self.renewals,
            "churned_at": self.churned_at,
            "last_event": self.last_event,
            "last_event_at": self.last_event_at,
            "health_score": round(float(self.health_score), 3),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CustomerRecord":
        return cls(
            customer_id=str(raw.get("customer_id", uuid.uuid4().hex[:10])),
            lead_id=str(raw.get("lead_id", "")),
            stage=_safe_stage(str(raw.get("stage", "customer"))),
            total_revenue=float(raw.get("total_revenue", 0.0)),
            orders=int(raw.get("orders", 0)),
            renewals=int(raw.get("renewals", 0)),
            churned_at=(
                float(raw["churned_at"])
                if raw.get("churned_at") is not None
                else None
            ),
            last_event=str(raw.get("last_event", "")),
            last_event_at=float(raw.get("last_event_at", _now())),
            health_score=float(raw.get("health_score", 0.75)),
        )


@dataclass
class RevenueAction:
    action_id: str
    action_type: str
    priority: str
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "priority": self.priority,
            "reason": self.reason,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RevenueAction":
        return cls(
            action_id=str(raw.get("action_id", uuid.uuid4().hex[:10])),
            action_type=str(raw.get("action_type", "task")),
            priority=str(raw.get("priority", "medium")),
            reason=str(raw.get("reason", "")),
            payload=dict(raw.get("payload") or {}),
            created_at=float(raw.get("created_at", _now())),
            status=str(raw.get("status", "open")),
        )


class BusinessGrowthEngine:
    """Lead-to-revenue operations engine with local persistence."""

    def __init__(self, store_path: Path = _GROWTH_STORE):
        self._store_path = Path(store_path)
        self._leads: dict[str, LeadRecord] = {}
        self._lead_index: dict[str, str] = {}
        self._campaigns: dict[str, CampaignRecord] = {}
        self._events: list[ConversionEvent] = []
        self._customers: dict[str, CustomerRecord] = {}
        self._actions: list[RevenueAction] = []
        self._load()

    # ------------------------------------------------------------------
    # Lead acquisition
    # ------------------------------------------------------------------

    def ingest_leads(self, leads: list[dict[str, Any]], source: str = "manual") -> dict[str, Any]:
        """Create or update leads from acquisition channels."""
        if not leads:
            return {
                "created": 0,
                "updated": 0,
                "total_leads": len(self._leads),
                "source": source,
            }

        created = 0
        updated = 0
        source_norm = (source or "manual").strip().lower() or "manual"

        for raw in leads:
            payload = dict(raw or {})
            key = self._lead_key(payload)
            existing_id = self._lead_index.get(key)

            if existing_id and existing_id in self._leads:
                lead = self._leads[existing_id]
                self._update_lead(lead, payload)
                updated += 1
                self._index_lead(lead, payload)
                continue

            lead_id = str(payload.get("lead_id") or uuid.uuid4().hex[:10])
            lead = LeadRecord(
                lead_id=lead_id,
                source=source_norm,
                email=_canonical_email(payload.get("email")),
                name=str(payload.get("name", "")).strip(),
                company=str(payload.get("company", "")).strip(),
                stage=_safe_stage(payload.get("stage", "lead")),
                score=float(payload.get("score", 0.0)),
                metadata=dict(payload.get("metadata") or {}),
            )
            lead.status = self._status_for_stage(lead.stage, lead.touch_count)
            self._leads[lead_id] = lead
            self._index_lead(lead, payload)
            created += 1

        self._save()
        return {
            "created": created,
            "updated": updated,
            "total_leads": len(self._leads),
            "source": source_norm,
        }

    # ------------------------------------------------------------------
    # Marketing automation loop
    # ------------------------------------------------------------------

    def register_campaign(
        self,
        name: str,
        channel: str,
        cta: str,
        target_stage: str = "lead",
        cadence_hours: float = 24.0,
        enabled: bool = True,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("Campaign name cannot be empty.")
        if not channel.strip():
            raise ValueError("Campaign channel cannot be empty.")
        if cadence_hours <= 0:
            raise ValueError("cadence_hours must be greater than 0.")

        campaign = CampaignRecord(
            campaign_id=uuid.uuid4().hex[:10],
            name=name.strip(),
            channel=channel.strip().lower(),
            cta=cta.strip() or "Book a demo",
            target_stage=_safe_stage(target_stage),
            cadence_hours=float(cadence_hours),
            enabled=bool(enabled),
        )
        self._campaigns[campaign.campaign_id] = campaign
        self._save()
        return campaign.to_dict()

    def run_marketing_automation(self, max_contacts: int = 25, now_ts: float | None = None) -> dict[str, Any]:
        """Run one deterministic nurture cycle and enqueue outreach actions."""
        if max_contacts <= 0:
            return {"contacts_sent": 0, "contacts": [], "reason": "max_contacts <= 0"}

        active_campaigns = [c for c in self._campaigns.values() if c.enabled]
        if not active_campaigns:
            return {"contacts_sent": 0, "contacts": [], "reason": "no_active_campaigns"}

        now = now_ts if now_ts is not None else _now()
        contacts: list[dict[str, Any]] = []

        candidates = [
            lead for lead in self._leads.values()
            if lead.stage not in ("customer", "retained", "churned")
        ]
        candidates.sort(key=lambda lead: (-lead.score, lead.first_seen))

        for lead in candidates:
            if len(contacts) >= max_contacts:
                break
            campaign = self._pick_campaign_for_stage(lead.stage, active_campaigns)
            if not campaign:
                continue

            cadence_seconds = max(3600.0, campaign.cadence_hours * 3600.0)
            if lead.last_touch is not None and (now - lead.last_touch) < cadence_seconds:
                continue

            lead.last_touch = now
            lead.touch_count += 1
            lead.status = self._status_for_stage(lead.stage, lead.touch_count)
            campaign.sent_count += 1

            action = self._queue_action(
                action_type="marketing_outreach",
                priority="medium",
                reason=f"Send {campaign.channel} nurture touch for lead {lead.lead_id}",
                payload={
                    "lead_id": lead.lead_id,
                    "campaign_id": campaign.campaign_id,
                    "channel": campaign.channel,
                    "cta": campaign.cta,
                    "stage": lead.stage,
                },
            )
            contacts.append(
                {
                    "lead_id": lead.lead_id,
                    "campaign_id": campaign.campaign_id,
                    "channel": campaign.channel,
                    "cta": campaign.cta,
                    "action_id": action["action_id"],
                }
            )

        self._save()
        return {
            "contacts_sent": len(contacts),
            "contacts": contacts,
            "active_campaigns": len(active_campaigns),
            "eligible_leads": len(candidates),
        }

    # ------------------------------------------------------------------
    # Conversion tracking + customer lifecycle
    # ------------------------------------------------------------------

    def track_conversion(
        self,
        lead_id: str,
        event_type: str,
        value: float = 0.0,
        currency: str = "USD",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        lead = self._leads.get(lead_id)
        if not lead:
            raise ValueError(f"Lead '{lead_id}' not found.")

        etype = (event_type or "").strip().lower()
        if not etype:
            raise ValueError("event_type cannot be empty.")

        event = ConversionEvent(
            event_id=uuid.uuid4().hex[:10],
            lead_id=lead_id,
            event_type=etype,
            value=float(value),
            currency=(currency or "USD").strip().upper(),
            metadata=dict(metadata or {}),
        )
        self._events.append(event)

        lead.last_touch = event.timestamp
        lead.conversion_count += 1
        lead.score += _EVENT_SCORE.get(etype, 2.0)

        target_stage = _EVENT_TO_STAGE.get(etype)
        if target_stage:
            if target_stage == "churned" or _stage_rank(target_stage) >= _stage_rank(lead.stage):
                lead.stage = target_stage
        lead.status = self._status_for_stage(lead.stage, lead.touch_count)

        customer_payload: dict[str, Any] | None = None
        if lead.stage in ("customer", "retained", "churned") or etype in ("purchase", "renewal", "churn"):
            customer = self._ensure_customer(lead, event.timestamp)
            customer.last_event = etype
            customer.last_event_at = event.timestamp

            if etype == "purchase":
                customer.orders += 1
                customer.total_revenue += max(0.0, float(value))
                customer.stage = "customer"
                customer.health_score = min(1.0, max(0.75, customer.health_score))
            elif etype == "renewal":
                customer.renewals += 1
                customer.total_revenue += max(0.0, float(value))
                customer.stage = "retained"
                customer.health_score = min(1.0, customer.health_score + 0.05)
            elif etype == "churn":
                customer.stage = "churned"
                customer.churned_at = event.timestamp
                customer.health_score = max(0.0, customer.health_score - 0.5)

            customer_payload = customer.to_dict()

        self._save()
        return {
            "event": event.to_dict(),
            "lead": lead.to_dict(),
            "customer": customer_payload,
        }

    def customer_lifecycle(self, stage: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        wanted = _safe_stage(stage) if stage else None
        rows = [c for c in self._customers.values() if (wanted is None or c.stage == wanted)]
        rows.sort(key=lambda c: c.last_event_at, reverse=True)
        return [c.to_dict() for c in rows[: max(1, int(limit))]]

    # ------------------------------------------------------------------
    # Revenue loop + metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        now = _now()
        leads = list(self._leads.values())
        customers = list(self._customers.values())

        stage_counts = {stage: 0 for stage in _STAGE_SEQUENCE}
        source_counts: dict[str, int] = {}
        touched = 0
        new_leads_7d = 0

        for lead in leads:
            stage_counts[lead.stage] = stage_counts.get(lead.stage, 0) + 1
            source_counts[lead.source] = source_counts.get(lead.source, 0) + 1
            if lead.touch_count > 0:
                touched += 1
            if now - lead.first_seen <= 7 * 86400:
                new_leads_7d += 1

        total_leads = len(leads)
        customers_total = sum(1 for lead in leads if lead.stage in ("customer", "retained", "churned"))
        churned_total = sum(1 for lead in leads if lead.stage == "churned")
        trial_total = sum(1 for lead in leads if _stage_rank(lead.stage) >= _stage_rank("trial"))
        sql_total = sum(1 for lead in leads if _stage_rank(lead.stage) >= _stage_rank("sales_qualified"))
        mql_total = sum(1 for lead in leads if _stage_rank(lead.stage) >= _stage_rank("marketing_qualified"))

        lead_to_customer_rate = (customers_total / total_leads) if total_leads else 0.0
        mql_rate = (mql_total / total_leads) if total_leads else 0.0
        sql_rate = (sql_total / total_leads) if total_leads else 0.0
        trial_rate = (trial_total / total_leads) if total_leads else 0.0
        churn_rate = (churned_total / customers_total) if customers_total else 0.0
        automation_coverage = (touched / total_leads) if total_leads else 0.0

        revenue_total = round(sum(c.total_revenue for c in customers), 2)
        purchase_events = sum(1 for e in self._events if e.event_type == "purchase")
        renewal_events = sum(1 for e in self._events if e.event_type == "renewal")

        return {
            "total_leads": total_leads,
            "new_leads_7d": new_leads_7d,
            "stage_counts": stage_counts,
            "lead_sources": source_counts,
            "active_campaigns": sum(1 for c in self._campaigns.values() if c.enabled),
            "campaign_count": len(self._campaigns),
            "customers_total": customers_total,
            "churned_total": churned_total,
            "lead_to_customer_rate": round(lead_to_customer_rate, 4),
            "mql_rate": round(mql_rate, 4),
            "sql_rate": round(sql_rate, 4),
            "trial_rate": round(trial_rate, 4),
            "churn_rate": round(churn_rate, 4),
            "automation_coverage": round(automation_coverage, 4),
            "events_total": len(self._events),
            "purchase_events": purchase_events,
            "renewal_events": renewal_events,
            "revenue_total": revenue_total,
            "open_revenue_actions": sum(1 for a in self._actions if a.status == "open"),
        }

    def run_revenue_loop(
        self,
        min_new_leads: int = 20,
        min_lead_to_customer_rate: float = 0.05,
        max_churn_rate: float = 0.20,
    ) -> dict[str, Any]:
        """Evaluate revenue health and queue autonomous remediation actions."""
        metrics = self.metrics()
        generated_actions: list[dict[str, Any]] = []

        if metrics["campaign_count"] == 0:
            generated_actions.append(
                self._queue_action(
                    action_type="create_campaigns",
                    priority="high",
                    reason="No active campaign loop exists.",
                    payload={
                        "suggestion": {
                            "name": "Always-on nurture",
                            "channel": "email",
                            "target_stage": "lead",
                        }
                    },
                )
            )

        if metrics["new_leads_7d"] < int(min_new_leads):
            generated_actions.append(
                self._queue_action(
                    action_type="increase_lead_acquisition",
                    priority="high",
                    reason="Top-of-funnel lead volume is below target.",
                    payload={
                        "current_new_leads_7d": metrics["new_leads_7d"],
                        "target_new_leads_7d": int(min_new_leads),
                    },
                )
            )

        if metrics["events_total"] == 0:
            generated_actions.append(
                self._queue_action(
                    action_type="instrument_conversion_tracking",
                    priority="high",
                    reason="No conversion events are being tracked.",
                    payload={"required_events": sorted(_EVENT_TO_STAGE.keys())},
                )
            )

        if metrics["total_leads"] > 0 and metrics["lead_to_customer_rate"] < float(min_lead_to_customer_rate):
            generated_actions.append(
                self._queue_action(
                    action_type="improve_conversion_rate",
                    priority="high",
                    reason="Lead-to-customer conversion rate is below target.",
                    payload={
                        "current_rate": metrics["lead_to_customer_rate"],
                        "target_rate": float(min_lead_to_customer_rate),
                    },
                )
            )

        if metrics["customers_total"] > 0 and metrics["churn_rate"] > float(max_churn_rate):
            generated_actions.append(
                self._queue_action(
                    action_type="launch_retention_playbook",
                    priority="high",
                    reason="Customer churn is above threshold.",
                    payload={
                        "current_churn_rate": metrics["churn_rate"],
                        "max_churn_rate": float(max_churn_rate),
                    },
                )
            )

        if (
            metrics["active_campaigns"] > 0
            and metrics["total_leads"] > 0
            and metrics["automation_coverage"] < 0.70
        ):
            generated_actions.append(
                self._queue_action(
                    action_type="expand_marketing_automation",
                    priority="medium",
                    reason="Too few leads are touched by automation.",
                    payload={
                        "automation_coverage": metrics["automation_coverage"],
                        "target": 0.70,
                    },
                )
            )

        self._save()
        return {
            "status": "attention_required" if generated_actions else "healthy",
            "actions": generated_actions,
            "metrics": metrics,
            "generated_at": _now(),
        }

    def open_actions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = [a for a in self._actions if a.status == "open"]
        rows.sort(key=lambda a: a.created_at, reverse=True)
        return [a.to_dict() for a in rows[: max(1, int(limit))]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lead_key(self, payload: dict[str, Any]) -> str:
        external_id = str(payload.get("external_id", "")).strip().lower()
        if external_id:
            return f"x:{external_id}"

        email = _canonical_email(payload.get("email"))
        if email:
            return f"e:{email}"

        name = str(payload.get("name", "")).strip().lower()
        company = str(payload.get("company", "")).strip().lower()
        if name or company:
            return f"n:{name}|c:{company}"

        return f"temp:{uuid.uuid4().hex[:12]}"

    def _index_lead(self, lead: LeadRecord, payload: dict[str, Any] | None = None) -> None:
        if payload:
            external_id = str(payload.get("external_id", "")).strip().lower()
            if external_id:
                self._lead_index[f"x:{external_id}"] = lead.lead_id

        if lead.email:
            self._lead_index[f"e:{lead.email}"] = lead.lead_id

        name = lead.name.strip().lower()
        company = lead.company.strip().lower()
        if name or company:
            self._lead_index[f"n:{name}|c:{company}"] = lead.lead_id

    def _update_lead(self, lead: LeadRecord, payload: dict[str, Any]) -> None:
        maybe_email = _canonical_email(payload.get("email"))
        if maybe_email:
            lead.email = maybe_email

        maybe_name = str(payload.get("name", "")).strip()
        if maybe_name:
            lead.name = maybe_name

        maybe_company = str(payload.get("company", "")).strip()
        if maybe_company:
            lead.company = maybe_company

        incoming_stage = _safe_stage(payload.get("stage", lead.stage))
        if _stage_rank(incoming_stage) >= _stage_rank(lead.stage):
            lead.stage = incoming_stage

        if "score" in payload:
            lead.score = max(lead.score, float(payload.get("score", lead.score)))

        lead.metadata.update(dict(payload.get("metadata") or {}))
        lead.status = self._status_for_stage(lead.stage, lead.touch_count)

    def _status_for_stage(self, stage: str, touch_count: int) -> str:
        if stage == "churned":
            return "churned"
        if stage in ("customer", "retained"):
            return "customer"
        if touch_count > 0:
            return "nurturing"
        return "new"

    def _pick_campaign_for_stage(
        self,
        stage: str,
        campaigns: list[CampaignRecord],
    ) -> CampaignRecord | None:
        for campaign in campaigns:
            if campaign.target_stage == stage:
                return campaign
        for campaign in campaigns:
            if campaign.target_stage == "lead":
                return campaign
        return campaigns[0] if campaigns else None

    def _ensure_customer(self, lead: LeadRecord, ts: float) -> CustomerRecord:
        if lead.customer_id and lead.customer_id in self._customers:
            return self._customers[lead.customer_id]

        customer_id = uuid.uuid4().hex[:10]
        customer = CustomerRecord(
            customer_id=customer_id,
            lead_id=lead.lead_id,
            stage=("churned" if lead.stage == "churned" else "customer"),
            last_event_at=ts,
        )
        self._customers[customer_id] = customer
        lead.customer_id = customer_id
        return customer

    def _queue_action(
        self,
        action_type: str,
        priority: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for existing in reversed(self._actions):
            if existing.status == "open" and existing.action_type == action_type:
                existing.priority = priority
                existing.reason = reason
                existing.payload = dict(payload or {})
                return existing.to_dict()

        action = RevenueAction(
            action_id=uuid.uuid4().hex[:10],
            action_type=action_type,
            priority=priority,
            reason=reason,
            payload=dict(payload or {}),
        )
        self._actions.append(action)
        return action.to_dict()

    def _save(self) -> None:
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "leads": {k: v.to_dict() for k, v in self._leads.items()},
                "lead_index": dict(self._lead_index),
                "campaigns": {k: v.to_dict() for k, v in self._campaigns.items()},
                "events": [e.to_dict() for e in self._events],
                "customers": {k: v.to_dict() for k, v in self._customers.items()},
                "actions": [a.to_dict() for a in self._actions],
            }
            self._store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("BusinessGrowthEngine._save failed: %s", exc)

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            self._leads = {
                str(k): LeadRecord.from_dict(v)
                for k, v in dict(raw.get("leads") or {}).items()
            }
            self._lead_index = {
                str(k): str(v)
                for k, v in dict(raw.get("lead_index") or {}).items()
            }
            self._campaigns = {
                str(k): CampaignRecord.from_dict(v)
                for k, v in dict(raw.get("campaigns") or {}).items()
            }
            self._events = [ConversionEvent.from_dict(v) for v in list(raw.get("events") or [])]
            self._customers = {
                str(k): CustomerRecord.from_dict(v)
                for k, v in dict(raw.get("customers") or {}).items()
            }
            self._actions = [RevenueAction.from_dict(v) for v in list(raw.get("actions") or [])]

            # Backfill index in case older stores are missing lead_index entries.
            for lead in self._leads.values():
                self._index_lead(lead)
        except Exception as exc:
            logger.error("BusinessGrowthEngine._load failed: %s", exc)
