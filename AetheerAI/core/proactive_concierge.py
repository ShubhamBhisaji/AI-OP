"""
Proactive Concierge — Event-Driven Autonomous AI Triggering

Most agents wait for a prompt.  The Proactive Concierge acts on signals.
It monitors metric feeds from connected apps (CRM, cloud logs, dashboards),
applies rule-based thresholds, and automatically spawns a "War Room" of
specialist agents when anomalies are detected — presenting a solution
before the user even checks their email.

Architecture
------------
  ConciergeRule   — threshold rule on a (source, metric) pair
  Signal          — incoming metric observation
  WarRoom         — an autonomous investigation session
  WarRoomFinding  — individual agent report within a War Room
  ProactiveConcierge — main facade

Usage
-----
    pc = ProactiveConcierge(ai_adapter)

    pc.add_rule(
        name="Sales Drop Alert",
        source="crm",
        metric="daily_revenue",
        threshold=0.10,
        comparison="pct_drop",    # trigger if value drops ≥ 10%
        agent_roles=["AnalystAgent", "SalesAgent", "ReportingAgent"],
    )

    # Feed live signals (from webhooks, poll loops, etc.)
    pc.feed_signal("crm", "daily_revenue", 8_500, context={"prev": 10_000})

    # Check for active war rooms
    for wr in pc.active_war_rooms():
        print(wr["status"], wr["findings"])
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Constants & helpers
# ═══════════════════════════════════════════════════════════════════════════

_COMPARISON_OPS = ("gt", "lt", "gte", "lte", "pct_drop", "pct_rise", "eq", "ne")

_SEVERITY_MAP = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🟢",
}


# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ConciergeRule:
    rule_id: str
    name: str
    source: str             # e.g. "crm", "cloud_logs", "analytics"
    metric: str             # e.g. "daily_revenue", "error_rate"
    threshold: float        # numeric threshold
    comparison: str         # one of _COMPARISON_OPS
    agent_roles: list[str]  # War Room members to spawn
    severity: str = "high"  # low | medium | high | critical
    enabled: bool = True
    cooldown_s: float = 300.0   # minimum seconds between triggers
    last_triggered: float = 0.0
    trigger_count: int = 0


@dataclass
class Signal:
    signal_id: str
    source: str
    metric: str
    value: float
    previous_value: float | None = None
    context: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class WarRoomFinding:
    agent_role: str
    finding: str
    severity: str = "medium"
    action_items: list[str] = field(default_factory=list)


@dataclass
class WarRoom:
    war_room_id: str
    name: str
    trigger_signal: Signal
    trigger_rule: str       # rule name
    agent_roles: list[str]
    status: str = "spawned"  # spawned | investigating | resolved | dismissed
    findings: list[WarRoomFinding] = field(default_factory=list)
    summary: str = ""
    recommended_actions: list[str] = field(default_factory=list)
    spawned_at: float = field(default_factory=time.time)
    resolved_at: float | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Proactive Concierge
# ═══════════════════════════════════════════════════════════════════════════


class ProactiveConcierge:
    """
    Event-driven AI concierge that monitors metric signals and autonomously
    spawns War Rooms when anomalies are detected.

    Parameters
    ----------
    ai_adapter : AIAdapter  — used to run War Room agent investigations.
    """

    def __init__(self, ai_adapter):
        self.ai_adapter = ai_adapter
        self._rules:        list[ConciergeRule] = []
        self._signal_log:   list[Signal]        = []
        self._war_rooms:    list[WarRoom]        = []

    # ──────────────────────────────────────────────────────────────────
    # Rule management
    # ──────────────────────────────────────────────────────────────────

    def add_rule(
        self,
        name: str,
        source: str,
        metric: str,
        threshold: float,
        comparison: str = "pct_drop",
        agent_roles: list[str] | None = None,
        severity: str = "high",
        cooldown_s: float = 300.0,
    ) -> ConciergeRule:
        """Register a monitoring rule.  Returns the created rule."""
        if comparison not in _COMPARISON_OPS:
            raise ValueError(f"comparison must be one of {_COMPARISON_OPS}")
        rule = ConciergeRule(
            rule_id=str(uuid.uuid4())[:8],
            name=name,
            source=source,
            metric=metric,
            threshold=threshold,
            comparison=comparison,
            agent_roles=agent_roles or ["AnalystAgent", "ReportingAgent"],
            severity=severity,
            cooldown_s=cooldown_s,
        )
        self._rules.append(rule)
        logger.info("Concierge: rule '%s' added (%s %s %s%s)",
                    name, metric, comparison, threshold,
                    "" if comparison not in ("pct_drop", "pct_rise") else "%")
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        return len(self._rules) < before

    def toggle_rule(self, rule_id: str, enabled: bool) -> bool:
        for r in self._rules:
            if r.rule_id == rule_id:
                r.enabled = enabled
                return True
        return False

    def rules(self) -> list[dict]:
        return [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "source": r.source,
                "metric": r.metric,
                "threshold": r.threshold,
                "comparison": r.comparison,
                "agent_roles": r.agent_roles,
                "severity": r.severity,
                "enabled": r.enabled,
                "trigger_count": r.trigger_count,
                "cooldown_s": r.cooldown_s,
            }
            for r in self._rules
        ]

    # ──────────────────────────────────────────────────────────────────
    # Signal ingestion
    # ──────────────────────────────────────────────────────────────────

    def feed_signal(
        self,
        source: str,
        metric: str,
        value: float,
        previous_value: float | None = None,
        context: dict | None = None,
    ) -> list[WarRoom]:
        """
        Feed a live metric signal.  Evaluates all matching rules and spawns
        War Rooms for any that are triggered.  Returns list of spawned War Rooms.
        """
        signal = Signal(
            signal_id=str(uuid.uuid4())[:8],
            source=source,
            metric=metric,
            value=value,
            previous_value=previous_value,
            context=context or {},
        )
        self._signal_log.append(signal)

        spawned: list[WarRoom] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            if rule.source != source or rule.metric != metric:
                continue
            # Cooldown check
            if time.time() - rule.last_triggered < rule.cooldown_s:
                continue

            if self._evaluate_rule(rule, signal):
                rule.last_triggered = time.time()
                rule.trigger_count  += 1
                war_room = self._spawn_war_room(signal, rule)
                spawned.append(war_room)

        return spawned

    def _evaluate_rule(self, rule: ConciergeRule, signal: Signal) -> bool:
        """Return True if the rule condition is met."""
        v   = signal.value
        thr = rule.threshold
        prev = signal.previous_value

        if rule.comparison == "gt":
            return v > thr
        if rule.comparison == "gte":
            return v >= thr
        if rule.comparison == "lt":
            return v < thr
        if rule.comparison == "lte":
            return v <= thr
        if rule.comparison == "eq":
            return v == thr
        if rule.comparison == "ne":
            return v != thr
        if rule.comparison == "pct_drop":
            if prev is None or prev == 0:
                return False
            return (prev - v) / prev >= thr
        if rule.comparison == "pct_rise":
            if prev is None or prev == 0:
                return v > thr
            return (v - prev) / prev >= thr
        return False

    # ──────────────────────────────────────────────────────────────────
    # War Room lifecycle
    # ──────────────────────────────────────────────────────────────────

    def _spawn_war_room(self, signal: Signal, rule: ConciergeRule) -> WarRoom:
        wr = WarRoom(
            war_room_id=str(uuid.uuid4())[:8],
            name=f"War Room — {rule.name}",
            trigger_signal=signal,
            trigger_rule=rule.name,
            agent_roles=rule.agent_roles[:],
        )
        self._war_rooms.append(wr)
        logger.warning(
            "Concierge: ⚠️  War Room spawned [%s] triggered by %s/%s = %s",
            wr.war_room_id, signal.source, signal.metric, signal.value,
        )
        return wr

    def investigate(self, war_room_id: str) -> WarRoom:
        """
        Run the War Room investigation.  Each agent role is given the
        signal context and provides findings + action items via AI.
        Returns the updated WarRoom with full findings and a summary.
        """
        wr = next((w for w in self._war_rooms if w.war_room_id == war_room_id), None)
        if not wr:
            raise ValueError(f"War Room '{war_room_id}' not found.")

        wr.status = "investigating"
        signal = wr.trigger_signal
        ctx = json.dumps(signal.context, indent=2) if signal.context else "{}"

        findings: list[WarRoomFinding] = []
        for role in wr.agent_roles:
            prompt = f"""You are the {role} in an emergency War Room investigation.

