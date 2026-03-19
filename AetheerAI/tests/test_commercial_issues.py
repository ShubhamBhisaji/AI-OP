"""test_commercial_issues.py — Tests for ISSUE 1–5 closure components.

ISSUE 1: Global Action Gate       → security/action_gate.py
ISSUE 2: Kill Switch              → core/kill_switch.py
ISSUE 3: Goal Scheduler           → core/scheduled_goals.py
ISSUE 4: Observability Engine     → core/observability.py
ISSUE 5: Version Manager          → core/version_manager.py
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE 1 — Global Action Gate
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionGate:

    def _make_gate(self, rules=None):
        from security.action_gate import ActionGate
        from security.guardrail_controller import GuardrailController, GuardrailRules
        gc = GuardrailController(rules=rules or GuardrailRules())
        return ActionGate(guardrail=gc)

    def test_enter_exit_success(self):
        gate = self._make_gate()
        token = gate.enter("read_data", agent_name="bot")
        assert token.status == "active"
        gate.exit_success(token, result="done")
        assert token.status == "completed"

    def test_enter_denied_by_guardrail(self):
        from security.guardrail_controller import GuardrailRules
        rules = GuardrailRules(restricted_operations=["delete_all"])
        gate = self._make_gate(rules)
        with pytest.raises(PermissionError, match="denied"):
            gate.enter("delete_all_records", agent_name="bot")

    def test_execute_guarded_success(self):
        gate = self._make_gate()
        result = gate.execute_guarded(
            agent_name="bot",
            action="calculate",
            fn=lambda ctx: 42,
            context={},
        )
        assert result.success
        assert result.result == 42

    def test_execute_guarded_timeout(self):
        gate = self._make_gate()
        result = gate.execute_guarded(
            agent_name="bot",
            action="slow_task",
            fn=lambda ctx: time.sleep(5),
            context={},
            timeout_seconds=0.2,
        )
        assert not result.success
        assert result.timed_out

    def test_execute_guarded_denied(self):
        from security.guardrail_controller import GuardrailRules
        rules = GuardrailRules(restricted_operations=["forbidden"])
        gate = self._make_gate(rules)
        result = gate.execute_guarded(
            agent_name="bot",
            action="forbidden_action",
            fn=lambda ctx: "should not run",
        )
        assert not result.success
        assert result.denied

    def test_execute_guarded_fn_exception(self):
        gate = self._make_gate()
        result = gate.execute_guarded(
            agent_name="bot",
            action="crash",
            fn=lambda ctx: 1 / 0,
        )
        assert not result.success
        assert "division by zero" in result.error

    def test_cancel_action(self):
        from security.action_gate import ActionGate
        gate = ActionGate()
        token = gate.enter("long_task", agent_name="bot")
        assert gate.cancel_action(token.token_id, reason="test")
        assert token.cancellation.is_cancelled

    def test_cancel_all(self):
        from security.action_gate import ActionGate
        gate = ActionGate()
        gate.enter("t1", agent_name="bot")
        gate.enter("t2", agent_name="bot")
        gate.enter("t3", agent_name="other")
        count = gate.cancel_all(agent_name="bot")
        assert count == 2

    def test_disable_blocks_all(self):
        from security.action_gate import ActionGate
        gate = ActionGate()
        gate.disable()
        with pytest.raises(PermissionError, match="disabled"):
            gate.enter("anything", agent_name="bot")

    def test_cancellation_token(self):
        from security.action_gate import CancellationToken
        token = CancellationToken()
        assert not token.is_cancelled
        token.cancel("test reason")
        assert token.is_cancelled
        assert token.reason == "test reason"
        with pytest.raises(InterruptedError):
            token.check()

    def test_decorator(self):
        gate = self._make_gate()

        @gate.require(action="compute", category="general", timeout_seconds=5)
        def compute(x, y, _agent_name="bot"):
            return x + y

        result = compute(3, 4, _agent_name="bot")
        assert result == 7

    def test_stats(self):
        gate = self._make_gate()
        gate.execute_guarded("bot", "a1", fn=lambda c: "ok")
        gate.execute_guarded("bot", "a2", fn=lambda c: 1 / 0)
        stats = gate.stats()
        assert stats["total_decisions"] >= 2
        assert stats["allowed"] >= 1

    def test_history(self):
        gate = self._make_gate()
        gate.execute_guarded("bot", "test", fn=lambda c: "ok")
        history = gate.history(limit=10)
        assert len(history) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE 2 — Kill Switch
# ═══════════════════════════════════════════════════════════════════════════════

class TestKillSwitch:

    def _make_ks(self, tmp_path):
        from core.kill_switch import KillSwitch
        return KillSwitch("test_agent", log_dir=tmp_path)

    def test_emergency_stop(self, tmp_path):
        from core.kill_switch import AgentMode
        ks = self._make_ks(tmp_path)

        gate = MagicMock()
        gate.cancel_all = MagicMock(return_value=3)
        gate.disable = MagicMock()
        ks.register_action_gate(gate)

        loop = MagicMock()
        ks.register_loop(loop)

        result = ks.emergency_stop(operator="admin", reason="breach")
        assert result["status"] == "emergency_stopped"
        assert result["actions_cancelled"] == 3
        assert ks.mode == AgentMode.EMERGENCY
        assert gate.disable.called
        assert loop.stop.called

    def test_safe_shutdown(self, tmp_path):
        from core.kill_switch import AgentMode
        ks = self._make_ks(tmp_path)
        loop = MagicMock()
        ks.register_loop(loop)

        result = ks.safe_shutdown(operator="admin")
        assert result["status"] == "safe_shutdown"
        assert ks.mode == AgentMode.SAFE_STOP
        assert loop.pause.called

    def test_disable_integrations(self, tmp_path):
        ks = self._make_ks(tmp_path)
        integrator = MagicMock()
        integrator.list_integrations.return_value = [
            {"name": "shopify"}, {"name": "stripe"}
        ]
        integrator.disconnect = MagicMock(return_value=True)
        ks.register_integrator(integrator)

        result = ks.disable_integrations(operator="admin")
        assert result["disconnected"] == 2
        assert integrator.disconnect.call_count == 2

    def test_throttle(self, tmp_path):
        from core.kill_switch import AgentMode
        ks = self._make_ks(tmp_path)
        result = ks.throttle(0.25, operator="admin")
        assert result["rate"] == 0.25
        assert ks.mode == AgentMode.THROTTLED
        assert ks.throttle_delay() > 0

    def test_reset(self, tmp_path):
        from core.kill_switch import AgentMode
        ks = self._make_ks(tmp_path)
        gate = MagicMock()
        ks.register_action_gate(gate)

        ks.emergency_stop(operator="admin")
        assert ks.mode == AgentMode.EMERGENCY

        ks.reset(operator="admin")
        assert ks.mode == AgentMode.NORMAL
        assert gate.enable.called

    def test_is_operational(self, tmp_path):
        ks = self._make_ks(tmp_path)
        assert ks.is_operational()
        ks.emergency_stop(operator="admin")
        assert not ks.is_operational()

    def test_event_persistence(self, tmp_path):
        from core.kill_switch import KillSwitch
        ks1 = KillSwitch("test_agent", log_dir=tmp_path)
        ks1.throttle(0.5, operator="admin")

        ks2 = KillSwitch("test_agent", log_dir=tmp_path)
        assert len(ks2._events) == 1

    def test_status(self, tmp_path):
        ks = self._make_ks(tmp_path)
        status = ks.status()
        assert status["mode"] == "normal"
        assert status["throttle_rate"] == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE 3 — Goal Scheduler
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoalScheduler:

    def _make_gm(self):
        gm = MagicMock()
        gm.add_goal = MagicMock(return_value="g1")
        gm.add_task = MagicMock(return_value="t1")
        gm.start_goal = MagicMock(return_value=True)
        return gm

    def test_schedule_and_dispatch(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = self._make_gm()
        gs = GoalScheduler(gm, persist_path=tmp_path / "sched.json")

        gs.schedule(
            description="Test goal",
            agent_name="bot",
            run_at=time.time() - 1,  # Already due
            tasks=["Task A", "Task B"],
        )

        dispatched = gs.tick()
        assert dispatched == 1
        assert gm.add_goal.called
        assert gm.add_task.call_count == 2

    def test_schedule_future(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = self._make_gm()
        gs = GoalScheduler(gm, persist_path=tmp_path / "sched.json")

        gs.schedule(
            description="Future goal",
            agent_name="bot",
            run_at=time.time() + 3600,  # 1 hour from now
            tasks=["Task A"],
        )

        dispatched = gs.tick()
        assert dispatched == 0

    def test_recurring_goal(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = self._make_gm()
        gs = GoalScheduler(gm, persist_path=tmp_path / "sched.json")

        sid = gs.schedule_recurring(
            description="Recurring check",
            agent_name="bot",
            interval_seconds=60,
            run_at=time.time() - 1,
            tasks=["Check"],
        )

        dispatched = gs.tick()
        assert dispatched == 1

        # Should be rescheduled for next interval
        goal = gs._scheduled[sid]
        assert goal.is_recurring
        assert goal.run_at > time.time()

    def test_cancel_goal(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = self._make_gm()
        gs = GoalScheduler(gm, persist_path=tmp_path / "sched.json")

        sid = gs.schedule("Cancel me", "bot", run_at=time.time() - 1, tasks=["X"])
        assert gs.cancel(sid)
        assert gs.tick() == 0

    def test_pause_resume(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = self._make_gm()
        gs = GoalScheduler(gm, persist_path=tmp_path / "sched.json")

        sid = gs.schedule("Pause me", "bot", run_at=time.time() - 1, tasks=["X"])
        assert gs.pause(sid)
        assert gs.tick() == 0

        assert gs.resume(sid)
        assert gs.tick() == 1

    def test_dlq_on_failure(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = MagicMock()
        gm.add_goal = MagicMock(side_effect=RuntimeError("DB down"))
        alert_called = []

        gs = GoalScheduler(
            gm,
            persist_path=tmp_path / "sched.json",
            on_dlq_alert=lambda dle: alert_called.append(dle),
        )

        gs.schedule("Fail goal", "bot", run_at=time.time() - 1, tasks=["X"], max_retries=0)

        # First tick should fail and DLQ (max_retries=0, so run_count > 0 triggers DLQ)
        gs.tick()

        assert gs.dlq_size >= 1
        assert len(alert_called) >= 1

    def test_retry_dlq(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = MagicMock()
        call_count = [0]

        def fail_then_succeed(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                raise RuntimeError("fail")
            return "g1"

        gm.add_goal = MagicMock(side_effect=fail_then_succeed)
        gm.add_task = MagicMock(return_value="t1")
        gm.start_goal = MagicMock()

        gs = GoalScheduler(gm, persist_path=tmp_path / "sched.json")
        sid = gs.schedule("Retry me", "bot", run_at=time.time() - 1, tasks=["X"], max_retries=0)
        gs.tick()
        assert gs.dlq_size == 1

        gs.retry_dlq(sid)
        assert gs.dlq_size == 0
        gs.tick()
        assert gm.add_goal.call_count >= 2

    def test_persistence(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = self._make_gm()

        gs1 = GoalScheduler(gm, persist_path=tmp_path / "sched.json")
        gs1.schedule("Persist me", "bot", run_at=time.time() + 100, tasks=["X"])

        gs2 = GoalScheduler(gm, persist_path=tmp_path / "sched.json")
        assert len(gs2.list_scheduled()) == 1

    def test_status(self, tmp_path):
        from core.scheduled_goals import GoalScheduler
        gm = self._make_gm()
        gs = GoalScheduler(gm, persist_path=tmp_path / "sched.json")
        gs.schedule("S1", "bot", tasks=["T"])
        status = gs.status()
        assert status["total_scheduled"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE 4 — Observability Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestObservabilityEngine:

    def _make_obs(self, tmp_path):
        from core.observability import ObservabilityEngine
        return ObservabilityEngine("test_agent", log_dir=tmp_path)

    def test_structured_logging(self, tmp_path):
        obs = self._make_obs(tmp_path)
        obs.log("test_event", level="info", key="value")
        log_path = tmp_path / "test_agent.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) >= 1
        import json
        entry = json.loads(lines[-1])
        assert entry["event"] == "test_event"

    def test_record_action(self, tmp_path):
        obs = self._make_obs(tmp_path)
        obs.record_action("process_refund", success=True, duration_seconds=1.5)
        obs.record_action("send_email", success=False, error="timeout")

        actions = obs.get_actions()
        assert len(actions) == 2

        successes = obs.get_actions(success=True)
        assert len(successes) == 1

    def test_error_reporting(self, tmp_path):
        obs = self._make_obs(tmp_path)
        obs.record_error("TimeoutError", "API timed out")
        obs.record_error("TimeoutError", "API timed out again")
        obs.record_error("ValueError", "Bad input")

        errors = obs.get_errors()
        assert len(errors) == 2
        timeout_err = next(e for e in errors if e["error_type"] == "TimeoutError")
        assert timeout_err["count"] == 2

    def test_health_check_healthy(self, tmp_path):
        obs = self._make_obs(tmp_path)
        obs.record_action("a1", success=True)
        obs.record_action("a2", success=True)
        health = obs.health_check()
        assert health["status"] == "healthy"

    def test_health_check_unhealthy(self, tmp_path):
        obs = self._make_obs(tmp_path)
        # Generate high error rate
        for i in range(10):
            obs.record_action(f"fail_{i}", success=False, error="boom")
            obs.record_error("Boom", "boom")
        health = obs.health_check()
        assert health["status"] in ("degraded", "unhealthy")

    def test_cli_dashboard(self, tmp_path):
        obs = self._make_obs(tmp_path)
        obs.record_action("task1", success=True, duration_seconds=0.5)
        obs.record_error("TestError", "test message")
        dashboard = obs.cli_dashboard()
        assert "test_agent" in dashboard
        assert "Metrics" in dashboard

    def test_log_rotation(self, tmp_path):
        from core.observability import ObservabilityEngine, _MAX_LOG_FILE_BYTES
        obs = ObservabilityEngine("test_agent", log_dir=tmp_path)

        # Write a large log
        log_path = tmp_path / "test_agent.jsonl"
        log_path.write_text("x" * (_MAX_LOG_FILE_BYTES + 100))

        result = obs.rotate_logs()
        assert result["rotated"]
        assert (tmp_path / "test_agent.1.jsonl").exists()

    def test_trace_ids(self, tmp_path):
        obs = self._make_obs(tmp_path)
        tid = obs.new_trace_id()
        assert len(tid) == 12
        obs.record_action("traced", success=True, trace_id=tid)
        obs.record_error("TracedError", "msg", trace_id=tid)

        errors = obs.get_errors()
        assert tid in errors[0]["recent_traces"]

    def test_export_report(self, tmp_path):
        obs = self._make_obs(tmp_path)
        obs.record_action("test", success=True)
        report = obs.export_report()
        assert "health" in report
        assert "recent_actions" in report


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUE 5 — Version Manager
# ═══════════════════════════════════════════════════════════════════════════════

class TestVersionManager:

    def _make_vm(self, tmp_path):
        from core.version_manager import VersionManager
        return VersionManager("test_agent", data_dir=tmp_path)

    def test_register_version(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["Initial release"], {"skills": ["crm"]})
        assert vm.current_version == "1.0.0"
        assert len(vm.list_versions()) == 1

    def test_version_supersedes_previous(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["v1"], {"skills": []})
        vm.register_version("1.1.0", ["v1.1"], {"skills": ["crm"]})
        assert vm.current_version == "1.1.0"
        assert vm.get_version("1.0.0").status == "superseded"

    def test_semver_parsing(self):
        from core.version_manager import SemVer
        v = SemVer.parse("2.3.1")
        assert v.major == 2
        assert v.minor == 3
        assert v.patch == 1
        assert str(v) == "2.3.1"

    def test_semver_comparison(self):
        from core.version_manager import SemVer
        v1 = SemVer.parse("1.0.0")
        v2 = SemVer.parse("1.1.0")
        v3 = SemVer.parse("2.0.0")
        assert v1 < v2 < v3
        assert v2.is_compatible_with(v1)
        assert not v3.is_compatible_with(v1)

    def test_semver_bump(self):
        from core.version_manager import SemVer
        v = SemVer.parse("1.2.3")
        assert str(v.bump("patch")) == "1.2.4"
        assert str(v.bump("minor")) == "1.3.0"
        assert str(v.bump("major")) == "2.0.0"

    def test_upgrade_with_migration(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["v1"], {"skills": ["crm"], "version": "1.0.0"})

        def migrate(spec):
            spec["skills"].append("email")
            spec["version"] = "1.1.0"
            return spec

        result = vm.upgrade("1.0.0", "1.1.0", migration_fn=migrate)
        assert result["status"] == "upgraded"
        assert "email" in result["spec"]["skills"]
        assert vm.current_version == "1.1.0"

    def test_upgrade_with_registered_migrations(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["v1"], {"version": "1.0.0", "features": []})

        vm.register_migration("1.0.0", "1.1.0", "Add feature A",
                              lambda s: {**s, "features": s["features"] + ["A"]})
        vm.register_migration("1.1.0", "1.2.0", "Add feature B",
                              lambda s: {**s, "features": s["features"] + ["B"]})

        result = vm.upgrade("1.0.0", "1.2.0")
        assert result["status"] == "upgraded"
        assert result["spec"]["features"] == ["A", "B"]

    def test_upgrade_no_path(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["v1"], {})
        result = vm.upgrade("1.0.0", "3.0.0")
        assert result["status"] == "error"

    def test_rollback(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["v1"], {"x": 1})
        vm.register_version("1.1.0", ["v1.1"], {"x": 2})
        assert vm.current_version == "1.1.0"

        result = vm.rollback("1.0.0")
        assert result["status"] == "rolled_back"
        assert vm.current_version == "1.0.0"
        assert vm.get_version("1.1.0").status == "rolled_back"
        assert vm.get_version("1.0.0").status == "active"

    def test_compatibility_check(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["v1"], {"skills": ["crm", "email"], "integrations": ["shopify"]})

        # Compatible
        result = vm.check_compatibility("1.0.0", required_skills=["crm"])
        assert result["compatible"]

        # Missing skill
        result = vm.check_compatibility("1.0.0", required_skills=["analytics"])
        assert not result["compatible"]

        # Version too low
        result = vm.check_compatibility("1.0.0", min_version="2.0.0")
        assert not result["compatible"]

    def test_changelog(self, tmp_path):
        vm = self._make_vm(tmp_path)
        vm.register_version("1.0.0", ["Initial"], {})
        vm.register_version("1.1.0", ["Added CRM"], {})

        log = vm.changelog()
        assert len(log) == 2
        assert log[0]["version"] == "1.1.0"  # newest first

    def test_persistence(self, tmp_path):
        from core.version_manager import VersionManager
        vm1 = VersionManager("test_agent", data_dir=tmp_path)
        vm1.register_version("1.0.0", ["v1"], {"data": True})

        vm2 = VersionManager("test_agent", data_dir=tmp_path)
        assert vm2.current_version == "1.0.0"
        assert vm2.get_version("1.0.0").spec_snapshot["data"] is True
