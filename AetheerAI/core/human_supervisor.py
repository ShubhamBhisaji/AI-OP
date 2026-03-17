"""
Human-Supervisor Mode — Adaptive Delegation & Bottleneck Detection

In 2026, the human's role is directing, not doing.  This module tracks
every approval event, detects categories where the human is creating
a bottleneck, and suggests policy upgrades that let trusted agents
handle recurring decisions autonomously going forward.

Architecture
------------
  DelegationLevel   — MANUAL → SUPERVISED → AUTONOMOUS
  ApprovalEvent     — timestamped record of a single human/auto approval
  BottleneckReport  — statistical summary of delay in a category
  PolicyUpdate      — AI-proposed permission upgrade for a category
  HumanSupervisor   — main facade

Usage
-----
    hs = HumanSupervisor(ai_adapter)

    hs.record_approval("BillingAgent", "send_invoice", category="finance",
                        wait_ms=45_000, approved=True)

    reports = hs.detect_bottlenecks()
    for r in reports:
        policy = hs.suggest_policy_update(r.category)
        hs.apply_policy(policy)
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Enums & data structures
# ═══════════════════════════════════════════════════════════════════════════


class DelegationLevel(str, Enum):
    MANUAL      = "MANUAL"       # human must approve every time
    SUPERVISED  = "SUPERVISED"   # agent acts, human reviews within window
    AUTONOMOUS  = "AUTONOMOUS"   # agent acts freely; human sees summary


@dataclass
class ApprovalEvent:
    event_id: str
    agent_name: str
    action: str
    category: str           # "finance", "comms", "deployment", "data", etc.
    wait_ms: float          # how long the human took to approve/reject (0 = auto)
    approved: bool
    auto_approved: bool = False
    timestamp: float = field(default_factory=time.time)
    notes: str = ""


@dataclass
class BottleneckReport:
    category: str
    event_count: int
    avg_wait_ms: float
    max_wait_ms: float
    approval_rate: float    # fraction that were ultimately approved
    bottleneck_score: float # 0–1 composite severity
    suggestion: str         # one-line human-readable recommendation


@dataclass
class PolicyUpdate:
    category: str
    action: str
    old_level: DelegationLevel
    new_level: DelegationLevel
    reasoning: str
    conditions: list[str]   # guard conditions that still apply
    proposed_at: float = field(default_factory=time.time)
    applied: bool = False


@dataclass
class ManagementStyleReport:
    total_events: int
    avg_wait_ms: float
    bottleneck_categories: list[str]
    style_label: str        # "Hands-On", "Balanced", "Delegator", "Liberator"
    style_description: str
    autonomy_score: float   # 0–1 (0 = micromanager, 1 = fully autonomous)
    recommended_next_step: str


# ═══════════════════════════════════════════════════════════════════════════
# Supervisor constants
# ═══════════════════════════════════════════════════════════════════════════

_BOTTLENECK_THRESHOLD_MS   = 30_000    # 30 s avg wait → potential bottleneck
_BOTTLENECK_MIN_EVENTS     = 3         # need at least 3 events to analyse
_HIGH_APPROVAL_RATE_FLOOR  = 0.85      # if ≥85% are approved, consider delegating


# ═══════════════════════════════════════════════════════════════════════════
# Human Supervisor
# ═══════════════════════════════════════════════════════════════════════════


class HumanSupervisor:
    """
    Tracks human approval behaviour, detects bottlenecks, and proposes
    Delegation Level upgrades for recurring, low-risk approval categories.

    Parameters
    ----------
    ai_adapter : AIAdapter  — for AI-generated policy suggestions.
    """

    def __init__(self, ai_adapter):
        self.ai_adapter = ai_adapter
        self._events:    list[ApprovalEvent]   = []
        self._policies:  dict[str, DelegationLevel] = {}
        self._updates:   list[PolicyUpdate]    = []

    # ──────────────────────────────────────────────────────────────────
    # Recording
    # ──────────────────────────────────────────────────────────────────

    def record_approval(
        self,
        agent_name: str,
        action: str,
        category: str,
        wait_ms: float,
        approved: bool,
        auto_approved: bool = False,
        notes: str = "",
    ) -> ApprovalEvent:
        """Record a single human or auto-approval event."""
        import uuid
        event = ApprovalEvent(
            event_id=str(uuid.uuid4())[:8],
            agent_name=agent_name,
            action=action,
            category=category,
            wait_ms=wait_ms,
            approved=approved,
            auto_approved=auto_approved,
            notes=notes,
        )
        self._events.append(event)
        return event

    # ──────────────────────────────────────────────────────────────────
    # Bottleneck detection
    # ──────────────────────────────────────────────────────────────────

    def detect_bottlenecks(self) -> list[BottleneckReport]:
        """
        Analyse approval events by category. Return categories where the
        human is statistically causing delays.
        """
        by_cat: dict[str, list[ApprovalEvent]] = {}
        for ev in self._events:
            if not ev.auto_approved:
                by_cat.setdefault(ev.category, []).append(ev)

        reports: list[BottleneckReport] = []
        for category, events in by_cat.items():
            if len(events) < _BOTTLENECK_MIN_EVENTS:
                continue

            waits       = [e.wait_ms for e in events]
            avg_wait    = statistics.mean(waits)
            max_wait    = max(waits)
            appr_rate   = sum(1 for e in events if e.approved) / len(events)

            # Bottleneck score: high wait + high approval rate → safe to delegate
            wait_score  = min(avg_wait / 120_000, 1.0)   # normalise to 2 min cap
            safety_score = appr_rate                      # high = safe to automate
            bottleneck  = (wait_score * 0.6) + (safety_score * 0.4)

            current_level = self._policies.get(category, DelegationLevel.MANUAL)
            suggestion = ""
            if avg_wait > _BOTTLENECK_THRESHOLD_MS and appr_rate >= _HIGH_APPROVAL_RATE_FLOOR:
                suggestion = (
                    f"You approve {appr_rate:.0%} of '{category}' requests "
                    f"(avg delay {avg_wait/1000:.0f}s). "
                    f"Consider upgrading to {DelegationLevel.SUPERVISED.value}."
                )
            elif current_level == DelegationLevel.SUPERVISED and appr_rate >= 0.95:
                suggestion = (
                    f"'{category}' has a {appr_rate:.0%} approval rate in SUPERVISED mode. "
                    f"Consider upgrading to AUTONOMOUS."
                )

            if bottleneck > 0.3:
                reports.append(BottleneckReport(
                    category=category,
                    event_count=len(events),
                    avg_wait_ms=avg_wait,
                    max_wait_ms=max_wait,
                    approval_rate=appr_rate,
                    bottleneck_score=round(bottleneck, 2),
                    suggestion=suggestion,
                ))

        reports.sort(key=lambda r: r.bottleneck_score, reverse=True)
        return reports

    # ──────────────────────────────────────────────────────────────────
    # Policy suggestions
    # ──────────────────────────────────────────────────────────────────

    def suggest_policy_update(self, category: str) -> PolicyUpdate | None:
        """
        Use the AI to generate a specific PolicyUpdate for a bottlenecked
        category.  Returns None if category has insufficient data.
        """
        events = [e for e in self._events if e.category == category and not e.auto_approved]
        if len(events) < _BOTTLENECK_MIN_EVENTS:
            return None

        current = self._policies.get(category, DelegationLevel.MANUAL)
        if current == DelegationLevel.AUTONOMOUS:
            return None  # already at max

        waits    = [e.wait_ms for e in events]
        appr_rate= sum(1 for e in events if e.approved) / len(events)
        actions  = list({e.action for e in events})

        prompt = f"""You are an AI delegation advisor. Analyse this approval data and propose a policy upgrade.

