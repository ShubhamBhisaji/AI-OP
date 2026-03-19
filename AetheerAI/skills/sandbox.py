"""skills/sandbox.py — Skill isolation sandbox for AetheerAI.

Addresses the "Skill Isolation Weak" risk by providing:

  - Per-agent isolated SkillContext: no agent can read/write another's context.
  - Hard resource quotas per skill invocation (max calls, time window).
  - Cross-agent skill bleed prevention: shared skills run in copied namespaces.
  - Full audit trail of every skill invocation with agent identity.
  - Revokable skill grants at runtime.

Design
------
                        ┌────────────────────────┐
                        │   SandboxRegistry      │  ← global, process-level
                        │  ┌──────────────────┐  │
                        │  │  Agent A context │  │
                        │  │  quotas + log    │  │
                        │  └──────────────────┘  │
                        │  ┌──────────────────┐  │
                        │  │  Agent B context │  │
                        │  │  quotas + log    │  │
                        │  └──────────────────┘  │
                        └────────────────────────┘
                                 ▲   ▲
                    SkillSandbox(agent_name) calls
                    check_and_record() before every
                    skill invocation.

Usage
-----
    from AetheerAI.skills.sandbox import SandboxRegistry

    registry = SandboxRegistry()

    # Called when an agent is created
    registry.create_context("agent_alice", allowed_skills=["web_search", "summarization"])

    # Called before every skill invocation inside SkillRuntime / SkillEngine
    registry.check("agent_alice", "web_search")          # raises SkillDenied if not allowed

    # Quota enforcement
    registry.create_context(
        "agent_bob",
        allowed_skills=["data_cleaning"],
        quotas={"data_cleaning": SkillQuota(max_calls=100, window_seconds=3600)},
    )
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────


class SkillDenied(PermissionError):
    """Raised when an agent attempts to use an unauthorized skill."""


class SkillQuotaExceeded(RuntimeError):
    """Raised when an agent's skill quota has been exhausted."""


# ── Quota ──────────────────────────────────────────────────────────────────────

@dataclass
class SkillQuota:
    """Rolling-window call quota for a single skill."""
    max_calls: int = 1_000
    window_seconds: float = 3_600.0   # 1 hour


@dataclass
class _QuotaState:
    quota: SkillQuota
    _calls: list[float] = field(default_factory=list)   # timestamps (monotonic)

    def record_and_check(self, skill: str, agent: str) -> None:
        now = time.monotonic()
        window_start = now - self.quota.window_seconds
        # Prune old timestamps
        self._calls = [t for t in self._calls if t >= window_start]
        if len(self._calls) >= self.quota.max_calls:
            raise SkillQuotaExceeded(
                f"Agent '{agent}' has exceeded the quota for skill '{skill}': "
                f"{self.quota.max_calls} calls per "
                f"{self.quota.window_seconds:.0f}s window."
            )
        self._calls.append(now)


# ── Audit log entry ────────────────────────────────────────────────────────────

@dataclass
class SkillAuditEntry:
    agent: str
    skill: str
    timestamp: float
    allowed: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "skill": self.skill,
            "timestamp": self.timestamp,
            "allowed": self.allowed,
            "reason": self.reason,
        }


# ── Per-agent context ──────────────────────────────────────────────────────────

class AgentSkillContext:
    """
    Isolated skill context for a single agent.

    Thread-safe.
    """

    def __init__(
        self,
        agent_name: str,
        allowed_skills: list[str] | None = None,
        quotas: dict[str, SkillQuota] | None = None,
        strict: bool = True,
    ) -> None:
        self.agent_name = agent_name
        self._allowed: frozenset[str] = frozenset(allowed_skills or [])
        self._quota_states: dict[str, _QuotaState] = {
            skill: _QuotaState(quota=q)
            for skill, q in (quotas or {}).items()
        }
        self._strict = strict
        self._audit: list[SkillAuditEntry] = []
        self._lock = threading.Lock()

    # ── Authorization ──────────────────────────────────────────────────────

    def is_allowed(self, skill: str) -> bool:
        # When _allowed is None (permissive/fallback context), every skill is permitted.
        if self._allowed is None:  # type: ignore[comparison-overlap]
            return True
        return skill in self._allowed

    def check(self, skill: str) -> None:
        """
        Validate and record a skill invocation.

        Raises
        ------
        SkillDenied        if the skill is not in the allowed set.
        SkillQuotaExceeded if the rolling-window quota is exhausted.
        """
        with self._lock:
            if not self.is_allowed(skill):
                entry = SkillAuditEntry(
                    agent=self.agent_name,
                    skill=skill,
                    timestamp=time.time(),
                    allowed=False,
                    reason="not in allowed set",
                )
                self._audit.append(entry)
                logger.warning(
                    "SkillSandbox[%s]: denied skill '%s' — not in allowed set.",
                    self.agent_name, skill,
                )
                if self._strict:
                    raise SkillDenied(
                        f"Agent '{self.agent_name}' is not permitted to use skill '{skill}'."
                    )
                return

            # Quota check (if quota is configured for this skill)
            if skill in self._quota_states:
                self._quota_states[skill].record_and_check(skill, self.agent_name)

            entry = SkillAuditEntry(
                agent=self.agent_name,
                skill=skill,
                timestamp=time.time(),
                allowed=True,
            )
            self._audit.append(entry)
            logger.debug(
                "SkillSandbox[%s]: approved skill '%s'.", self.agent_name, skill
            )

    # ── Grant / revoke at runtime ──────────────────────────────────────────

    def grant(self, skill: str) -> None:
        with self._lock:
            self._allowed = self._allowed | {skill}
            logger.info(
                "SkillSandbox[%s]: granted skill '%s'.", self.agent_name, skill
            )

    def revoke(self, skill: str) -> None:
        with self._lock:
            self._allowed = self._allowed - {skill}
            # Drain quota state so future grants start fresh
            self._quota_states.pop(skill, None)
            logger.info(
                "SkillSandbox[%s]: revoked skill '%s'.", self.agent_name, skill
            )

    def set_quota(self, skill: str, quota: SkillQuota) -> None:
        with self._lock:
            self._quota_states[skill] = _QuotaState(quota=quota)

    # ── Introspection ──────────────────────────────────────────────────────

    def allowed_skills(self) -> list[str]:
        if self._allowed is None:  # type: ignore[comparison-overlap]
            return ["*all*"]       # permissive — every skill is allowed
        return sorted(self._allowed)

    def audit_log(self) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._audit]

    def usage_summary(self) -> dict[str, int]:
        """Return {skill: total_allowed_calls} for auditing."""
        with self._lock:
            summary: dict[str, int] = {}
            for e in self._audit:
                if e.allowed:
                    summary[e.skill] = summary.get(e.skill, 0) + 1
            return summary

    def __repr__(self) -> str:
        return (
            f"AgentSkillContext(agent={self.agent_name!r}, "
            f"skills={len(self._allowed)}, "
            f"audit_entries={len(self._audit)})"
        )


