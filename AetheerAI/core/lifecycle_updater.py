"""lifecycle_updater.py — Bridge between AgentLifecycleManager and UpdateChannel.

Closes BLOCKER 4: Update & Lifecycle Management Missing.

Provides the missing link between the runtime lifecycle state of an agent
(warm/idle/cold/retired) and its software version history (upgrades/rollbacks).

Responsibilities
----------------
1. **Version checking**  — per-agent and fleet-wide pending update scan
2. **Patch delivery**    — apply updates through the UpdateChannel and mirror
                           the result to the LifecycleRecord
3. **Upgrade path**      — validate compatibility, chain migrations, staged rollout
4. **Rollback**          — one-call rollback that undoes both UpdateChannel and
                           LifecycleRecord in concert

Architecture
------------
    LifecycleUpdater
        ├─ AgentLifecycleManager   (tracks state + version history per agent)
        ├─ GovernanceRuntime       (owns VersionManager + UpdateChannel per agent)
        └─ SecurityScanThread      (background thread: alerts on critical updates)

Usage
-----
    updater = LifecycleUpdater(
        lifecycle=kernel.lifecycle,
        governance=kernel.governance_runtime,
    )

    # Check one agent
    status = updater.agent_update_status("store_bot")

    # Upgrade one agent
    result = updater.upgrade_agent("store_bot", version="1.2.0")

    # Rollback
    result = updater.rollback_agent("store_bot")

    # Fleet-wide security scan
    report = updater.fleet_security_scan()

    # Push the same update to every agent at once
    results = updater.broadcast_update(
        version="2.0.0",
        update_type="feature",
        changes=["New AI engine"],
        agent_names=["store_bot", "support_bot"],
    )
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Seconds between background security-scan sweeps
_SCAN_INTERVAL_SEC: int = 300  # 5 minutes


class LifecycleUpdater:
    """
    Bridges AgentLifecycleManager and GovernanceRuntime so that software
    upgrades, patches, and rollbacks are reflected in both places.

    Parameters
    ----------
    lifecycle   : AgentLifecycleManager instance.
    governance  : GovernanceRuntime instance (owns UpdateChannel +
                  VersionManager).
    auto_scan   : Start background security-scan thread on construction.
    scan_interval_sec : Seconds between background scan sweeps.
    """

    def __init__(
        self,
        lifecycle: Any,
        governance: Any,
        auto_scan: bool = True,
        scan_interval_sec: int = _SCAN_INTERVAL_SEC,
    ) -> None:
        self._lifecycle = lifecycle
        self._gov = governance
        self._scan_interval = scan_interval_sec

        # Pending security alerts keyed by agent name
        self._security_alerts: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

        if auto_scan:
            self._scan_thread = threading.Thread(
                target=self._security_scan_loop, daemon=True, name="lifecycle-updater-scan"
            )
            self._scan_thread.start()
            logger.info("LifecycleUpdater: background security scan started (interval=%ds).",
                        self._scan_interval)

    # ── Per-agent status ──────────────────────────────────────────────────

    def agent_update_status(self, agent_name: str) -> dict[str, Any]:
        """
        Return the full update status for one agent.

        Combines:
          - Lifecycle state (warm/idle/cold/retired)
          - Current deployed version
          - Pending updates (count, types, severities)
          - Security alerts
        """
        lifecycle_state = self._lifecycle.get_state(agent_name)
        deployed_version = self._lifecycle.get_version(agent_name)

        # Pull update channel status from governance runtime
        update_status: dict[str, Any] = {}
        available_updates: list[dict[str, Any]] = []
        try:
            channel = self._gov.update_channel
            update_status = channel.update_status()
            available_updates = channel.check_updates()
        except Exception as exc:
            logger.warning("LifecycleUpdater: could not read update channel for %s: %s",
                          agent_name, exc)

        security_pending = [u for u in available_updates if u.get("update_type") == "security"]

        return {
            "agent": agent_name,
            "lifecycle_state": lifecycle_state,
            "deployed_version": deployed_version,
            "governance_version": update_status.get("current_version", ""),
            "available_updates": len(available_updates),
            "security_pending": len(security_pending),
            "security_alerts": security_pending,
            "update_channel": update_status,
            "updates": available_updates,
        }

    # ── Upgrade ────────────────────────────────────────────────────────────

    def upgrade_agent(
        self,
        agent_name: str,
        version: str,
        migration_fn: Callable | None = None,
        pre_check_fn: Callable | None = None,
        post_check_fn: Callable | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Upgrade an agent to the target version.

        Steps:
            1. Verify the update exists in UpdateChannel (or publish it on the fly
               if a migration_fn is supplied but no record exists yet).
            2. Apply via UpdateChannel.apply_staged() with optional pre/post hooks.
            3. On success, mirror the new version into LifecycleRecord.

        Parameters
        ----------
        agent_name    : Agent to upgrade.
        version       : Target semantic version.
        migration_fn  : (old_spec) -> new_spec — published on-the-fly if needed.
        pre_check_fn  : () -> (bool, str) — runs before migration.
        post_check_fn : () -> (bool, str) — runs after migration; triggers rollback on fail.
        dry_run       : Returns compatibility check without applying.
        """
        channel = self._gov.update_channel
        prior_version = self._gov.version_manager.current_version

        # If no update record exists yet and we have a migration fn, publish it
        if version not in {u["version"] for u in channel.list_updates()}:
            if migration_fn is not None:
                channel.publish_update(
                    version=version,
                    update_type="feature",
                    changes=[f"Upgrade to {version}"],
                    migration_fn=migration_fn,
                )
            elif dry_run:
                # Dry run without a published update — return current state
                return {
                    "status": "not_published",
                    "agent": agent_name,
                    "current": prior_version,
                    "target": version,
                    "dry_run": True,
                }
            else:
                return {
                    "status": "error",
                    "agent": agent_name,
                    "message": (
                        f"Update {version} not found in channel. "
                        "Publish it first via UpdateChannel.publish_update() or supply migration_fn."
                    ),
                }

        if dry_run:
            return channel.apply_update(version, dry_run=True)

        # Use staged rollout only when pre/post check hooks are supplied.
        # For routine upgrades (no hooks), use apply_update directly —
        # apply_staged enforces migration_fn presence which is too strict
        # for simple spec-free version bumps.
        if pre_check_fn is not None or post_check_fn is not None:
            result = channel.apply_staged(
                version=version,
                pre_check_fn=pre_check_fn,
                post_check_fn=post_check_fn,
            )
        else:
            result = channel.apply_update(version)

        if result.get("status") in ("applied", "staged"):
            # Mirror to lifecycle record
            self._lifecycle.record_upgrade(
                agent_name=agent_name,
                to_version=version,
                from_version=prior_version,
                update_type=result.get("update_type", "feature"),
                changes=result.get("changes", [f"Upgraded to {version}"]),
            )
            logger.info("LifecycleUpdater: agent '%s' upgraded %s → %s.",
                       agent_name, prior_version, version)

        result["agent"] = agent_name
        result["from"] = prior_version
        return result

    # ── Rollback ───────────────────────────────────────────────────────────

    def rollback_agent(
        self,
        agent_name: str,
        to_version: str | None = None,
    ) -> dict[str, Any]:
        """
        Roll back an agent to a previous version.

        If to_version is None, the UpdateChannel rolls back to the version
        immediately before the current one.

        On success the LifecycleRecord is updated to reflect the rollback.
        """
        channel = self._gov.update_channel
        prior_version = self._gov.version_manager.current_version

        result = channel.rollback(to_version)

        if result.get("status") == "rolled_back":
            rolled_to = result.get("to", to_version or "")
            self._lifecycle.record_rollback(
                agent_name=agent_name,
                to_version=rolled_to,
                from_version=prior_version,
            )
            logger.warning("LifecycleUpdater: agent '%s' rolled back %s → %s.",
                          agent_name, prior_version, rolled_to)

        result["agent"] = agent_name
        return result

    # ── Fleet operations ───────────────────────────────────────────────────

    def broadcast_update(
        self,
        version: str,
        update_type: str,
        changes: list[str],
        agent_names: list[str],
        description: str = "",
        severity: str = "normal",
        migration_fn: Callable | None = None,
        rollback_fn: Callable | None = None,
        requires_restart: bool = False,
        breaking_changes: list[str] | None = None,
        min_version: str = "",
        dry_run: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Push the same update to multiple agents at once.

        Publishes the update to the shared UpdateChannel and then applies it
        for each named agent.  Results are keyed by agent name under
        ``{"applied": [...], "failed": [...]}``.

        Parameters
        ----------
        agent_names : Names of agents to upgrade.  Pass [] to target all
                      warm/idle agents.
        dry_run     : If True, only run compatibility checks.
        """
        if not agent_names:
            # Default: all non-retired agents
            summary = self._lifecycle.summary().get("by_state", {})
            agent_names = []
            for state in ("warm", "idle"):
                agent_names.extend(summary.get(state, []))

        # Publish once to the shared channel (if not already published)
        channel = self._gov.update_channel
        existing = {u["version"] for u in channel.list_updates()}
        if version not in existing:
            channel.publish_update(
                version=version,
                update_type=update_type,
                changes=changes,
                description=description,
                severity=severity,
                migration_fn=migration_fn,
                rollback_fn=rollback_fn,
                requires_restart=requires_restart,
                breaking_changes=breaking_changes or [],
                min_version=min_version,
            )

        # Apply the platform-level update once
        prior_version = self._gov.version_manager.current_version
        if dry_run:
            apply_result = channel.apply_update(version, dry_run=True)
        else:
            # Check if already applied (can happen in multi-agent broadcast)
            updates_status = {u["version"]: u["status"] for u in channel.list_updates()}
            if updates_status.get(version) == "applied":
                apply_result = {"status": "applied", "version": version, "from": prior_version}
            else:
                apply_result = channel.apply_update(version)

        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        is_success = apply_result.get("status") in ("applied", "compatible")

        for name in agent_names:
            try:
                if is_success and not dry_run:
                    self._lifecycle.record_upgrade(
                        agent_name=name,
                        to_version=version,
                        from_version=prior_version,
                        update_type=apply_result.get("update_type", update_type),
                        changes=apply_result.get("changes", changes),
                    )
                    applied.append({"agent": name, "result": apply_result})
                elif dry_run and apply_result.get("status") == "compatible":
                    applied.append({"agent": name, "result": apply_result})
                else:
                    failed.append({"agent": name, "result": apply_result})
            except Exception as exc:
                logger.error(
                    "LifecycleUpdater.broadcast_update: agent '%s' record failed: %s", name, exc
                )
                failed.append({"agent": name, "error": str(exc)})

        logger.info(
            "LifecycleUpdater.broadcast_update v%s: applied=%d, failed=%d.",
            version, len(applied), len(failed),
        )
        return {"applied": applied, "failed": failed}

    # ── Security scan ──────────────────────────────────────────────────────

    def fleet_security_scan(self) -> dict[str, Any]:
        """
        Scan the update channel for pending security updates.

        Returns a health report with:
          - agents_with_security_updates: names
          - critical_count: number of critical patches pending
          - update_list: the raw update records
        """
        try:
            channel = self._gov.update_channel
            security_updates = channel.check_updates(update_type="security")
        except Exception as exc:
            logger.warning("LifecycleUpdater.fleet_security_scan: channel error: %s", exc)
            security_updates = []

        critical = [u for u in security_updates if u.get("severity") == "critical"]
        high = [u for u in security_updates if u.get("severity") == "high"]

        # Get all non-retired agent names for the report
        summary = self._lifecycle.summary().get("by_state", {})
        active_agents: list[str] = []
        for state in ("warm", "idle", "cold"):
            active_agents.extend(summary.get(state, []))

        # Any agent on the current version potentially needs these patches
        needs_update = active_agents if security_updates else []

        with self._lock:
            if security_updates:
                for name in active_agents:
                    self._security_alerts[name] = security_updates
            else:
                self._security_alerts.clear()

        overall_health = "healthy"
        if critical:
            overall_health = "critical"
        elif security_updates:
            overall_health = "at_risk"

        return {
            "health": overall_health,
            "agents_checked": len(active_agents),
            "security_updates_pending": len(security_updates),
            "critical_count": len(critical),
            "high_count": len(high),
            "agents_needing_update": needs_update,
            "updates": security_updates,
            "scanned_at": time.time(),
        }

    def security_alerts_for(self, agent_name: str) -> list[dict[str, Any]]:
        """Return current security alerts for one agent."""
        with self._lock:
            return list(self._security_alerts.get(agent_name, []))

    # ── Version changelog ──────────────────────────────────────────────────

    def agent_changelog(
        self, agent_name: str, limit: int = 20
    ) -> dict[str, Any]:
        """
        Return the version changelog for one agent.

        Combines:
          - LifecycleRecord.version_history   (actual deployed upgrades)
          - VersionManager.changelog()        (registered version records)
        """
        lifecycle_history = self._lifecycle.get_version_history(agent_name, limit=limit)
        vm_changelog: list[dict[str, Any]] = []
        try:
            vm_changelog = self._gov.version_manager.changelog(limit=limit)
        except Exception:
            pass

        return {
            "agent": agent_name,
            "current_version": self._lifecycle.get_version(agent_name),
            "governance_current": self._gov.version_manager.current_version,
            "lifecycle_history": lifecycle_history,
            "version_manager_log": vm_changelog,
        }

    # ── Full lifecycle + version status for API ────────────────────────────

    def full_status(self, agent_name: str) -> dict[str, Any]:
        """
        One-call status combining lifecycle state, version, and pending updates.
        Used by the /api/lifecycle/{agent_name}/version endpoint.
        """
        update_status = self.agent_update_status(agent_name)
        changelog = self.agent_changelog(agent_name, limit=10)
        compatibility: dict[str, Any] = {}
        try:
            current = self._gov.version_manager.current_version
            compatibility = self._gov.version_manager.check_compatibility(current)
        except Exception:
            pass

        return {
            **update_status,
            "changelog": changelog,
            "compatibility": compatibility,
        }

    # ── Background security scan thread ────────────────────────────────────

    def _security_scan_loop(self) -> None:
        """Background thread: periodically scan for pending security updates."""
        while True:
            time.sleep(self._scan_interval)
            try:
                report = self.fleet_security_scan()
                if report["security_updates_pending"] > 0:
                    logger.warning(
                        "LifecycleUpdater: %d security update(s) pending "
                        "(critical=%d, high=%d). Agents affected: %s",
                        report["security_updates_pending"],
                        report["critical_count"],
                        report["high_count"],
                        report["agents_needing_update"],
                    )
            except Exception as exc:
                logger.error("LifecycleUpdater._security_scan_loop error: %s", exc)

    def __repr__(self) -> str:
        with self._lock:
            alerts = sum(len(v) for v in self._security_alerts.values())
        return (
            f"LifecycleUpdater("
            f"agents={len(self._lifecycle._records)}, "
            f"security_alerts={alerts})"
        )