TRIGGER: {wr.trigger_rule}
METRIC: {signal.source}/{signal.metric}
CURRENT VALUE: {signal.value}
PREVIOUS VALUE: {signal.previous_value or "unknown"}
CONTEXT: {ctx}

As {role}, provide your analysis and action items.
Return ONLY valid JSON:
{{
  "finding": "<2-3 sentence analysis from your role's perspective>",
  "severity": "low|medium|high|critical",
  "action_items": ["<immediate action>", "<follow-up action>"]
}}"""
            try:
                raw = self.ai_adapter.chat([
                    {"role": "system", "content": f"You are {role} in an emergency AI War Room. Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ])
                data = self._parse_json(raw)
                finding = WarRoomFinding(
                    agent_role=role,
                    finding=data.get("finding", raw[:200]),
                    severity=data.get("severity", "medium"),
                    action_items=data.get("action_items", []),
                )
            except Exception as exc:
                finding = WarRoomFinding(
                    agent_role=role,
                    finding=f"Investigation failed: {exc}",
                    severity="low",
                )
            findings.append(finding)

        wr.findings = findings

        # Generate executive summary
        summary_prompt = f"""Summarise this War Room investigation for an executive.
Be concise, action-oriented, and flag the top priority.

War Room: {wr.name}
Trigger: {signal.source}/{signal.metric} = {signal.value} (prev: {signal.previous_value})
Agent Findings:
{chr(10).join(f"- {f.agent_role}: {f.finding}" for f in findings)}

