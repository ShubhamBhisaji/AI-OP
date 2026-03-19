"""registry/marketplace.py — Agent discovery and marketplace for AetheerAI.

Addresses "Limited Marketplace Readiness" by providing:

  - AgentListing: a rich searchable metadata record for published agents.
  - AgentMarketplace: discovery engine (search by role, skill, category, tag).
  - VersionCompatibilityChecker: semantic-version compatibility matrix.
  - LicenseEnforcer: license type validation and enforcement.
  - DependencyManager: dependency graph resolution with cycle detection.

Design
------
                        ┌──────────────────────┐
                        │  AgentMarketplace    │
                        │  ┌────────────────┐  │
                        │  │ AgentListing[] │  │  ← search / discover
                        │  └────────────────┘  │
                        │  VersionChecker       │  ← compatible?
                        │  LicenseEnforcer      │  ← allowed?
                        │  DependencyManager    │  ← resolve deps
                        └──────────────────────┘

Usage
-----
    from AetheerAI.registry.marketplace import AgentMarketplace, AgentListing

    market = AgentMarketplace()

    # Publish an agent
    market.publish(AgentListing(
        name="research-bot", version="1.2.0",
        description="Deep research agent with citation support.",
        categories=["research", "knowledge"],
        skills=["web_search", "summarization"],
        license="MIT",
        requires_aetheerai=">=1.0.0",
        dependencies=["citation-formatter>=0.5.0"],
    ))

    # Discover
    results = market.search("research")
    listing = market.get("research-bot")

    # Version check
    from AetheerAI.registry.marketplace import VersionCompatibilityChecker
    checker = VersionCompatibilityChecker(current_version="1.2.0")
    checker.is_compatible(">=1.0.0")   # True

    # License enforcement
    from AetheerAI.registry.marketplace import LicenseEnforcer
    enforcer = LicenseEnforcer(allowed=["MIT", "Apache-2.0"])
    enforcer.assert_allowed("MIT")     # OK
    enforcer.assert_allowed("GPL-3.0") # raises LicenseViolation

    # Dependency resolution
    from AetheerAI.registry.marketplace import DependencyManager
    dm = DependencyManager(market)
    resolved = dm.resolve("research-bot")
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────


class MarketplaceError(RuntimeError):
    """Base class for marketplace errors."""


class AgentNotFound(MarketplaceError):
    """Raised when a requested agent listing does not exist."""


class LicenseViolation(MarketplaceError):
    """Raised when an agent's license is not in the permitted set."""


class VersionIncompatible(MarketplaceError):
    """Raised when an agent's AetheerAI version requirement is not satisfied."""


class DependencyCycle(MarketplaceError):
    """Raised when circular dependencies are detected."""


class DependencyNotFound(MarketplaceError):
    """Raised when a dependency cannot be resolved."""


# ── Semantic version helpers ──────────────────────────────────────────────────

_VER_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[.\-].*)?$")
_CONSTRAINT_RE = re.compile(
    r"^(>=|<=|==|!=|>|<|~=)\s*(\d+(?:\.\d+)*(?:[.\-].*)?)$"
)


def _parse_version(ver: str) -> tuple[int, int, int]:
    """Parse a semver string into (major, minor, patch). Extras ignored."""
    m = _VER_RE.match(ver.strip())
    if not m:
        raise ValueError(f"Cannot parse version: {ver!r}")
    return (
        int(m.group(1) or 0),
        int(m.group(2) or 0),
        int(m.group(3) or 0),
    )


def _version_satisfies(version: str, constraint: str) -> bool:
    """
    Check whether *version* satisfies *constraint*.

    Supported operators: >=, <=, ==, !=, >, <, ~= (compatible release)
    Multiple constraints may be comma-separated: ">=1.0,<2.0"
    """
    constraint = constraint.strip()
    if not constraint or constraint == "*":
        return True
    parts = [c.strip() for c in constraint.split(",") if c.strip()]
    for part in parts:
        m = _CONSTRAINT_RE.match(part)
        if not m:
            logger.warning("Cannot parse version constraint %r — skipping.", part)
            continue
        op, req = m.group(1), m.group(2)
        try:
            v = _parse_version(version)
            r = _parse_version(req)
        except ValueError:
            logger.warning("Version parse failure: %r vs %r", version, req)
            continue
        ops = {
            ">=": v >= r,
            "<=": v <= r,
            "==": v == r,
            "!=": v != r,
            ">":  v > r,
            "<":  v < r,
            "~=": v[0] == r[0] and v[1:] >= r[1:],   # compatible release
        }
        if not ops.get(op, True):
            return False
    return True


