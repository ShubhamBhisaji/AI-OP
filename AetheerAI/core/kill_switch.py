"""kill_switch.py — Emergency stop and fail-safe controls.

Closes ISSUE 2: No Strong Fail-Safe / Kill Switch.

The KillSwitch provides instant, irrevocable agent shutdown capabilities:

    1. Emergency Stop     — Immediately cancel all in-flight work + stop loops
    2. Safe Shutdown       — Graceful wind-down: finish current task, then stop
    3. Disable Integrations — Sever all external connections instantly
    4. Rate Throttle        — Dynamically slow agent operations

All operations are thread-safe and audited.

Usage
-----
    ks = KillSwitch(agent_name="store_bot")
    ks.register_loop(loop)
    ks.register_action_gate(gate)
    ks.register_integrator(integrator)

    # Emergency stop — everything halts NOW
    ks.emergency_stop(operator="admin", reason="Customer complaint")

    # Safe shutdown — finish current work, then stop
    ks.safe_shutdown(operator="admin")

    # Disable all integrations
    ks.disable_integrations(operator="admin")

    # Throttle to 25% speed
    ks.throttle(rate=0.25, operator="admin")

    # Restore normal operation
    ks.reset(operator="admin")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AgentMode(str, Enum):
    NORMAL      = "normal"
    THROTTLED   = "throttled"
    SAFE_STOP   = "safe_stop"
    EMERGENCY   = "emergency"
    LOCKED      = "locked"
    SAFE_MODE   = "safe_mode"   # Running under maximum restrictions


@dataclass
class KillSwitchEvent:
    action: str
    operator: str
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "operator": self.operator,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "details": self.details,
        }


class KillSwitch:
    """
    Emergency stop and fail-safe controls for a single agent.

    Thread-safe. Auditable. Irrevocable until explicitly reset.

    Parameters
    ----------
    agent_name : The agent this kill switch controls.
    log_dir    : Directory to persist kill switch events.
    """

    def __init__(
        self,
        agent_name: str,
        log_dir: str | Path | None = None,
    ) -> None:
        self.agent_name = agent_name
        self._mode = AgentMode.NORMAL
        self._throttle_rate: float = 1.0   # 1.0 = normal, 0.0 = stopped
        self._lock = threading.Lock()

        # Registered components
        self._loop = None          # AutonomousGoalLoop
        self._action_gate = None   # ActionGate
        self._integrator = None    # SelfIntegrator
        self._goal_manager = None  # GoalManager
        self._control_panel = None # AgentControlPanel
        self._audit = None         # AuditLogger

        # Event log
        self._log_dir = Path(log_dir or Path(__file__).resolve().parents[1] / "workspace" / "killswitch")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self._log_dir / f"{agent_name}_killswitch.json"
        self._events: list[KillSwitchEvent] = []
        self._load_events()

    # ── Component registration ───────────────────────────────────────────

    def register_loop(self, loop: Any) -> None:
        self._loop = loop

    def register_action_gate(self, gate: Any) -> None:
        self._action_gate = gate

    def register_integrator(self, integrator: Any) -> None:
        self._integrator = integrator

    def register_goal_manager(self, gm: Any) -> None:
        self._goal_manager = gm

    def register_control_panel(self, panel: Any) -> None:
        self._control_panel = panel

    def register_audit(self, audit: Any) -> None:
        self._audit = audit

    # ── 1. Emergency Stop ────────────────────────────────────────────────

    def emergency_stop(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        EMERGENCY STOP — Immediately halt all agent activity.

        This is the nuclear option:
        1. Cancel ALL in-flight actions (via ActionGate)
        2. Stop the autonomous loop immediately
        3. Disable the action gate (no new actions permitted)
        4. Set mode to EMERGENCY

        The agent will NOT resume until explicitly reset.
        """
        with self._lock:
            self._mode = AgentMode.EMERGENCY

        actions_cancelled = 0
        errors: list[str] = []

        # 1. Cancel all in-flight actions
        if self._action_gate is not None:
            try:
                actions_cancelled = self._action_gate.cancel_all(
                    agent_name=self.agent_name,
                    reason=f"Emergency stop: {reason}",
                )
                self._action_gate.disable()
            except Exception as exc:
                errors.append(f"ActionGate cancel failed: {exc}")

        # 2. Stop the autonomous loop
        if self._loop is not None:
            try:
                self._loop.stop()
            except Exception as exc:
                errors.append(f"Loop stop failed: {exc}")

        # 3. Log the event
        event = KillSwitchEvent(
            action="emergency_stop",
            operator=operator,
            reason=reason,
            details={
                "actions_cancelled": actions_cancelled,
                "errors": errors,
            },
        )
        self._record_event(event)
        self._audit_log("emergency_stop", operator, reason, {"cancelled": actions_cancelled})

        logger.critical(
            "KillSwitch[%s]: EMERGENCY STOP by %s. Reason: %s. Actions cancelled: %d.",
            self.agent_name, operator, reason, actions_cancelled,
        )

        return {
            "status": "emergency_stopped",
            "agent": self.agent_name,
            "mode": self._mode.value,
            "actions_cancelled": actions_cancelled,
            "errors": errors,
            "operator": operator,
            "reason": reason,
        }

    # ── 2. Safe Shutdown ─────────────────────────────────────────────────

    def safe_shutdown(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        SAFE SHUTDOWN — Graceful wind-down.

        1. Pause the autonomous loop (finishes current task)
        2. Set mode to SAFE_STOP
        3. No new actions permitted after current task completes

        Does NOT cancel in-flight work. Use emergency_stop for that.
        """
        with self._lock:
            self._mode = AgentMode.SAFE_STOP

        # Pause loop (finish current task, then stop)
        if self._loop is not None:
            try:
                self._loop.pause()
            except Exception as exc:
                logger.warning("KillSwitch[%s]: loop pause failed: %s", self.agent_name, exc)

        event = KillSwitchEvent(
            action="safe_shutdown",
            operator=operator,
            reason=reason,
        )
        self._record_event(event)
        self._audit_log("safe_shutdown", operator, reason)

        logger.warning("KillSwitch[%s]: SAFE SHUTDOWN by %s. Reason: %s",
                        self.agent_name, operator, reason)

        return {
            "status": "safe_shutdown",
            "agent": self.agent_name,
            "mode": self._mode.value,
            "operator": operator,
        }

    # ── 3. Disable Integrations ──────────────────────────────────────────

    def disable_integrations(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        Sever all external connections immediately.

        Disconnects all integrations via the SelfIntegrator.
        The agent continues running but cannot reach external services.
        """
        disconnected = 0
        errors: list[str] = []

        if self._integrator is not None:
            try:
                integrations = self._integrator.list_integrations(self.agent_name)
                for integration in integrations:
                    name = integration.get("name", "")
                    try:
                        self._integrator.disconnect(self.agent_name, name)
                        disconnected += 1
                    except Exception as exc:
                        errors.append(f"Disconnect {name}: {exc}")
            except Exception as exc:
                errors.append(f"List integrations failed: {exc}")

        event = KillSwitchEvent(
            action="disable_integrations",
            operator=operator,
            reason=reason,
            details={"disconnected": disconnected, "errors": errors},
        )
        self._record_event(event)
        self._audit_log("disable_integrations", operator, reason, {"disconnected": disconnected})

        logger.warning("KillSwitch[%s]: integrations disabled by %s. Disconnected: %d.",
                        self.agent_name, operator, disconnected)

        return {
            "status": "integrations_disabled",
            "disconnected": disconnected,
            "errors": errors,
        }

    # ── 4. Rate Throttle ─────────────────────────────────────────────────

    def throttle(self, rate: float, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        Throttle agent operations to a fraction of normal speed.

        Parameters
        ----------
        rate : Float 0.0–1.0. E.g. 0.25 = 25% speed.
               0.0 effectively pauses the agent.
               1.0 restores normal speed.
        """
        rate = max(0.0, min(1.0, rate))

        with self._lock:
            self._throttle_rate = rate
            if rate < 1.0 and self._mode == AgentMode.NORMAL:
                self._mode = AgentMode.THROTTLED
            elif rate >= 1.0 and self._mode == AgentMode.THROTTLED:
                self._mode = AgentMode.NORMAL

        event = KillSwitchEvent(
            action="throttle",
            operator=operator,
            reason=reason,
            details={"rate": rate},
        )
        self._record_event(event)
        self._audit_log("throttle", operator, reason, {"rate": rate})

        logger.info("KillSwitch[%s]: throttled to %.0f%% by %s.",
                     self.agent_name, rate * 100, operator)

        return {
            "status": "throttled",
            "rate": rate,
            "mode": self._mode.value,
        }

    @property
    def throttle_rate(self) -> float:
        """Current throttle rate (1.0 = normal, 0.0 = stopped)."""
        return self._throttle_rate

    # ── 5. Safe Mode ─────────────────────────────────────────────────────

    def safe_mode(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        SAFE MODE — Agent keeps running with maximum restrictions.

        All non-trivial actions (financial, external API, system, bulk,
        data writes, communication) require manual approval before execution.
        External HTTP calls are blocked at the transport layer.
        Unlike safe_shutdown, the agent remains alive and responsive.

        Use reset() to exit safe mode and return to normal operations.
        """
        with self._lock:
            self._mode = AgentMode.SAFE_MODE

        # Signal action gate to enter safe mode
        if self._action_gate is not None:
            try:
                if hasattr(self._action_gate, "enter_safe_mode"):
                    self._action_gate.enter_safe_mode()
            except Exception as exc:
                logger.warning("KillSwitch[%s]: gate safe_mode signal failed: %s", self.agent_name, exc)

        event = KillSwitchEvent(
            action="safe_mode",
            operator=operator,
            reason=reason,
        )
        self._record_event(event)
        self._audit_log("safe_mode", operator, reason)

        logger.warning("KillSwitch[%s]: SAFE MODE by %s. Reason: %s",
                       self.agent_name, operator, reason)

        return {
            "status": "safe_mode",
            "agent": self.agent_name,
            "mode": self._mode.value,
            "operator": operator,
            "reason": reason,
        }

    # ── 6. Restart ────────────────────────────────────────────────────────

    def restart(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        RESTART — Stop all in-flight work cleanly, then resume normal operation.

        1. Cancel all in-flight actions via ActionGate
        2. Reset kill switch state to NORMAL (re-enables gate)
        3. Exit safe mode if active
        4. Resume or restart the autonomous loop

        The agent resumes from scratch — no pending in-flight work carries over.
        Use this instead of emergency_stop when you want a clean restart rather
        than a permanent lockdown.
        """
        # 1. Cancel in-flight actions
        cancelled = 0
        if self._action_gate is not None:
            try:
                cancelled = self._action_gate.cancel_all(
                    agent_name=self.agent_name,
                    reason=f"Restart by {operator}: {reason}",
                )
            except Exception as exc:
                logger.warning("KillSwitch[%s]: cancel_all failed during restart: %s", self.agent_name, exc)

        # 2. Reset mode and throttle
        with self._lock:
            prev_mode = self._mode.value
            self._mode = AgentMode.NORMAL
            self._throttle_rate = 1.0

        # 3. Re-enable gate and exit safe mode
        if self._action_gate is not None:
            try:
                self._action_gate.enable()
                if hasattr(self._action_gate, "exit_safe_mode"):
                    self._action_gate.exit_safe_mode()
            except Exception as exc:
                logger.warning("KillSwitch[%s]: gate re-enable failed during restart: %s", self.agent_name, exc)

        # 4. Resume loop
        loop_restarted = False
        if self._loop is not None:
            try:
                if hasattr(self._loop, "restart"):
                    self._loop.restart()
                else:
                    self._loop.resume()
                loop_restarted = True
            except Exception as exc:
                logger.warning("KillSwitch[%s]: loop resume failed during restart: %s", self.agent_name, exc)

        event = KillSwitchEvent(
            action="restart",
            operator=operator,
            reason=reason,
            details={
                "previous_mode": prev_mode,
                "cancelled_actions": cancelled,
                "loop_restarted": loop_restarted,
            },
        )
        self._record_event(event)
        self._audit_log("restart", operator, reason, {"previous_mode": prev_mode})

        logger.warning("KillSwitch[%s]: RESTART by %s. Previous mode: %s.",
                       self.agent_name, operator, prev_mode)

        return {
            "status": "restarted",
            "agent": self.agent_name,
            "mode": self._mode.value,
            "previous_mode": prev_mode,
            "cancelled_actions": cancelled,
            "loop_restarted": loop_restarted,
            "operator": operator,
        }

    def throttle_delay(self) -> float:
        """
        Returns the delay (in seconds) to inject between operations
        based on the current throttle rate.

        At 1.0 = 0s delay. At 0.5 = 1s delay. At 0.1 = 9s delay.
        """
        if self._throttle_rate >= 1.0:
            return 0.0
        if self._throttle_rate <= 0.0:
            return 60.0  # Effectively paused
        return (1.0 / self._throttle_rate) - 1.0

    # ── 5. Reset (restore normal operation) ──────────────────────────────

    def reset(self, operator: str = "system", reason: str = "") -> dict[str, Any]:
        """
        Reset the kill switch and restore normal operation.

        Clears emergency/safe_stop modes, re-enables the action gate,
        and restores throttle to 1.0.
        """
        with self._lock:
            prev_mode = self._mode
            self._mode = AgentMode.NORMAL
            self._throttle_rate = 1.0

        # Re-enable the action gate and exit any safe mode
        if self._action_gate is not None:
            try:
                self._action_gate.enable()
                if hasattr(self._action_gate, "exit_safe_mode"):
                    self._action_gate.exit_safe_mode()
            except Exception as exc:
                logger.warning("KillSwitch[%s]: gate re-enable failed: %s", self.agent_name, exc)

        event = KillSwitchEvent(
            action="reset",
            operator=operator,
            reason=reason,
            details={"previous_mode": prev_mode.value},
        )
        self._record_event(event)
        self._audit_log("reset", operator, reason, {"previous_mode": prev_mode.value})

        logger.info("KillSwitch[%s]: RESET by %s. Previous mode: %s.",
                     self.agent_name, operator, prev_mode.value)

        return {
            "status": "normal",
            "previous_mode": prev_mode.value,
            "mode": self._mode.value,
        }

    # ── Status ───────────────────────────────────────────────────────────

    @property
    def mode(self) -> AgentMode:
        return self._mode

    def status(self) -> dict[str, Any]:
        """Return current kill switch status."""
        return {
            "agent": self.agent_name,
            "mode": self._mode.value,
            "throttle_rate": self._throttle_rate,
            "throttle_delay": round(self.throttle_delay(), 2),
            "action_gate_enabled": (
                self._action_gate.is_enabled if self._action_gate else None
            ),
            "loop_state": (
                str(getattr(self._loop, "state", "unregistered"))
                if self._loop else "unregistered"
            ),
            "recent_events": [e.to_dict() for e in self._events[-5:]],
        }

    def is_operational(self) -> bool:
        """Return True if the agent is in a mode that permits operations."""
        return self._mode in (AgentMode.NORMAL, AgentMode.THROTTLED, AgentMode.SAFE_MODE)

    # ── Event persistence ────────────────────────────────────────────────

    def _record_event(self, event: KillSwitchEvent) -> None:
        self._events.append(event)
        self._save_events()

    def _save_events(self) -> None:
        try:
            data = [e.to_dict() for e in self._events[-200:]]
            import os
            tmp = self._events_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self._events_path)
        except OSError as exc:
            logger.warning("KillSwitch: could not save events: %s", exc)

    def _load_events(self) -> None:
        if not self._events_path.exists():
            return
        try:
            data = json.loads(self._events_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    self._events.append(KillSwitchEvent(
                        action=item.get("action", ""),
                        operator=item.get("operator", ""),
                        reason=item.get("reason", ""),
                        timestamp=item.get("timestamp", 0),
                        details=item.get("details", {}),
                    ))
        except (OSError, json.JSONDecodeError):
            pass

    def _audit_log(
        self,
        action: str,
        operator: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        if self._audit is None:
            return
        try:
            self._audit.log({
                "event": "kill_switch",
                "agent": self.agent_name,
                "action": action,
                "operator": operator,
                "reason": reason,
                **(details or {}),
            })
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"KillSwitch(agent={self.agent_name!r}, mode={self._mode.value})"
