"""Tests for the GuardrailController (GAP 4)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from security.guardrail_controller import (
    GuardrailController,
    GuardrailRules,
    GuardrailVerdict,
)


@pytest.fixture
def rules():
    return GuardrailRules(
        max_transaction=500.0,
        allowed_apis=["stripe", "supabase", "infobip"],
        blocked_apis=["kubernetes", "aws_lambda"],
        rate_limits={"send_email": 10, "process_refund": 5},
        restricted_operations=["delete_database", "drop_table", "rm_rf"],
        human_approval_triggers=["customer_data_export", "deploy_production"],
        data_access_scope="orders_only",
        max_budget_usd=1000.0,
        max_runtime_seconds=3600,
        permission_level=2,
    )


@pytest.fixture
def controller(rules):
    return GuardrailController(rules=rules)


# ── Basic authorization ──────────────────────────────────────────────────────

class TestBasicAuthorization:
    def test_allow_simple_action(self, controller):
        verdict = controller.authorize("bot", "check_status")
        assert verdict.allowed is True

    def test_deny_restricted_operation(self, controller):
        verdict = controller.authorize("bot", "delete_database")
        assert verdict.allowed is False
        assert "restricted" in verdict.checks_failed[0]

    def test_deny_partial_match_restricted(self, controller):
        verdict = controller.authorize("bot", "rm_rf_all")
        assert verdict.allowed is False


# ── Transaction limits ───────────────────────────────────────────────────────

class TestTransactionLimits:
    def test_allow_within_limit(self, controller):
        verdict = controller.authorize("bot", "process_refund", context={"amount": 200})
        assert verdict.allowed is True

    def test_deny_over_limit(self, controller):
        verdict = controller.authorize("bot", "process_refund", context={"amount": 600})
        assert verdict.allowed is False
        assert "transaction_limit" in verdict.checks_failed[0]

    def test_no_amount_passes(self, controller):
        verdict = controller.authorize("bot", "process_refund")
        assert verdict.allowed is True


# ── API access ───────────────────────────────────────────────────────────────

class TestAPIAccess:
    def test_allow_whitelisted_api(self, controller):
        verdict = controller.authorize("bot", "call_api", context={"api": "stripe"})
        assert verdict.allowed is True

    def test_deny_blocked_api(self, controller):
        verdict = controller.authorize("bot", "call_api", context={"api": "kubernetes"})
        assert verdict.allowed is False

    def test_deny_unlisted_api(self, controller):
        verdict = controller.authorize("bot", "call_api", context={"api": "unknown_service"})
        assert verdict.allowed is False

    def test_no_api_passes(self, controller):
        verdict = controller.authorize("bot", "do_stuff")
        assert verdict.allowed is True


# ── Rate limits ──────────────────────────────────────────────────────────────

class TestRateLimits:
    def test_within_rate_limit(self, controller):
        for _ in range(4):
            controller.record_execution("process_refund")
        verdict = controller.authorize("bot", "process_refund")
        assert verdict.allowed is True

    def test_exceed_rate_limit(self, controller):
        for _ in range(5):
            controller.record_execution("process_refund")
        verdict = controller.authorize("bot", "process_refund")
        assert verdict.allowed is False
        assert "rate_limit" in verdict.checks_failed[0]


# ── Data scope ───────────────────────────────────────────────────────────────

class TestDataScope:
    def test_allow_valid_scope(self, controller):
        verdict = controller.authorize("bot", "read_data", context={"data_scope": "read_only"})
        assert verdict.allowed is True

    def test_deny_elevated_scope(self, controller):
        verdict = controller.authorize("bot", "read_data", context={"data_scope": "full"})
        assert verdict.allowed is False


# ── Budget limits ────────────────────────────────────────────────────────────

class TestBudgetLimits:
    def test_within_budget(self, controller):
        verdict = controller.authorize("bot", "action", context={"cost_usd": 100})
        assert verdict.allowed is True

    def test_exceed_budget(self, controller):
        controller._spent_usd = 950
        verdict = controller.authorize("bot", "action", context={"cost_usd": 100})
        assert verdict.allowed is False
        assert "budget" in verdict.checks_failed[0]


# ── Human approval triggers ─────────────────────────────────────────────────

class TestHumanApproval:
    def test_trigger_approval(self, controller):
        verdict = controller.authorize("bot", "customer_data_export")
        assert verdict.requires_human_approval is True

    def test_write_action_requires_approval(self, controller):
        verdict = controller.authorize("bot", "create_order")
        assert verdict.requires_human_approval is True

    def test_read_action_no_approval(self, rules):
        rules.require_approval_for_write = False
        controller = GuardrailController(rules=rules)
        verdict = controller.authorize("bot", "read_orders")
        assert verdict.requires_human_approval is False


# ── Configuration management ────────────────────────────────────────────────

class TestConfiguration:
    def test_update_rules(self, controller):
        controller.update_rules({"max_transaction": 1000})
        assert controller.rules.max_transaction == 1000

    def test_status(self, controller):
        status = controller.status()
        assert "rules" in status
        assert "rate_counts" in status
        assert "spent_usd" in status

    def test_from_dict(self):
        gc = GuardrailController.from_dict({
            "max_transaction": 300,
            "restricted_operations": ["drop_table"],
        })
        assert gc.rules.max_transaction == 300
        assert "drop_table" in gc.rules.restricted_operations


# ── Audit logging ────────────────────────────────────────────────────────────

class TestAuditLogging:
    def test_audit_called_on_denial(self):
        audit = MagicMock()
        gc = GuardrailController(
            rules=GuardrailRules(restricted_operations=["bad_action"]),
            audit_logger=audit,
        )
        gc.authorize("bot", "bad_action")
        audit.log.assert_called()

    def test_record_execution_tracking(self, controller):
        controller.record_execution("send_email", cost_usd=0.01)
        assert controller._spent_usd == pytest.approx(0.01)
