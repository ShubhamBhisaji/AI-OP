"""Targeted regression tests for the ISSUE 1 / 5 / 6 / 7 fixes.

Covers:
- EconomicGuardrails enforced by EnforcementGate
- Governance operator auth gating
- MissionControl REST endpoints
- AIAdapter token usage forwarded to guardrails
- AuditLogger HMAC chain integrity
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import governance_api
from api.routes_v2 import router as v2_router
from ai.ai_adapter import AIAdapter
from security.audit_logger import AuditLogger
from security.enforcement_gate import EnforcementGate, PolicyViolation


class _DummyDecision:
    def __init__(self, allowed: bool = True, reason: str = ""):
        self.allowed = allowed
        self.reason = reason


class _DummyPolicy:
    def evaluate_tool_call(self, **kwargs):
        return _DummyDecision(True, "")


class _DummyAudit:
    def __init__(self):
        self.events: list[dict] = []

    def log(self, event: dict):
        self.events.append(dict(event))


class _StubGuardrails:
    def __init__(self, verdict: dict[str, object]):
        self.verdict = verdict
        self.calls: list[dict[str, object]] = []
        self.usage: list[dict[str, object]] = []

    def check_quota(self, **kwargs):
        self.calls.append(dict(kwargs))
        return dict(self.verdict)

    def record_usage(self, **kwargs):
        self.usage.append(dict(kwargs))


class _FakeResponse:
    def __init__(self, total_tokens: int = 7):
        self.usage = MagicMock(prompt_tokens=3, completion_tokens=4, total_tokens=total_tokens)
        self.choices = [MagicMock(message=MagicMock(content="ok"))]


@pytest.fixture(autouse=True)
def _clear_gate_singleton():
    EnforcementGate.reset()
    yield
    EnforcementGate.reset()


@pytest.fixture(autouse=True)
def _clear_operator_token_env(monkeypatch):
    monkeypatch.delenv("AETHEERAI_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("AETHEERAI_AUDIT_HMAC_SECRET", raising=False)


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE 1 — EnforcementGate must honor EconomicGuardrails
# ──────────────────────────────────────────────────────────────────────────────


def test_enforcement_gate_denies_when_guardrails_block():
    audit = _DummyAudit()
    gate = EnforcementGate.install(
        policy_engine=_DummyPolicy(),
        audit_logger=audit,
        tool_permissions={"tool.alpha": 2},
        default_permission=2,
        economic_guardrails=_StubGuardrails({"allowed": False, "reason": "quota exceeded"}),
    )

    with pytest.raises(PolicyViolation) as exc:
        gate.check("tool.alpha", agent_name="bot", agent_level=5, context={"category": "api_call"})

    assert "quota exceeded" in str(exc.value)
    assert gate._economic_guardrails is not None
    assert any(event.get("source") == "economic_guardrails" for event in audit.events)


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE 2/3 — Governance operator auth
# ──────────────────────────────────────────────────────────────────────────────


def _make_governance_app() -> TestClient:
    app = FastAPI()
    app.include_router(governance_api.router)

    gov = MagicMock()
    gov.status.return_value = {"agent": "api_bot"}
    gov.dashboard.return_value = {"governance": {}, "monitor": {}}
    gov.control_plane_status.return_value = {"controls": {}, "status_indicators": {}}
    gov.health.return_value = {"ok": True}
    gov.pause.return_value = {"status": "paused"}
    gov.resume.return_value = {"status": "resumed"}
    gov.emergency_stop.return_value = {"status": "stopped"}
    gov.safe_shutdown.return_value = {"status": "shutdown"}
    gov.safe_mode.return_value = {"status": "safe"}
    gov.restart.return_value = {"status": "restarted"}
    gov.disable_integrations.return_value = {"disconnected": 1}
    gov.throttle.return_value = None
    gov.policy_update.return_value = {"status": "applied"}
    gov.human_override.pending_approvals.return_value = []
    gov.human_override.approve.return_value = {"status": "approved"}
    gov.human_override.reject.return_value = {"status": "rejected"}
    gov.trigger_manual_approval.return_value = {"status": "created"}
    gov.monitor.decision_log.return_value = []
    gov.monitor.actions_taken.return_value = []
    gov.monitor.error_report.return_value = []
    gov.monitor.retry_summary.return_value = {"total_retries": 0}
    gov.monitor.activity_timeline.return_value = []
    gov.monitor.current_tasks.return_value = []
    gov.monitor.resource_usage.return_value = {"api_calls": 0}
    gov.monitor.integration_status.return_value = {"services": {}}
    gov.monitor.status_indicators.return_value = {"integration_status": {}}
    gov.economic_guardrails.cost_by_category.return_value = {}
    gov.economic_guardrails.cost_by_agent.return_value = {}
    gov.economic_guardrails.top_cost_operations.return_value = []
    gov.economic_guardrails.status.return_value = {"budget": 0}
    gov.update_channel.update_status.return_value = {"versions": []}
    gov.verify_update.return_value = {"ok": True}
    gov.update_channel.apply_staged.return_value = {"ok": True}
    gov.rollback_update.return_value = {"ok": True}
    app.state.governance = gov
    return TestClient(app)


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/api/governance/pause", {"operator": "admin", "reason": "maintenance"}),
        ("post", "/api/governance/emergency-stop", {"operator": "admin", "reason": "breach"}),
        ("get", "/api/governance/decisions", None),
        ("post", "/api/governance/updates/apply", {"version": "1.2.3"}),
    ],
)
def test_governance_endpoints_require_operator_token(monkeypatch, method, path, payload):
    monkeypatch.setenv("AETHEERAI_OPERATOR_TOKEN", "secret-token")
    client = _make_governance_app()

    request = getattr(client, method)
    if payload is None:
        no_auth = request(path)
        ok = request(path, headers={"Authorization": "Bearer secret-token"})
    else:
        no_auth = request(path, json=payload)
        ok = request(path, json=payload, headers={"Authorization": "Bearer secret-token"})
    assert no_auth.status_code in {401, 403}
    assert ok.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE 5 — MissionControl REST surface
# ──────────────────────────────────────────────────────────────────────────────


def _make_mission_app(kernel_mock: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(v2_router)
    app.state.kernel = kernel_mock
    return TestClient(app)


@pytest.fixture
def _kernel_for_missions(monkeypatch):
    kernel = MagicMock()
    kernel.launch_mission.return_value = "goal-123"
    kernel.mission_status.return_value = {"status": "running"}
    kernel.pause_mission.return_value = True
    kernel.resume_mission.return_value = True
    kernel.cancel_mission.return_value = True
    kernel.retry_failed_mission_tasks.return_value = 2
    kernel.mission_health.return_value = {"healthy": True}
    monkeypatch.setattr("api.routes_v2._kernel", lambda: kernel)
    return kernel


def test_mission_launch_status_and_controls(_kernel_for_missions):
    client = _make_mission_app(_kernel_for_missions)

    launch = client.post(
        "/api/missions",
        json={
            "agent_name": "bot",
            "goal": "run a mission",
            "tasks": [{"description": "step 1"}],
            "priority": 4,
            "max_retries_per_task": 1,
        },
    )
    assert launch.status_code == 201
    assert launch.json()["data"]["goal_id"] == "goal-123"

    status = client.get("/api/missions/bot/status")
    assert status.status_code == 200
    assert status.json()["data"]["status"] == "running"

    assert client.post("/api/missions/bot/pause").status_code == 200
    assert client.post("/api/missions/bot/resume").status_code == 200
    assert client.delete("/api/missions/bot/goal-123").status_code == 200
    assert client.post("/api/missions/bot/goal-123/retry").status_code == 200
    assert client.get("/api/missions/health").status_code == 200

    _kernel_for_missions.launch_mission.assert_called_once()
    _kernel_for_missions.mission_status.assert_called_once_with("bot")
    _kernel_for_missions.pause_mission.assert_called_once_with("bot")
    _kernel_for_missions.resume_mission.assert_called_once_with("bot")
    _kernel_for_missions.cancel_mission.assert_called_once_with("bot", "goal-123")
    _kernel_for_missions.retry_failed_mission_tasks.assert_called_once_with("bot", "goal-123")
    _kernel_for_missions.mission_health.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE 7 — AIAdapter token tracking forwarded to guardrails
# ──────────────────────────────────────────────────────────────────────────────


def test_ai_adapter_records_tokens_into_guardrails(monkeypatch):
    adapter = AIAdapter(provider="github", model="gpt-4.1")
    stub = _StubGuardrails({"allowed": True})
    adapter._guardrails = stub

    fake_response = _FakeResponse(total_tokens=9)
    monkeypatch.setattr("ai.ai_adapter._litellm", lambda: None)
    with patch("ai.ai_adapter._litellm", return_value=MagicMock(completion=MagicMock(return_value=fake_response))):
        with patch.object(adapter, "_default_model", return_value="gpt-4.1"):
            out = adapter._call("gpt-4.1", [{"role": "user", "content": "hello"}])

    assert out == "ok"
    assert adapter._session_usage["total_tokens"] == 9
    assert stub.usage and stub.usage[0]["tokens"] == 9
    assert stub.usage[0]["category"] == "api_call"


# ──────────────────────────────────────────────────────────────────────────────
# ISSUE 6 — AuditLogger chain integrity
# ──────────────────────────────────────────────────────────────────────────────


def test_audit_logger_appends_hmac_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHEERAI_AUDIT_HMAC_SECRET", "audit-secret")
    log_path = tmp_path / "audit_log.jsonl"
    logger = AuditLogger(log_path)

    logger.log({"event": "one", "actor": "bot"})
    logger.log({"event": "two", "actor": "bot"})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert len(first["chain"]) == 64
    assert len(second["chain"]) == 64
    assert first["chain"] != second["chain"]

    payload1 = {k: first[k] for k in first if k != "chain"}
    payload2 = {k: second[k] for k in second if k != "chain"}
    expected1 = hmac.new(
        b"audit-secret",
        ("0" * 64 + json.dumps(payload1, ensure_ascii=True, sort_keys=True)).encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    expected2 = hmac.new(
        b"audit-secret",
        (first["chain"] + json.dumps(payload2, ensure_ascii=True, sort_keys=True)).encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    assert first["chain"] == expected1
    assert second["chain"] == expected2
