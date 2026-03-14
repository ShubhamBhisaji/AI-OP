import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.tool_manager import ToolManager
from security.approval_gate import ApprovalGate, require_approval
from tools.http_client import http_client
from tools.web_scraper_pro import web_scraper_pro
from core.aether_kernel import AetherKernel


class _LeanToolManager(ToolManager):
    def _register_builtins(self) -> None:
        # Keep tests isolated from optional third-party tool deps.
        self._tools = {}


class SecurityHardeningTests(unittest.TestCase):
    def test_call_does_not_inject_kwargs_into_plain_tool(self):
        tm = _LeanToolManager()

        def plain_tool(value):
            return value

        tm.register("plain_tool", plain_tool)
        out = tm.call("plain_tool", "ok", agent_name="tester", agent_level=1)
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

    def test_http_client_blocks_localhost(self):
        out = http_client("http://localhost")
        self.assertIn("SSRF guard", out)

    def test_web_scraper_blocks_localhost(self):
        out = web_scraper_pro("http://localhost", action="scrape")
        self.assertIn("Security", out)

    def test_approval_legacy_bypass_flag_is_ignored(self):
        @require_approval
        def guarded_echo(value, **kwargs):
            return value

        with patch("builtins.input", return_value="n"):
            with self.assertRaises(PermissionError):
                guarded_echo("ok", _approval_already_granted=True, _agent_name="attacker")

    def test_safe_fs_component_strips_traversal_chars(self):
        safe = AetherKernel._safe_fs_component("../../windows/system32", fallback="x")
        self.assertNotIn("/", safe)
        self.assertNotIn("\\", safe)
        self.assertNotIn("..", safe)


if __name__ == "__main__":
    unittest.main()