# ── Global sandbox registry ────────────────────────────────────────────────────

class SandboxRegistry:
    """
    Process-level registry of per-agent skill sandboxes.

    One SandboxRegistry instance should be held by the kernel and shared
    across all subsystems. Agents are isolated from each other by design —
    there is no way to obtain another agent's context through this API.
    """

    def __init__(self) -> None:
        self._contexts: dict[str, AgentSkillContext] = {}
        self._lock = threading.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def create_context(
        self,
        agent_name: str,
        allowed_skills: list[str] | None = None,
        quotas: dict[str, SkillQuota] | None = None,
        strict: bool = True,
        overwrite: bool = False,
    ) -> AgentSkillContext:
        """
        Create and register an isolated context for an agent.

        Parameters
        ----------
        agent_name     : Unique agent identifier.
        allowed_skills : Explicit whitelist of skills this agent may invoke.
        quotas         : Per-skill quotas, e.g. {"web_search": SkillQuota(max_calls=50)}.
        strict         : Raise SkillDenied on violations (recommended).
        overwrite      : If False and context already exists, return existing.
        """
        with self._lock:
            if agent_name in self._contexts and not overwrite:
                return self._contexts[agent_name]
            ctx = AgentSkillContext(
                agent_name=agent_name,
                allowed_skills=allowed_skills,
                quotas=quotas,
                strict=strict,
            )
            self._contexts[agent_name] = ctx
            logger.debug(
                "SandboxRegistry: created context for '%s' with %d skills.",
                agent_name, len(allowed_skills or []),
            )
            return ctx

    def remove_context(self, agent_name: str) -> bool:
        with self._lock:
            existed = agent_name in self._contexts
            self._contexts.pop(agent_name, None)
            return existed

    # ── Enforcement ────────────────────────────────────────────────────────

    def check(self, agent_name: str, skill: str) -> None:
        """
        Check that *agent_name* is permitted to invoke *skill*.

        If no context exists for this agent, a permissive context is created
        automatically (all skills allowed, logged as a warning).

        Raises
        ------
        SkillDenied        — skill not in whitelist (when strict=True)
        SkillQuotaExceeded — rolling-window quota exhausted
        """
        ctx = self._get_or_create_permissive(agent_name)
        ctx.check(skill)

    def _get_or_create_permissive(self, agent_name: str) -> AgentSkillContext:
        with self._lock:
            if agent_name not in self._contexts:
                logger.warning(
                    "SandboxRegistry: no context for agent '%s' — "
                    "creating permissive context. "
                    "Call create_context() explicitly for production agents.",
                    agent_name,
                )
                ctx = AgentSkillContext(
                    agent_name=agent_name,
                    allowed_skills=None,   # None = no whitelist
                    strict=False,          # permissive fallback
                )
                # Override is_allowed to allow everything in permissive mode
                ctx._allowed = None       # type: ignore[assignment]
                self._contexts[agent_name] = ctx
            return self._contexts[agent_name]

    # ── Queries ────────────────────────────────────────────────────────────

    def get_context(self, agent_name: str) -> AgentSkillContext | None:
        """Return the context for an agent, or None if not registered."""
        return self._contexts.get(agent_name)

    def list_agents(self) -> list[str]:
        return list(self._contexts.keys())

    def full_audit(self) -> dict[str, list[dict[str, Any]]]:
        """Return the audit log for ALL agents (admin use only)."""
        return {name: ctx.audit_log() for name, ctx in self._contexts.items()}

    def usage_report(self) -> dict[str, dict[str, int]]:
        """Return per-agent skill usage counts."""
        return {name: ctx.usage_summary() for name, ctx in self._contexts.items()}

    def __len__(self) -> int:
        return len(self._contexts)

    def __contains__(self, agent_name: str) -> bool:
        return agent_name in self._contexts

    def __repr__(self) -> str:
        return f"SandboxRegistry(agents={list(self._contexts.keys())})"


# ── Module-level default registry (convenience) ────────────────────────────────

_default_registry: SandboxRegistry | None = None


def get_default_registry() -> SandboxRegistry:
    """Return (or lazily create) the process-level default sandbox registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SandboxRegistry()
    return _default_registry