Return ONLY valid JSON:
{{
  "summary": "<3-sentence executive summary>",
  "recommended_actions": ["<top action>", "<second action>", "<monitoring action>"]
}}"""
        try:
            raw_sum = self.ai_adapter.chat([
                {"role": "system", "content": "You are a War Room coordinator. Return valid JSON only."},
                {"role": "user", "content": summary_prompt},
            ])
            sum_data = self._parse_json(raw_sum)
            wr.summary = sum_data.get("summary", "")
            wr.recommended_actions = sum_data.get("recommended_actions", [])
        except Exception:
            wr.summary = "Investigation complete. See individual agent findings."

        wr.status = "resolved"
        wr.resolved_at = time.time()
        logger.info("Concierge: War Room [%s] resolved — %d findings", war_room_id, len(findings))
        return wr

    def dismiss_war_room(self, war_room_id: str) -> bool:
        for wr in self._war_rooms:
            if wr.war_room_id == war_room_id:
                wr.status = "dismissed"
                return True
        return False

    # ──────────────────────────────────────────────────────────────────
    # Read-only views
    # ──────────────────────────────────────────────────────────────────

    def active_war_rooms(self) -> list[dict]:
        return [
            {
                "war_room_id": wr.war_room_id,
                "name": wr.name,
                "trigger_rule": wr.trigger_rule,
                "status": wr.status,
                "agents": wr.agent_roles,
                "summary": wr.summary,
                "findings_count": len(wr.findings),
                "recommended_actions": wr.recommended_actions,
                "spawned_at": wr.spawned_at,
            }
            for wr in self._war_rooms
            if wr.status in ("spawned", "investigating", "resolved")
        ]

    def war_room_detail(self, war_room_id: str) -> dict | None:
        wr = next((w for w in self._war_rooms if w.war_room_id == war_room_id), None)
        if not wr:
            return None
        return {
            "war_room_id": wr.war_room_id,
            "name": wr.name,
            "trigger_rule": wr.trigger_rule,
            "signal": {
                "source": wr.trigger_signal.source,
                "metric": wr.trigger_signal.metric,
                "value": wr.trigger_signal.value,
                "previous": wr.trigger_signal.previous_value,
            },
            "status": wr.status,
            "summary": wr.summary,
            "findings": [
                {
                    "agent": f.agent_role,
                    "finding": f.finding,
                    "severity": f.severity,
                    "actions": f.action_items,
                }
                for f in wr.findings
            ],
            "recommended_actions": wr.recommended_actions,
            "spawned_at": wr.spawned_at,
            "resolved_at": wr.resolved_at,
        }

    def signal_history(self, limit: int = 100) -> list[dict]:
        return [
            {
                "source": s.source,
                "metric": s.metric,
                "value": s.value,
                "previous": s.previous_value,
                "timestamp": s.timestamp,
            }
            for s in self._signal_log[-limit:]
        ]

    def stats(self) -> dict:
        return {
            "rules_active": sum(1 for r in self._rules if r.enabled),
            "total_rules": len(self._rules),
            "signals_received": len(self._signal_log),
            "war_rooms_total": len(self._war_rooms),
            "war_rooms_active": sum(1 for w in self._war_rooms if w.status in ("spawned", "investigating")),
            "war_rooms_resolved": sum(1 for w in self._war_rooms if w.status == "resolved"),
        }

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
