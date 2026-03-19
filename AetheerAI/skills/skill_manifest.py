"""skill_manifest.py — Formal descriptor for a skill plugin pack.

Every skill domain (communication/, analytics/, ecommerce/, …) exposes its
capabilities through an SkillManifest so the runtime can:

  - Discover what skills are available without importing them
  - Validate that requested skills exist before loading
  - Enforce isolation (agent only gets skills listed in its manifest)
  - Audit which skills are active for an agent

Schema (skill_manifest.json, one per domain folder)
-----------------------------------------------------
{
  "domain": "communication",
  "version": "1.0",
  "skills": ["active_listening", "persuasive_messaging", ...],
  "tools":  ["email_tool", "slack_discord_tool"],
  "tiers": {
    "foundation":    ["active_listening", "clear_writing"],
    "intermediate":  ["persuasive_messaging", "conflict_resolution"],
    "advanced":      ["executive_communication", "negotiation"]
  },
  "integration_hints": ["email", "slack"],
  "requires": [],
  "description": "Human communication skills for customer-facing agents"
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillManifest:
    """
    Formal descriptor for a skill plugin pack.

    Each domain directory should contain either a skill_manifest.json file
    or expose its manifest via get_manifest() in its __init__.py.
    """

    domain: str
    version: str = "1.0"
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tiers: dict[str, list[str]] = field(default_factory=dict)
    integration_hints: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)   # other domains required
    description: str = ""

    # ── Validation ──────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.domain:
            errors.append("'domain' is required.")
        if not isinstance(self.skills, list):
            errors.append("'skills' must be a list.")
        return errors

    def is_valid(self) -> bool:
        return len(self.validate()) == 0

    # ── Queries ─────────────────────────────────────────────────────────────

    def has_skill(self, skill: str) -> bool:
        return skill in self.skills

    def skills_for_tier(self, tier: str) -> list[str]:
        """Return skills for a given tier (foundation/intermediate/advanced)."""
        return list(self.tiers.get(tier, []))

    def skills_up_to_tier(self, tier: str) -> list[str]:
        """Return all skills up to and including the given tier."""
        order = ["foundation", "intermediate", "advanced"]
        result: list[str] = []
        for t in order:
            result.extend(self.tiers.get(t, []))
            if t == tier:
                break
        return result

    # ── Serialisation ───────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "version": self.version,
            "description": self.description,
            "skills": list(self.skills),
            "tools": list(self.tools),
            "tiers": {k: list(v) for k, v in self.tiers.items()},
            "integration_hints": list(self.integration_hints),
            "requires": list(self.requires),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillManifest":
        return cls(
            domain=str(data.get("domain", "")),
            version=str(data.get("version", "1.0")),
            skills=list(data.get("skills", [])),
            tools=list(data.get("tools", [])),
            tiers={k: list(v) for k, v in data.get("tiers", {}).items()},
            integration_hints=list(data.get("integration_hints", [])),
            requires=list(data.get("requires", [])),
            description=str(data.get("description", "")),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "SkillManifest":
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_file(cls, path: str | Path) -> "SkillManifest":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"skill_manifest.json not found: {path}")
        return cls.from_json(path.read_text(encoding="utf-8"))

    @classmethod
    def from_module(cls, domain: str) -> "SkillManifest":
        """
        Load a SkillManifest from a skills/<domain>/ package.

        Tries (in order):
        1. skills/<domain>/skill_manifest.json
        2. skills/<domain>/__init__.py → get_manifest() callable
        3. skills/<domain>/__init__.py → SKILLS / TOOLS / etc. attributes
        """
        from importlib import import_module

        # 1. JSON manifest file
        package_dir = Path(__file__).parent / domain
        json_path = package_dir / "skill_manifest.json"
        if json_path.exists():
            return cls.from_file(json_path)

        # 2 & 3. Python module attributes
        try:
            mod = import_module(f"skills.{domain}")
        except ModuleNotFoundError:
            raise ModuleNotFoundError(f"Skill domain '{domain}' not found.")

        if hasattr(mod, "get_manifest") and callable(mod.get_manifest):
            data = mod.get_manifest()
            if isinstance(data, dict):
                return cls.from_dict(data)
            if isinstance(data, cls):
                return data

        # Fall back to module-level attributes
        return cls(
            domain=domain,
            skills=list(getattr(mod, "SKILLS", [])),
            tools=list(getattr(mod, "TOOLS", [])),
            integration_hints=list(getattr(mod, "INTEGRATION_HINTS", [])),
            description=str(getattr(mod, "__doc__", "") or "").strip().split("\n")[0],
        )

    def __repr__(self) -> str:
        return (
            f"SkillManifest(domain={self.domain!r}, v{self.version}, "
            f"{len(self.skills)} skills, {len(self.tools)} tools)"
        )
