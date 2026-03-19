"""
test_update_lifecycle.py — Coverage for BLOCKER 4: Update & Lifecycle Management

Tests:
  1. LifecycleRecord  — version_tracking fields and serialization
  2. AgentLifecycleManager  — record_upgrade, record_rollback, get_version,
                              get_version_history (new methods)
  3. LifecycleUpdater  — upgrade_agent, rollback_agent, fleet_security_scan,
                         broadcast_update, full_status, security_alerts_for
  4. Integration  — VersionManager + UpdateChannel + LifecycleUpdater end-to-end:
       publish → upgrade → rollback → rollback, verify lifecycle history at each step

Security notes:
  - All paths use tmp_path for isolation (no global state pollution)
  - No network calls (all update channel ops are local)
  - No DESTRUCTIVE tools invoked — all ops are reversible
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.version_manager import VersionManager
from core.update_channel import UpdateChannel
from core.lifecycle_updater import LifecycleUpdater
from factory.lifecycle_manager import AgentLifecycleManager, LifecycleRecord


# ─── Helpers ─────────────────────────────────────────────────────────────────


class DummyAgent:
    def __init__(self, profile: dict):
        self.profile = dict(profile)


class DummyRegistry:
    def __init__(self, agents: dict | None = None):
        self._agents = {
            name: DummyAgent(p)
            for name, p in (agents or {}).items()
        }

    def get(self, name: str):
        return self._agents.get(name)

    def list_agents(self) -> dict:
        return {n: dict(a.profile) for n, a in self._agents.items()}


def _make_governance(tmp_path: Path, agent_name: str = "bot"):
    """Build a stripped-down governance-like object with version_manager + update_channel."""
    vm = VersionManager(agent_name=agent_name, data_dir=tmp_path)
    vm.register_version("1.0.0", ["Initial release"], {"name": agent_name})
    ch = UpdateChannel(
        agent_name=agent_name,
        version_manager=vm,
        data_dir=tmp_path,
        auto_apply_security=False,
    )
    gov = MagicMock()
    gov.version_manager = vm
    gov.update_channel = ch
    return gov


def _make_lifecycle(tmp_path: Path):
    """Build an AgentLifecycleManager backed by tmp_path."""
    registry = DummyRegistry({"bot": {"name": "bot", "role": "assistant", "skills": ["crm"]}})
    mgr = AgentLifecycleManager(registry=registry, ai_adapter=None)
    # Override store path to use tmp_path so tests don't share state
    import factory.lifecycle_manager as lm
    lm._LIFECYCLE_STORE = tmp_path / "lifecycle_store.json"
    mgr._records.clear()
    return mgr


def _make_updater(tmp_path: Path, agent_name: str = "bot", auto_scan: bool = False):
    """Return (LifecycleUpdater, lifecycle, governance)."""
    gov = _make_governance(tmp_path, agent_name)
    lifecycle = _make_lifecycle(tmp_path)
    updater = LifecycleUpdater(lifecycle=lifecycle, governance=gov, auto_scan=auto_scan)
    return updater, lifecycle, gov


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LifecycleRecord — version tracking fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestLifecycleRecordVersionFields(unittest.TestCase):

    def test_default_version_fields(self):
        rec = LifecycleRecord(name="bot")
        self.assertEqual(rec.current_version, "")
        self.assertEqual(rec.version_history, [])

    def test_to_dict_includes_version(self):
        rec = LifecycleRecord(name="bot")
        rec.current_version = "1.2.0"
        rec.version_history = [{"from": "1.0.0", "to": "1.2.0", "ts": 1234}]
        d = rec.to_dict()
        self.assertEqual(d["current_version"], "1.2.0")
        self.assertEqual(len(d["version_history"]), 1)

    def test_from_dict_restores_version(self):
        original = LifecycleRecord(name="bot")
        original.current_version = "2.0.0"
        original.version_history = [{"from": "1.0.0", "to": "2.0.0", "ts": 0}]
        restored = LifecycleRecord.from_dict(original.to_dict())
        self.assertEqual(restored.current_version, "2.0.0")
        self.assertEqual(restored.version_history[0]["to"], "2.0.0")

    def test_from_dict_tolerates_missing_version_fields(self):
        """Old records without version fields must load without errors."""
        old_data = {
            "name": "legacy_bot",
            "state": "idle",
            "last_active": time.time(),
            "task_count": 5,
            "success_count": 4,
            "fail_count": 1,
            "avg_duration_sec": 1.0,
            "composed_skills": [],
            "specialization_applied": False,
            "task_history": [],
        }
        rec = LifecycleRecord.from_dict(old_data)
        self.assertEqual(rec.current_version, "")
        self.assertEqual(rec.version_history, [])

    def test_version_history_capped_at_50(self):
        """to_dict() keeps at most 50 version history entries."""
        rec = LifecycleRecord(name="bot")
        rec.version_history = [{"entry": i} for i in range(80)]
        d = rec.to_dict()
        self.assertLessEqual(len(d["version_history"]), 50)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AgentLifecycleManager — record_upgrade / record_rollback / get_version
# ═══════════════════════════════════════════════════════════════════════════════

class TestLifecycleManagerVersionMethods(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import factory.lifecycle_manager as lm
        lm._LIFECYCLE_STORE = Path(self.tmp) / "lifecycle_store.json"
        registry = DummyRegistry({"bot": {"name": "bot", "role": "assistant"}})
        self.mgr = AgentLifecycleManager(registry=registry, ai_adapter=None)
        self.mgr._records.clear()

    def test_record_upgrade_sets_version(self):
        self.mgr.record_upgrade("bot", to_version="1.1.0", from_version="1.0.0",
                                update_type="feature", changes=["New search"])
        self.assertEqual(self.mgr.get_version("bot"), "1.1.0")

    def test_record_upgrade_appends_history(self):
        self.mgr.record_upgrade("bot", "1.1.0", "1.0.0", "feature", ["A"])
        self.mgr.record_upgrade("bot", "1.2.0", "1.1.0", "bugfix", ["B"])
        history = self.mgr.get_version_history("bot")
        # Newest first
        self.assertEqual(history[0]["to"], "1.2.0")
        self.assertEqual(history[1]["to"], "1.1.0")

    def test_record_rollback_sets_version(self):
        self.mgr.record_upgrade("bot", "1.1.0", "1.0.0", "feature", ["A"])
        self.mgr.record_rollback("bot", to_version="1.0.0", from_version="1.1.0")
        self.assertEqual(self.mgr.get_version("bot"), "1.0.0")

    def test_record_rollback_tagged_as_rollback(self):
        self.mgr.record_upgrade("bot", "1.1.0", "1.0.0", "feature", ["A"])
        self.mgr.record_rollback("bot", "1.0.0", "1.1.0")
        history = self.mgr.get_version_history("bot")
        self.assertEqual(history[0]["update_type"], "rollback")

    def test_get_version_unknown_agent_returns_empty(self):
        self.assertEqual(self.mgr.get_version("no_such_agent"), "")

    def test_get_version_history_unknown_agent_returns_empty_list(self):
        self.assertEqual(self.mgr.get_version_history("ghost"), [])

    def test_history_capped_at_50_entries(self):
        for i in range(60):
            self.mgr.record_upgrade("bot", f"1.{i}.0", f"1.{i-1}.0", "feature", [f"v{i}"])
        history = self.mgr.get_version_history("bot", limit=100)
        # version_history list should not exceed 50 (trimmed in record_upgrade)
        self.assertLessEqual(len(history), 50)

    def test_version_persists_after_reload(self):
        self.mgr.record_upgrade("bot", "1.3.0", "1.0.0", "feature", ["Big release"])
        # Reload from same store path
        registry = DummyRegistry({"bot": {"name": "bot", "role": "assistant"}})
        mgr2 = AgentLifecycleManager(registry=registry, ai_adapter=None)
        self.assertEqual(mgr2.get_version("bot"), "1.3.0")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. LifecycleUpdater — unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestLifecycleUpdater(unittest.TestCase):

    def _make(self, name="bot"):
        tmp = Path(tempfile.mkdtemp())
        import factory.lifecycle_manager as lm
        lm._LIFECYCLE_STORE = tmp / "lifecycle_store.json"
        return _make_updater(tmp, agent_name=name, auto_scan=False)

    # ── upgrade_agent ────────────────────────────────────────────────────

    def test_upgrade_agent_applies_published_update(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.1.0", "feature", ["Search"])
        result = updater.upgrade_agent("bot", "1.1.0")
        self.assertIn(result.get("status"), ("applied", "staged"))
        self.assertEqual(lifecycle.get_version("bot"), "1.1.0")

    def test_upgrade_agent_publishes_on_the_fly_with_migration_fn(self):
        updater, lifecycle, gov = self._make()
        result = updater.upgrade_agent(
            "bot", "1.1.0",
            migration_fn=lambda spec: {**spec, "patched": True},
        )
        self.assertIn(result.get("status"), ("applied", "staged"))
        self.assertEqual(lifecycle.get_version("bot"), "1.1.0")

    def test_upgrade_agent_error_when_no_record_and_no_fn(self):
        updater, lifecycle, gov = self._make()
        result = updater.upgrade_agent("bot", "9.9.9")
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"].lower())

    def test_upgrade_dry_run_does_not_change_version(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.1.0", "feature", ["A"])
        result = updater.upgrade_agent("bot", "1.1.0", dry_run=True)
        self.assertIn(result["status"], ("compatible", "not_published"))
        self.assertEqual(gov.version_manager.current_version, "1.0.0")

    def test_upgrade_migration_failure_does_not_update_lifecycle(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update(
            "1.1.0", "bugfix", ["Fix"],
            migration_fn=lambda s: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        result = updater.upgrade_agent("bot", "1.1.0")
        self.assertEqual(result["status"], "error")
        # Lifecycle record must NOT reflect failed upgrade
        self.assertNotEqual(lifecycle.get_version("bot"), "1.1.0")

    # ── rollback_agent ────────────────────────────────────────────────────

    def test_rollback_agent_reverts_version(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.1.0", "feature", ["A"])
        updater.upgrade_agent("bot", "1.1.0")
        result = updater.rollback_agent("bot")
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(lifecycle.get_version("bot"), "1.0.0")

    def test_rollback_agent_records_in_lifecycle_history(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.1.0", "feature", ["A"])
        updater.upgrade_agent("bot", "1.1.0")
        updater.rollback_agent("bot")
        history = lifecycle.get_version_history("bot")
        rollback_entries = [h for h in history if h["update_type"] == "rollback"]
        self.assertEqual(len(rollback_entries), 1)

    def test_rollback_to_specific_version(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.1.0", "feature", ["A"])
        gov.update_channel.publish_update("1.2.0", "feature", ["B"])
        updater.upgrade_agent("bot", "1.1.0")
        updater.upgrade_agent("bot", "1.2.0")
        result = updater.rollback_agent("bot", to_version="1.0.0")
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(lifecycle.get_version("bot"), "1.0.0")

    def test_rollback_when_no_prior_version_returns_error(self):
        updater, lifecycle, gov = self._make()
        result = updater.rollback_agent("bot")
        self.assertEqual(result["status"], "error")

    # ── agent_update_status / full_status ─────────────────────────────────

    def test_agent_update_status_shape(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.1.0", "feature", ["A"])
        status = updater.agent_update_status("bot")
        self.assertIn("agent", status)
        self.assertIn("deployed_version", status)
        self.assertIn("available_updates", status)
        self.assertIn("security_pending", status)
        self.assertEqual(status["available_updates"], 1)

    def test_full_status_includes_changelog(self):
        updater, lifecycle, gov = self._make()
        status = updater.full_status("bot")
        self.assertIn("changelog", status)
        self.assertIn("compatibility", status)

    # ── fleet_security_scan ───────────────────────────────────────────────

    def test_fleet_security_scan_no_updates(self):
        updater, lifecycle, gov = self._make()
        report = updater.fleet_security_scan()
        self.assertEqual(report["health"], "healthy")
        self.assertEqual(report["security_updates_pending"], 0)
        self.assertEqual(report["critical_count"], 0)

    def test_fleet_security_scan_detects_critical(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_security_patch(
            "1.0.1", "CVE-2026-0001", "Critical vuln", severity="critical",
        )
        report = updater.fleet_security_scan()
        self.assertEqual(report["health"], "critical")
        self.assertEqual(report["critical_count"], 1)

    def test_fleet_security_scan_at_risk_for_high(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_security_patch(
            "1.0.1", "CVE-2026-0002", "High severity", severity="high",
        )
        report = updater.fleet_security_scan()
        self.assertEqual(report["health"], "at_risk")

    def test_security_alerts_populated_after_scan(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_security_patch(
            "1.0.1", "CVE-2026-0003", "Vuln", severity="critical",
        )
        lifecycle.activate("bot")  # agent is warm
        updater.fleet_security_scan()
        alerts = updater.security_alerts_for("bot")
        self.assertGreater(len(alerts), 0)
        self.assertEqual(alerts[0]["update_type"], "security")

    def test_security_alerts_cleared_after_update_applied(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_security_patch(
            "1.0.1", "CVE-2026-0004", "Vuln", severity="critical",
        )
        lifecycle.activate("bot")
        updater.fleet_security_scan()
        self.assertGreater(len(updater.security_alerts_for("bot")), 0)
        # Now apply the patch
        updater.upgrade_agent("bot", "1.0.1")
        # After patch applied, security_updates list in channel is empty
        # Rescan — channel has no more available security updates
        report = updater.fleet_security_scan()
        # security_updates_pending drops to 0 (the patch is applied, not available)
        self.assertEqual(report["security_updates_pending"], 0)
        self.assertEqual(len(updater.security_alerts_for("bot")), 0)

    # ── broadcast_update ──────────────────────────────────────────────────

    def test_broadcast_update_applies_to_named_agents(self):
        tmp = Path(tempfile.mkdtemp())
        import factory.lifecycle_manager as lm
        lm._LIFECYCLE_STORE = tmp / "lifecycle_store.json"
        gov = _make_governance(tmp, "bot")
        registry = DummyRegistry({"bot": {"name": "bot", "role": "A"}, "worker": {"name": "worker", "role": "B"}})
        lifecycle = AgentLifecycleManager(registry=registry, ai_adapter=None)
        lifecycle._records.clear()
        lifecycle.activate("bot")
        lifecycle.activate("worker")
        updater = LifecycleUpdater(lifecycle=lifecycle, governance=gov, auto_scan=False)

        results = updater.broadcast_update(
            version="1.1.0",
            update_type="feature",
            changes=["Fleet upgrade"],
            agent_names=["bot", "worker"],
        )
        self.assertIn("applied", results)
        self.assertIn("failed", results)
        # Platform update applied once; both agents get lifecycle records updated
        applied_agents = [r["agent"] for r in results["applied"]]
        self.assertIn("bot", applied_agents)
        self.assertIn("worker", applied_agents)
        self.assertEqual(lifecycle.get_version("bot"), "1.1.0")
        self.assertEqual(lifecycle.get_version("worker"), "1.1.0")

    def test_broadcast_update_dry_run_does_not_change_versions(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.2.0", "feature", ["Big"])
        lifecycle.activate("bot")
        results = updater.broadcast_update(
            version="1.2.0",
            update_type="feature",
            changes=["Big"],
            agent_names=["bot"],
            dry_run=True,
        )
        # dry_run: no actual version change
        self.assertEqual(gov.version_manager.current_version, "1.0.0")
        self.assertEqual(lifecycle.get_version("bot"), "")

    # ── agent_changelog ───────────────────────────────────────────────────

    def test_agent_changelog_includes_lifecycle_and_vm_history(self):
        updater, lifecycle, gov = self._make()
        gov.update_channel.publish_update("1.1.0", "feature", ["A"])
        result = updater.upgrade_agent("bot", "1.1.0")
        self.assertIn(result.get("status"), ("applied", "staged"))
        changelog = updater.agent_changelog("bot")
        self.assertEqual(changelog["agent"], "bot")
        self.assertIn("lifecycle_history", changelog)
        self.assertIn("version_manager_log", changelog)
        # After a successful upgrade, lifecycle history must be non-empty
        self.assertGreater(len(changelog["lifecycle_history"]), 0)
        self.assertEqual(changelog["lifecycle_history"][0]["to"], "1.1.0")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Integration — full upgrade → rollback → re-upgrade cycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestLifecycleUpdateIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        import factory.lifecycle_manager as lm
        lm._LIFECYCLE_STORE = self.tmp / "lifecycle_store.json"
        self.gov = _make_governance(self.tmp, "store_bot")
        self.lifecycle = _make_lifecycle(self.tmp)
        self.updater = LifecycleUpdater(
            lifecycle=self.lifecycle,
            governance=self.gov,
            auto_scan=False,
        )

    def test_full_upgrade_rollback_reupgrade_cycle(self):
        ch = self.gov.update_channel
        vm = self.gov.version_manager

        # Publish v1.1.0 and v1.2.0
        ch.publish_update("1.1.0", "feature", ["Search"])
        ch.publish_update("1.2.0", "feature", ["Dashboard"])

        # Upgrade 1.0.0 → 1.1.0
        r1 = self.updater.upgrade_agent("store_bot", "1.1.0")
        self.assertEqual(r1["status"], "applied")
        self.assertEqual(vm.current_version, "1.1.0")
        self.assertEqual(self.lifecycle.get_version("store_bot"), "1.1.0")

        # Upgrade 1.1.0 → 1.2.0
        r2 = self.updater.upgrade_agent("store_bot", "1.2.0")
        self.assertEqual(r2["status"], "applied")
        self.assertEqual(vm.current_version, "1.2.0")
        self.assertEqual(self.lifecycle.get_version("store_bot"), "1.2.0")

        # Rollback to 1.1.0
        rbk = self.updater.rollback_agent("store_bot", to_version="1.1.0")
        self.assertEqual(rbk["status"], "rolled_back")
        self.assertEqual(vm.current_version, "1.1.0")
        self.assertEqual(self.lifecycle.get_version("store_bot"), "1.1.0")

        # Verify full history has 3 entries: upgrade, upgrade, rollback
        history = self.lifecycle.get_version_history("store_bot")
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["update_type"], "rollback")

    def test_security_patch_auto_detected_and_applied(self):
        ch = self.gov.update_channel

        # Publish a non-critical security patch
        ch.publish_security_patch(
            "1.0.1", "CVE-2026-9876", "Credential leak fix", severity="high",
        )
        scan = self.updater.fleet_security_scan()
        self.assertEqual(scan["health"], "at_risk")

        # Operator applies the patch
        result = self.updater.upgrade_agent("store_bot", "1.0.1")
        self.assertEqual(result["status"], "applied")

        # Post-apply scan should be clean
        scan2 = self.updater.fleet_security_scan()
        self.assertEqual(scan2["health"], "healthy")

    def test_compatibility_check_before_breaking_upgrade(self):
        ch = self.gov.update_channel
        ch.publish_update(
            "2.0.0", "feature", ["Complete rewrite"],
            breaking_changes=["Old API removed"],
            min_version="1.0.0",
        )
        # Dry run should flag the breaking changes
        result = self.updater.upgrade_agent("store_bot", "2.0.0", dry_run=True)
        self.assertIn(result["status"], ("compatible", "not_published"))
        # Version still at 1.0.0
        self.assertEqual(self.gov.version_manager.current_version, "1.0.0")

    def test_version_status_after_multiple_ops(self):
        ch = self.gov.update_channel
        ch.publish_update("1.1.0", "bugfix", ["Fix null pointer"])
        self.updater.upgrade_agent("store_bot", "1.1.0")

        status = self.updater.agent_update_status("store_bot")
        self.assertEqual(status["deployed_version"], "1.1.0")
        self.assertEqual(status["available_updates"], 0)
        self.assertEqual(status["security_pending"], 0)

    def test_repr_is_informative(self):
        r = repr(self.updater)
        self.assertIn("LifecycleUpdater", r)
        self.assertIn("security_alerts", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
