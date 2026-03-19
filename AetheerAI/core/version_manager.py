"""version_manager.py — Agent versioning, upgrades, and rollback.

Closes ISSUE 5: Update & Version System Missing.

Provides:
    1. Version tracking with semantic versioning
    2. Upgrade migrations (v1.0 → v1.1 → v2.0)
    3. Compatibility checks between agent, skills, and manifest
    4. Rollback to previous versions
    5. Changelog with structured entries

Usage
-----
    vm = VersionManager(agent_name="store_bot", data_dir="workspace/versions")

    # Register a version
    vm.register_version(
        version="1.1.0",
        changes=["Added refund automation", "Fixed email templates"],
        spec_snapshot=spec.to_dict(),
    )

    # Check compatibility
    compat = vm.check_compatibility("1.1.0", required_skills=["crm", "email"])

    # Upgrade
    vm.upgrade("1.0.0", "1.1.0", migration_fn=migrate_v1_to_v1_1)

    # Rollback
    vm.rollback("1.0.0")

    # View changelog
    for entry in vm.changelog():
        print(entry)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Semantic Version ─────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")


@dataclass(frozen=True, order=True)
class SemVer:
    """Semantic version with comparison support."""
    major: int
    minor: int
    patch: int
    prerelease: str = ""

    @classmethod
    def parse(cls, version: str) -> "SemVer":
        m = _SEMVER_RE.match(version.strip())
        if not m:
            raise ValueError(f"Invalid semantic version: {version!r}")
        return cls(
            major=int(m.group(1)),
            minor=int(m.group(2)),
            patch=int(m.group(3)),
            prerelease=m.group(4) or "",
        )

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base

    def bump(self, part: str = "patch") -> "SemVer":
        if part == "major":
            return SemVer(self.major + 1, 0, 0)
        elif part == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        else:
            return SemVer(self.major, self.minor, self.patch + 1)

    def is_compatible_with(self, other: "SemVer") -> bool:
        """Check if this version is backward-compatible with other (same major)."""
        return self.major == other.major and self >= other


# ── Version Record ───────────────────────────────────────────────────────────

@dataclass
class VersionRecord:
    version: str
    changes: list[str]
    spec_snapshot: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    migrated_from: str = ""
    status: str = "active"     # active | superseded | rolled_back
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "changes": self.changes,
            "spec_snapshot": self.spec_snapshot,
            "created_at": self.created_at,
            "migrated_from": self.migrated_from,
            "status": self.status,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Migration ────────────────────────────────────────────────────────────────

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]
"""Signature: (old_spec_dict) → new_spec_dict"""


@dataclass
class MigrationStep:
    from_version: str
    to_version: str
    description: str
    migrate_fn: MigrationFn | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_version,
            "to": self.to_version,
            "description": self.description,
        }


# ── VersionManager ───────────────────────────────────────────────────────────

class VersionManager:
    """
    Version tracking, migrations, compatibility checks, and rollback.

    Parameters
    ----------
    agent_name : Agent this manager tracks.
    data_dir   : Directory to store version history.
    """

    def __init__(
        self,
        agent_name: str,
        data_dir: str | Path | None = None,
    ) -> None:
        self.agent_name = agent_name
        self._data_dir = Path(data_dir or Path(__file__).resolve().parents[1] / "workspace" / "versions")
        self._agent_dir = self._data_dir / agent_name
        self._agent_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = self._agent_dir / "version_history.json"

        self._versions: dict[str, VersionRecord] = {}
        self._current_version: str = ""
        self._migrations: list[MigrationStep] = []

        self._load()

    # ── Version registration ─────────────────────────────────────────────

    def register_version(
        self,
        version: str,
        changes: list[str],
        spec_snapshot: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a new version with changelog and spec snapshot."""
        # Validate semver
        SemVer.parse(version)

        # Mark previous versions as superseded
        if self._current_version and self._current_version in self._versions:
            self._versions[self._current_version].status = "superseded"

        record = VersionRecord(
            version=version,
            changes=changes,
            spec_snapshot=spec_snapshot,
            migrated_from=self._current_version,
            metadata=metadata or {},
        )
        self._versions[version] = record
        self._current_version = version
        self._save()

        logger.info("VersionManager[%s]: registered version %s.", self.agent_name, version)

    @property
    def current_version(self) -> str:
        return self._current_version

    def get_version(self, version: str) -> VersionRecord | None:
        return self._versions.get(version)

    # ── Upgrade / Migration ──────────────────────────────────────────────

    def register_migration(
        self,
        from_version: str,
        to_version: str,
        description: str,
        migrate_fn: MigrationFn | None = None,
    ) -> None:
        """Register a migration step between two versions."""
        self._migrations.append(MigrationStep(
            from_version=from_version,
            to_version=to_version,
            description=description,
            migrate_fn=migrate_fn,
        ))

    def upgrade(
        self,
        from_version: str,
        to_version: str,
        migration_fn: MigrationFn | None = None,
    ) -> dict[str, Any]:
        """
        Upgrade from one version to another.

        If a migration_fn is provided, it transforms the old spec to the new.
        If registered migration steps exist, they are chained automatically.
        """
        old_record = self._versions.get(from_version)
        if old_record is None:
            return {"status": "error", "message": f"Version {from_version} not found."}

        old_spec = dict(old_record.spec_snapshot)

        # Find migration path
        if migration_fn:
            new_spec = migration_fn(old_spec)
        else:
            path = self._find_migration_path(from_version, to_version)
            if not path:
                return {
                    "status": "error",
                    "message": f"No migration path from {from_version} to {to_version}.",
                }
            new_spec = old_spec
            for step in path:
                if step.migrate_fn:
                    new_spec = step.migrate_fn(new_spec)

        # Register the new version
        self.register_version(
            version=to_version,
            changes=[f"Upgraded from {from_version}"],
            spec_snapshot=new_spec,
            metadata={"upgraded_from": from_version},
        )

        logger.info("VersionManager[%s]: upgraded %s → %s.",
                     self.agent_name, from_version, to_version)

        return {
            "status": "upgraded",
            "from": from_version,
            "to": to_version,
            "spec": new_spec,
        }

    def _find_migration_path(
        self,
        from_version: str,
        to_version: str,
    ) -> list[MigrationStep] | None:
        """Find a chain of migration steps from → to. BFS."""
        # Build adjacency
        adj: dict[str, list[MigrationStep]] = {}
        for step in self._migrations:
            adj.setdefault(step.from_version, []).append(step)

        # BFS
        queue: list[tuple[str, list[MigrationStep]]] = [(from_version, [])]
        visited: set[str] = set()

        while queue:
            current, path = queue.pop(0)
            if current == to_version:
                return path
            if current in visited:
                continue
            visited.add(current)
            for step in adj.get(current, []):
                queue.append((step.to_version, path + [step]))

        return None

    # ── Rollback ─────────────────────────────────────────────────────────

    def rollback(self, to_version: str) -> dict[str, Any]:
        """
        Roll back to a previous version.

        The current version is marked as 'rolled_back'.
        The target version is restored as 'active'.
        """
        target = self._versions.get(to_version)
        if target is None:
            return {"status": "error", "message": f"Version {to_version} not found."}

        # Mark current as rolled back
        if self._current_version and self._current_version in self._versions:
            self._versions[self._current_version].status = "rolled_back"

        # Restore target
        target.status = "active"
        prev = self._current_version
        self._current_version = to_version
        self._save()

        logger.warning("VersionManager[%s]: rolled back %s → %s.",
                        self.agent_name, prev, to_version)

        return {
            "status": "rolled_back",
            "from": prev,
            "to": to_version,
            "spec": target.spec_snapshot,
        }

    # ── Compatibility Check ──────────────────────────────────────────────

    def check_compatibility(
        self,
        version: str,
        required_skills: list[str] | None = None,
        required_integrations: list[str] | None = None,
        min_version: str | None = None,
    ) -> dict[str, Any]:
        """
        Check if a version meets compatibility requirements.

        Parameters
        ----------
        version              : Version to check.
        required_skills      : Skills that must be present.
        required_integrations: Integrations that must be present.
        min_version          : Minimum acceptable version.
        """
        record = self._versions.get(version)
        if record is None:
            return {"compatible": False, "reason": f"Version {version} not found."}

        issues: list[str] = []

        # Version floor check
        if min_version:
            try:
                v = SemVer.parse(version)
                min_v = SemVer.parse(min_version)
                if v < min_v:
                    issues.append(f"Version {version} is below minimum {min_version}.")
            except ValueError as exc:
                issues.append(str(exc))

        # Skill check
        if required_skills:
            spec_skills = set(record.spec_snapshot.get("skills", []))
            missing = [s for s in required_skills if s not in spec_skills]
            if missing:
                issues.append(f"Missing required skills: {missing}")

        # Integration check
        if required_integrations:
            spec_integrations = set(record.spec_snapshot.get("integrations", []))
            missing = [i for i in required_integrations if i not in spec_integrations]
            if missing:
                issues.append(f"Missing required integrations: {missing}")

        compatible = len(issues) == 0
        return {
            "compatible": compatible,
            "version": version,
            "issues": issues,
        }

    # ── Changelog ────────────────────────────────────────────────────────

    def changelog(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return version history as a changelog, newest first."""
        records = sorted(
            self._versions.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return [
            {
                "version": r.version,
                "changes": r.changes,
                "status": r.status,
                "created_at": r.created_at,
                "migrated_from": r.migrated_from,
            }
            for r in records[:limit]
        ]

    def list_versions(self) -> list[str]:
        """Return all registered versions, sorted."""
        versions = list(self._versions.keys())
        try:
            versions.sort(key=lambda v: SemVer.parse(v))
        except ValueError:
            versions.sort()
        return versions

    # ── Persistence ──────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data = {
                "agent_name": self.agent_name,
                "current_version": self._current_version,
                "versions": {k: v.to_dict() for k, v in self._versions.items()},
                "migrations": [m.to_dict() for m in self._migrations],
                "saved_at": time.time(),
            }
            tmp = self._history_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self._history_path)
        except OSError as exc:
            logger.warning("VersionManager: save failed: %s", exc)

    def _load(self) -> None:
        if not self._history_path.exists():
            return
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
            self._current_version = data.get("current_version", "")
            for ver, vdata in data.get("versions", {}).items():
                self._versions[ver] = VersionRecord.from_dict(vdata)
            logger.info("VersionManager[%s]: loaded %d versions (current: %s).",
                        self.agent_name, len(self._versions), self._current_version)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("VersionManager: load failed: %s", exc)

    def __repr__(self) -> str:
        return (
            f"VersionManager(agent={self.agent_name!r}, "
            f"current={self._current_version!r}, "
            f"versions={len(self._versions)})"
        )
