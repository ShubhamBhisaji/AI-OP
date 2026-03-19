"""AgentSpec — Formal, serialisable contract that fully describes an agent
before it is built.

This is the single source of truth for dynamic agent generation.  The factory
reads an AgentSpec and produces a ready-to-run BaseAgent without any hard-coded
class definitions.

Usage
-----
spec = AgentSpec(
    name="store_bot",
    purpose="Handle customer queries and orders for an e-commerce store",
    skills=["conversation", "order_lookup", "product_search"],
    integrations=["website", "crm"],
    permissions=["read:knowledge", "read:crm", "write:crm"],
    knowledge=["docs/faq.txt", "docs/products.csv"],
)
agent = factory.build_from_spec(spec)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSpec:
    """
    Structured definition of an agent.

    Attributes
    ----------
    name            : Unique agent identifier (snake_case recommended).
    purpose         : Human-readable description of what the agent does.
    skills          : List of skill identifiers the agent should be loaded with.
    integrations    : List of integration type names (e.g. "website", "crm", "api").
    permissions     : List of permission strings ("read:web", "write:workspace", …).
    knowledge       : File paths, URLs, or raw text blocks to inject as knowledge.
    permission_level: Numeric level 0–5 (default 1 = STANDARD).
    tools           : Explicit tool names to attach; auto-resolved if empty.
    objectives      : Ordered list of what the agent must accomplish.
    metadata        : Arbitrary key/value pairs for caller-specific context.
    spec_id         : Auto-generated UUID for traceability.
    created_at      : Unix timestamp set at spec creation.
    version         : Semantic version string, bumped on every spec edit.
    """

    name: str
    purpose: str
    skills: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    permission_level: int = 1
    tools: list[str] = field(default_factory=list)
    objectives: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    spec_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    version: str = "1.0.0"

    # ── Validation ──────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty = valid)."""
        errors: list[str] = []

        if not self.name or not self.name.strip():
            errors.append("'name' is required and cannot be blank.")

        if not self.purpose or not self.purpose.strip():
            errors.append("'purpose' is required and cannot be blank.")

        if not isinstance(self.permission_level, int) or not (0 <= self.permission_level <= 5):
            errors.append("'permission_level' must be an integer between 0 and 5.")

        for attr in ("skills", "integrations", "permissions", "knowledge", "tools", "objectives"):
            val = getattr(self, attr)
            if not isinstance(val, list):
                errors.append(f"'{attr}' must be a list, got {type(val).__name__}.")
            elif any(not isinstance(i, str) for i in val):
                errors.append(f"All items in '{attr}' must be strings.")

        return errors

    def is_valid(self) -> bool:
        return len(self.validate()) == 0

    # ── Serialisation ───────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Convert spec to a plain dict suitable for JSON serialisation."""
        return {
            "spec_id": self.spec_id,
            "version": self.version,
            "created_at": self.created_at,
            "name": self.name,
            "purpose": self.purpose,
            "skills": list(self.skills),
            "integrations": list(self.integrations),
            "permissions": list(self.permissions),
            "knowledge": list(self.knowledge),
            "permission_level": self.permission_level,
            "tools": list(self.tools),
            "objectives": list(self.objectives),
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSpec":
        """Reconstruct an AgentSpec from a plain dict (e.g. loaded from JSON)."""
        return cls(
            name=str(data.get("name", "")),
            purpose=str(data.get("purpose", "")),
            skills=list(data.get("skills", [])),
            integrations=list(data.get("integrations", [])),
            permissions=list(data.get("permissions", [])),
            knowledge=list(data.get("knowledge", [])),
            permission_level=int(data.get("permission_level", 1)),
            tools=list(data.get("tools", [])),
            objectives=list(data.get("objectives", [])),
            metadata=dict(data.get("metadata", {})),
            spec_id=str(data.get("spec_id", str(uuid.uuid4()))),
            created_at=float(data.get("created_at", time.time())),
            version=str(data.get("version", "1.0.0")),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentSpec":
        return cls.from_dict(json.loads(json_str))

    # ── Mutation helpers ────────────────────────────────────────────────────

    def bump_version(self, part: str = "patch") -> "AgentSpec":
        """Increment semantic version in-place and return self."""
        major, minor, patch = (int(x) for x in self.version.split("."))
        if part == "major":
            major += 1
            minor = patch = 0
        elif part == "minor":
            minor += 1
            patch = 0
        else:
            patch += 1
        self.version = f"{major}.{minor}.{patch}"
        return self

    def add_skill(self, skill: str) -> "AgentSpec":
        if skill and skill not in self.skills:
            self.skills.append(skill)
        return self

    def add_integration(self, integration: str) -> "AgentSpec":
        if integration and integration not in self.integrations:
            self.integrations.append(integration)
        return self

    def add_permission(self, permission: str) -> "AgentSpec":
        if permission and permission not in self.permissions:
            self.permissions.append(permission)
        return self

    def add_knowledge(self, source: str) -> "AgentSpec":
        if source and source not in self.knowledge:
            self.knowledge.append(source)
        return self

    # ── Display ─────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"AgentSpec(name={self.name!r}, purpose={self.purpose[:60]!r}, "
            f"skills={self.skills}, integrations={self.integrations}, "
            f"version={self.version!r})"
        )

    def summary(self) -> str:
        lines = [
            f"Agent Spec: {self.name}  [v{self.version}]",
            f"  Purpose    : {self.purpose}",
            f"  Skills     : {', '.join(self.skills) or '(none)'}",
            f"  Integrations: {', '.join(self.integrations) or '(none)'}",
            f"  Permissions: {', '.join(self.permissions) or '(none)'}",
            f"  Knowledge  : {len(self.knowledge)} source(s)",
            f"  Tools      : {', '.join(self.tools) or '(auto)'}",
            f"  Perm Level : {self.permission_level}",
        ]
        return "\n".join(lines)