Category: {category}
Current delegation level: {current.value}
Number of approval events: {len(events)}
Average human wait time: {statistics.mean(waits)/1000:.1f} seconds
Approval rate: {appr_rate:.0%}
Actions in this category: {actions}

The human is creating a bottleneck. Propose a targeted policy upgrade.
Return ONLY valid JSON:
{{
  "new_level": "SUPERVISED" or "AUTONOMOUS",
  "conditions": ["<guard condition still required>"],
  "reasoning": "<why this upgrade is safe — 2 sentences>",
  "action": "<one sentence describing the new delegation policy>"
}}"""

        raw = self.ai_adapter.chat([
            {"role": "system", "content": "You are an AI delegation policy advisor. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ])
        data = self._parse_json(raw)
        try:
            new_level = DelegationLevel(data.get("new_level", "SUPERVISED"))
        except ValueError:
            new_level = DelegationLevel.SUPERVISED

        update = PolicyUpdate(
            category=category,
            action=data.get("action", f"Auto-approve {category} actions"),
            old_level=current,
            new_level=new_level,
            reasoning=data.get("reasoning", ""),
            conditions=data.get("conditions", []),
        )
        self._updates.append(update)
        return update

    def apply_policy(self, update: PolicyUpdate) -> None:
        """Apply a PolicyUpdate — upgrades the delegation level for a category."""
        self._policies[update.category] = update.new_level
        update.applied = True
        logger.info(
            "HumanSupervisor: '%s' upgraded from %s → %s",
            update.category, update.old_level.value, update.new_level.value,
        )

    def set_delegation_level(self, category: str, level: DelegationLevel) -> None:
        self._policies[category] = level

    def get_delegation_level(self, category: str) -> DelegationLevel:
        return self._policies.get(category, DelegationLevel.MANUAL)

    def can_auto_approve(self, agent_name: str, action: str, category: str) -> bool:
        """
        Returns True if the current delegation policy allows an agent
        to act without human review.
        """
        level = self.get_delegation_level(category)
        return level == DelegationLevel.AUTONOMOUS

    # ──────────────────────────────────────────────────────────────────
    # Management style analysis
    # ──────────────────────────────────────────────────────────────────

    def management_style_report(self) -> ManagementStyleReport:
        """Infer the user's management style from their approval history."""
        human_events = [e for e in self._events if not e.auto_approved]
        if not human_events:
            return ManagementStyleReport(
                total_events=0,
                avg_wait_ms=0,
                bottleneck_categories=[],
                style_label="No Data",
                style_description="Record some approval events to see your management style.",
                autonomy_score=0.0,
                recommended_next_step="Start recording approvals with record_approval().",
            )

        waits       = [e.wait_ms for e in human_events]
        avg_wait    = statistics.mean(waits)
        auto_events = [e for e in self._events if e.auto_approved]
        auto_rate   = len(auto_events) / max(len(self._events), 1)

        bottleneck_cats = [
            r.category for r in self.detect_bottlenecks() if r.bottleneck_score > 0.5
        ]

        autonomy_score = round(auto_rate * 0.6 + min(1.0, 1 - avg_wait / 120_000) * 0.4, 2)
        autonomy_score = max(0.0, min(1.0, autonomy_score))

        if autonomy_score >= 0.75:
            style_label = "Liberator"
            style_desc  = "You delegate freely and trust your agents to act. Smart scaling."
        elif autonomy_score >= 0.5:
            style_label = "Delegator"
            style_desc  = "You're comfortable automating routine tasks. Room to push further."
        elif autonomy_score >= 0.25:
            style_label = "Balanced"
            style_desc  = "You balance oversight with efficiency. A few categories could be delegated further."
        else:
            style_label = "Hands-On"
            style_desc  = "You like to stay involved. You may be creating bottlenecks in high-volume categories."

        next_step = (
            f"Upgrade '{bottleneck_cats[0]}' to SUPERVISED mode to reclaim ~{avg_wait/1000:.0f}s per approval."
            if bottleneck_cats else
            "Your delegation is healthy. Consider reviewing policy_updates for further automation."
        )

        return ManagementStyleReport(
            total_events=len(human_events),
            avg_wait_ms=avg_wait,
            bottleneck_categories=bottleneck_cats,
            style_label=style_label,
            style_description=style_desc,
            autonomy_score=autonomy_score,
            recommended_next_step=next_step,
        )

    # ──────────────────────────────────────────────────────────────────
    # Read-only views
    # ──────────────────────────────────────────────────────────────────

    def delegation_levels(self) -> dict[str, str]:
        return {k: v.value for k, v in self._policies.items()}

    def pending_policy_updates(self) -> list[dict]:
        return [
            {
                "category": u.category,
                "action": u.action,
                "old_level": u.old_level.value,
                "new_level": u.new_level.value,
                "reasoning": u.reasoning,
                "conditions": u.conditions,
                "applied": u.applied,
            }
            for u in self._updates
            if not u.applied
        ]

    def recent_events(self, limit: int = 50) -> list[dict]:
        return [
            {
                "agent": e.agent_name,
                "action": e.action,
                "category": e.category,
                "wait_s": round(e.wait_ms / 1000, 1),
                "approved": e.approved,
                "auto": e.auto_approved,
                "ts": e.timestamp,
            }
            for e in self._events[-limit:]
        ]

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> dict:
        import re
        for pattern in (r"```(?:json)?\s*([\s\S]+?)```", r"\{[\s\S]+\}"):
            m = re.search(pattern, text)
            if m:
                fragment = m.group(1) if "```" in pattern else m.group()
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError:
                    pass
        return {}