# ── Version compatibility checker ─────────────────────────────────────────────

class VersionCompatibilityChecker:
    """
    Checks whether a constraint string is satisfied by the running version.

    Parameters
    ----------
    current_version : The version of AetheerAI (or any component) that is
                      currently running, e.g. "1.2.3".
    """

    def __init__(self, current_version: str = "1.0.0") -> None:
        self.current_version = current_version
        try:
            self._parsed = _parse_version(current_version)
        except ValueError:
            logger.warning("Could not parse current_version %r; defaulting to 1.0.0", current_version)
            self._parsed = (1, 0, 0)
            self.current_version = "1.0.0"

    def is_compatible(self, constraint: str) -> bool:
        """Return True if *constraint* is satisfied by the current version."""
        return _version_satisfies(self.current_version, constraint)

    def assert_compatible(self, constraint: str, name: str = "") -> None:
        """
        Raise VersionIncompatible if the constraint is not satisfied.

        Parameters
        ----------
        constraint : Version constraint, e.g. ">=1.0.0,<2.0.0"
        name       : Human-readable name for the component being checked.
        """
        if not self.is_compatible(constraint):
            label = f"'{name}' " if name else ""
            raise VersionIncompatible(
                f"Component {label}requires AetheerAI {constraint}, "
                f"but running {self.current_version}."
            )

    def find_compatible(
        self,
        listings: list["AgentListing"],
    ) -> list["AgentListing"]:
        """Filter a list of listings to those compatible with the running version."""
        return [
            lst for lst in listings
            if not lst.requires_aetheerai
            or self.is_compatible(lst.requires_aetheerai)
        ]


# ── License enforcer ──────────────────────────────────────────────────────────

#: SPDX-compatible license identifiers considered open.
OPEN_LICENSES: frozenset[str] = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause",
    "ISC", "MPL-2.0", "LGPL-2.1", "LGPL-3.0", "CC0-1.0",
})

#: Licenses that are copyleft (require source disclosure on distribution).
COPYLEFT_LICENSES: frozenset[str] = frozenset({
    "GPL-2.0", "GPL-3.0", "AGPL-3.0", "EUPL-1.2",
})


class LicenseEnforcer:
    """
    Enforces which software licenses are permitted in a deployment.

    Parameters
    ----------
    allowed : Explicit set of permitted SPDX license identifiers.
              If None, all open licenses are permitted; copyleft is warned.
    deny    : Explicit set of denied license identifiers (overrides allowed).
    """

    def __init__(
        self,
        allowed: list[str] | None = None,
        deny: list[str] | None = None,
    ) -> None:
        self._allowed: frozenset[str] | None = (
            frozenset(allowed) if allowed is not None else None
        )
        self._deny: frozenset[str] = frozenset(deny or [])

    def is_allowed(self, license_id: str) -> bool:
        """Return True if the license is permitted."""
        if license_id in self._deny:
            return False
        if self._allowed is not None:
            return license_id in self._allowed
        # Default: allow open licenses, warn on copyleft, deny unknown
        if license_id in OPEN_LICENSES:
            return True
        if license_id in COPYLEFT_LICENSES:
            logger.warning(
                "LicenseEnforcer: copyleft license %r may impose redistribution "
                "obligations. Review before distributing.", license_id
            )
            return True   # warn but allow by default
        # Unknown license — allow but log
        logger.warning(
            "LicenseEnforcer: unknown license %r; allowing but review recommended.",
            license_id,
        )
        return True

    def assert_allowed(self, license_id: str, agent_name: str = "") -> None:
        """Raise LicenseViolation if the license is not permitted."""
        if not self.is_allowed(license_id):
            label = f" (agent: {agent_name!r})" if agent_name else ""
            raise LicenseViolation(
                f"License '{license_id}' is not permitted in this deployment{label}."
            )

    def classify(self, license_id: str) -> str:
        """Return 'open', 'copyleft', or 'unknown'."""
        if license_id in OPEN_LICENSES:
            return "open"
        if license_id in COPYLEFT_LICENSES:
            return "copyleft"
        return "unknown"


