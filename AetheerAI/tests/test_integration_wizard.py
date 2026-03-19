"""Tests for the IntegrationWizard (GAP 1)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrator.integration_wizard import (
    IntegrationWizard,
    WizardPhase,
    WizardSession,
    WizardStep,
    _detect_platform,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_registry():
    reg = MagicMock()
    agent = MagicMock()
    agent.name = "test_agent"
    reg.get.return_value = agent
    return reg


@pytest.fixture
def mock_integrator():
    integrator = MagicMock()
    from integrator.self_integrator import IntegrationResult
    result = IntegrationResult(
        status="connected",
        integration_type="website",
        target="https://myshop.com",
        endpoints_discovered=[{"path": "/api/v1/products", "method": "GET"}],
        connected_at=1000.0,
    )
    integrator.integrate.return_value = result
    return integrator


@pytest.fixture
def wizard(mock_registry, mock_integrator, tmp_path):
    return IntegrationWizard(
        registry=mock_registry,
        integrator=mock_integrator,
        config_dir=tmp_path / "integrations",
    )


# ── Platform detection ────────────────────────────────────────────────────────

class TestPlatformDetection:
    def test_detect_shopify(self):
        result = _detect_platform("https://mystore.myshopify.com")
        assert result["platform"] == "shopify"
        assert result["confidence"] == "high"

    def test_detect_supabase(self):
        result = _detect_platform("https://xyz.supabase.co")
        assert result["platform"] == "supabase"

    def test_detect_generic(self):
        result = _detect_platform("https://example.com/api/v1")
        assert result["platform"] == "generic_rest"
        assert result["confidence"] == "low"

    def test_detect_stripe(self):
        result = _detect_platform("https://api.stripe.com/v1")
        assert result["platform"] == "stripe"


# ── Wizard session lifecycle ─────────────────────────────────────────────────

class TestWizardLifecycle:
    def test_start_session(self, wizard):
        step = wizard.start_session("test_agent", "https://myshop.com")
        assert step.phase == WizardPhase.INITIATED
        assert step.success is True
        assert "session_id" in step.data

    def test_discover(self, wizard):
        start = wizard.start_session("test_agent", "https://myshop.com")
        session_id = start.data["session_id"]
        step = wizard.discover(session_id)
        assert step.phase == WizardPhase.AWAITING_CREDS
        assert step.success is True
        assert "platform" in step.data

    def test_discover_invalid_session(self, wizard):
        step = wizard.discover("nonexistent")
        assert step.phase == WizardPhase.FAILED
        assert step.success is False

    def test_provide_credentials(self, wizard):
        start = wizard.start_session("test_agent", "https://myshop.com")
        session_id = start.data["session_id"]
        wizard.discover(session_id)
        step = wizard.provide_credentials(session_id, {"api_key": "sk-test"})
        assert step.phase == WizardPhase.TESTING
        assert step.success is True

    def test_provide_empty_credentials(self, wizard):
        start = wizard.start_session("test_agent", "https://myshop.com")
        session_id = start.data["session_id"]
        wizard.discover(session_id)
        step = wizard.provide_credentials(session_id, {})
        assert step.success is False

    def test_test_connection_success(self, wizard):
        start = wizard.start_session("test_agent", "https://myshop.com")
        session_id = start.data["session_id"]
        wizard.discover(session_id)
        wizard.provide_credentials(session_id, {"api_key": "sk-test"})
        step = wizard.test_connection(session_id)
        assert step.phase == WizardPhase.CONFIGURING
        assert step.success is True

    def test_configure(self, wizard, tmp_path):
        start = wizard.start_session("test_agent", "https://myshop.com")
        session_id = start.data["session_id"]
        wizard.discover(session_id)
        wizard.provide_credentials(session_id, {"api_key": "sk-test"})
        wizard.test_connection(session_id)
        step = wizard.configure(session_id)
        assert step.phase == WizardPhase.CONFIRMING
        assert step.success is True
        assert "config_path" in step.data

    def test_confirm(self, wizard):
        start = wizard.start_session("test_agent", "https://myshop.com")
        session_id = start.data["session_id"]
        wizard.discover(session_id)
        wizard.provide_credentials(session_id, {"api_key": "sk-test"})
        wizard.test_connection(session_id)
        wizard.configure(session_id)
        step = wizard.confirm(session_id)
        assert step.phase == WizardPhase.COMPLETED
        assert step.success is True

    def test_full_auto_run(self, wizard):
        step = wizard.run_auto(
            agent_name="test_agent",
            target_url="https://myshop.com",
            credentials={"api_key": "sk-test"},
        )
        assert step.phase == WizardPhase.COMPLETED
        assert step.success is True


# ── Failure handling ─────────────────────────────────────────────────────────

class TestFailureHandling:
    def test_connection_failure_retry(self, mock_registry, tmp_path):
        mock_integrator = MagicMock()
        from integrator.self_integrator import IntegrationResult
        mock_integrator.integrate.return_value = IntegrationResult(
            status="error",
            errors=["Connection refused"],
        )
        wizard = IntegrationWizard(
            registry=mock_registry,
            integrator=mock_integrator,
            config_dir=tmp_path,
        )
        start = wizard.start_session("test_agent", "https://bad.example.com")
        session_id = start.data["session_id"]
        wizard.discover(session_id)
        wizard.provide_credentials(session_id, {"api_key": "sk-bad"})

        step = wizard.test_connection(session_id)
        assert step.success is False
        assert step.phase == WizardPhase.AWAITING_CREDS  # retry

    def test_connection_failure_max_attempts(self, mock_registry, tmp_path):
        mock_integrator = MagicMock()
        from integrator.self_integrator import IntegrationResult
        mock_integrator.integrate.return_value = IntegrationResult(
            status="error",
            errors=["Timeout"],
        )
        wizard = IntegrationWizard(
            registry=mock_registry,
            integrator=mock_integrator,
            config_dir=tmp_path,
        )
        start = wizard.start_session("test_agent", "https://bad.example.com")
        session_id = start.data["session_id"]
        wizard.discover(session_id)

        for _ in range(3):
            wizard.provide_credentials(session_id, {"api_key": "sk-bad"})
            step = wizard.test_connection(session_id)

        assert step.phase == WizardPhase.FAILED
        assert step.success is False


# ── Session queries ──────────────────────────────────────────────────────────

class TestSessionQueries:
    def test_list_sessions(self, wizard):
        wizard.start_session("test_agent", "https://a.com")
        wizard.start_session("test_agent", "https://b.com")
        sessions = wizard.list_sessions("test_agent")
        assert len(sessions) == 2

    def test_get_session(self, wizard):
        start = wizard.start_session("test_agent", "https://a.com")
        session = wizard.get_session(start.data["session_id"])
        assert session is not None
        assert session.agent_name == "test_agent"

    def test_session_serialization(self, wizard):
        start = wizard.start_session("test_agent", "https://a.com")
        session = wizard.get_session(start.data["session_id"])
        d = session.to_dict()
        assert "credentials" in d
        # Credentials should be masked
        for v in d["credentials"].values():
            assert v == "***"
