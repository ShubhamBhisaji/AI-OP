"""test_gap_closures.py — Tests for GAP 1–5 closure components.

GAP 1: Integration Wizard        → integrator/integration_wizard.py
GAP 2: Autonomous Goal Loop      → core/autonomous_loop.py
GAP 3: Persistent Memory Engine  → memory/persistent_memory_engine.py
GAP 4: Guardrail Controller      → security/guardrail_controller.py
GAP 5: Agent Control Panel       → core/agent_control_panel.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Fix import path ──────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 1 — Integration Wizard
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrationWizard:
    """Tests for integrator/integration_wizard.py."""

    def test_wizard_run_with_mock_manifest(self, tmp_path):
        """Wizard runs end-to-end with a mock manifest and no real connections."""
        from integrator.integration_wizard import IntegrationWizard, WizardReport

        manifest = MagicMock()
        manifest.name = "test_agent"
        manifest.integrations = ["website"]

        wizard = IntegrationWizard(manifest=manifest, env_path=tmp_path / ".env", auto=True, silent=True)

        # Pre-populate env so validation passes
        wizard._env["WEBSITE_URL"] = "https://example.com"

        report = wizard.run()
        assert isinstance(report, WizardReport)
        assert report.agent_name == "test_agent"
        assert len(report.integrations) == 1

    def test_wizard_no_integrations(self, tmp_path):
        """Wizard handles empty integration list gracefully."""
        from integrator.integration_wizard import IntegrationWizard

        manifest = MagicMock()
        manifest.name = "empty_agent"
        manifest.integrations = []

        wizard = IntegrationWizard(manifest=manifest, env_path=tmp_path / ".env", auto=True, silent=True)
        report = wizard.run()
        assert report.agent_name == "empty_agent"
        assert len(report.integrations) == 0

    def test_wizard_credential_validation_fails(self, tmp_path):
        """Wizard correctly flags missing required credentials."""
        from integrator.integration_wizard import IntegrationWizard

        manifest = MagicMock()
        manifest.name = "missing_creds"
        manifest.integrations = ["api"]

        wizard = IntegrationWizard(manifest=manifest, env_path=tmp_path / ".env", auto=True, silent=True)
        # Don't set required API_BASE_URL
        report = wizard.run()
        assert len(report.integrations) == 1
        assert report.integrations[0].status == "failed"
        assert "missing" in report.integrations[0].error.lower() or "required" in report.integrations[0].error.lower()

    def test_wizard_report_summary(self, tmp_path):
        """WizardReport.summary() produces readable output."""
        from integrator.integration_wizard import WizardReport, IntegrationStatus

        report = WizardReport(agent_name="test")
        report.integrations = [
            IntegrationStatus(name="api", status="connected", endpoints=["/v1"]),
            IntegrationStatus(name="email", status="failed", error="Auth failed"),
        ]
        summary = report.summary()
        assert "test" in summary
        assert "1/2" in summary

    def test_wizard_env_persistence(self, tmp_path):
        """Wizard persists credentials to .env file."""
        from integrator.integration_wizard import IntegrationWizard

        manifest = MagicMock()
        manifest.name = "persist_test"
        manifest.integrations = []

        env_path = tmp_path / ".env"
        wizard = IntegrationWizard(manifest=manifest, env_path=env_path, auto=True, silent=True)
        wizard._env["TEST_KEY"] = "test_value"
        wizard._save_env()

        assert env_path.exists()
        content = env_path.read_text()
        assert "TEST_KEY=test_value" in content

    def test_wizard_retry_on_connection_failure(self, tmp_path):
        """Wizard retries failed connections up to max_retries."""
        from integrator.integration_wizard import IntegrationWizard

        manifest = MagicMock()
        manifest.name = "retry_agent"
        manifest.integrations = ["analytics"]

        wizard = IntegrationWizard(
            manifest=manifest, env_path=tmp_path / ".env",
            auto=True, silent=True, max_retries=2,
        )
        wizard._env["ANALYTICS_API_KEY"] = "test-key-123"

        report = wizard.run()
        # Should have attempted but the integration itself may succeed or fail
        # depending on connector availability — key point is it doesn't crash
        assert len(report.integrations) == 1
        assert report.integrations[0].name == "analytics"

    def test_wizard_retry_failed_only(self, tmp_path):
        """Wizard retry_failed_only=True re-runs only previously failed integrations."""
        from integrator.integration_wizard import IntegrationWizard

        manifest = MagicMock()
        manifest.name = "retry_only"
        manifest.integrations = ["website", "api"]

        # Create a fake prior state with one failed integration
        state_path = tmp_path / "integration_state.json"
        state_path.write_text(json.dumps({
            "integrations": [
                {"name": "website", "status": "connected"},
                {"name": "api", "status": "failed"},
            ]
        }))

        wizard = IntegrationWizard(
            manifest=manifest, env_path=tmp_path / ".env",
            auto=True, silent=True,
        )
        wizard._state_path = state_path
        wizard._env["API_BASE_URL"] = "https://example.com/api"
        wizard._env["API_KEY"] = "test"

        report = wizard.run(retry_failed_only=True)
        # Should only have retried "api", not "website"
        assert len(report.integrations) == 1
        assert report.integrations[0].name == "api"


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 2 — Autonomous Goal Loop
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomousGoalLoop:
    """Tests for core/autonomous_loop.py."""

    def _make_execute_fn(self, return_value="Task completed successfully."):
        return MagicMock(return_value=return_value)

    def _make_goal_manager(self, actions=None):
        gm = MagicMock()
        gm.next_actions = MagicMock(return_value=actions or [])
        gm.start_task = MagicMock(return_value=True)
        gm.complete_task = MagicMock(return_value=True)
        gm.fail_task = MagicMock(return_value=True)
        gm.status_report = MagicMock(return_value={"goals": {"total": 0}})
        return gm

    def test_loop_lifecycle(self):
        """Loop can start, pause, resume, and stop."""
        from core.autonomous_loop import AutonomousGoalLoop, LoopConfig, LoopState

        execute_fn = self._make_execute_fn()
        gm = self._make_goal_manager()
        config = LoopConfig(tick_interval_seconds=0.1, idle_backoff_seconds=0.1)

        loop = AutonomousGoalLoop(
            agent_name="test_agent",
            goal_manager=gm,
            execute_fn=execute_fn,
            config=config,
        )

        assert loop.state == LoopState.IDLE

        loop.start()
        assert loop.state == LoopState.RUNNING

        loop.pause()
        assert loop.state == LoopState.PAUSED

        loop.resume()
        assert loop.state == LoopState.RUNNING

        loop.stop()
        assert loop.state == LoopState.STOPPED

    def test_loop_executes_tasks(self):
        """Loop picks up tasks and executes them."""
        from core.autonomous_loop import AutonomousGoalLoop, LoopConfig

        execute_fn = self._make_execute_fn()
        actions = [
            {"task_id": "t1", "description": "Do something", "context": {}},
        ]
        gm = self._make_goal_manager(actions)
        config = LoopConfig(tick_interval_seconds=0.1, max_runtime_seconds=1)

        loop = AutonomousGoalLoop(
            agent_name="test_agent",
            goal_manager=gm,
            execute_fn=execute_fn,
            config=config,
        )
        loop.start()
        time.sleep(0.5)
        loop.stop()

        assert gm.start_task.called
        assert execute_fn.called

    def test_loop_status_report(self):
        """Loop returns a structured status report."""
        from core.autonomous_loop import AutonomousGoalLoop, LoopConfig

        execute_fn = self._make_execute_fn()
        gm = self._make_goal_manager()
        loop = AutonomousGoalLoop(
            agent_name="test_agent",
            goal_manager=gm,
            execute_fn=execute_fn,
            config=LoopConfig(),
        )

        status = loop.status()
        assert "agent_name" in status or "agent" in status
        assert "state" in status

    def test_loop_error_budget(self):
        """Loop stops after exceeding consecutive failure limit."""
        from core.autonomous_loop import AutonomousGoalLoop, LoopConfig, LoopState

        execute_fn = MagicMock(side_effect=RuntimeError("boom"))
        actions = [{"task_id": "t1", "description": "Fail", "context": {}}]
        gm = self._make_goal_manager(actions)
        config = LoopConfig(
            tick_interval_seconds=0.05,
            idle_backoff_seconds=0.05,
            max_consecutive_failures=2,
        )

        loop = AutonomousGoalLoop(
            agent_name="test_agent",
            goal_manager=gm,
            execute_fn=execute_fn,
            config=config,
        )
        loop.start()
        time.sleep(1)

        assert loop.state in (LoopState.ERROR, LoopState.STOPPED, LoopState.PAUSED)
        loop.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 3 — Persistent Memory Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersistentMemoryEngine:
    """Tests for memory/persistent_memory_engine.py."""

    def test_decision_journal(self, tmp_path):
        """Decisions are logged and queryable."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        did = engine.log_decision(
            action="approve_refund",
            reason="VIP customer, small amount",
            outcome="success",
            context={"amount": 25.0},
        )

        decisions = engine.get_decisions()
        assert len(decisions) == 1
        assert decisions[0]["action"] == "approve_refund"
        assert decisions[0]["id"] == did

    def test_decision_outcome_update(self, tmp_path):
        """Decision outcomes can be updated."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        did = engine.log_decision("test", "because", outcome="pending")
        assert engine.update_decision_outcome(did, "success")

        decisions = engine.get_decisions()
        assert decisions[0]["outcome"] == "success"

    def test_work_history(self, tmp_path):
        """Work entries are recorded and filterable."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        engine.record_work("Task A", "Done", success=True, duration_seconds=1.5)
        engine.record_work("Task B", "Failed", success=False, duration_seconds=0.5)

        all_work = engine.get_work_history()
        assert len(all_work) == 2

        successes = engine.get_work_history(success=True)
        assert len(successes) == 1

        stats = engine.work_stats()
        assert stats["total_tasks"] == 2
        assert stats["success_rate"] == 0.5

    def test_state_snapshots(self, tmp_path):
        """State snapshots are saved and retrievable."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path, max_snapshots=3)
        engine.snapshot_state({"orders": 10})
        engine.snapshot_state({"orders": 15})

        latest = engine.get_latest_snapshot()
        assert latest["state"]["orders"] == 15

        snaps = engine.get_snapshots()
        assert len(snaps) == 2

    def test_snapshot_pruning(self, tmp_path):
        """Old snapshots are pruned when over limit."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path, max_snapshots=2)
        engine.snapshot_state({"v": 1})
        engine.snapshot_state({"v": 2})
        engine.snapshot_state({"v": 3})

        snaps = engine.get_snapshots()
        assert len(snaps) == 2
        assert snaps[-1]["state"]["v"] == 3

    def test_learned_patterns(self, tmp_path):
        """Patterns are learned, applied, and searchable."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        pid = engine.learn_pattern(
            name="fast_refund",
            description="Auto-refund VIP orders under $50",
            confidence=0.8,
        )

        patterns = engine.get_patterns(min_confidence=0.5)
        assert len(patterns) == 1
        assert patterns[0]["name"] == "fast_refund"

        # Apply pattern — confidence should increase
        result = engine.apply_pattern("fast_refund")
        assert result is not None
        assert result.times_applied == 1
        assert result.confidence > 0.8

    def test_pattern_forget(self, tmp_path):
        """Patterns can be forgotten."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        engine.learn_pattern("temp", "Temporary pattern")
        assert engine.forget_pattern("temp")
        assert len(engine.get_patterns()) == 0

    def test_interaction_log(self, tmp_path):
        """Interactions are logged and retrievable."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        engine.log_interaction("user", "Hello")
        engine.log_interaction("agent", "Hi! How can I help?")

        interactions = engine.get_interactions()
        assert len(interactions) == 2
        assert interactions[0]["role"] == "user"

    def test_search_history(self, tmp_path):
        """Cross-type search returns matching entries."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        engine.log_decision("approve_refund", "VIP customer")
        engine.record_work("Process refund", "Done", success=True)
        engine.learn_pattern("refund_fast", "Quick refund for VIPs")
        engine.log_interaction("user", "Can I get a refund?")

        results = engine.search_history("refund")
        assert len(results) >= 3  # decision + work + pattern + interaction

    def test_persistence_across_instances(self, tmp_path):
        """Data survives engine recreation (simulates restart)."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine1 = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        engine1.log_decision("action1", "reason1")
        engine1.record_work("task1", "result1", success=True)
        engine1.learn_pattern("p1", "Pattern 1")
        engine1.snapshot_state({"x": 1})
        engine1.log_interaction("user", "Hello")

        # Create new instance (simulates restart)
        engine2 = PersistentMemoryEngine("test_agent", data_dir=tmp_path)
        assert len(engine2.get_decisions()) == 1
        assert len(engine2.get_work_history()) == 1
        assert len(engine2.get_patterns()) == 1
        assert engine2.get_latest_snapshot()["state"]["x"] == 1
        assert len(engine2.get_interactions()) == 1

    def test_export_import(self, tmp_path):
        """Data can be exported and imported."""
        from memory.persistent_memory_engine import PersistentMemoryEngine

        engine1 = PersistentMemoryEngine("agent_a", data_dir=tmp_path)
        engine1.log_decision("d1", "r1")
        engine1.learn_pattern("p1", "Pattern")
        data = engine1.export_all()

        engine2 = PersistentMemoryEngine("agent_b", data_dir=tmp_path)
        engine2.import_data(data)
        assert len(engine2.get_decisions()) == 1
        assert len(engine2.get_patterns()) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 4 — Guardrail Controller
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuardrailController:
    """Tests for security/guardrail_controller.py."""

    def test_basic_allow(self):
        """Action with no restrictions is allowed."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        gc = GuardrailController(rules=GuardrailRules())
        verdict = gc.authorize("bot", "read_orders")
        assert verdict.allowed

    def test_restricted_operation_blocked(self):
        """Restricted operations are denied."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(restricted_operations=["delete_customer", "drop_table"])
        gc = GuardrailController(rules=rules)

        verdict = gc.authorize("bot", "delete_customer_record")
        assert not verdict.allowed
        assert "restricted" in verdict.reason.lower()

    def test_transaction_limit_enforced(self):
        """Transactions above the limit are blocked."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(max_transaction=100.0)
        gc = GuardrailController(rules=rules)

        # Under limit — allowed
        v1 = gc.authorize("bot", "process_refund", context={"amount": 50})
        assert v1.allowed

        # Over limit — denied
        v2 = gc.authorize("bot", "process_refund", context={"amount": 150})
        assert not v2.allowed
        assert "exceeds" in v2.reason.lower()

    def test_api_whitelist(self):
        """Only whitelisted APIs are allowed."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(allowed_apis=["shopify", "stripe"])
        gc = GuardrailController(rules=rules)

        v1 = gc.authorize("bot", "call_api", context={"api": "shopify"})
        assert v1.allowed

        v2 = gc.authorize("bot", "call_api", context={"api": "unknown_service"})
        assert not v2.allowed

    def test_api_blocklist(self):
        """Blocked APIs are denied even without a whitelist."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(blocked_apis=["dangerous_api"])
        gc = GuardrailController(rules=rules)

        v = gc.authorize("bot", "call", context={"api": "dangerous_api"})
        assert not v.allowed

    def test_rate_limit(self):
        """Actions are blocked after rate limit is exceeded."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(rate_limits={"send_email": 2})
        gc = GuardrailController(rules=rules)

        # First two should be allowed
        gc.record_execution("send_email")
        gc.record_execution("send_email")

        v = gc.authorize("bot", "send_email")
        assert not v.allowed
        assert "rate" in v.reason.lower() or "limit" in v.reason.lower()

    def test_data_scope_enforcement(self):
        """Data access scope is enforced."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(data_access_scope="orders_only")
        gc = GuardrailController(rules=rules)

        v1 = gc.authorize("bot", "query", context={"data_scope": "orders_only"})
        assert v1.allowed

        v2 = gc.authorize("bot", "query", context={"data_scope": "full"})
        assert not v2.allowed

    def test_human_approval_trigger(self):
        """Escalation triggers flag actions for human approval."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(human_approval_triggers=["refund_over_100"])
        gc = GuardrailController(rules=rules)

        v = gc.authorize("bot", "refund_over_100_process")
        assert v.requires_human_approval

    def test_budget_enforcement(self):
        """Budget limits are enforced."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(max_budget_usd=10.0)
        gc = GuardrailController(rules=rules)
        gc._spent_usd = 9.0

        v = gc.authorize("bot", "expensive_op", context={"cost_usd": 5.0})
        assert not v.allowed
        assert "budget" in v.reason.lower()

    def test_runtime_enforcement(self):
        """Runtime limits are enforced."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(max_runtime_seconds=1)
        gc = GuardrailController(rules=rules)
        gc._started_at = time.time() - 5  # Simulate 5 seconds elapsed

        v = gc.authorize("bot", "action")
        assert not v.allowed
        assert "runtime" in v.reason.lower()

    def test_write_approval(self):
        """Write actions require approval when configured."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        rules = GuardrailRules(require_approval_for_write=True)
        gc = GuardrailController(rules=rules)

        v = gc.authorize("bot", "delete_record")
        assert v.requires_human_approval

    def test_rule_update(self):
        """Rules can be updated dynamically."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        gc = GuardrailController(rules=GuardrailRules(max_transaction=100))
        gc.update_rules({"max_transaction": 500})
        assert gc.rules.max_transaction == 500

    def test_from_manifest(self):
        """Controller builds correctly from a manifest."""
        from security.guardrail_controller import GuardrailController

        manifest = MagicMock()
        manifest.permissions = {
            "refund_limit": 200,
            "allowed_apis": ["shopify"],
            "rate_limits": {"refund": 10},
            "restricted_commands": ["drop_table"],
            "escalation_triggers": ["large_refund"],
            "data_access": "orders_only",
        }
        manifest.runtime = {"permission_level": 3}

        gc = GuardrailController.from_manifest(manifest)
        assert gc.rules.max_transaction == 200.0
        assert gc.rules.allowed_apis == ["shopify"]
        assert gc.rules.permission_level == 3

    def test_audit_logging(self):
        """Audit logger is called on authorization checks."""
        from security.guardrail_controller import GuardrailController, GuardrailRules

        audit = MagicMock()
        gc = GuardrailController(rules=GuardrailRules(), audit_logger=audit)
        gc.authorize("bot", "test_action")
        assert audit.log.called


# ═══════════════════════════════════════════════════════════════════════════════
# GAP 5 — Agent Control Panel
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentControlPanel:
    """Tests for core/agent_control_panel.py."""

    def _make_panel(self, tmp_path):
        from core.agent_control_panel import AgentControlPanel
        return AgentControlPanel("test_agent", log_dir=tmp_path)

    def test_pause_resume_stop(self, tmp_path):
        """Panel can pause, resume, and stop an agent loop."""
        panel = self._make_panel(tmp_path)

        loop = MagicMock()
        loop.state = MagicMock()
        loop.state.value = "running"
        panel.register_loop(loop)

        result = panel.pause(operator="admin")
        assert result["status"] == "paused"
        assert loop.pause.called

        result = panel.resume(operator="admin")
        assert result["status"] == "running"
        assert loop.resume.called

        result = panel.stop(operator="admin")
        assert result["status"] == "stopped"
        assert loop.stop.called

    def test_pause_without_loop(self, tmp_path):
        """Panel returns error when no loop is registered."""
        panel = self._make_panel(tmp_path)
        result = panel.pause()
        assert result["status"] == "error"

    def test_inspect(self, tmp_path):
        """Panel returns inspection data from all registered components."""
        panel = self._make_panel(tmp_path)

        loop = MagicMock()
        loop.status.return_value = {"state": "running", "iterations": 5}
        panel.register_loop(loop)

        gm = MagicMock()
        gm.status_report.return_value = {"goals": {"total": 3}}
        panel.register_goal_manager(gm)

        result = panel.inspect()
        assert result["agent"] == "test_agent"
        assert result["loop"]["state"] == "running"
        assert result["goals"]["goals"]["total"] == 3

    def test_override_decision(self, tmp_path):
        """Panel can override a decision in the memory engine."""
        panel = self._make_panel(tmp_path)

        mem = MagicMock()
        mem.update_decision_outcome = MagicMock(return_value=True)
        mem.get_decisions = MagicMock(return_value=[])
        mem.get_work_history = MagicMock(return_value=[])
        mem.status = MagicMock(return_value={})
        panel.register_memory(mem)

        result = panel.override_decision("d123", "denied", operator="admin", reason="Policy change")
        assert result["status"] == "overridden"
        mem.update_decision_outcome.assert_called_with("d123", "denied")

    def test_review_logs(self, tmp_path):
        """Panel returns control events and audit logs."""
        panel = self._make_panel(tmp_path)
        panel._record_event("pause", "admin")
        panel._record_event("resume", "admin")

        logs = panel.review_logs()
        assert len(logs) >= 2
        assert any(log["action"] == "pause" for log in logs)

    def test_update_config(self, tmp_path):
        """Panel updates guardrail rules at runtime."""
        panel = self._make_panel(tmp_path)

        gc = MagicMock()
        gc.rules = MagicMock()
        gc.rules.to_dict.return_value = {"max_transaction": 500}
        panel.register_guardrails(gc)

        result = panel.update_config({"max_transaction": 500}, operator="admin")
        assert result["status"] == "updated"
        gc.update_rules.assert_called_with({"max_transaction": 500})

    def test_cancel_goal(self, tmp_path):
        """Panel can cancel a goal."""
        panel = self._make_panel(tmp_path)

        gm = MagicMock()
        gm.cancel_goal = MagicMock(return_value=True)
        panel.register_goal_manager(gm)

        result = panel.cancel_goal("g123", operator="admin")
        assert result["status"] == "cancelled"

    def test_dashboard(self, tmp_path):
        """Dashboard returns complete view."""
        panel = self._make_panel(tmp_path)
        dashboard = panel.dashboard()
        assert "agent" in dashboard
        assert "state" in dashboard
        assert "activity" in dashboard
        assert "recent_logs" in dashboard

    def test_event_persistence(self, tmp_path):
        """Control events persist across panel instances."""
        from core.agent_control_panel import AgentControlPanel

        panel1 = AgentControlPanel("test_agent", log_dir=tmp_path)
        panel1._record_event("pause", "admin")
        panel1._record_event("resume", "admin")

        panel2 = AgentControlPanel("test_agent", log_dir=tmp_path)
        assert len(panel2._events) == 2

    def test_agent_state_unregistered(self, tmp_path):
        """Panel returns 'unregistered' when no loop is set."""
        panel = self._make_panel(tmp_path)
        assert panel.agent_state() == "unregistered"
