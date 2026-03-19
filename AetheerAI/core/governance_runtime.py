"""governance_runtime.py — Unified governance compositor.

Wires ALL 8 governance components into a single, pre-connected stack
that makes the answer to "how do we control this?" obvious.

Components wired:
    1. GuardrailController  — Rule-based permission checks
    2. ActionGate            — Mandatory, non-bypassable action checkpoint
    3. ActionProxy           — High-level proxy for all 6 action categories
    4. GatedHTTPTransport    — Transport-layer HTTP enforcement
    5. KillSwitch            — Emergency stop + safe shutdown
    6. HumanOverrideController — Pause, approve, policy hotswap
    7. AgentControlPanel     — Operator dashboard
    8. EconomicGuardrails    — Rate limits, budgets, quotas, throttling
    9. UnifiedMonitor        — Decision-grade observability
   10. UpdateChannel         — Patch verification + staged rollout

Usage
-----
    from core.governance_runtime import GovernanceRuntime, GovernanceConfig

    gov = GovernanceRuntime(GovernanceConfig(
        agent_name="store_bot",
        monthly_budget_usd=50.0,
        restricted_operations=["delete_customer", "drop_table"],
        approval_required=["refund_over_100", "bulk_email"],
    ))

    # Every agent gets governance attached
    gov.attach_to_agent(agent)

    # Operator controls
    gov.pause(operator="admin")
    gov.resume(operator="admin")
    gov.emergency_stop(operator="admin", reason="breach")
    gov.dashboard()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class GovernanceConfig:
    """All governance settings in one place."""

    agent_name: str = "agent"

    # Economic
    monthly_budget_usd: float = 50.0
    default_rate_limit: int = 60
    rate_limits: dict[str, dict[str, int]] = field(default_factory=dict)
    quotas: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Guardrails
    max_transaction_usd: float = 500.0
    restricted_operations: list[str] = field(default_factory=list)
    allowed_apis: list[str] = field(default_factory=list)

    # Human override
    approval_required: list[str] = field(default_factory=list)
    approval_timeout_seconds: float = 300.0

    # Update channel
    auto_apply_security: bool = True
    data_dir: str = ""

    @classmethod
    def from_env(cls, agent_name: str = "agent") -> GovernanceConfig:
        """Build config from environment variables."""
        return cls(
            agent_name=agent_name,
            monthly_budget_usd=float(
                os.environ.get("AETHEERAI_MONTHLY_BUDGET_USD", "50.0")
            ),
            default_rate_limit=int(
                os.environ.get("AETHEERAI_DEFAULT_RATE_LIMIT", "60")
            ),
            max_transaction_usd=float(
                os.environ.get("AETHEERAI_MAX_TRANSACTION_USD", "500.0")
            ),
            auto_apply_security=os.environ.get(
                "AETHEERAI_AUTO_APPLY_SECURITY", "true"
            ).lower() in ("1", "true", "yes"),
        )


# ── Governance Runtime ────────────────────────────────────────────────────────

class GovernanceRuntime:
    """
    The single object that owns and wires all governance components.

    Answers the business question:
        "How do we control this if something goes wrong?"

    With:
        gov.pause()         — Freeze agent immediately
        gov.resume()        — Resume operations
        gov.emergency_stop()— Kill everything NOW
        gov.dashboard()     — Full visibility
        gov.policy_update() — Change rules without redeploy
    """

    def __init__(self, config: GovernanceConfig | None = None) -> None:
        self.config = config or GovernanceConfig()
        self._agent_name = self.config.agent_name
        self._integrator = None
        self._scheduler = None
        self._goal_manager = None
        self._observability = None

        # ── 1. Guardrail Controller (rules engine) ───────────────────────
        from security.guardrail_controller import GuardrailController, GuardrailRules

        self.guardrail_rules = GuardrailRules(
            max_transaction=self.config.max_transaction_usd,
            restricted_operations=list(self.config.restricted_operations),
            allowed_apis=list(self.config.allowed_apis),
        )
        self.guardrail_controller = GuardrailController(rules=self.guardrail_rules)

        # ── 2. ActionGate (mandatory checkpoint) ─────────────────────────
        from security.action_gate import ActionGate

        self.action_gate = ActionGate(guardrail=self.guardrail_controller)

        # ── 3. Economic Guardrails ───────────────────────────────────────
        from core.economic_guardrails import EconomicGuardrails

        self.economic_guardrails = EconomicGuardrails(
            agent_name=self._agent_name,
            monthly_budget_usd=self.config.monthly_budget_usd,
            default_rate_limit=self.config.default_rate_limit,
        )
        for cat, limits in self.config.rate_limits.items():
            self.economic_guardrails.set_rate_limit(cat, **limits)
        for agent, quotas in self.config.quotas.items():
            for cat, q in quotas.items():
                self.economic_guardrails.set_quota(agent, cat, **q)

        # ── 4. ActionProxy (high-level action control) ───────────────────
        from security.action_proxy import ActionProxy

        self.action_proxy = ActionProxy(
            agent_name=self._agent_name,
            action_gate=self.action_gate,
            guardrails=self.economic_guardrails,
        )

        # ── 5. GatedHTTPTransport (wire-level enforcement) ───────────────
        from security.action_proxy import GatedHTTPTransport

        self.gated_transport = GatedHTTPTransport(
            agent_name=self._agent_name,
            action_gate=self.action_gate,
            guardrails=self.economic_guardrails,
        )

        # ── 6. KillSwitch ────────────────────────────────────────────────
        from core.kill_switch import KillSwitch

        self.kill_switch = KillSwitch(agent_name=self._agent_name)
        self.kill_switch.register_action_gate(self.action_gate)

        # ── 7. Agent Control Panel ───────────────────────────────────────
        from core.agent_control_panel import AgentControlPanel

        self.control_panel = AgentControlPanel(agent_name=self._agent_name)
        self.control_panel.register_guardrails(self.guardrail_controller)
        self.kill_switch.register_control_panel(self.control_panel)

        # ── 8. Human Override Controller ─────────────────────────────────
        from core.human_override import HumanOverrideController

        self.human_override = HumanOverrideController(
            agent_name=self._agent_name,
            approval_timeout=self.config.approval_timeout_seconds,
        )
        self.human_override.register_control_panel(self.control_panel)
        self.human_override.register_kill_switch(self.kill_switch)
        self.human_override.register_action_gate(self.action_gate)
        self.human_override.register_guardrails(self.guardrail_controller)
        self.action_gate.register_approval_controller(self.human_override)

        for pattern in self.config.approval_required:
            self.human_override.require_approval(pattern)

        # ── 9. Unified Monitor ───────────────────────────────────────────
        from core.unified_monitor import UnifiedMonitor

        self.monitor = UnifiedMonitor(agent_name=self._agent_name)
        self.monitor.register_action_proxy(self.action_proxy)
        self.monitor.register_action_gate(self.action_gate)
        self.monitor.register_kill_switch(self.kill_switch)
        self.monitor.register_human_override(self.human_override)
        self.monitor.register_control_panel(self.control_panel)
        self.human_override.register_observability(self.monitor)

        # ── 10. Update Channel ───────────────────────────────────────────
        from core.version_manager import VersionManager

        data_dir = self.config.data_dir or None
        self.version_manager = VersionManager(
            agent_name=self._agent_name,
            data_dir=data_dir,
        )
        from core.update_channel import UpdateChannel

        self.update_channel = UpdateChannel(
            agent_name=self._agent_name,
            version_manager=self.version_manager,
            data_dir=data_dir,
            auto_apply_security=self.config.auto_apply_security,
        )
        self.monitor.register_update_channel(self.update_channel)

        from integrations.base_client import set_default_transport_factory

        set_default_transport_factory(
            lambda service_name=None, timeout_seconds=None: self.gated_transport
        )

        logger.info(
            "GovernanceRuntime[%s]: fully wired — "
            "gate + proxy + transport + kill_switch + override + monitor + updates.",
            self._agent_name,
        )

    # ── Operator Controls (the "obvious answer") ─────────────────────────────

    @property
    def agent_name(self) -> str:
        return self._agent_name

    def pause(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """Pause the agent — no actions will execute."""
        return self.human_override.pause(operator=operator, reason=reason)

    def resume(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """Resume the agent after pause."""
        return self.human_override.resume(operator=operator, reason=reason)

    def emergency_stop(
        self, operator: str = "system", reason: str = ""
    ) -> dict[str, Any]:
        """Kill everything NOW. Cancels pending approvals, disables gate."""
        return self.human_override.emergency_disable(
            operator=operator, reason=reason,
        )

    def safe_shutdown(
        self, operator: str = "system", reason: str = ""
    ) -> dict[str, Any]:
        """Graceful shutdown — finish current work, then stop."""
        return self.kill_switch.safe_shutdown(operator=operator, reason=reason)

    def policy_update(
        self, policy: dict[str, Any], operator: str = "system"
    ) -> dict[str, Any]:
        """Change rules, approval patterns, budgets without redeploy."""
        return self.human_override.policy_hotswap(policy, operator=operator)

    def disable_integrations(
        self, operator: str = "system", reason: str = ""
    ) -> dict[str, Any]:
        """Disable external integrations without stopping the whole runtime."""
        return self.kill_switch.disable_integrations(operator=operator, reason=reason)

    def throttle(self, rate: float, operator: str = "system") -> None:
        """Throttle agent to fraction of normal speed (0.0–1.0)."""
        self.economic_guardrails.set_throttle(rate)
        self.kill_switch.throttle(rate=rate, operator=operator)

    def verify_update(self, version: str) -> dict[str, Any]:
        """Verify an update before staged application."""
        return self.update_channel.verify_update(version)

    def rollback_update(self, to_version: str | None = None) -> dict[str, Any]:
        """Rollback the runtime to a previous compatible version."""
        return self.update_channel.rollback(to_version)

    def control_plane_status(self) -> dict[str, Any]:
        """Return the unified operator control-plane view."""
        return {
            "agent": self._agent_name,
            "controls": {
                "pause_resume": True,
                "manual_approvals": True,
                "policy_edits": True,
                "disable_integrations": self._integrator is not None,
                "emergency_stop": True,
                "safe_shutdown": True,
                "update_verify": True,
                "rollback": True,
            },
            "registrations": {
                "integrator": self._integrator is not None,
                "scheduler": self._scheduler is not None,
                "goal_manager": self._goal_manager is not None,
                "observability": self._observability is not None,
            },
            "status_indicators": self.monitor.status_indicators(),
            "pending_approvals": self.human_override.pending_approvals(),
            "active_actions": self.action_gate.active_actions(),
            "current_tasks": self.monitor.current_tasks(limit=20),
        }

    # ── Observability ────────────────────────────────────────────────────────

    def dashboard(self) -> dict[str, Any]:
        """Full governance dashboard — everything in one call."""
        return {
            "agent": self._agent_name,
            "governance": {
                "kill_switch": self.kill_switch.status(),
                "human_override": self.human_override.status(),
                "economic": self.economic_guardrails.status(),
                "action_proxy": self.action_proxy.stats(),
                "action_gate": self.action_gate.stats(),
                "transport": self.gated_transport.stats,
                "control_panel": self.control_panel.dashboard(),
                "control_plane": self.control_plane_status(),
            },
            "monitor": self.monitor.dashboard(),
            "updates": {
                "status": self.update_channel.update_status(),
                "available": self.update_channel.check_updates(),
            },
        }

    def status(self) -> dict[str, Any]:
        """Quick status check."""
        ks_mode = self.kill_switch.status().get("mode", "normal")
        paused = ks_mode in ("safe_stop", "emergency", "locked")
        return {
            "agent": self._agent_name,
            "kill_switch": ks_mode,
            "paused": paused,
            "budget_remaining": self.economic_guardrails.status().get(
                "remaining_budget_usd", 0
            ),
            "actions_blocked": self.action_proxy.stats().get("total_blocked", 0),
            "pending_approvals": len(self.human_override.pending_approvals()),
            "control_plane": self.monitor.status_indicators(),
        }

    def health(self) -> dict[str, Any]:
        """Health check for load balancers / readiness probes."""
        return self.monitor.health_status()

    # ── Agent Wiring ─────────────────────────────────────────────────────────

    def attach_to_agent(self, agent: Any) -> None:
        """
        Attach governance to a BaseAgent instance.

        Injects the governance runtime so the agent's actions
        are enforced through the single gate.
        """
        if hasattr(agent, "attach_runtime"):
            agent.attach_runtime(governance=self)

        tool_manager = getattr(agent, "_tool_manager", None)
        if tool_manager is not None and hasattr(tool_manager, "register_governance"):
            tool_manager.register_governance(self)

        # Store reference on agent for direct access
        agent._governance = self
        logger.info(
            "GovernanceRuntime[%s]: attached to agent '%s'.",
            self._agent_name,
            getattr(agent, "name", "unknown"),
        )

    def get_transport(self) -> Any:
        """Return the gated HTTP transport for integration clients."""
        return self.gated_transport

    def attach_integrator(self, integrator: Any) -> None:
        """Register the integration manager with kill-switch and monitor surfaces."""
        self._integrator = integrator
        self.kill_switch.register_integrator(integrator)
        self.monitor.register_integrator(integrator)

    def attach_scheduler(self, scheduler: Any) -> None:
        """Register the job scheduler for queue visibility."""
        self._scheduler = scheduler
        self.monitor.register_scheduler(scheduler)

    def attach_goal_manager(self, goal_manager: Any) -> None:
        """Register the goal manager for operator inspection and cancellation."""
        self._goal_manager = goal_manager
        self.control_panel.register_goal_manager(goal_manager)
        self.kill_switch.register_goal_manager(goal_manager)
        self.monitor.register_goal_manager(goal_manager)

    def attach_observability(self, observability: Any) -> None:
        """Register structured observability to enrich monitor and control views."""
        self._observability = observability
        self.monitor.register_observability(observability)

    # ── Serialization ────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"GovernanceRuntime(agent={self._agent_name!r}, "
            f"components=10, "
            f"status={self.kill_switch.status().get('mode', 'unknown')!r})"
        )
