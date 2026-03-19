import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch
import tempfile
import json

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.tool_manager import ToolManager
from security.approval_gate import ApprovalGate, require_approval
from security.audit_logger import AuditLogger
from security.enforcement_gate import EnforcementGate, PolicyViolation
from security.policy_engine import PolicyEngine
from tools.http_client import http_client
from tools.web_scraper_pro import web_scraper_pro
from tools.calculator import calculator


class _LeanToolManager(ToolManager):
    def _register_builtins(self) -> None:
        # Keep tests isolated from optional third-party tool deps.
        self._tools = {}


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._audit_tmp = tempfile.TemporaryDirectory()
        audit_path = Path(self._audit_tmp.name) / "audit.jsonl"
        EnforcementGate.install(
            policy_engine=PolicyEngine(),
            audit_logger=AuditLogger(audit_path),
            tool_permissions={
                "calculator": 0,
                "http_client": 1,
                "web_scraper_pro": 1,
                "github_tool": 3,
            },
            default_permission=3,
        )

    def tearDown(self) -> None:
        EnforcementGate.reset()
        self._audit_tmp.cleanup()

    def test_direct_tool_import_denied_when_enforcement_gate_closed(self):
        EnforcementGate.reset()
        with self.assertRaises(PolicyViolation):
            calculator("1+1")

    def test_direct_tool_import_allowed_after_enforcement_gate_install(self):
        EnforcementGate.reset()
        with tempfile.TemporaryDirectory() as td:
            audit_path = Path(td) / "audit.jsonl"
            tm = _LeanToolManager(
                policy_engine=PolicyEngine(),
                audit_logger=AuditLogger(audit_path),
            )
            EnforcementGate.install(
                policy_engine=tm.policy_engine,
                audit_logger=AuditLogger(audit_path),
                tool_permissions={"calculator": 0},
                default_permission=3,
            )
            out = calculator("1+1", _agent_name="tester", _agent_level=1)
            self.assertEqual(out, "2")

    def test_call_does_not_inject_kwargs_into_plain_tool(self):
        tm = _LeanToolManager()

        def plain_tool(value):
            return value

        tm.register("plain_tool", plain_tool)
        out = tm.call("plain_tool", "ok", agent_name="tester", agent_level=3)
        self.assertEqual(out, "ok")

    def test_guarded_tool_uses_central_approval(self):
        tm = _LeanToolManager()
        calls = []

        def guarded_tool(value):
            return value

        tm.register("github_tool", guarded_tool)

        with patch.object(
            ApprovalGate,
            "request",
            side_effect=lambda tool_name, agent_name, args_summary: calls.append(
                (tool_name, agent_name)
            ),
        ):
            out = tm.call("github_tool", "ok", agent_name="agent-x", agent_level=3)
            self.assertEqual(out, "ok")
            self.assertIn(("github_tool", "agent-x"), calls)

    def test_policy_engine_deny_by_default_for_unregistered_tool(self):
        policy = PolicyEngine()
        d = policy.evaluate_tool_call(
            tool_name="unknown_tool",
            tool_registered=False,
            agent_level=3,
            required_level=1,
        )
        self.assertFalse(d.allowed)
        self.assertIn("deny-by-default", d.reason)

    def test_audit_entry_written_once_per_decision(self):
        with tempfile.TemporaryDirectory() as td:
            audit_path = Path(td) / "audit.jsonl"
            tm = _LeanToolManager(
                policy_engine=PolicyEngine(),
                audit_logger=AuditLogger(audit_path),
            )

            def plain_tool(value):
                return value

            tm.register("plain_tool", plain_tool)
            tm.call("plain_tool", "ok", agent_name="tester", agent_level=3)

            lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertEqual(event["event"], "tool_call")
            self.assertEqual(event["decision"], "allow")

    def test_http_client_blocks_localhost(self):
        out = http_client("http://localhost", _agent_name="tester", _agent_level=1)
        self.assertIn("SSRF guard", out)

    def test_web_scraper_blocks_localhost(self):
        out = web_scraper_pro(
            "http://localhost",
            action="scrape",
            _agent_name="tester",
            _agent_level=1,
        )
        self.assertIn("Security", out)

    def test_approval_legacy_bypass_flag_is_ignored(self):
        @require_approval
        def guarded_echo(value, **kwargs):
            return value

        with patch("builtins.input", return_value="n"):
            with self.assertRaises(PermissionError):
                guarded_echo("ok", _approval_already_granted=True, _agent_name="attacker")

    def test_safe_fs_component_strips_traversal_chars(self):
        try:
            from core.aetheerai_kernel import AetheerAiKernel
        except Exception as exc:
            self.skipTest(f"Kernel import unavailable in this environment: {exc}")
        safe = AetheerAiKernel._safe_fs_component("../../windows/system32", fallback="x")
        self.assertNotIn("/", safe)
        self.assertNotIn("\\", safe)
        self.assertNotIn("..", safe)

    def test_sync_request_rejects_awaitable_async_callback(self):
        tm = _LeanToolManager()

        def guarded_tool(value):
            return value

        async def _approval_callback(_tool_name, _agent_name, _tier, _args_summary):
            return True

        tm.register("github_tool", guarded_tool)

        async def _invoke() -> None:
            ApprovalGate.set_headless(False)
            ApprovalGate.set_auto_approve(False)
            ApprovalGate.set_async_callback(_approval_callback)
            try:
                with self.assertRaises(PermissionError):
                    tm.call("github_tool", "ok", agent_name="agent-z", agent_level=3)
            finally:
                ApprovalGate.set_async_callback(None)

        asyncio.run(_invoke())


if __name__ == "__main__":
    unittest.main()
