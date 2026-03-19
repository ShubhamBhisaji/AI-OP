"""agent_control_panel.py — Operator monitoring and control dashboard.

Closes GAP 5: Monitoring & Control Missing.

Customers must be able to:
    - Pause agent
    - Inspect activity
    - Override decisions
    - Review logs
    - Update configuration

The AgentControlPanel is the single control surface for operators to
manage running agents. It aggregates data from:
    - AutonomousGoalLoop (pause/resume/stop)
    - GoalManager (goal/task state)
    - PersistentMemoryEngine (decisions, work history)
    - GuardrailController (guardrail rules, rate limits)
    - AuditLogger (audit trail)
    - MemoryManager (agent memory)

Usage
-----
    panel = AgentControlPanel(agent_name="store_bot")
    panel.register_loop(loop)
    panel.register_goal_manager(gm)
    panel.register_memory(persistent_mem)
    panel.register_guardrails(gc)
    panel.register_audit(audit_logger)

    # Operator actions
    panel.pause()
    panel.resume()
    panel.stop()
    activity = panel.inspect()
    panel.override_decision(decision_id, new_outcome="denied")
    logs = panel.review_logs(limit=50)
    panel.update_config({"max_transaction": 200})

    # Full dashboard
    dashboard = panel.dashboard()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Event types for the control panel ────────────────────────────────────────

@dataclass
class ControlEvent:
    """An operator action recorded by the control panel."""
    action: str
    operator: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "operator": self.operator,
            "details": self.details,
            "timestamp": self.timestamp,
        }


# ── AgentControlPanel ───────────────────────────────────────────────────────

class AgentControlPanel:
    """
    Operator monitoring and control dashboard for a single agent.

    Provides a unified interface to:
    - Pause, resume, stop the agent's autonomous loop
    - Inspect current activity (goals, tasks, decisions)
    - Override agent decisions
    - Review audit logs
    - Update guardrail configuration at runtime
    - View full dashboard with all metrics

    Parameters
    ----------
    agent_name : The agent this panel controls.
    log_dir    : Directory to persist control events (default: workspace/control/).
    """

    def __init__(
        self,
        agent_name: str,
        log_dir: str | Path | None = None,
    ) -> None:
        self.agent_name = agent_name
        self._log_dir = Path(log_dir or Path(__file__).resolve().parents[1] / "workspace" / "control")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._events_path = self._log_dir / f"{agent_name}_events.json"

        # Registered components (set via register_* methods)
        self._loop = None          # AutonomousGoalLoop
        self._goal_manager = None  # GoalManager
        self._memory = None        # PersistentMemoryEngine
        self._guardrails = None    # GuardrailController
        self._audit = None         # AuditLogger
        self._base_memory = None   # MemoryManager (base)

        # Control event history
        self._events: list[ControlEvent] = []
        self._load_events()

    # ── Component registration ───────────────────────────────────────────

    def register_loop(self, loop: Any) -> None:
        """Register the AutonomousGoalLoop for pause/resume/stop control."""
        self._loop = loop

    def register_goal_manager(self, gm: Any) -> None:
        """Register the GoalManager for goal/task inspection."""
        self._goal_manager = gm

    def register_memory(self, mem: Any) -> None:
        """Register the PersistentMemoryEngine for decision/work inspection."""
        self._memory = mem

    def register_guardrails(self, gc: Any) -> None:
        """Register the GuardrailController for rule management."""
        self._guardrails = gc

    def register_audit(self, audit: Any) -> None:
        """Register the AuditLogger for log review."""
        self._audit = audit

    def register_base_memory(self, mem: Any) -> None:
        """Register the base MemoryManager."""
        self._base_memory = mem

    # ── 1. Pause / Resume / Stop ─────────────────────────────────────────

    def pause(self, operator: str = "system") -> dict[str, Any]:
        """Pause the agent's autonomous loop."""
        if self._loop is None:
            return {"status": "error", "message": "No autonomous loop registered."}

        self._loop.pause()
        self._record_event("pause", operator)
        logger.info("ControlPanel[%s]: PAUSED by %s.", self.agent_name, operator)
        return {"status": "paused", "agent": self.agent_name, "operator": operator}

    def resume(self, operator: str = "system") -> dict[str, Any]:
        """Resume the agent's autonomous loop."""
        if self._loop is None:
            return {"status": "error", "message": "No autonomous loop registered."}

        self._loop.resume()
        self._record_event("resume", operator)
        logger.info("ControlPanel[%s]: RESUMED by %s.", self.agent_name, operator)
        return {"status": "running", "agent": self.agent_name, "operator": operator}

    def stop(self, operator: str = "system") -> dict[str, Any]:
        """Stop the agent's autonomous loop."""
        if self._loop is None:
            return {"status": "error", "message": "No autonomous loop registered."}

        self._loop.stop()
        self._record_event("stop", operator)
        logger.info("ControlPanel[%s]: STOPPED by %s.", self.agent_name, operator)
        return {"status": "stopped", "agent": self.agent_name, "operator": operator}

    def agent_state(self) -> str:
        """Return the current agent loop state."""
        if self._loop is None:
            return "unregistered"
        return str(self._loop.state.value if hasattr(self._loop.state, "value") else self._loop.state)

    # ── 2. Inspect Activity ──────────────────────────────────────────────

    def inspect(self) -> dict[str, Any]:
        """
        Return a comprehensive snapshot of the agent's current activity.

        Includes: loop status, active goals/tasks, recent decisions,
        recent work, memory stats, and guardrail status.
        """
        result: dict[str, Any] = {
            "agent": self.agent_name,
            "timestamp": time.time(),
            "loop": None,
            "goals": None,
            "recent_decisions": [],
            "recent_work": [],
            "memory_status": None,
            "guardrail_status": None,
        }

        # Loop status
        if self._loop is not None:
            try:
                result["loop"] = self._loop.status()
            except Exception as exc:
                result["loop"] = {"error": str(exc)}

        # Goals and tasks
        if self._goal_manager is not None:
            try:
                result["goals"] = self._goal_manager.status_report()
            except Exception as exc:
                result["goals"] = {"error": str(exc)}

        # Recent decisions
        if self._memory is not None:
            try:
                result["recent_decisions"] = self._memory.get_decisions(limit=10)
            except Exception:
                pass

        # Recent work
        if self._memory is not None:
            try:
                result["recent_work"] = self._memory.get_work_history(limit=10)
            except Exception:
                pass

        # Memory status
        if self._memory is not None:
            try:
                result["memory_status"] = self._memory.status()
            except Exception as exc:
                result["memory_status"] = {"error": str(exc)}

        # Guardrail status
        if self._guardrails is not None:
            try:
                result["guardrail_status"] = self._guardrails.status()
            except Exception as exc:
                result["guardrail_status"] = {"error": str(exc)}

        return result

    # ── 3. Override Decisions ────────────────────────────────────────────

    def override_decision(
        self,
        decision_id: str,
        new_outcome: str,
        operator: str = "system",
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Override a previous agent decision.

        Parameters
        ----------
        decision_id : The ID of the decision to override.
        new_outcome : New outcome value (e.g. "denied", "approved", "reversed").
        operator    : Who is making this override.
        reason      : Why the override is being made.
        """
        if self._memory is None:
            return {"status": "error", "message": "No memory engine registered."}

        success = self._memory.update_decision_outcome(decision_id, new_outcome)
        if not success:
            return {"status": "error", "message": f"Decision '{decision_id}' not found."}

        self._record_event("override_decision", operator, {
            "decision_id": decision_id,
            "new_outcome": new_outcome,
            "reason": reason,
        })

        logger.info("ControlPanel[%s]: decision %s overridden to '%s' by %s.",
                     self.agent_name, decision_id, new_outcome, operator)
        return {
            "status": "overridden",
            "decision_id": decision_id,
            "new_outcome": new_outcome,
            "operator": operator,
        }

    # ── 4. Review Logs ───────────────────────────────────────────────────

    def review_logs(self, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
        """
        Review audit logs and control events.

        Parameters
        ----------
        limit      : Maximum entries to return.
        event_type : Optional filter (e.g. "guardrail_check", "pause").
        """
        logs: list[dict[str, Any]] = []

        # Control events
        for event in self._events[-limit:]:
            entry = event.to_dict()
            entry["source"] = "control_panel"
            if event_type and event.action != event_type:
                continue
            logs.append(entry)

        # Audit log entries (read from file)
        if self._audit is not None:
            try:
                audit_path = getattr(self._audit, "_path", None)
                if audit_path and Path(audit_path).exists():
                    lines = Path(audit_path).read_text(encoding="utf-8").strip().splitlines()
                    for line in lines[-limit:]:
                        try:
                            entry = json.loads(line)
                            entry["source"] = "audit_log"
                            if event_type and entry.get("event") != event_type:
                                continue
                            logs.append(entry)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                pass

        # Sort by timestamp descending
        logs.sort(key=lambda x: x.get("timestamp", x.get("ts", 0)), reverse=True)
        return logs[:limit]

    # ── 5. Update Configuration ──────────────────────────────────────────

    def update_config(
        self,
        updates: dict[str, Any],
        operator: str = "system",
    ) -> dict[str, Any]:
        """
        Update guardrail rules at runtime.

        Parameters
        ----------
        updates  : Dict of rule names → new values.
        operator : Who is making the change.

        Example
        -------
        panel.update_config({
            "max_transaction": 200,
            "rate_limits": {"refund": 5},
        })
        """
        if self._guardrails is None:
            return {"status": "error", "message": "No guardrail controller registered."}

        self._guardrails.update_rules(updates)
        self._record_event("config_update", operator, {"updates": updates})

        logger.info("ControlPanel[%s]: config updated by %s — %s",
                     self.agent_name, operator, list(updates.keys()))
        return {
            "status": "updated",
            "updated_keys": list(updates.keys()),
            "operator": operator,
        }

    # ── Goal management shortcuts ────────────────────────────────────────

    def cancel_goal(self, goal_id: str, operator: str = "system") -> dict[str, Any]:
        """Cancel a goal via the goal manager."""
        if self._goal_manager is None:
            return {"status": "error", "message": "No goal manager registered."}

        success = self._goal_manager.cancel_goal(goal_id)
        if success:
            self._record_event("cancel_goal", operator, {"goal_id": goal_id})
            return {"status": "cancelled", "goal_id": goal_id}
        return {"status": "error", "message": f"Goal '{goal_id}' not found."}

    def pause_goal(self, goal_id: str, operator: str = "system") -> dict[str, Any]:
        """Pause a goal via the goal manager."""
        if self._goal_manager is None:
            return {"status": "error", "message": "No goal manager registered."}

        success = self._goal_manager.pause_goal(goal_id)
        if success:
            self._record_event("pause_goal", operator, {"goal_id": goal_id})
            return {"status": "paused", "goal_id": goal_id}
        return {"status": "error", "message": f"Goal '{goal_id}' not found."}

    # ── Full dashboard ───────────────────────────────────────────────────

    def dashboard(self) -> dict[str, Any]:
        """
        Return a complete dashboard view for the operator.

        Combines: agent state, activity inspection, recent logs,
        guardrail rules, memory stats, and control event history.
        """
        return {
            "agent": self.agent_name,
            "state": self.agent_state(),
            "timestamp": time.time(),
            "activity": self.inspect(),
            "recent_logs": self.review_logs(limit=20),
            "control_history": [e.to_dict() for e in self._events[-20:]],
            "guardrail_rules": (
                self._guardrails.rules.to_dict() if self._guardrails else None
            ),
        }

    # ── Event persistence ────────────────────────────────────────────────

    def _record_event(
        self,
        action: str,
        operator: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a control event."""
        event = ControlEvent(
            action=action,
            operator=operator,
            details=details or {},
        )
        self._events.append(event)
        self._save_events()

    def _save_events(self) -> None:
        """Persist control events to disk."""
        try:
            data = [e.to_dict() for e in self._events[-500:]]  # Keep last 500
            tmp = self._events_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            import os
            os.replace(tmp, self._events_path)
        except OSError as exc:
            logger.warning("ControlPanel[%s]: could not save events: %s",
                           self.agent_name, exc)

    def _load_events(self) -> None:
        """Load control events from disk."""
        if not self._events_path.exists():
            return
        try:
            data = json.loads(self._events_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    self._events.append(ControlEvent(
                        action=item.get("action", ""),
                        operator=item.get("operator", ""),
                        details=item.get("details", {}),
                        timestamp=item.get("timestamp", 0),
                    ))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("ControlPanel[%s]: could not load events: %s",
                           self.agent_name, exc)

    # ── Repr ─────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"AgentControlPanel(agent={self.agent_name!r}, "
            f"state={self.agent_state()}, "
            f"events={len(self._events)})"
        )
