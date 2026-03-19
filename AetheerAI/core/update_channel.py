"""update_channel.py — Update & patch distribution channel.

Closes GAP 4: Update & Patch Channel Missing.

Provides a full update lifecycle for deployed agents:
    1. Security updates    — Urgent patches with forced application
    2. Feature upgrades    — New capabilities with compatibility checks
    3. Compatibility fixes — Resolve breaking changes between components
    4. Bug patches         — Targeted fixes with rollback support

Architecture
------------
    UpdateChannel  ──► VersionManager  (version tracking + migration)
                   ──► Update Registry (available updates)
                   ──► Patch Applier   (safe apply + rollback)

Usage
-----
    channel = UpdateChannel(agent_name="store_bot", version_manager=vm)

    # Publish an update
    channel.publish_update(
        version="1.1.0",
        update_type="feature",
        changes=["Added refund automation"],
        migration_fn=migrate_v1_to_v1_1,
    )

    # Check for updates
    available = channel.check_updates()

    # Apply an update
    result = channel.apply_update("1.1.0")

    # Rollback if issues
    result = channel.rollback()

    # Security patch (forced)
    channel.publish_security_patch(
        version="1.0.1",
        cve="CVE-2026-1234",
        description="Fix credential leak",
        patch_fn=fix_credential_leak,
    )
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Update Types ────────────────────────────────────────────────────────────

class UpdateType(str, Enum):
    SECURITY = "security"
    FEATURE = "feature"
    COMPATIBILITY = "compatibility"
    BUGFIX = "bugfix"


class UpdateStatus(str, Enum):
    AVAILABLE = "available"
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


# ── Update Record ───────────────────────────────────────────────────────────

@dataclass
class UpdateRecord:
    version: str
    update_type: str       # security | feature | compatibility | bugfix
    changes: list[str]
    description: str = ""
    severity: str = "normal"   # low | normal | high | critical
    status: str = "available"
    from_version: str = ""
    published_at: float = field(default_factory=time.time)
    applied_at: float = 0.0
    requires_restart: bool = False
    breaking_changes: list[str] = field(default_factory=list)
    min_version: str = ""      # minimum version this update applies to
    cve: str = ""              # CVE identifier for security patches
    migration_fn: Callable | None = field(default=None, repr=False)
    rollback_fn: Callable | None = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "update_type": self.update_type,
            "changes": self.changes,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "from_version": self.from_version,
            "published_at": self.published_at,
            "applied_at": self.applied_at,
            "requires_restart": self.requires_restart,
            "breaking_changes": self.breaking_changes,
            "min_version": self.min_version,
            "cve": self.cve,
        }


# ── UpdateChannel ───────────────────────────────────────────────────────────

class UpdateChannel:
    """
    Update & patch distribution channel for deployed agents.

    Manages the full update lifecycle: publish, check, apply, rollback.

    Parameters
    ----------
    agent_name       : Agent to manage updates for.
    version_manager  : VersionManager instance for version tracking.
    data_dir         : Directory to persist update registry.
    auto_apply_security : Auto-apply critical security patches.
    """

    def __init__(
        self,
        agent_name: str,
        version_manager: Any,
        data_dir: str | Path | None = None,
        auto_apply_security: bool = True,
    ) -> None:
        self.agent_name = agent_name
        self._vm = version_manager
        self._auto_apply_security = auto_apply_security

        self._data_dir = Path(data_dir or Path(__file__).resolve().parents[1] / "workspace" / "updates")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path = self._data_dir / f"{agent_name}_updates.json"

        self._updates: dict[str, UpdateRecord] = {}
        self._apply_history: list[dict[str, Any]] = []
        self._load()

    # ── Publish Updates ───────────────────────────────────────────────────

    def publish_update(
        self,
        version: str,
        update_type: str,
        changes: list[str],
        description: str = "",
        severity: str = "normal",
        migration_fn: Callable | None = None,
        rollback_fn: Callable | None = None,
        requires_restart: bool = False,
        breaking_changes: list[str] | None = None,
        min_version: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> UpdateRecord:
        """
        Publish a new update to the channel.

        Parameters
        ----------
        version        : Target version (semver).
        update_type    : "security", "feature", "compatibility", "bugfix".
        changes        : List of change descriptions.
        migration_fn   : (old_spec) -> new_spec transformation.
        rollback_fn    : (new_spec) -> old_spec reverse transformation.
        """
        record = UpdateRecord(
            version=version,
            update_type=update_type,
            changes=changes,
            description=description,
            severity=severity,
            from_version=self._vm.current_version,
            migration_fn=migration_fn,
            rollback_fn=rollback_fn,
            requires_restart=requires_restart,
            breaking_changes=breaking_changes or [],
            min_version=min_version,
            metadata=metadata or {},
        )

        self._updates[version] = record
        self._save()

        logger.info("UpdateChannel[%s]: published %s update %s (%s).",
                    self.agent_name, update_type, version, severity)

        # Auto-apply critical security patches
        if (
            self._auto_apply_security
            and update_type == "security"
            and severity == "critical"
        ):
            logger.warning("UpdateChannel[%s]: auto-applying critical security patch %s.",
                          self.agent_name, version)
            self.apply_update(version)

        return record

    def publish_security_patch(
        self,
        version: str,
        cve: str,
        description: str,
        patch_fn: Callable | None = None,
        rollback_fn: Callable | None = None,
        severity: str = "critical",
    ) -> UpdateRecord:
        """Convenience: publish a security patch with CVE tracking."""
        record = self.publish_update(
            version=version,
            update_type="security",
            changes=[f"Security fix: {cve} — {description}"],
            description=description,
            severity=severity,
            migration_fn=patch_fn,
            rollback_fn=rollback_fn,
            metadata={"cve": cve},
        )
        record.cve = cve
        self._save()
        return record

    # ── Check for Updates ─────────────────────────────────────────────────

    def check_updates(
        self,
        update_type: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Check for available updates.

        Returns updates that haven't been applied yet.
        """
        available = []
        for rec in self._updates.values():
            if rec.status != "available":
                continue
            if update_type and rec.update_type != update_type:
                continue
            if severity and rec.severity != severity:
                continue

            # Check min_version compatibility
            if rec.min_version and self._vm.current_version:
                try:
                    from .version_manager import SemVer
                    current = SemVer.parse(self._vm.current_version)
                    minimum = SemVer.parse(rec.min_version)
                    if current < minimum:
                        continue  # Not eligible for this update
                except (ValueError, ImportError):
                    pass

            available.append(rec.to_dict())

        # Sort: security first, then by severity, then by version
        severity_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        type_order = {"security": 0, "bugfix": 1, "compatibility": 2, "feature": 3}
        available.sort(key=lambda u: (
            type_order.get(u["update_type"], 9),
            severity_order.get(u["severity"], 9),
        ))

        return available

    def has_security_updates(self) -> bool:
        """Check if there are pending security updates."""
        return any(
            r.status == "available" and r.update_type == "security"
            for r in self._updates.values()
        )

    # ── Apply Update ──────────────────────────────────────────────────────

    def apply_update(
        self,
        version: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Apply an update.

        Steps:
            1. Validate the update exists and is applicable
            2. Run compatibility check
            3. Apply migration function (if provided)
            4. Register new version in VersionManager
            5. Record result

        Parameters
        ----------
        version : Target version to apply.
        dry_run : If True, check compatibility without applying.
        """
        record = self._updates.get(version)
        if record is None:
            return {"status": "error", "message": f"Update {version} not found."}

        if record.status == "applied":
            return {"status": "error", "message": f"Update {version} already applied."}

        current = self._vm.current_version

        # Step 1: Compatibility check
        if record.min_version and current:
            try:
                from .version_manager import SemVer
                cur_v = SemVer.parse(current)
                min_v = SemVer.parse(record.min_version)
                if cur_v < min_v:
                    return {
                        "status": "error",
                        "message": f"Current version {current} below minimum {record.min_version}.",
                    }
            except (ValueError, ImportError):
                pass

        if dry_run:
            return {
                "status": "compatible",
                "current": current,
                "target": version,
                "breaking_changes": record.breaking_changes,
                "requires_restart": record.requires_restart,
            }

        # Step 2: Get current spec
        current_record = self._vm.get_version(current) if current else None
        old_spec = current_record.spec_snapshot if current_record else {}

        # Step 3: Apply migration
        new_spec = dict(old_spec)
        if record.migration_fn is not None:
            try:
                new_spec = record.migration_fn(new_spec)
            except Exception as exc:
                record.status = "failed"
                self._save()
                error_msg = f"Migration failed: {exc}"
                logger.error("UpdateChannel[%s]: %s", self.agent_name, error_msg)
                self._apply_history.append({
                    "version": version,
                    "status": "failed",
                    "error": error_msg,
                    "timestamp": time.time(),
                })
                return {"status": "error", "message": error_msg}

        # Step 4: Register in VersionManager
        try:
            self._vm.register_version(
                version=version,
                changes=record.changes,
                spec_snapshot=new_spec,
                metadata={
                    "update_type": record.update_type,
                    "severity": record.severity,
                    "cve": record.cve,
                    "from_version": current,
                },
            )
        except Exception as exc:
            record.status = "failed"
            self._save()
            return {"status": "error", "message": f"Version registration failed: {exc}"}

        # Step 5: Record success
        record.status = "applied"
        record.applied_at = time.time()
        self._save()

        self._apply_history.append({
            "version": version,
            "from": current,
            "status": "applied",
            "update_type": record.update_type,
            "timestamp": time.time(),
        })

        logger.info("UpdateChannel[%s]: applied %s update %s (from %s).",
                    self.agent_name, record.update_type, version, current)

        return {
            "status": "applied",
            "version": version,
            "from": current,
            "update_type": record.update_type,
            "changes": record.changes,
            "requires_restart": record.requires_restart,
        }

    # ── Rollback ──────────────────────────────────────────────────────────

    def rollback(self, to_version: str | None = None) -> dict[str, Any]:
        """
        Rollback to a previous version.

        If to_version is None, rolls back to the version before the
        most recent update.
        """
        current = self._vm.current_version
        if not current:
            return {"status": "error", "message": "No current version to rollback from."}

        # Determine target
        if to_version is None:
            current_record = self._vm.get_version(current)
            if current_record and current_record.migrated_from:
                to_version = current_record.migrated_from
            else:
                return {"status": "error", "message": "No previous version to rollback to."}

        # Execute rollback via VersionManager
        result = self._vm.rollback(to_version)

        if result.get("status") == "rolled_back":
            # Update the update record status
            update_rec = self._updates.get(current)
            if update_rec:
                update_rec.status = "rolled_back"
                self._save()

            self._apply_history.append({
                "version": to_version,
                "from": current,
                "status": "rolled_back",
                "timestamp": time.time(),
            })

            logger.warning("UpdateChannel[%s]: rolled back %s -> %s.",
                          self.agent_name, current, to_version)

        return result

    # ── Update Status ─────────────────────────────────────────────────────

    def update_status(self) -> dict[str, Any]:
        """Return overview of update channel status."""
        available = sum(1 for r in self._updates.values() if r.status == "available")
        applied = sum(1 for r in self._updates.values() if r.status == "applied")
        failed = sum(1 for r in self._updates.values() if r.status == "failed")
        security_pending = sum(
            1 for r in self._updates.values()
            if r.status == "available" and r.update_type == "security"
        )

        return {
            "agent": self.agent_name,
            "current_version": self._vm.current_version,
            "available_updates": available,
            "applied_updates": applied,
            "failed_updates": failed,
            "security_pending": security_pending,
            "auto_apply_security": self._auto_apply_security,
            "recent_history": self._apply_history[-5:],
        }

    def list_updates(
        self,
        status: str | None = None,
        update_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all updates with optional filters."""
        results = list(self._updates.values())
        if status:
            results = [r for r in results if r.status == status]
        if update_type:
            results = [r for r in results if r.update_type == update_type]
        return [r.to_dict() for r in sorted(results, key=lambda r: r.published_at, reverse=True)]

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data = {
                "agent_name": self.agent_name,
                "updates": {k: v.to_dict() for k, v in self._updates.items()},
                "history": self._apply_history[-100:],
                "saved_at": time.time(),
            }
            tmp = self._registry_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self._registry_path)
        except OSError as exc:
            logger.warning("UpdateChannel: save failed: %s", exc)

    def _load(self) -> None:
        if not self._registry_path.exists():
            return
        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            for ver, udata in data.get("updates", {}).items():
                self._updates[ver] = UpdateRecord(**{
                    k: v for k, v in udata.items()
                    if k in UpdateRecord.__dataclass_fields__
                    and k not in ("migration_fn", "rollback_fn")
                })
            self._apply_history = data.get("history", [])
            logger.info("UpdateChannel[%s]: loaded %d updates.",
                       self.agent_name, len(self._updates))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("UpdateChannel: load failed: %s", exc)

    def __repr__(self) -> str:
        available = sum(1 for r in self._updates.values() if r.status == "available")
        return (
            f"UpdateChannel(agent={self.agent_name!r}, "
            f"current={self._vm.current_version!r}, "
            f"available={available})"
        )

    # ── Patch Verification ────────────────────────────────────────────────

    def verify_update(
        self,
        version: str,
        verify_fn: Callable | None = None,
    ) -> dict[str, Any]:
        """
        Verify an update before application.

        Runs a verification function against the update to check
        integrity, compatibility, and safety.

        Parameters
        ----------
        version   : Version to verify.
        verify_fn : (UpdateRecord) -> (bool, str) verification callable.
                    Returns (passed, message).
        """
        record = self._updates.get(version)
        if record is None:
            return {"status": "error", "message": f"Update {version} not found."}

        checks: list[dict[str, Any]] = []

        # 1. Version format check
        try:
            from .version_manager import SemVer
            SemVer.parse(version)
            checks.append({"check": "version_format", "passed": True})
        except (ValueError, ImportError):
            checks.append({"check": "version_format", "passed": False, "error": "Invalid semver"})

        # 2. Has changes listed
        has_changes = bool(record.changes)
        checks.append({"check": "changelog", "passed": has_changes})

        # 3. Breaking changes documented
        if record.update_type != "bugfix":
            checks.append({
                "check": "breaking_changes_documented",
                "passed": True,  # informational
                "breaking": record.breaking_changes,
            })

        # 4. Migration function provided for non-trivial updates
        has_migration = record.migration_fn is not None
        checks.append({
            "check": "migration_fn",
            "passed": has_migration or record.update_type == "bugfix",
            "has_migration": has_migration,
        })

        # 5. Custom verification
        if verify_fn is not None:
            try:
                passed, message = verify_fn(record)
                checks.append({"check": "custom", "passed": passed, "message": message})
            except Exception as exc:
                checks.append({"check": "custom", "passed": False, "error": str(exc)})

        all_passed = all(c["passed"] for c in checks)
        return {
            "status": "verified" if all_passed else "failed",
            "version": version,
            "checks": checks,
            "all_passed": all_passed,
        }

    # ── Staged Rollout ────────────────────────────────────────────────────

    def apply_staged(
        self,
        version: str,
        pre_check_fn: Callable | None = None,
        post_check_fn: Callable | None = None,
    ) -> dict[str, Any]:
        """
        Apply an update with staged validation.

        Steps:
            1. Verify the update
            2. Run pre-check (if provided)
            3. Apply the update
            4. Run post-check (if provided) — rollback on failure

        Parameters
        ----------
        version       : Version to apply.
        pre_check_fn  : () -> (bool, str) — runs before migration.
        post_check_fn : () -> (bool, str) — runs after migration, rollback on fail.
        """
        # Step 1: Verify
        verify_result = self.verify_update(version)
        if not verify_result["all_passed"]:
            return {
                "status": "verification_failed",
                "verification": verify_result,
            }

        # Step 2: Pre-check
        if pre_check_fn is not None:
            try:
                passed, message = pre_check_fn()
                if not passed:
                    return {
                        "status": "pre_check_failed",
                        "message": message,
                    }
            except Exception as exc:
                return {"status": "pre_check_error", "message": str(exc)}

        prior_version = self._vm.current_version

        # Step 3: Apply
        apply_result = self.apply_update(version)
        if apply_result.get("status") != "applied":
            return apply_result

        # Step 4: Post-check
        if post_check_fn is not None:
            try:
                passed, message = post_check_fn()
                if not passed:
                    # Rollback
                    logger.warning(
                        "UpdateChannel[%s]: post-check failed for %s — rolling back. Reason: %s",
                        self.agent_name, version, message,
                    )
                    self.rollback(prior_version)
                    return {
                        "status": "rolled_back",
                        "reason": f"Post-check failed: {message}",
                        "rolled_back_to": prior_version,
                    }
            except Exception as exc:
                logger.error(
                    "UpdateChannel[%s]: post-check error for %s — rolling back.",
                    self.agent_name, version,
                )
                self.rollback(prior_version)
                return {
                    "status": "rolled_back",
                    "reason": f"Post-check error: {exc}",
                    "rolled_back_to": prior_version,
                }

        return {
            "status": "applied",
            "version": version,
            "from": prior_version,
            "staged": True,
        }
