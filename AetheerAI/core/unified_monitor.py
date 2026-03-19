"""unified_monitor.py — Unified monitoring & reporting dashboard.

Closes GAP 3: Monitoring & Reporting Still Minimal.

Aggregates all observability data into a single, queryable interface:
    1. Activity timeline     — Unified event stream across all subsystems
    2. Decision logs         — Full context for every agent decision
    3. Error reporting       — Aggregated, deduplicated, with trace correlation
    4. Health status         — Multi-component health check
    5. Resource usage        — Token, API call, memory, and cost tracking
    6. Integration status    — Live health of all external connections

Usage
-----
    monitor = UnifiedMonitor(agent_name="store_bot")
    monitor.register_observability(obs)
    monitor.register_finops(finops)
    monitor.register_action_proxy(proxy)
    monitor.register_integrator(integrator)

    # Full dashboard
    dashboard = monitor.dashboard()

    # Activity timeline
    events = monitor.activity_timeline(limit=100)

    # Decision log
    decisions = monitor.decision_log(limit=50)

    # Resource usage
    usage = monitor.resource_usage()

    # Integration health
    health = monitor.integration_status()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Timeline Event ──────────────────────────────────────────────────────────

@dataclass
class TimelineEvent:
    """A unified event in the activity timeline."""
    source: str       # "action", "decision", "error", "control", "system"
    event: str
    level: str = "info"
    agent_name: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "event": self.event,
            "level": self.level,
            "agent": self.agent_name,
            "details": self.details,
            "ts": self.timestamp,
        }


# ── Decision Record ────────────────────────────────────────────────────────

@dataclass
class DecisionRecord:
    """A recorded decision with full context."""
    decision_id: str
    action: str
    agent_name: str
    outcome: str           # "allowed", "blocked", "pending_approval", "error"
    reason: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    impact: str = ""       # "low", "medium", "high", "critical"
    reversible: bool = True
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.decision_id,
            "action": self.action,
            "agent": self.agent_name,
            "outcome": self.outcome,
            "reason": self.reason,
            "impact": self.impact,
            "reversible": self.reversible,
            "ts": self.timestamp,
        }


# ── Resource Snapshot ───────────────────────────────────────────────────────

@dataclass
class ResourceSnapshot:
    """Point-in-time resource usage."""
    api_calls: int = 0
    api_calls_blocked: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    budget_usd: float = 0.0
    budget_remaining_usd: float = 0.0
    actions_total: int = 0
    actions_success: int = 0
    actions_failed: int = 0
    error_count: int = 0
    uptime_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_calls": self.api_calls,
            "api_calls_blocked": self.api_calls_blocked,
            "tokens_used": self.tokens_used,
            "cost_usd": round(self.cost_usd, 4),
            "budget_usd": self.budget_usd,
            "budget_remaining_usd": round(self.budget_remaining_usd, 4),
            "actions_total": self.actions_total,
            "actions_success": self.actions_success,
            "actions_failed": self.actions_failed,
            "error_count": self.error_count,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "ts": self.timestamp,
        }


# ── UnifiedMonitor ──────────────────────────────────────────────────────────

class UnifiedMonitor:
    """
    Unified monitoring & reporting for AetheerAI agents.

    Aggregates data from all subsystems into a single query interface.

    Parameters
    ----------
    agent_name     : Agent to monitor.
    max_timeline   : Maximum timeline events to keep in memory.
    max_decisions  : Maximum decision records to keep.
    """

    def __init__(
        self,
        agent_name: str,
        max_timeline: int = 2000,
        max_decisions: int = 500,
    ) -> None:
        self.agent_name = agent_name
        self._started_at = time.time()
        self._max_timeline = max_timeline
        self._max_decisions = max_decisions

        # Registered components
        self._observability = None
        self._finops = None
        self._action_proxy = None
        self._integrator = None
        self._kill_switch = None
        self._human_override = None
        self._goal_manager = None

        # Local stores
        self._timeline: list[TimelineEvent] = []
        self._decisions: list[DecisionRecord] = []

    # ── Component registration ────────────────────────────────────────────

    def register_observability(self, obs: Any) -> None:
        self._observability = obs

    def register_finops(self, finops: Any) -> None:
        self._finops = finops

    def register_action_proxy(self, proxy: Any) -> None:
        self._action_proxy = proxy

    def register_integrator(self, integrator: Any) -> None:
        self._integrator = integrator

    def register_kill_switch(self, ks: Any) -> None:
        self._kill_switch = ks

    def register_human_override(self, hoc: Any) -> None:
        self._human_override = hoc

    def register_goal_manager(self, gm: Any) -> None:
        self._goal_manager = gm

    # ── Record events ─────────────────────────────────────────────────────

    def record_event(
        self,
        source: str,
        event: str,
        level: str = "info",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an event to the unified timeline."""
        te = TimelineEvent(
            source=source,
            event=event,
            level=level,
            agent_name=self.agent_name,
            details=details or {},
        )
        self._timeline.append(te)
        if len(self._timeline) > self._max_timeline:
            self._timeline = self._timeline[-self._max_timeline:]

    def record_decision(
        self,
        decision_id: str,
        action: str,
        outcome: str,
        reason: str = "",
        context: dict[str, Any] | None = None,
        impact: str = "low",
        reversible: bool = True,
    ) -> None:
        """Record a decision with full context."""
        dr = DecisionRecord(
            decision_id=decision_id,
            action=action,
            agent_name=self.agent_name,
            outcome=outcome,
            reason=reason,
            context=context or {},
            impact=impact,
            reversible=reversible,
        )
        self._decisions.append(dr)
        if len(self._decisions) > self._max_decisions:
            self._decisions = self._decisions[-self._max_decisions:]

        # Also add to timeline
        self.record_event(
            source="decision",
            event=f"{outcome}: {action}",
            level="warning" if outcome == "blocked" else "info",
            details={"decision_id": decision_id, "reason": reason, "impact": impact},
        )

    # ── 1. Activity Timeline ─────────────────────────────────────────────

    def activity_timeline(
        self,
        source: str | None = None,
        level: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Query the unified activity timeline.

        Parameters
        ----------
        source : Filter by source ("action", "decision", "error", "control").
        level  : Filter by level ("info", "warning", "error").
        limit  : Max results.
        """
        results = list(self._timeline)

        # Merge events from observability if registered
        if self._observability is not None:
            try:
                obs_actions = self._observability.get_actions(limit=limit)
                for a in obs_actions:
                    results.append(TimelineEvent(
                        source="action",
                        event=a.get("action", ""),
                        level="info" if a.get("success") else "warning",
                        agent_name=self.agent_name,
                        details=a,
                        timestamp=a.get("ts", 0),
                    ))
            except Exception:
                pass

        if source:
            results = [e for e in results if e.source == source]
        if level:
            results = [e for e in results if e.level == level]

        results.sort(key=lambda e: e.timestamp, reverse=True)
        return [e.to_dict() for e in results[:limit]]

    # ── 2. Decision Log ──────────────────────────────────────────────────

    def decision_log(
        self,
        outcome: str | None = None,
        impact: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Query the decision log.

        Parameters
        ----------
        outcome : Filter by outcome ("allowed", "blocked", "error").
        impact  : Filter by impact ("low", "medium", "high", "critical").
        """
        results = list(self._decisions)
        if outcome:
            results = [d for d in results if d.outcome == outcome]
        if impact:
            results = [d for d in results if d.impact == impact]
        results.sort(key=lambda d: d.timestamp, reverse=True)
        return [d.to_dict() for d in results[:limit]]

    # ── 3. Error Report ──────────────────────────────────────────────────

    def error_report(self, limit: int = 20) -> list[dict[str, Any]]:
        """Aggregated error report from ObservabilityEngine."""
        if self._observability is not None:
            try:
                return self._observability.get_errors(limit=limit)
            except Exception:
                pass
        return []

    # ── 4. Health Status ─────────────────────────────────────────────────

    def health_status(self) -> dict[str, Any]:
        """
        Multi-component health check.

        Returns per-component health plus an overall status.
        """
        components: dict[str, dict[str, Any]] = {}
        overall = "healthy"

        # Observability health
        if self._observability is not None:
            try:
                obs_health = self._observability.health_check()
                components["observability"] = obs_health
                if obs_health.get("status") == "unhealthy":
                    overall = "unhealthy"
                elif obs_health.get("status") == "degraded" and overall == "healthy":
                    overall = "degraded"
            except Exception as exc:
                components["observability"] = {"status": "error", "error": str(exc)}
                overall = "unhealthy"

        # Kill switch status
        if self._kill_switch is not None:
            try:
                ks_status = self._kill_switch.status()
                ks_mode = ks_status.get("mode", "unknown")
                components["kill_switch"] = {
                    "status": "healthy" if ks_mode == "normal" else "degraded",
                    "mode": ks_mode,
                }
                if ks_mode in ("emergency", "locked"):
                    overall = "unhealthy"
                elif ks_mode in ("safe_stop", "throttled") and overall == "healthy":
                    overall = "degraded"
            except Exception as exc:
                components["kill_switch"] = {"status": "error", "error": str(exc)}

        # FinOps budget
        if self._finops is not None:
            try:
                fin_status = self._finops.status()
                over = fin_status.get("over_budget", False)
                pct = fin_status.get("percent_used", 0)
                components["budget"] = {
                    "status": "unhealthy" if over else ("degraded" if pct > 80 else "healthy"),
                    **fin_status,
                }
                if over:
                    overall = "unhealthy"
                elif pct > 80 and overall == "healthy":
                    overall = "degraded"
            except Exception as exc:
                components["budget"] = {"status": "error", "error": str(exc)}

        # Action proxy stats
        if self._action_proxy is not None:
            try:
                proxy_stats = self._action_proxy.stats()
                block_rate = proxy_stats.get("block_rate", 0)
                components["action_proxy"] = {
                    "status": "degraded" if block_rate > 0.3 else "healthy",
                    **proxy_stats,
                }
            except Exception as exc:
                components["action_proxy"] = {"status": "error", "error": str(exc)}

        # Integration health
        integration_health = self._check_integrations()
        if integration_health:
            components["integrations"] = integration_health
            unhealthy_integrations = sum(
                1 for v in integration_health.get("services", {}).values()
                if v.get("status") != "healthy"
            )
            if unhealthy_integrations > 0 and overall == "healthy":
                overall = "degraded"

        return {
            "agent": self.agent_name,
            "status": overall,
            "uptime_seconds": round(time.time() - self._started_at, 1),
            "components": components,
            "checked_at": time.time(),
        }

    # ── 5. Resource Usage ────────────────────────────────────────────────

    def resource_usage(self) -> dict[str, Any]:
        """
        Current resource usage snapshot.

        Aggregates: tokens, cost, API calls, actions, errors.
        """
        snap = ResourceSnapshot(uptime_seconds=time.time() - self._started_at)

        # From FinOps
        if self._finops is not None:
            try:
                fin = self._finops.status()
                snap.cost_usd = fin.get("used_usd", 0)
                snap.budget_usd = fin.get("budget_usd", 0)
                snap.budget_remaining_usd = fin.get("remaining_usd", 0) or 0

                # Sum tokens from ledger
                ledger = self._finops.ledger(limit=10000)
                snap.tokens_used = sum(
                    r.get("prompt_tokens", 0) + r.get("completion_tokens", 0)
                    for r in ledger
                )
            except Exception:
                pass

        # From ObservabilityEngine
        if self._observability is not None:
            try:
                health = self._observability.health_check()
                metrics = health.get("metrics", {})
                snap.actions_total = metrics.get("total_actions", 0)
                snap.error_count = metrics.get("total_errors", 0)
                snap.actions_success = int(
                    snap.actions_total * metrics.get("success_rate", 1.0)
                )
                snap.actions_failed = snap.actions_total - snap.actions_success
            except Exception:
                pass

        # From ActionProxy
        if self._action_proxy is not None:
            try:
                stats = self._action_proxy.stats()
                snap.api_calls = stats.get("total_calls", 0)
                snap.api_calls_blocked = stats.get("total_blocked", 0)
            except Exception:
                pass

        return snap.to_dict()

    # ── 6. Integration Status ────────────────────────────────────────────

    def integration_status(self) -> dict[str, Any]:
        """Live health of all external connections."""
        return self._check_integrations()

    def _check_integrations(self) -> dict[str, Any]:
        """Check integration health via registered integrator."""
        if self._integrator is None:
            return {"status": "no_integrator", "services": {}}

        services: dict[str, dict[str, Any]] = {}
        try:
            integrations = self._integrator.list_integrations(self.agent_name)
            for integ in integrations:
                name = integ.get("name", "unknown")
                connected = integ.get("connected", False)
                services[name] = {
                    "status": "healthy" if connected else "disconnected",
                    "connected": connected,
                    "type": integ.get("type", "unknown"),
                }
        except Exception as exc:
            return {"status": "error", "error": str(exc), "services": {}}

        total = len(services)
        healthy = sum(1 for s in services.values() if s["status"] == "healthy")

        return {
            "status": "healthy" if healthy == total else ("degraded" if healthy > 0 else "unhealthy"),
            "total": total,
            "healthy": healthy,
            "services": services,
        }

    # ── Full Dashboard ───────────────────────────────────────────────────

    def dashboard(self) -> dict[str, Any]:
        """Full monitoring dashboard — all data in one call."""
        return {
            "agent": self.agent_name,
            "health": self.health_status(),
            "resources": self.resource_usage(),
            "recent_activity": self.activity_timeline(limit=20),
            "recent_decisions": self.decision_log(limit=10),
            "errors": self.error_report(limit=10),
            "integrations": self.integration_status(),
            "generated_at": time.time(),
        }

    # ── CLI Dashboard ────────────────────────────────────────────────────

    def cli_dashboard(self) -> str:
        """Generate a CLI-friendly monitoring dashboard."""
        health = self.health_status()
        resources = self.resource_usage()
        sep = "=" * 65

        lines = [
            f"\n{sep}",
            f"  Unified Monitor — {self.agent_name}",
            f"{sep}",
            f"",
            f"  Status:   {health['status'].upper()}",
            f"  Uptime:   {health['uptime_seconds']:.0f}s",
            f"",
            f"  --- Resources ---",
            f"  API Calls:     {resources['api_calls']}  (blocked: {resources['api_calls_blocked']})",
            f"  Tokens Used:   {resources['tokens_used']:,}",
            f"  Cost:          ${resources['cost_usd']:.4f} / ${resources['budget_usd']:.2f}",
            f"  Actions:       {resources['actions_total']}  (ok: {resources['actions_success']}, fail: {resources['actions_failed']})",
            f"  Errors:        {resources['error_count']}",
            f"",
            f"  --- Component Health ---",
        ]

        for name, comp in health.get("components", {}).items():
            status = comp.get("status", "unknown")
            icon = "+" if status == "healthy" else ("~" if status == "degraded" else "X")
            lines.append(f"  [{icon}] {name:<20} {status}")

        # Recent decisions
        decisions = self.decision_log(limit=5)
        if decisions:
            lines.append(f"\n  --- Recent Decisions ---")
            for d in decisions:
                icon = "+" if d["outcome"] == "allowed" else "X"
                lines.append(f"  [{icon}] {d['action'][:30]:<30} {d['outcome']}")

        lines.append(f"\n{sep}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"UnifiedMonitor(agent={self.agent_name!r}, "
            f"events={len(self._timeline)}, decisions={len(self._decisions)})"
        )
