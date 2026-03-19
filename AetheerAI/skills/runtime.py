"""skills/runtime.py — Plugin-style skill isolation layer.

The SkillRuntime is the single gateway through which an agent accesses skills.
It enforces that:

  - Agents load ONLY the skills listed in their manifest / spec.
  - Unknown skills are rejected before they can affect the agent.
  - Skill domains are isolated — one domain's failure doesn't crash others.
  - Skills can be listed, inspected, and revoked at runtime.
  - Each agent operates inside an isolated SandboxRegistry context so no
    agent can invoke a skill on behalf of another agent's identity.

Usage
-----
runtime = SkillRuntime(allowed_skills=["active_listening", "crm", "analytics"])
runtime.load(agent_name="store_bot")

# Check before using a skill
if runtime.is_allowed("active_listening"):
    ...

# Enforce sandbox isolation before a skill is invoked
runtime.enforce_sandbox("active_listening")

# Get tools that come with loaded skills
tools = runtime.required_tools()

# Get full report
print(runtime.status())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from skills.sandbox import SandboxRegistry, SkillQuota, get_default_registry

logger = logging.getLogger(__name__)


# ── Loaded skill pack ─────────────────────────────────────────────────────────

@dataclass
class LoadedSkillPack:
    """Represents a successfully loaded skill domain."""
    domain: str
    skills: list[str]
    tools: list[str]
    integration_hints: list[str]
    source: str = "module"   # "module" | "manifest_file"

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "skills": self.skills,
            "tools": self.tools,
            "integration_hints": self.integration_hints,
            "source": self.source,
        }


# ── Runtime ───────────────────────────────────────────────────────────────────

class SkillRuntime:
    """
    Plugin-style skill isolation layer.

    Parameters
    ----------
    allowed_skills : List of skill names or domain names the agent is
                     permitted to use. Everything else is rejected.
    strict         : If True, raise on unknown skills. If False, warn only.
    """

    def __init__(
        self,
        allowed_skills: list[str] | None = None,
        strict: bool = False,
        sandbox_registry: SandboxRegistry | None = None,
        skill_quotas: dict[str, SkillQuota] | None = None,
    ) -> None:
        self._allowed_raw: list[str] = list(allowed_skills or [])
        self._strict = strict
        self._packs: dict[str, LoadedSkillPack] = {}      # domain → pack
        self._individual_skills: set[str] = set()          # flat skill names
        self._loaded: bool = False
        self._agent_name: str = ""
        # Sandbox integration — uses the process-level default unless overridden
        self._sandbox: SandboxRegistry = sandbox_registry or get_default_registry()
        self._skill_quotas: dict[str, SkillQuota] = skill_quotas or {}

    # ── Loading ──────────────────────────────────────────────────────────────

    def load(self, agent_name: str = "") -> "SkillRuntime":
        """
        Resolve allowed_skills into concrete skill packs and register this
        agent's isolated sandbox context.

        For each entry in allowed_skills:
        - Try to import it as a domain module (skills.<name>).
        - If that fails, treat it as an individual skill name.
        """
        self._agent_name = agent_name
        for name in self._allowed_raw:
            if not name:
                continue
            # Try to load as domain pack
            try:
                pack = self._load_domain(name)
                self._packs[pack.domain] = pack
                self._individual_skills.update(pack.skills)
                logger.debug(
                    "SkillRuntime[%s]: loaded domain '%s' with %d skills.",
                    agent_name, pack.domain, len(pack.skills),
                )
                continue
            except ModuleNotFoundError:
                pass
            except Exception as exc:
                logger.warning(
                    "SkillRuntime[%s]: failed to load domain '%s': %s",
                    agent_name, name, exc,
                )

            # Treat as flat skill name
            self._individual_skills.add(name)

        self._loaded = True
        # Register isolated sandbox context for this agent
        if agent_name:
            self._sandbox.create_context(
                agent_name=agent_name,
                allowed_skills=list(self._individual_skills),
                quotas=self._skill_quotas,
                strict=self._strict,
                overwrite=True,
            )
        logger.info(
            "SkillRuntime[%s]: ready — %d domain(s), %d individual skill(s).",
            agent_name, len(self._packs), len(self._individual_skills),
        )
        return self

    @staticmethod
    def _load_domain(domain: str) -> LoadedSkillPack:
        """Load a skill domain by module name."""
        mod = import_module(f"skills.{domain}")
        skills: list[str] = list(getattr(mod, "SKILLS", []))
        tools: list[str] = list(getattr(mod, "TOOLS", []))
        hints: list[str] = list(getattr(mod, "INTEGRATION_HINTS", []))
        return LoadedSkillPack(
            domain=domain,
            skills=skills,
            tools=tools,
            integration_hints=hints,
            source="module",
        )

    # ── Authorization ────────────────────────────────────────────────────────

    def is_allowed(self, skill: str) -> bool:
        """Return True if the skill is within this agent's allowed set."""
        if not self._loaded:
            raise RuntimeError("SkillRuntime.load() must be called before checking skills.")
        # Check individual skill names
        if skill in self._individual_skills:
            return True
        # Check domain packs by domain name
        if skill in self._packs:
            return True
        return False

    def assert_allowed(self, skill: str) -> None:
        """Raise PermissionError if skill is not allowed."""
        if not self.is_allowed(skill):
            msg = (
                f"Skill '{skill}' is not in this agent's allowed skill set. "
                f"Allowed: {sorted(self._individual_skills)[:10]}…"
            )
            if self._strict:
                raise PermissionError(msg)
            logger.warning(msg)

    def enforce_sandbox(self, skill: str) -> None:
        """
        Full isolation check: verifies the skill is allowed AND enforces the
        sandbox quota, logging an audit entry regardless of outcome.

        This should be the preferred call site inside SkillEngine and any
        code that actually *invokes* a skill (as opposed to just inspecting
        whether it is available).

        Raises
        ------
        SkillDenied        — skill not in whitelist (sandbox strict mode)
        SkillQuotaExceeded — rolling-window quota exhausted
        PermissionError    — runtime strict mode violation
        """
        self.assert_allowed(skill)
        if self._agent_name:
            self._sandbox.check(self._agent_name, skill)

    # ── Queries ──────────────────────────────────────────────────────────────

    def all_skills(self) -> list[str]:
        """Return deduplicated list of all allowed skill names."""
        return sorted(self._individual_skills)

    def all_domains(self) -> list[str]:
        """Return list of loaded domain names."""
        return list(self._packs.keys())

    def required_tools(self) -> list[str]:
        """Return deduplicated list of tools required by all loaded skill packs."""
        tools: list[str] = []
        for pack in self._packs.values():
            for tool in pack.tools:
                if tool not in tools:
                    tools.append(tool)
        return tools

    def integration_hints(self) -> list[str]:
        """Return integration hints from all loaded packs."""
        hints: list[str] = []
        for pack in self._packs.values():
            for hint in pack.integration_hints:
                if hint not in hints:
                    hints.append(hint)
        return hints

    def get_pack(self, domain: str) -> LoadedSkillPack | None:
        return self._packs.get(domain)

    # ── Mutation ─────────────────────────────────────────────────────────────

    def grant_skill(self, skill: str) -> None:
        """Dynamically add an individual skill (e.g. after an upgrade)."""
        self._individual_skills.add(skill)
        if skill not in self._allowed_raw:
            self._allowed_raw.append(skill)

    def revoke_skill(self, skill: str) -> bool:
        """Remove an individual skill from the allowed set. Returns True if removed."""
        if skill in self._individual_skills:
            self._individual_skills.discard(skill)
            try:
                self._allowed_raw.remove(skill)
            except ValueError:
                pass
            return True
        return False

    def revoke_domain(self, domain: str) -> bool:
        """Unload an entire skill domain. Returns True if it was loaded."""
        if domain not in self._packs:
            return False
        pack = self._packs.pop(domain)
        # Remove skills that came exclusively from this pack
        # (skip skills that also appear in other packs)
        other_skills: set[str] = set()
        for remaining_pack in self._packs.values():
            other_skills.update(remaining_pack.skills)
        for skill in pack.skills:
            if skill not in other_skills:
                self._individual_skills.discard(skill)
        return True

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        sandbox_ctx = (
            self._sandbox.get_context(self._agent_name)
            if self._agent_name else None
        )
        return {
            "loaded": self._loaded,
            "agent": self._agent_name,
            "domains": [p.to_dict() for p in self._packs.values()],
            "individual_skills": sorted(self._individual_skills),
            "required_tools": self.required_tools(),
            "integration_hints": self.integration_hints(),
            "strict_mode": self._strict,
            "sandbox": sandbox_ctx.usage_summary() if sandbox_ctx else {},
        }

    def __repr__(self) -> str:
        return (
            f"SkillRuntime(domains={list(self._packs.keys())}, "
            f"skills={len(self._individual_skills)}, strict={self._strict})"
        )


# ── Convenience factory ───────────────────────────────────────────────────────

def build_skill_runtime(
    agent_name: str,
    skills: list[str],
    strict: bool = False,
    sandbox_registry: SandboxRegistry | None = None,
    skill_quotas: dict[str, SkillQuota] | None = None,
) -> SkillRuntime:
    """Build and load a SkillRuntime for a given agent with sandbox isolation."""
    return SkillRuntime(
        allowed_skills=skills,
        strict=strict,
        sandbox_registry=sandbox_registry,
        skill_quotas=skill_quotas,
    ).load(agent_name=agent_name)