# ── Agent listing ─────────────────────────────────────────────────────────────

@dataclass
class AgentListing:
    """
    Marketplace metadata for a publishable / discoverable agent.

    Similar to a package.json but for AetheerAI agents.
    """
    name: str
    version: str = "1.0.0"
    description: str = ""
    categories: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    author: str = ""
    license: str = "MIT"
    homepage: str = ""
    requires_aetheerai: str = ">=1.0.0"
    dependencies: list[str] = field(default_factory=list)   # "name>=version"
    permission_level: int = 1
    published_at: float = field(default_factory=time.time)
    downloads: int = 0
    rating: float = 0.0

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "categories": self.categories,
            "skills": self.skills,
            "tools": self.tools,
            "tags": self.tags,
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "requires_aetheerai": self.requires_aetheerai,
            "dependencies": self.dependencies,
            "permission_level": self.permission_level,
            "published_at": self.published_at,
            "downloads": self.downloads,
            "rating": self.rating,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentListing":
        return cls(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            categories=data.get("categories", []),
            skills=data.get("skills", []),
            tools=data.get("tools", []),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            license=data.get("license", "MIT"),
            homepage=data.get("homepage", ""),
            requires_aetheerai=data.get("requires_aetheerai", ">=1.0.0"),
            dependencies=data.get("dependencies", []),
            permission_level=data.get("permission_level", 1),
            published_at=data.get("published_at", time.time()),
            downloads=data.get("downloads", 0),
            rating=data.get("rating", 0.0),
        )


# ── Dependency manager ────────────────────────────────────────────────────────

@dataclass
class ResolvedDep:
    name: str
    version_constraint: str
    listing: AgentListing | None = None
    satisfied: bool = False


class DependencyManager:
    """
    Resolves an agent's dependency graph.

    Resolution strategy
    -------------------
    1. Parse dependency strings "name>=1.0.0" into (name, constraint).
    2. Look up each dependency in the marketplace.
    3. Check version compatibility.
    4. Recursively resolve transitive dependencies.
    5. Detect and reject circular dependencies.
    """

    _DEP_RE = re.compile(r"^([A-Za-z0-9_\-\.]+)((?:>=|<=|==|!=|>|<|~=)\S+)?$")

    def __init__(self, marketplace: "AgentMarketplace") -> None:
        self._market = marketplace

    # ── Public ─────────────────────────────────────────────────────────────

    def resolve(
        self,
        agent_name: str,
        _visited: set[str] | None = None,
    ) -> list[ResolvedDep]:
        """
        Recursively resolve all dependencies for *agent_name*.

        Returns
        -------
        list[ResolvedDep]
            Flat list of all direct and transitive dependencies in
            topological order.

        Raises
        ------
        AgentNotFound    — a dependency is not in the marketplace.
        DependencyCycle  — circular dependency detected.
        VersionIncompatible — a dependency's version constraint is not met.
        """
        if _visited is None:
            _visited = set()

        listing = self._market.get(agent_name)
        if listing is None:
            raise AgentNotFound(f"Agent '{agent_name}' not found in marketplace.")

        if agent_name in _visited:
            raise DependencyCycle(
                f"Circular dependency detected: '{agent_name}' is already "
                f"in the resolution chain: {sorted(_visited)}"
            )
        _visited.add(agent_name)

        resolved: list[ResolvedDep] = []
        for dep_str in listing.dependencies:
            name, constraint = self._parse_dep(dep_str)
            dep_listing = self._market.get(name)
            dep = ResolvedDep(
                name=name,
                version_constraint=constraint or "*",
                listing=dep_listing,
                satisfied=False,
            )
            if dep_listing is None:
                logger.warning(
                    "DependencyManager: dependency '%s' not found in marketplace.", name
                )
                resolved.append(dep)
                continue

            # Version check
            if constraint and not _version_satisfies(dep_listing.version, constraint):
                raise VersionIncompatible(
                    f"Dependency '{name}' version {dep_listing.version} does not "
                    f"satisfy constraint '{constraint}' required by '{agent_name}'."
                )

            dep.satisfied = True
            resolved.append(dep)

            # Recurse for transitive deps
            transitive = self.resolve(name, _visited=set(_visited))
            for t in transitive:
                if not any(r.name == t.name for r in resolved):
                    resolved.append(t)

        return resolved

    def check(self, agent_name: str) -> dict[str, Any]:
        """
        Non-raising dependency check.  Returns a report dict with keys:
        ``resolved``, ``missing``, ``version_conflicts``.
        """
        report: dict[str, Any] = {
            "resolved": [],
            "missing": [],
            "version_conflicts": [],
        }
        try:
            deps = self.resolve(agent_name)
            for d in deps:
                if d.satisfied:
                    report["resolved"].append(d.name)
                else:
                    report["missing"].append(d.name)
        except VersionIncompatible as exc:
            report["version_conflicts"].append(str(exc))
        except AgentNotFound as exc:
            report["missing"].append(str(exc))
        return report

    @staticmethod
    def _parse_dep(dep_str: str) -> tuple[str, str]:
        """Parse 'name>=1.0.0' → ('name', '>=1.0.0')."""
        m = DependencyManager._DEP_RE.match(dep_str.strip())
        if not m:
            return dep_str.strip(), ""
        return m.group(1), m.group(2) or ""


