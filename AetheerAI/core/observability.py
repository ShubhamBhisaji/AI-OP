"""observability.py — Product-grade observability for AetheerAI agents.

Closes ISSUE 4: Observability / Logs Not Product-Grade.

Provides:
    1. Structured JSON logging with trace IDs
    2. Activity log (human-readable event stream)
    3. Action history (searchable, filterable)
    4. Error reporting (aggregated, deduplicated)
    5. Health check endpoint
    6. CLI-friendly status dashboard
    7. Audit log rotation

Usage
-----
    obs = ObservabilityEngine(agent_name="store_bot")

    # Structured logging
    obs.log("refund_processed", agent="bot", amount=50, order="1234")

    # Record action
    obs.record_action("process_refund", success=True, duration=1.2)

    # Record error
    obs.record_error("PaymentGatewayTimeout", "Stripe API timed out")

    # Health check
    health = obs.health_check()

    # CLI dashboard
    print(obs.cli_dashboard())
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_LOG_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_ROTATED_FILES = 5


# ── Structured Log Entry ────────────────────────────────────────────────────

@dataclass
class LogEntry:
    event: str
    level: str = "info"        # debug | info | warning | error | critical
    agent_name: str = ""
    trace_id: str = ""
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "level": self.level,
            "agent": self.agent_name,
            "trace_id": self.trace_id,
            "ts": self.timestamp,
            **self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=True)


# ── Action Record ───────────────────────────────────────────────────────────

@dataclass
class ActionRecord:
    action: str
    success: bool
    duration_seconds: float = 0.0
    agent_name: str = ""
    trace_id: str = ""
    error: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "success": self.success,
            "duration": round(self.duration_seconds, 3),
            "agent": self.agent_name,
            "trace_id": self.trace_id,
            "error": self.error,
            "ts": self.timestamp,
        }


# ── Error Report ────────────────────────────────────────────────────────────

@dataclass
class ErrorReport:
    error_type: str
    message: str
    count: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    agent_name: str = ""
    trace_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message": self.message[:500],
            "count": self.count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "agent": self.agent_name,
            "recent_traces": self.trace_ids[-5:],
        }


# ── ObservabilityEngine ─────────────────────────────────────────────────────

class ObservabilityEngine:
    """
    Product-grade observability for AetheerAI agents.

    Parameters
    ----------
    agent_name : Agent this engine monitors.
    log_dir    : Directory for log files (default: workspace/logs/).
    max_actions : Maximum action records to keep in memory.
    max_errors  : Maximum deduplicated error reports.
    """

    def __init__(
        self,
        agent_name: str,
        log_dir: str | Path | None = None,
        max_actions: int = 1000,
        max_errors: int = 200,
    ) -> None:
        self.agent_name = agent_name
        self._log_dir = Path(log_dir or Path(__file__).resolve().parents[1] / "workspace" / "logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._log_path = self._log_dir / f"{agent_name}.jsonl"
        self._max_actions = max_actions
        self._max_errors = max_errors

        self._actions: list[ActionRecord] = []
        self._errors: dict[str, ErrorReport] = {}  # error_type → report
        self._started_at = time.time()
        self._total_actions = 0
        self._total_errors = 0
        self._total_successes = 0

    # ── Trace IDs ────────────────────────────────────────────────────────

    @staticmethod
    def new_trace_id() -> str:
        """Generate a new trace ID for request correlation."""
        return str(uuid.uuid4())[:12]

    # ── 1. Structured Logging ────────────────────────────────────────────

    def log(
        self,
        event: str,
        level: str = "info",
        trace_id: str = "",
        **data: Any,
    ) -> None:
        """Write a structured log entry to the JSONL log file."""
        entry = LogEntry(
            event=event,
            level=level,
            agent_name=self.agent_name,
            trace_id=trace_id,
            data=data,
        )

        # Write to file
        self._append_log(entry.to_json())

        # Also emit to Python logger
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, "[%s] %s %s", self.agent_name, event,
                   json.dumps(data, default=str) if data else "")

    # ── 2. Action History ────────────────────────────────────────────────

    def record_action(
        self,
        action: str,
        success: bool,
        duration_seconds: float = 0.0,
        trace_id: str = "",
        error: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a completed action for history tracking."""
        record = ActionRecord(
            action=action,
            success=success,
            duration_seconds=duration_seconds,
            agent_name=self.agent_name,
            trace_id=trace_id,
            error=error,
            context=context or {},
        )
        self._actions.append(record)
        self._total_actions += 1
        if success:
            self._total_successes += 1

        # Prune old records
        if len(self._actions) > self._max_actions:
            self._actions = self._actions[-self._max_actions:]

        # Log it
        self.log(
            f"action.{action}",
            level="info" if success else "warning",
            trace_id=trace_id,
            success=success,
            duration=round(duration_seconds, 3),
            error=error,
        )

    def get_actions(
        self,
        action: str | None = None,
        success: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query action history with optional filters."""
        results = list(self._actions)
        if action:
            results = [a for a in results if action.lower() in a.action.lower()]
        if success is not None:
            results = [a for a in results if a.success == success]
        return [a.to_dict() for a in results[-limit:]]

    # ── 3. Error Reporting ───────────────────────────────────────────────

    def record_error(
        self,
        error_type: str,
        message: str,
        trace_id: str = "",
    ) -> None:
        """Record an error (deduplicated by error_type)."""
        self._total_errors += 1

        if error_type in self._errors:
            report = self._errors[error_type]
            report.count += 1
            report.last_seen = time.time()
            report.message = message[:500]
            if trace_id:
                report.trace_ids.append(trace_id)
                report.trace_ids = report.trace_ids[-10:]
        else:
            self._errors[error_type] = ErrorReport(
                error_type=error_type,
                message=message[:500],
                agent_name=self.agent_name,
                trace_ids=[trace_id] if trace_id else [],
            )

        # Prune if too many error types
        if len(self._errors) > self._max_errors:
            # Remove least-recent errors
            sorted_errors = sorted(self._errors.items(), key=lambda x: x[1].last_seen)
            for key, _ in sorted_errors[:len(self._errors) - self._max_errors]:
                del self._errors[key]

        self.log("error", level="error", trace_id=trace_id,
                 error_type=error_type, message=message[:200])

    def get_errors(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return deduplicated error reports, most frequent first."""
        reports = sorted(self._errors.values(), key=lambda r: r.count, reverse=True)
        return [r.to_dict() for r in reports[:limit]]

    # ── 4. Health Check ──────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """
        Run a health check and return status.

        Returns a dict with:
        - status: "healthy" | "degraded" | "unhealthy"
        - checks: individual check results
        - metrics: key performance indicators
        """
        checks: list[dict[str, Any]] = []
        uptime = time.time() - self._started_at

        # Check 1: Error rate
        error_rate = (
            self._total_errors / self._total_actions
            if self._total_actions > 0 else 0
        )
        error_ok = error_rate < 0.1  # <10% error rate
        checks.append({
            "name": "error_rate",
            "passed": error_ok,
            "value": f"{error_rate:.1%}",
            "threshold": "<10%",
        })

        # Check 2: Recent activity (agent is doing work)
        recent_cutoff = time.time() - 300  # Last 5 minutes
        recent_actions = sum(1 for a in self._actions if a.timestamp > recent_cutoff)
        activity_ok = self._total_actions == 0 or recent_actions > 0
        checks.append({
            "name": "recent_activity",
            "passed": activity_ok,
            "value": f"{recent_actions} actions in last 5m",
        })

        # Check 3: No repeated failures
        repeated_failures = any(r.count >= 10 for r in self._errors.values())
        failure_ok = not repeated_failures
        checks.append({
            "name": "no_repeated_failures",
            "passed": failure_ok,
            "value": f"{'repeated failures detected' if repeated_failures else 'ok'}",
        })

        # Check 4: Log file writable
        log_ok = True
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log_ok = False
        checks.append({
            "name": "log_writable",
            "passed": log_ok,
            "value": str(self._log_dir),
        })

        # Overall status
        all_passed = all(c["passed"] for c in checks)
        critical_failed = not error_ok or not failure_ok
        if all_passed:
            status = "healthy"
        elif critical_failed:
            status = "unhealthy"
        else:
            status = "degraded"

        return {
            "status": status,
            "agent": self.agent_name,
            "uptime_seconds": round(uptime, 1),
            "checks": checks,
            "metrics": {
                "total_actions": self._total_actions,
                "total_errors": self._total_errors,
                "success_rate": round(
                    self._total_successes / self._total_actions, 4
                ) if self._total_actions > 0 else 1.0,
                "error_rate": round(error_rate, 4),
                "unique_error_types": len(self._errors),
            },
        }

    # ── 5. CLI Dashboard ─────────────────────────────────────────────────

    def cli_dashboard(self) -> str:
        """Generate a CLI-friendly status dashboard."""
        health = self.health_check()
        sep = "=" * 60
        lines = [
            f"\n{sep}",
            f"  Agent Dashboard — {self.agent_name}",
            f"{sep}",
            f"",
            f"  Status:  {health['status'].upper()}",
            f"  Uptime:  {health['uptime_seconds']:.0f}s",
            f"",
            f"  --- Metrics ---",
            f"  Actions:      {health['metrics']['total_actions']}",
            f"  Successes:    {self._total_successes}",
            f"  Errors:       {health['metrics']['total_errors']}",
            f"  Success Rate: {health['metrics']['success_rate']:.1%}",
            f"  Error Types:  {health['metrics']['unique_error_types']}",
            f"",
            f"  --- Health Checks ---",
        ]

        for check in health["checks"]:
            icon = "+" if check["passed"] else "X"
            lines.append(f"  [{icon}] {check['name']:<25} {check['value']}")

        # Recent actions
        recent = self._actions[-5:]
        if recent:
            lines.append(f"\n  --- Recent Actions ---")
            for a in reversed(recent):
                icon = "+" if a.success else "X"
                lines.append(
                    f"  [{icon}] {a.action:<25} {a.duration_seconds:.1f}s"
                    f"{'  ERR: ' + a.error[:30] if a.error else ''}"
                )

        # Top errors
        top_errors = sorted(self._errors.values(), key=lambda r: r.count, reverse=True)[:3]
        if top_errors:
            lines.append(f"\n  --- Top Errors ---")
            for err in top_errors:
                lines.append(f"  [{err.count}x] {err.error_type}: {err.message[:40]}")

        lines.append(f"\n{sep}")
        return "\n".join(lines)

    # ── 6. Log Rotation ──────────────────────────────────────────────────

    def rotate_logs(self) -> dict[str, Any]:
        """
        Rotate the JSONL log file if it exceeds the size limit.

        Keeps up to _MAX_ROTATED_FILES rotated copies:
            agent.jsonl → agent.1.jsonl → agent.2.jsonl → ...
        """
        if not self._log_path.exists():
            return {"rotated": False, "reason": "no log file"}

        size = self._log_path.stat().st_size
        if size < _MAX_LOG_FILE_BYTES:
            return {"rotated": False, "size_bytes": size, "limit_bytes": _MAX_LOG_FILE_BYTES}

        # Rotate existing files
        for i in range(_MAX_ROTATED_FILES, 0, -1):
            src = self._log_dir / f"{self.agent_name}.{i}.jsonl"
            dst = self._log_dir / f"{self.agent_name}.{i + 1}.jsonl"
            if src.exists():
                if i == _MAX_ROTATED_FILES:
                    src.unlink()  # Delete oldest
                else:
                    src.rename(dst)

        # Move current to .1
        rotated_path = self._log_dir / f"{self.agent_name}.1.jsonl"
        self._log_path.rename(rotated_path)

        logger.info("ObservabilityEngine[%s]: log rotated (%d bytes).",
                     self.agent_name, size)
        return {"rotated": True, "previous_size_bytes": size}

    # ── Internal helpers ─────────────────────────────────────────────────

    def _append_log(self, json_line: str) -> None:
        """Append a JSONL line to the log file with auto-rotation."""
        try:
            # Auto-rotate if needed
            if self._log_path.exists() and self._log_path.stat().st_size >= _MAX_LOG_FILE_BYTES:
                self.rotate_logs()

            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json_line + "\n")
        except OSError as exc:
            # Last resort — don't crash the agent for a log failure
            logger.debug("ObservabilityEngine: log write failed: %s", exc)

    # ── Export ───────────────────────────────────────────────────────────

    def export_report(self) -> dict[str, Any]:
        """Export a full observability report as a dict."""
        return {
            "agent": self.agent_name,
            "health": self.health_check(),
            "recent_actions": self.get_actions(limit=20),
            "errors": self.get_errors(limit=20),
            "generated_at": time.time(),
        }

    def __repr__(self) -> str:
        return (
            f"ObservabilityEngine(agent={self.agent_name!r}, "
            f"actions={self._total_actions}, errors={self._total_errors})"
        )
