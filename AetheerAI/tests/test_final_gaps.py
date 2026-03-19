"""Tests for the 5 final GAP closures.

GAP 1: ActionProxy — Centralized, impossible-to-bypass action control
GAP 2: HumanOverrideController — Unified human override mechanism
GAP 3: UnifiedMonitor — Complete monitoring & reporting
GAP 4: UpdateChannel — Update & patch distribution
GAP 5: EconomicGuardrails — Hard rate limits, cost caps, quotas
"""

import sys, os, time, tempfile, shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ═════════════════════════════════════════════════════════════════════════════
# GAP 1 — ActionProxy
# ═════════════════════════════════════════════════════════════════════════════

from security.action_proxy import ActionProxy, ProxyResult, ActionCategory
from security.action_gate import ActionGate
from security.guardrail_controller import GuardrailController, GuardrailRules


def _make_gate(blocked_ops=None):
    rules = GuardrailRules(
        restricted_operations=blocked_ops or [],
    )
    gc = GuardrailController(rules=rules)
    gate = ActionGate(guardrail=gc)
    return gate


class TestActionProxy:
    def test_api_call_success(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.api_call("GET", "https://api.example.com/orders",
                                execute_fn=lambda: {"orders": [1, 2, 3]})
        assert result.allowed is True
        assert result.success is True
        assert result.result == {"orders": [1, 2, 3]}
        assert result.category == "api_call"

    def test_api_call_blocked(self):
        gate = _make_gate(blocked_ops=["api.GET"])
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.api_call("GET", "https://api.example.com/orders",
                                execute_fn=lambda: "nope")
        assert result.allowed is False
        assert result.success is False

    def test_data_write_success(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.data_write("insert", "users", {"name": "Alice"},
                                  execute_fn=lambda: {"id": 1})
        assert result.allowed is True
        assert result.result == {"id": 1}
        assert result.category == "data_write"

    def test_message_send_success(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.message_send("email", "user@test.com", "Hello!",
                                    execute_fn=lambda: "sent")
        assert result.allowed is True
        assert result.category == "message_send"

    def test_transaction_success(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.transaction("refund", amount=49.99, currency="USD",
                                   execute_fn=lambda: {"refund_id": "R123"})
        assert result.allowed is True
        assert result.result == {"refund_id": "R123"}
        assert result.category == "transaction"

    def test_system_command_success(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.system_command("ls", ["-la"],
                                      execute_fn=lambda: "file_list")
        assert result.allowed is True
        assert result.category == "system_command"

    def test_generic_execute(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.execute("custom_action",
                               execute_fn=lambda: "done",
                               category="custom")
        assert result.allowed is True

    def test_dry_run_no_fn(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.api_call("GET", "https://api.example.com/health")
        assert result.allowed is True
        assert result.result == {"dry_run": True}

    def test_stats_tracking(self):
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        proxy.api_call("GET", "https://a.com", execute_fn=lambda: "ok")
        proxy.data_write("insert", "t", execute_fn=lambda: "ok")
        stats = proxy.stats()
        assert stats["total_calls"] == 2
        assert stats["total_blocked"] == 0
        assert "by_category" in stats

    def test_history_filter(self):
        gate = _make_gate(blocked_ops=["txn.refund"])
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        proxy.api_call("GET", "https://a.com", execute_fn=lambda: "ok")
        proxy.transaction("refund", amount=10, execute_fn=lambda: "nope")
        all_hist = proxy.history()
        assert len(all_hist) == 2
        blocked = proxy.history(allowed=False)
        assert len(blocked) == 1
        assert "txn.refund" in blocked[0]["action"]

    def test_economic_guardrails_integration(self):
        gate = _make_gate()
        mock_guardrails = MagicMock()
        mock_guardrails.check_quota.return_value = {"allowed": False, "reason": "budget exceeded"}
        proxy = ActionProxy(agent_name="bot", action_gate=gate, guardrails=mock_guardrails)
        result = proxy.api_call("POST", "https://expensive.api/run",
                                execute_fn=lambda: "expensive")
        assert result.allowed is False
        assert "budget" in result.error.lower()

    def test_observability_integration(self):
        gate = _make_gate()
        mock_obs = MagicMock()
        proxy = ActionProxy(agent_name="bot", action_gate=gate, observability=mock_obs)
        proxy.api_call("GET", "https://a.com", execute_fn=lambda: "ok")
        mock_obs.record_action.assert_called_once()

    def test_all_categories_must_go_through_gate(self):
        """Verify every category routes through the ActionGate."""
        gate = _make_gate()
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        categories_tested = set()

        proxy.api_call("GET", "https://a.com", execute_fn=lambda: 1)
        categories_tested.add("api_call")

        proxy.data_write("insert", "t", execute_fn=lambda: 2)
        categories_tested.add("data_write")

        proxy.message_send("email", "a@b.com", "hi", execute_fn=lambda: 3)
        categories_tested.add("message_send")

        proxy.transaction("charge", amount=10, execute_fn=lambda: 4)
        categories_tested.add("transaction")

        proxy.system_command("echo", ["hello"], execute_fn=lambda: 5)
        categories_tested.add("system_command")

        proxy.execute("custom", execute_fn=lambda: 6)
        categories_tested.add("custom")

        assert len(categories_tested) == 6
        assert proxy.stats()["total_calls"] == 6


# ═════════════════════════════════════════════════════════════════════════════
# GAP 2 — HumanOverrideController
# ═════════════════════════════════════════════════════════════════════════════

from core.human_override import (
    HumanOverrideController,
    ApprovalRequest,
    ApprovalStatus,
)


class TestHumanOverride:
    def test_pause_agent(self):
        hoc = HumanOverrideController(agent_name="bot")
        mock_panel = MagicMock()
        mock_panel.pause.return_value = {"status": "paused"}
        hoc.register_control_panel(mock_panel)
        result = hoc.pause(operator="admin", reason="maintenance")
        assert "control_panel" in result
        mock_panel.pause.assert_called_once()

    def test_resume_agent(self):
        hoc = HumanOverrideController(agent_name="bot")
        mock_panel = MagicMock()
        mock_panel.resume.return_value = {"status": "resumed"}
        hoc.register_control_panel(mock_panel)
        result = hoc.resume(operator="admin")
        assert "control_panel" in result

    def test_require_approval(self):
        hoc = HumanOverrideController(agent_name="bot")
        result = hoc.require_approval("refund", operator="admin")
        assert result["status"] == "approval_required"
        assert hoc.needs_approval("process_refund") is True
        assert hoc.needs_approval("read_data") is False

    def test_request_and_approve(self):
        hoc = HumanOverrideController(agent_name="bot")
        req = hoc.request_approval("refund $100", category="transaction")
        assert req.status == ApprovalStatus.PENDING
        assert len(hoc.pending_approvals()) == 1

        result = hoc.approve(req.id, operator="admin", reason="Looks good")
        assert result["status"] == "approved"
        assert len(hoc.pending_approvals()) == 0

    def test_request_and_reject(self):
        hoc = HumanOverrideController(agent_name="bot")
        req = hoc.request_approval("delete all users", category="data_write")
        result = hoc.reject(req.id, operator="admin", reason="Too dangerous")
        assert result["status"] == "rejected"

    def test_approval_expiry(self):
        hoc = HumanOverrideController(agent_name="bot", approval_timeout=0.01)
        hoc.request_approval("slow action", timeout=0.01)
        time.sleep(0.02)
        expired = hoc.expire_stale()
        assert expired == 1
        assert len(hoc.pending_approvals()) == 0

    def test_approval_callback(self):
        hoc = HumanOverrideController(agent_name="bot")
        callback_called = []
        req = hoc.request_approval(
            "test action",
            callback=lambda r: callback_called.append(r.id),
        )
        hoc.approve(req.id, operator="admin")
        assert len(callback_called) == 1
        assert callback_called[0] == req.id

    def test_modify_rules(self):
        hoc = HumanOverrideController(agent_name="bot")
        mock_guardrails = MagicMock()
        hoc.register_guardrails(mock_guardrails)
        result = hoc.modify_rules({"max_transaction_usd": 100}, operator="admin")
        assert result["status"] == "modified"
        mock_guardrails.update_rules.assert_called_once()

    def test_safe_shutdown(self):
        hoc = HumanOverrideController(agent_name="bot")
        mock_ks = MagicMock()
        mock_ks.safe_shutdown.return_value = {"status": "shutting_down"}
        hoc.register_kill_switch(mock_ks)
        result = hoc.shutdown(operator="admin", mode="safe", reason="EOD")
        assert "kill_switch" in result
        mock_ks.safe_shutdown.assert_called_once()

    def test_emergency_shutdown(self):
        hoc = HumanOverrideController(agent_name="bot")
        mock_ks = MagicMock()
        mock_ks.emergency_stop.return_value = {"status": "stopped"}
        mock_gate = MagicMock()
        hoc.register_kill_switch(mock_ks)
        hoc.register_action_gate(mock_gate)
        result = hoc.shutdown(operator="admin", mode="emergency", reason="breach")
        mock_ks.emergency_stop.assert_called_once()
        mock_gate.disable.assert_called_once()

    def test_status_dashboard(self):
        hoc = HumanOverrideController(agent_name="bot")
        hoc.require_approval("delete", operator="admin")
        hoc.request_approval("test")
        status = hoc.status()
        assert status["agent"] == "bot"
        assert status["pending_approvals"] == 1
        assert "delete" in status["approval_patterns"]

    def test_event_log(self):
        hoc = HumanOverrideController(agent_name="bot")
        hoc.pause(operator="admin")
        hoc.resume(operator="admin")
        log = hoc.event_log()
        assert len(log) == 2
        assert log[0]["action"] == "pause"
        assert log[1]["action"] == "resume"

    def test_remove_approval_requirement(self):
        hoc = HumanOverrideController(agent_name="bot")
        hoc.require_approval("refund", operator="admin")
        assert hoc.needs_approval("refund") is True
        hoc.remove_approval_requirement("refund", operator="admin")
        assert hoc.needs_approval("refund") is False


# ═════════════════════════════════════════════════════════════════════════════
# GAP 3 — UnifiedMonitor
# ═════════════════════════════════════════════════════════════════════════════

from core.unified_monitor import UnifiedMonitor, TimelineEvent, DecisionRecord


class TestUnifiedMonitor:
    def test_record_event(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_event("action", "api_call", level="info", details={"url": "https://a.com"})
        timeline = mon.activity_timeline()
        assert len(timeline) == 1
        assert timeline[0]["source"] == "action"

    def test_record_decision(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_decision("d1", "refund $100", "allowed", reason="within limit", impact="medium")
        mon.record_decision("d2", "delete user", "blocked", reason="restricted", impact="high")
        decisions = mon.decision_log()
        assert len(decisions) == 2
        blocked = mon.decision_log(outcome="blocked")
        assert len(blocked) == 1
        assert blocked[0]["action"] == "delete user"

    def test_activity_timeline_filters(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_event("action", "api_call")
        mon.record_event("error", "timeout", level="error")
        mon.record_event("control", "paused", level="warning")
        errors = mon.activity_timeline(level="error")
        assert len(errors) == 1

    def test_health_status_healthy(self):
        mon = UnifiedMonitor(agent_name="bot")
        health = mon.health_status()
        assert health["status"] == "healthy"
        assert health["agent"] == "bot"
        assert "uptime_seconds" in health

    def test_health_status_with_observability(self):
        mon = UnifiedMonitor(agent_name="bot")
        mock_obs = MagicMock()
        mock_obs.health_check.return_value = {"status": "healthy", "metrics": {}}
        mon.register_observability(mock_obs)
        health = mon.health_status()
        assert "observability" in health["components"]

    def test_health_status_degraded(self):
        mon = UnifiedMonitor(agent_name="bot")
        mock_ks = MagicMock()
        mock_ks.status.return_value = {"mode": "throttled"}
        mon.register_kill_switch(mock_ks)
        health = mon.health_status()
        assert health["status"] == "degraded"

    def test_resource_usage(self):
        mon = UnifiedMonitor(agent_name="bot")
        mock_finops = MagicMock()
        mock_finops.status.return_value = {"used_usd": 5.0, "budget_usd": 50.0, "remaining_usd": 45.0}
        mock_finops.ledger.return_value = [{"prompt_tokens": 1000, "completion_tokens": 500}]
        mon.register_finops(mock_finops)
        usage = mon.resource_usage()
        assert usage["cost_usd"] == 5.0
        assert usage["tokens_used"] == 1500

    def test_resource_usage_with_proxy(self):
        mon = UnifiedMonitor(agent_name="bot")
        mock_proxy = MagicMock()
        mock_proxy.stats.return_value = {"total_calls": 100, "total_blocked": 5}
        mon.register_action_proxy(mock_proxy)
        usage = mon.resource_usage()
        assert usage["api_calls"] == 100
        assert usage["api_calls_blocked"] == 5

    def test_integration_status(self):
        mon = UnifiedMonitor(agent_name="bot")
        mock_integrator = MagicMock()
        mock_integrator.list_integrations.return_value = [
            {"name": "slack", "connected": True, "type": "messaging"},
            {"name": "stripe", "connected": False, "type": "payment"},
        ]
        mon.register_integrator(mock_integrator)
        status = mon.integration_status()
        assert status["total"] == 2
        assert status["healthy"] == 1
        assert status["status"] == "degraded"

    def test_full_dashboard(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_event("action", "test")
        mon.record_decision("d1", "test_action", "allowed")
        dash = mon.dashboard()
        assert "health" in dash
        assert "resources" in dash
        assert "recent_activity" in dash
        assert "recent_decisions" in dash
        assert "integrations" in dash

    def test_cli_dashboard(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_decision("d1", "test_action", "allowed")
        cli = mon.cli_dashboard()
        assert "Unified Monitor" in cli
        assert "bot" in cli

    def test_error_report(self):
        mon = UnifiedMonitor(agent_name="bot")
        mock_obs = MagicMock()
        mock_obs.get_errors.return_value = [{"type": "TimeoutError", "count": 5}]
        mon.register_observability(mock_obs)
        errors = mon.error_report()
        assert len(errors) == 1


# ═════════════════════════════════════════════════════════════════════════════
# GAP 4 — UpdateChannel
# ═════════════════════════════════════════════════════════════════════════════

from core.update_channel import UpdateChannel, UpdateRecord, UpdateType
from core.version_manager import VersionManager


class TestUpdateChannel:
    def _make_channel(self, tmpdir):
        vm = VersionManager(agent_name="bot", data_dir=tmpdir)
        vm.register_version("1.0.0", ["Initial release"], {"name": "bot"})
        channel = UpdateChannel(
            agent_name="bot",
            version_manager=vm,
            data_dir=tmpdir,
            auto_apply_security=False,
        )
        return channel, vm

    def test_publish_and_check(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "feature", ["Added search"],
                          description="Search feature")
        available = ch.check_updates()
        assert len(available) == 1
        assert available[0]["version"] == "1.1.0"

    def test_apply_update(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "bugfix", ["Fixed crash"],
                          migration_fn=lambda spec: {**spec, "fixed": True})
        result = ch.apply_update("1.1.0")
        assert result["status"] == "applied"
        assert vm.current_version == "1.1.0"
        available = ch.check_updates()
        assert len(available) == 0

    def test_apply_already_applied(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "bugfix", ["Fix"])
        ch.apply_update("1.1.0")
        result = ch.apply_update("1.1.0")
        assert result["status"] == "error"
        assert "already" in result["message"].lower()

    def test_apply_not_found(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        result = ch.apply_update("9.9.9")
        assert result["status"] == "error"

    def test_dry_run(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "feature", ["New feature"],
                          breaking_changes=["API change"])
        result = ch.apply_update("1.1.0", dry_run=True)
        assert result["status"] == "compatible"
        assert result["breaking_changes"] == ["API change"]
        assert vm.current_version == "1.0.0"  # Not changed

    def test_migration_failure(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        def bad_migration(spec):
            raise RuntimeError("Migration crashed")
        ch.publish_update("1.1.0", "bugfix", ["Fix"],
                          migration_fn=bad_migration)
        result = ch.apply_update("1.1.0")
        assert result["status"] == "error"
        assert "migration" in result["message"].lower()

    def test_security_patch(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        rec = ch.publish_security_patch(
            version="1.0.1",
            cve="CVE-2026-1234",
            description="Fix credential leak",
            severity="high",
        )
        assert rec.cve == "CVE-2026-1234"
        assert rec.update_type == "security"
        assert ch.has_security_updates() is True

    def test_auto_apply_critical_security(self, tmp_path):
        vm = VersionManager(agent_name="bot", data_dir=tmp_path)
        vm.register_version("1.0.0", ["Init"], {"name": "bot"})
        ch = UpdateChannel(agent_name="bot", version_manager=vm,
                           data_dir=tmp_path, auto_apply_security=True)
        ch.publish_security_patch(
            version="1.0.1", cve="CVE-2026-9999",
            description="Critical fix", severity="critical",
        )
        # Should have been auto-applied
        assert vm.current_version == "1.0.1"
        assert ch.has_security_updates() is False

    def test_rollback(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "feature", ["New feature"])
        ch.apply_update("1.1.0")
        assert vm.current_version == "1.1.0"
        result = ch.rollback()
        assert result.get("status") == "rolled_back"

    def test_update_status(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "feature", ["New"])
        ch.publish_security_patch("1.0.1", "CVE-1", "Fix", severity="high")
        status = ch.update_status()
        assert status["available_updates"] == 2
        assert status["security_pending"] == 1
        assert status["current_version"] == "1.0.0"

    def test_persistence(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "feature", ["New feature"])
        # Reload
        ch2 = UpdateChannel(agent_name="bot", version_manager=vm,
                            data_dir=tmp_path, auto_apply_security=False)
        available = ch2.check_updates()
        assert len(available) == 1

    def test_check_updates_priority_order(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "feature", ["Feature"], severity="normal")
        ch.publish_update("1.0.2", "bugfix", ["Fix"], severity="normal")
        ch.publish_security_patch("1.0.1", "CVE-1", "Urgent", severity="critical")
        available = ch.check_updates()
        assert available[0]["update_type"] == "security"  # Security first
        assert available[1]["update_type"] == "bugfix"     # Bugfix second


# ═════════════════════════════════════════════════════════════════════════════
# GAP 5 — EconomicGuardrails
# ═════════════════════════════════════════════════════════════════════════════

from core.economic_guardrails import EconomicGuardrails, RateLimitConfig, QuotaConfig


class TestEconomicGuardrails:
    def test_default_allows(self):
        eg = EconomicGuardrails(agent_name="bot")
        result = eg.check_quota(agent_name="bot", category="api_call")
        assert result["allowed"] is True

    def test_rate_limit_blocks(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_rate_limit("api_call", max_per_minute=3, max_per_hour=100, max_per_day=1000)
        # First 3 should pass
        for _ in range(3):
            result = eg.check_quota(agent_name="bot", category="api_call")
            assert result["allowed"] is True
        # 4th should be blocked
        result = eg.check_quota(agent_name="bot", category="api_call")
        assert result["allowed"] is False
        assert "rate limit" in result["reason"].lower()

    def test_budget_blocks(self):
        eg = EconomicGuardrails(agent_name="bot", monthly_budget_usd=10.0)
        eg._total_cost_usd = 9.50
        result = eg.check_quota(agent_name="bot", category="api_call", estimated_cost=1.00)
        assert result["allowed"] is False
        assert "budget" in result["reason"].lower()

    def test_budget_allows_within_limit(self):
        eg = EconomicGuardrails(agent_name="bot", monthly_budget_usd=10.0)
        eg._total_cost_usd = 5.00
        result = eg.check_quota(agent_name="bot", category="api_call", estimated_cost=1.00)
        assert result["allowed"] is True

    def test_concurrent_limit(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_quota("bot", "api_call", max_concurrent=2)
        eg.enter_operation("api_call")
        eg.enter_operation("api_call")
        result = eg.check_quota(agent_name="bot", category="api_call")
        assert result["allowed"] is False
        assert "concurrent" in result["reason"].lower()
        eg.exit_operation("api_call")
        result = eg.check_quota(agent_name="bot", category="api_call")
        assert result["allowed"] is True

    def test_daily_quota(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_quota("bot", "transaction", daily_limit=3)
        for _ in range(3):
            eg.record_usage(category="transaction", agent_name="bot")
        result = eg.check_quota(agent_name="bot", category="transaction")
        assert result["allowed"] is False
        assert "daily quota" in result["reason"].lower()

    def test_hourly_quota(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_quota("bot", "email", hourly_limit=2)
        for _ in range(2):
            eg.record_usage(category="email", agent_name="bot")
        result = eg.check_quota(agent_name="bot", category="email")
        assert result["allowed"] is False
        assert "hourly quota" in result["reason"].lower()

    def test_per_action_cost_limit(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_quota("bot", "api_call", max_cost_per_action=0.50)
        result = eg.check_quota(agent_name="bot", category="api_call", estimated_cost=1.00)
        assert result["allowed"] is False
        assert "cost" in result["reason"].lower()

    def test_record_usage(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.record_usage(category="api_call", cost_usd=0.05, tokens=500)
        eg.record_usage(category="api_call", cost_usd=0.10, tokens=1000)
        assert eg._total_cost_usd == pytest.approx(0.15)
        assert eg._total_tokens == 1500

    def test_usage_summary(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.record_usage(category="api_call", cost_usd=0.05, tokens=500)
        eg.record_usage(category="transaction", cost_usd=0.10, tokens=0)
        summary = eg.usage_summary(hours=1)
        assert summary["total_operations"] == 2
        assert summary["total_cost_usd"] == pytest.approx(0.15)
        assert "api_call" in summary["by_category"]

    def test_rate_limit_status(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_rate_limit("api_call", max_per_minute=10, max_per_hour=100, max_per_day=1000)
        eg.check_quota(agent_name="bot", category="api_call")
        status = eg.rate_limit_status("api_call")
        assert status["minute"]["used"] == 1
        assert status["minute"]["limit"] == 10
        assert status["minute"]["remaining"] == 9

    def test_status(self):
        eg = EconomicGuardrails(agent_name="bot", monthly_budget_usd=50.0)
        eg.set_rate_limit("api_call", max_per_minute=30)
        eg.set_quota("bot", "transaction", daily_limit=100)
        status = eg.status()
        assert status["monthly_budget_usd"] == 50.0
        assert "api_call" in status["rate_limits"]
        assert "bot/transaction" in status["quotas"]

    def test_reset(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_rate_limit("api_call", max_per_minute=3)
        for _ in range(3):
            eg.check_quota(category="api_call")
        eg.record_usage(category="api_call", cost_usd=1.0, tokens=100)
        eg.reset()
        assert eg._total_cost_usd == 0.0
        assert eg._total_tokens == 0
        # Rate limiter should be reset too
        result = eg.check_quota(category="api_call")
        assert result["allowed"] is True

    def test_finops_integration(self):
        mock_finops = MagicMock()
        mock_finops.status.return_value = {"used_usd": 45.0}
        eg = EconomicGuardrails(agent_name="bot", monthly_budget_usd=50.0, finops=mock_finops)
        result = eg.check_quota(agent_name="bot", category="api_call", estimated_cost=10.0)
        assert result["allowed"] is False
        assert "budget" in result["reason"].lower()

    def test_unlimited_budget(self):
        eg = EconomicGuardrails(agent_name="bot", monthly_budget_usd=0.0)
        result = eg.check_quota(agent_name="bot", category="api_call", estimated_cost=1000.0)
        assert result["allowed"] is True


# ═════════════════════════════════════════════════════════════════════════════
# RISK HARDENING TESTS — Additional coverage for each risk area
# ═════════════════════════════════════════════════════════════════════════════

from security.action_proxy import GatedHTTPTransport


class TestRisk1_GatedTransport:
    """RISK 1 — Verify HTTP-level enforcement makes bypass impossible."""

    def test_gated_transport_blocks_denied_requests(self):
        gate = _make_gate(blocked_ops=["http.GET"])
        transport = GatedHTTPTransport(agent_name="bot", action_gate=gate)
        with pytest.raises(PermissionError, match="ActionGate denied"):
            transport.request("GET", "https://evil.com/data")

    def test_gated_transport_allows_permitted(self):
        gate = _make_gate()
        # Mock inner transport to avoid real HTTP
        mock_inner = MagicMock()
        mock_inner.request.return_value = MagicMock(
            status_code=200, headers={}, body={"ok": True}
        )
        transport = GatedHTTPTransport(
            agent_name="bot", action_gate=gate, inner_transport=mock_inner
        )
        result = transport.request("GET", "https://api.example.com/status")
        assert result.body == {"ok": True}
        mock_inner.request.assert_called_once()

    def test_gated_transport_stats(self):
        gate = _make_gate(blocked_ops=["http.POST"])
        mock_inner = MagicMock()
        mock_inner.request.return_value = MagicMock(
            status_code=200, headers={}, body="ok"
        )
        transport = GatedHTTPTransport(
            agent_name="bot", action_gate=gate, inner_transport=mock_inner
        )
        transport.request("GET", "https://a.com")
        try:
            transport.request("POST", "https://a.com")
        except PermissionError:
            pass
        assert transport.stats["total"] == 2
        assert transport.stats["blocked"] == 1

    def test_gated_transport_economic_guardrails_block(self):
        gate = _make_gate()
        mock_guardrails = MagicMock()
        mock_guardrails.check_quota.return_value = {"allowed": False, "reason": "over budget"}
        transport = GatedHTTPTransport(
            agent_name="bot", action_gate=gate, guardrails=mock_guardrails
        )
        with pytest.raises(PermissionError, match="Economic guardrail"):
            transport.request("GET", "https://a.com")


class TestRisk2_HumanGovernance:
    """RISK 2 — Emergency disable + policy hotswap."""

    def test_emergency_disable(self):
        hoc = HumanOverrideController(agent_name="bot")
        mock_ks = MagicMock()
        mock_ks.emergency_stop.return_value = {"status": "stopped"}
        mock_gate = MagicMock()
        hoc.register_kill_switch(mock_ks)
        hoc.register_action_gate(mock_gate)

        # Create a pending approval to verify it gets cancelled
        hoc.request_approval("pending action")
        assert len(hoc.pending_approvals()) == 1

        result = hoc.emergency_disable(operator="admin", reason="breach detected")
        assert result["approvals_cancelled"] == 1
        assert result.get("gate_disabled") is True
        mock_ks.emergency_stop.assert_called_once()
        mock_gate.disable.assert_called_once()
        assert len(hoc.pending_approvals()) == 0

    def test_policy_hotswap_rules(self):
        hoc = HumanOverrideController(agent_name="bot")
        mock_guardrails = MagicMock()
        hoc.register_guardrails(mock_guardrails)
        result = hoc.policy_hotswap(
            {"rules": {"max_transaction_usd": 200}},
            operator="admin",
        )
        assert result["status"] == "applied"
        assert "rules" in result["applied"]
        mock_guardrails.update_rules.assert_called_once()

    def test_policy_hotswap_approval_patterns(self):
        hoc = HumanOverrideController(agent_name="bot")
        hoc.require_approval("old_pattern")
        assert hoc.needs_approval("old_pattern") is True

        hoc.policy_hotswap(
            {"approval_patterns": ["new_pattern", "another"]},
            operator="admin",
        )
        assert hoc.needs_approval("old_pattern") is False
        assert hoc.needs_approval("new_pattern") is True
        assert hoc.needs_approval("another") is True

    def test_policy_hotswap_no_redeploy(self):
        """Verify policy changes take effect immediately without redeploy."""
        hoc = HumanOverrideController(agent_name="bot")
        mock_panel = MagicMock()
        hoc.register_control_panel(mock_panel)
        result = hoc.policy_hotswap(
            {"budget_usd": 100, "rate_limits": {"api": 50}},
            operator="admin",
        )
        assert "config" in result["applied"]
        mock_panel.update_config.assert_called_once()


class TestRisk3_DecisionGradeObs:
    """RISK 3 — Decision-grade observability."""

    def test_retry_tracking(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_retry("api_call", attempt=1, max_attempts=3, error="timeout")
        mon.record_retry("api_call", attempt=2, max_attempts=3, error="timeout")
        mon.record_retry("api_call", attempt=3, max_attempts=3, outcome="succeeded")
        timeline = mon.activity_timeline(source="retry")
        assert len(timeline) == 3

    def test_retry_summary(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_retry("api_call", 1, 3, error="err")
        mon.record_retry("api_call", 2, 3, error="err")
        mon.record_retry("api_call", 3, 3, outcome="exhausted")
        mon.record_retry("db_write", 1, 2, error="err")
        summary = mon.retry_summary()
        assert summary["total_retries"] == 4
        assert summary["by_action"]["api_call"]["exhausted"] == 1

    def test_actions_taken_report(self):
        mon = UnifiedMonitor(agent_name="bot")
        mock_proxy = MagicMock()
        mock_proxy.history.return_value = [
            {"action": "api.GET:/orders", "category": "api_call",
             "allowed": True, "success": True, "duration": 0.5, "ts": time.time()},
        ]
        mon.register_action_proxy(mock_proxy)
        mon.record_event("action", "manual_action")
        actions = mon.actions_taken()
        assert len(actions) >= 2

    def test_full_decision_context(self):
        mon = UnifiedMonitor(agent_name="bot")
        mon.record_decision(
            "d1", "refund $500", "allowed",
            reason="within daily limit",
            context={"customer_id": 123, "amount": 500},
            impact="high",
            reversible=True,
        )
        decisions = mon.decision_log()
        assert decisions[0]["impact"] == "high"
        assert decisions[0]["reason"] == "within daily limit"


class TestRisk4_PatchVerification:
    """RISK 4 — Patch verification + staged rollout."""

    def _make_channel(self, tmpdir):
        vm = VersionManager(agent_name="bot", data_dir=tmpdir)
        vm.register_version("1.0.0", ["Initial release"], {"name": "bot"})
        return UpdateChannel(
            agent_name="bot", version_manager=vm,
            data_dir=tmpdir, auto_apply_security=False,
        ), vm

    def test_verify_update_passes(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "bugfix", ["Fix crash"])
        result = ch.verify_update("1.1.0")
        assert result["all_passed"] is True
        assert result["status"] == "verified"

    def test_verify_update_custom_check(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "feature", ["New feature"])
        result = ch.verify_update(
            "1.1.0",
            verify_fn=lambda rec: (False, "Fails security audit"),
        )
        assert result["all_passed"] is False

    def test_staged_rollout_success(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "bugfix", ["Fix"])
        result = ch.apply_staged(
            "1.1.0",
            pre_check_fn=lambda: (True, "ok"),
            post_check_fn=lambda: (True, "healthy"),
        )
        assert result["status"] == "applied"
        assert result["staged"] is True
        assert vm.current_version == "1.1.0"

    def test_staged_rollout_post_check_failure_triggers_rollback(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "bugfix", ["Fix"],
                          migration_fn=lambda s: {**s, "v": "1.1"})
        result = ch.apply_staged(
            "1.1.0",
            post_check_fn=lambda: (False, "Health check failed"),
        )
        assert result["status"] == "rolled_back"
        assert "Health check failed" in result["reason"]

    def test_staged_pre_check_failure_blocks(self, tmp_path):
        ch, vm = self._make_channel(tmp_path)
        ch.publish_update("1.1.0", "bugfix", ["Fix"])
        result = ch.apply_staged(
            "1.1.0",
            pre_check_fn=lambda: (False, "Not ready"),
        )
        assert result["status"] == "pre_check_failed"
        assert vm.current_version == "1.0.0"  # Not changed


class TestRisk5_ThrottleAndCostTracking:
    """RISK 5 — Throttling + per-operation cost tracking."""

    def test_throttle_reduces_rate_limits(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_rate_limit("api_call", max_per_minute=10, max_per_hour=100, max_per_day=1000)
        eg.set_throttle(0.5)  # 50%
        assert eg.throttle_rate == 0.5
        status = eg.rate_limit_status("api_call")
        assert status["minute"]["limit"] == 5
        assert status["hour"]["limit"] == 50
        assert status["day"]["limit"] == 500

    def test_throttle_zero_blocks_nearly_all(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.set_rate_limit("api_call", max_per_minute=10)
        eg.set_throttle(0.0)
        # Max should be clamped to 1
        status = eg.rate_limit_status("api_call")
        assert status["minute"]["limit"] == 1

    def test_cost_by_category(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.record_usage(category="api_call", cost_usd=0.10)
        eg.record_usage(category="api_call", cost_usd=0.20)
        eg.record_usage(category="transaction", cost_usd=0.50)
        costs = eg.cost_by_category(hours=1)
        assert costs["api_call"] == pytest.approx(0.30)
        assert costs["transaction"] == pytest.approx(0.50)

    def test_cost_by_agent(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.record_usage(category="api_call", agent_name="bot1", cost_usd=0.10)
        eg.record_usage(category="api_call", agent_name="bot2", cost_usd=0.30)
        costs = eg.cost_by_agent(hours=1)
        assert costs["bot1"] == pytest.approx(0.10)
        assert costs["bot2"] == pytest.approx(0.30)

    def test_top_cost_operations(self):
        eg = EconomicGuardrails(agent_name="bot")
        eg.record_usage(category="cheap", cost_usd=0.01)
        eg.record_usage(category="expensive", cost_usd=5.00)
        eg.record_usage(category="medium", cost_usd=0.50)
        top = eg.top_cost_operations(limit=2)
        assert len(top) == 2
        assert top[0]["cost_usd"] == 5.0
        assert top[0]["category"] == "expensive"


# ═════════════════════════════════════════════════════════════════════════════
# GOVERNANCE RUNTIME — Full integration wiring tests
# ═════════════════════════════════════════════════════════════════════════════

from core.governance_runtime import GovernanceRuntime, GovernanceConfig


class TestGovernanceRuntime:
    """Test the unified governance compositor wires everything correctly."""

    def test_creates_all_components(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="test_bot"))
        assert gov.agent_name == "test_bot"
        assert gov.guardrail_controller is not None
        assert gov.action_gate is not None
        assert gov.economic_guardrails is not None
        assert gov.action_proxy is not None
        assert gov.gated_transport is not None
        assert gov.kill_switch is not None
        assert gov.control_panel is not None
        assert gov.human_override is not None
        assert gov.monitor is not None
        assert gov.update_channel is not None
        assert gov.version_manager is not None

    def test_status_returns_all_fields(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        status = gov.status()
        assert "agent" in status
        assert "kill_switch" in status
        assert "paused" in status
        assert "budget_remaining" in status
        assert "actions_blocked" in status
        assert "pending_approvals" in status

    def test_dashboard_returns_all_sections(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        dash = gov.dashboard()
        assert "governance" in dash
        assert "monitor" in dash
        assert "updates" in dash
        assert "kill_switch" in dash["governance"]
        assert "human_override" in dash["governance"]
        assert "economic" in dash["governance"]
        assert "action_proxy" in dash["governance"]
        assert "transport" in dash["governance"]
        assert "control_panel" in dash["governance"]

    def test_pause_and_resume(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        result = gov.pause(operator="admin", reason="maintenance")
        assert result.get("status") == "paused" or result.get("action") == "pause"
        result = gov.resume(operator="admin")
        assert result.get("status") == "resumed" or result.get("action") == "resume"

    def test_emergency_stop(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        result = gov.emergency_stop(operator="admin", reason="breach")
        assert "emergency_disable" in str(result.get("action", "")) or "approvals_cancelled" in result

    def test_policy_update(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        result = gov.policy_update(
            {"approval_patterns": ["delete_customer", "bulk_email"]},
            operator="admin",
        )
        assert result["status"] == "applied"
        assert gov.human_override.needs_approval("delete_customer") is True

    def test_throttle(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        gov.economic_guardrails.set_rate_limit("api_call", max_per_minute=100)
        gov.throttle(rate=0.5, operator="admin")
        assert gov.economic_guardrails.throttle_rate == 0.5

    def test_health_check(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        health = gov.health()
        assert isinstance(health, dict)

    def test_config_from_env(self):
        config = GovernanceConfig.from_env(agent_name="env_bot")
        assert config.agent_name == "env_bot"
        assert config.monthly_budget_usd > 0

    def test_get_transport_returns_gated(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        transport = gov.get_transport()
        assert hasattr(transport, "request")
        assert hasattr(transport, "stats")

    def test_attach_to_agent(self):
        from agents.base_agent import BaseAgent
        agent = BaseAgent(name="test_agent", role="worker", tools=["search"])
        gov = GovernanceRuntime(GovernanceConfig(agent_name="test_agent"))
        gov.attach_to_agent(agent)
        assert agent._governance is gov

    def test_approval_required_config(self):
        gov = GovernanceRuntime(GovernanceConfig(
            agent_name="bot",
            approval_required=["refund_over_100", "bulk_email"],
        ))
        assert gov.human_override.needs_approval("refund_over_100") is True
        assert gov.human_override.needs_approval("bulk_email") is True
        assert gov.human_override.needs_approval("read_data") is False

    def test_restricted_operations_config(self):
        gov = GovernanceRuntime(GovernanceConfig(
            agent_name="bot",
            restricted_operations=["delete_customer"],
        ))
        gate = gov.action_gate
        proxy = ActionProxy(agent_name="bot", action_gate=gate)
        result = proxy.execute("delete_customer")
        assert result.allowed is False

    def test_repr(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        r = repr(gov)
        assert "GovernanceRuntime" in r
        assert "bot" in r

    def test_agent_execute_blocked_when_paused(self):
        from agents.base_agent import BaseAgent
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        agent = BaseAgent(name="bot", role="worker", tools=["search"])
        gov.attach_to_agent(agent)
        gov.pause(operator="admin")
        with pytest.raises(RuntimeError, match="paused"):
            agent.execute_task("do something")

    def test_tool_call_requires_and_consumes_manual_approval(self):
        from tools.tool_manager import PermissionDenied, ToolManager

        gov = GovernanceRuntime(GovernanceConfig(
            agent_name="bot",
            approval_required=["tool.custom_write"],
        ))
        tool_manager = ToolManager()
        tool_manager.register("custom_write", lambda: "ok")
        tool_manager.register_governance(gov)

        with pytest.raises(PermissionDenied, match="approval"):
            tool_manager.call("custom_write", agent_name="bot", agent_level=5)

        pending = gov.human_override.pending_approvals()
        assert len(pending) == 1
        gov.human_override.approve(pending[0]["id"], operator="admin")

        assert tool_manager.call("custom_write", agent_name="bot", agent_level=5) == "ok"

    def test_disable_integrations(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        integrator = MagicMock()
        integrator.list_integrations.return_value = [
            {"name": "shopify", "connected": True},
            {"name": "stripe", "connected": True},
        ]
        gov.attach_integrator(integrator)

        result = gov.disable_integrations(operator="admin", reason="maintenance")
        assert result["status"] == "integrations_disabled"
        assert result["disconnected"] == 2

    def test_control_plane_status_includes_current_tasks(self):
        gov = GovernanceRuntime(GovernanceConfig(agent_name="bot"))
        scheduler = MagicMock()
        scheduler.stats.return_value = {"by_status": {"running": 1, "pending": 2}, "dlq": 0}
        scheduler.list_jobs.return_value = [
            {"job_id": "j1", "name": "nightly-sync", "status": "running", "agent_name": "bot", "mode": "immediate", "started_at": 123.0, "attempts": 1},
        ]
        gov.attach_scheduler(scheduler)

        control = gov.control_plane_status()
        assert control["status_indicators"]["running_jobs"] == 1
        assert any(item["name"] == "nightly-sync" for item in control["current_tasks"])


# ═════════════════════════════════════════════════════════════════════════════
# GOVERNANCE API — Endpoint tests using FastAPI TestClient
# ═════════════════════════════════════════════════════════════════════════════

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import governance_api directly via importlib.util to avoid the parent-level
# api/__init__.py which tries to import the full server module.
import importlib.util as _ilu
_gov_spec = _ilu.spec_from_file_location(
    "governance_api",
    str(ROOT / "api" / "governance_api.py"),
)
_gov_mod = _ilu.module_from_spec(_gov_spec)
sys.modules["governance_api"] = _gov_mod  # Register so Pydantic can resolve types
_gov_spec.loader.exec_module(_gov_mod)
governance_router = _gov_mod.router


def _make_test_app():
    """Create a minimal FastAPI app with governance wired in."""
    test_app = FastAPI()
    test_app.include_router(governance_router)
    gov = GovernanceRuntime(GovernanceConfig(agent_name="api_bot"))
    test_app.state.governance = gov
    return test_app, gov


class TestGovernanceAPI:
    """Test all governance REST endpoints."""

    def test_status_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.get("/api/governance/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"] == "api_bot"
        assert "kill_switch" in data

    def test_dashboard_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.get("/api/governance/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "governance" in data
        assert "monitor" in data

    def test_control_plane_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.get("/api/governance/control-plane")
        assert resp.status_code == 200
        data = resp.json()
        assert "controls" in data
        assert "status_indicators" in data

    def test_health_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.get("/api/governance/health")
        assert resp.status_code == 200

    def test_pause_resume_endpoints(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/governance/pause", json={"operator": "admin", "reason": "test"})
        assert resp.status_code == 200

        resp = client.post("/api/governance/resume", json={"operator": "admin"})
        assert resp.status_code == 200

    def test_emergency_stop_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/governance/emergency-stop", json={"operator": "admin", "reason": "breach"})
        assert resp.status_code == 200

    def test_safe_shutdown_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/governance/safe-shutdown", json={"operator": "admin"})
        assert resp.status_code == 200

    def test_disable_integrations_endpoint(self):
        app, gov = _make_test_app()
        integrator = MagicMock()
        integrator.list_integrations.return_value = [{"name": "shopify", "connected": True}]
        gov.attach_integrator(integrator)
        client = TestClient(app)
        resp = client.post(
            "/api/governance/disable-integrations",
            json={"operator": "admin", "reason": "maintenance"},
        )
        assert resp.status_code == 200
        assert resp.json()["disconnected"] == 1

    def test_throttle_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/governance/throttle", json={"rate": 0.5, "operator": "admin"})
        assert resp.status_code == 200
        assert resp.json()["rate"] == "0.5"

    def test_policy_endpoint(self):
        app, gov = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/governance/policy", json={
            "policy": {"approval_patterns": ["delete_all"]},
            "operator": "admin",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "applied"
        assert gov.human_override.needs_approval("delete_all") is True

    def test_approvals_endpoint(self):
        app, gov = _make_test_app()
        client = TestClient(app)
        gov.human_override.request_approval("test_action")
        resp = client.get("/api/governance/approvals")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_decisions_endpoint(self):
        app, gov = _make_test_app()
        gov.monitor.record_decision("d1", "refund", "allowed")
        client = TestClient(app)
        resp = client.get("/api/governance/decisions")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_activity_and_current_tasks_endpoints(self):
        app, gov = _make_test_app()
        scheduler = MagicMock()
        scheduler.stats.return_value = {"by_status": {"running": 1, "pending": 0}, "dlq": 0}
        scheduler.list_jobs.return_value = [
            {"job_id": "job-1", "name": "daily-report", "status": "running", "agent_name": "api_bot", "mode": "immediate", "started_at": 1.0, "attempts": 1},
        ]
        gov.attach_scheduler(scheduler)
        gov.monitor.record_event("control", "operator viewed dashboard")
        client = TestClient(app)

        activity = client.get("/api/governance/activity")
        assert activity.status_code == 200
        assert len(activity.json()) >= 1

        current = client.get("/api/governance/current-tasks")
        assert current.status_code == 200
        assert current.json()[0]["name"] == "daily-report"

    def test_resources_integrations_and_status_indicators_endpoints(self):
        app, gov = _make_test_app()
        integrator = MagicMock()
        integrator.list_integrations.return_value = [{"name": "shopify", "connected": True, "type": "api"}]
        gov.attach_integrator(integrator)
        client = TestClient(app)

        resources = client.get("/api/governance/resources")
        assert resources.status_code == 200
        assert "api_calls" in resources.json()

        integrations = client.get("/api/governance/integrations")
        assert integrations.status_code == 200
        assert integrations.json()["services"]["shopify"]["status"] == "healthy"

        indicators = client.get("/api/governance/status-indicators")
        assert indicators.status_code == 200
        assert "integration_status" in indicators.json()

    def test_actions_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.get("/api/governance/actions")
        assert resp.status_code == 200

    def test_errors_endpoint(self):
        app, _ = _make_test_app()
        client = TestClient(app)
        resp = client.get("/api/governance/errors")
        assert resp.status_code == 200

    def test_costs_endpoint(self):
        app, gov = _make_test_app()
        gov.economic_guardrails.record_usage(category="api_call", cost_usd=0.05)
        client = TestClient(app)
        resp = client.get("/api/governance/costs?hours=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "by_category" in data
        assert "status" in data

    def test_retries_endpoint(self):
        app, gov = _make_test_app()
        gov.monitor.record_retry("api_call", 1, 3, error="timeout")
        client = TestClient(app)
        resp = client.get("/api/governance/retries")
        assert resp.status_code == 200
        assert resp.json()["total_retries"] >= 1

    def test_updates_endpoint(self):
        app, gov = _make_test_app()
        gov.update_channel.publish_update(
            version="1.0.1",
            update_type="bugfix",
            changes=["Fix scheduler telemetry"],
        )
        client = TestClient(app)
        resp = client.get("/api/governance/updates")
        assert resp.status_code == 200

        verify = client.get("/api/governance/updates/verify/1.0.1")
        assert verify.status_code == 200
        assert verify.json()["status"] in {"verified", "failed"}

    def test_updates_rollback_endpoint(self):
        app, gov = _make_test_app()
        gov.version_manager.register_version(
            version="1.0.0",
            changes=["Initial release"],
            spec_snapshot={"feature": "base"},
        )
        gov.update_channel.publish_update(
            version="1.0.1",
            update_type="bugfix",
            changes=["Fix bug"],
            migration_fn=lambda spec: {**spec, "feature": "patched"},
        )
        gov.update_channel.apply_update("1.0.1")
        client = TestClient(app)
        resp = client.post("/api/governance/updates/rollback", json={})
        assert resp.status_code == 200
        assert resp.json()["status"] in {"rolled_back", "error"}

    def test_503_when_no_governance(self):
        bare_app = FastAPI()
        bare_app.include_router(governance_router)
        client = TestClient(bare_app, raise_server_exceptions=False)
        resp = client.get("/api/governance/status")
        assert resp.status_code == 503