# ── Agent marketplace ─────────────────────────────────────────────────────────

class AgentMarketplace:
    """
    In-process agent discovery catalogue with optional JSON persistence.

    Features
    --------
    - Full-text and field search (name, description, skills, categories, tags)
    - Version-aware retrieval (latest or specific)
    - License validation on publish / install
    - Dependency resolution via DependencyManager
    - JSON persistence to ``marketplace_store.json`` next to this file
    """

    _STORE_FILE = Path(__file__).parent / "marketplace_store.json"

    def __init__(
        self,
        persist: bool = True,
        version_checker: VersionCompatibilityChecker | None = None,
        license_enforcer: LicenseEnforcer | None = None,
    ) -> None:
        self._listings: dict[str, AgentListing] = {}  # name → listing
        self._persist = persist
        self._lock = threading.Lock()
        self.version_checker: VersionCompatibilityChecker = (
            version_checker or VersionCompatibilityChecker()
        )
        self.license_enforcer: LicenseEnforcer = (
            license_enforcer or LicenseEnforcer()
        )
        self.dependency_manager = DependencyManager(self)
        if persist and self._STORE_FILE.exists():
            self._load()

    # ── Publishing ─────────────────────────────────────────────────────────

    def publish(
        self,
        listing: AgentListing,
        validate_license: bool = True,
        validate_compat: bool = True,
    ) -> AgentListing:
        """
        Publish an agent to the marketplace.

        Parameters
        ----------
        listing          : The AgentListing to publish.
        validate_license : Raise LicenseViolation if license is not permitted.
        validate_compat  : Raise VersionIncompatible if AetheerAI version req
                           is not satisfied by the current version checker.
        """
        if validate_license:
            self.license_enforcer.assert_allowed(listing.license, listing.name)
        if validate_compat and listing.requires_aetheerai:
            self.version_checker.assert_compatible(
                listing.requires_aetheerai, listing.name
            )

        with self._lock:
            self._listings[listing.name] = listing
            logger.info(
                "Marketplace: published agent '%s' v%s.", listing.name, listing.version
            )
            self._save()

        return listing

    def unpublish(self, name: str) -> bool:
        with self._lock:
            if name not in self._listings:
                return False
            del self._listings[name]
            self._save()
            logger.info("Marketplace: unpublished agent '%s'.", name)
            return True

    # ── Discovery ──────────────────────────────────────────────────────────

    def get(self, name: str) -> AgentListing | None:
        """Return listing by exact name, or None."""
        return self._listings.get(name)

    def list_all(self) -> list[AgentListing]:
        """Return all published listings sorted by name."""
        return sorted(self._listings.values(), key=lambda x: x.name)

    def search(
        self,
        query: str = "",
        categories: list[str] | None = None,
        skills: list[str] | None = None,
        tags: list[str] | None = None,
        min_rating: float = 0.0,
        compatible_only: bool = True,
        limit: int = 50,
    ) -> list[AgentListing]:
        """
        Search the marketplace.

        Parameters
        ----------
        query          : Free-text search across name, description, tags.
        categories     : Filter by any of these category strings.
        skills         : Filter agents that have ALL of these skills.
        tags           : Filter agents that have ANY of these tags.
        min_rating     : Minimum average rating (0–5).
        compatible_only: Only return agents compatible with current version.
        limit          : Maximum results to return.
        """
        query_lower = query.lower() if query else ""
        results: list[AgentListing] = []

        for listing in self._listings.values():
            # Version compatibility gate
            if compatible_only and listing.requires_aetheerai:
                if not self.version_checker.is_compatible(listing.requires_aetheerai):
                    continue

            # Rating filter
            if listing.rating < min_rating:
                continue

            # Category filter (any match)
            if categories:
                if not any(
                    c.lower() in [x.lower() for x in listing.categories]
                    for c in categories
                ):
                    continue

            # Skills filter (ALL must match)
            if skills:
                listing_skills_lower = [s.lower() for s in listing.skills]
                if not all(s.lower() in listing_skills_lower for s in skills):
                    continue

            # Tags filter (any match)
            if tags:
                listing_tags_lower = [t.lower() for t in listing.tags]
                if not any(t.lower() in listing_tags_lower for t in tags):
                    continue

            # Free-text filter
            if query_lower:
                searchable = " ".join([
                    listing.name,
                    listing.description,
                    " ".join(listing.tags),
                    " ".join(listing.categories),
                ]).lower()
                if query_lower not in searchable:
                    continue

            results.append(listing)

        # Sort: rating desc, then name asc
        results.sort(key=lambda x: (-x.rating, x.name))
        return results[:limit]

    def install(self, name: str) -> AgentListing:
        """
        'Install' an agent: validate, resolve deps, increment download count.

        Returns the listing. Raises if validation fails.
        """
        listing = self.get(name)
        if listing is None:
            raise AgentNotFound(f"Agent '{name}' not found in marketplace.")

        # Full validation
        self.license_enforcer.assert_allowed(listing.license, name)
        if listing.requires_aetheerai:
            self.version_checker.assert_compatible(listing.requires_aetheerai, name)

        # Dependency check
        dep_report = self.dependency_manager.check(name)
        if dep_report["missing"]:
            logger.warning(
                "Marketplace: agent '%s' has unresolved dependencies: %s",
                name, dep_report["missing"],
            )
        if dep_report["version_conflicts"]:
            raise VersionIncompatible(
                f"Agent '{name}' has version conflicts: {dep_report['version_conflicts']}"
            )

        with self._lock:
            listing.downloads += 1
            self._save()

        logger.info("Marketplace: installed agent '%s' v%s.", name, listing.version)
        return listing

    # ── Introspection ──────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the marketplace."""
        listings = list(self._listings.values())
        categories: set[str] = set()
        licenses: dict[str, int] = {}
        for lst in listings:
            categories.update(lst.categories)
            licenses[lst.license] = licenses.get(lst.license, 0) + 1
        return {
            "total_agents": len(listings),
            "categories": sorted(categories),
            "licenses": licenses,
            "top_rated": [
                {"name": x.name, "rating": x.rating}
                for x in sorted(listings, key=lambda x: -x.rating)[:5]
            ],
            "most_downloaded": [
                {"name": x.name, "downloads": x.downloads}
                for x in sorted(listings, key=lambda x: -x.downloads)[:5]
            ],
        }

    # ── Persistence ────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._persist:
            return
        tmp = Path(str(self._STORE_FILE) + ".tmp")
        try:
            data = {name: lst.to_dict() for name, lst in self._listings.items()}
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self._STORE_FILE)
        except OSError as exc:
            logger.error("Marketplace: failed to persist store: %s", exc)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _load(self) -> None:
        try:
            raw = json.loads(self._STORE_FILE.read_text(encoding="utf-8"))
            for name, data in raw.items():
                try:
                    self._listings[name] = AgentListing.from_dict(data)
                except Exception as exc:
                    logger.warning("Marketplace: skipping invalid listing '%s': %s", name, exc)
            logger.info(
                "Marketplace: loaded %d listing(s) from store.", len(self._listings)
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Marketplace: failed to load store: %s", exc)

    def __len__(self) -> int:
        return len(self._listings)

    def __contains__(self, name: str) -> bool:
        return name in self._listings

    def __repr__(self) -> str:
        return f"AgentMarketplace(agents={len(self._listings)})"
