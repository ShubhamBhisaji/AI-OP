"""
intent_manifest.py — Intent Manifest & Kill-Switch Governance for AetheerAI.

Feature 4 — Enterprise-Safe Action-Layer Guardrails:

    When a sub-agent is created, an IntentManifest can be assigned to it.
    The manifest hard-codes exactly what the agent is allowed to do:
      - Which specific tools it may call (allow-list).
      - Which tool categories (operations) are permitted.
      - Maximum number of tool calls per task (circuit-breaker).
      - Whether network access is allowed.
      - Which tools are unconditionally denied (deny-list override).

    ManifestGuard enforces these rules inside ToolManager.call(). Any
    attempt to violate the manifest raises ManifestViolation immediately
    — before any execution takes place — and records the event in the
    audit log.

Usage
-----
    # Create a read-only manifest for a research agent
    manifest = IntentManifest.read_only()
    kernel.register_manifest("research_agent", manifest)

    # Agent with strict limits
    manifest = IntentManifest(
        allowed_tools={"web_search", "file_reader", "calculator"},
        allowed_operations={"read", "network"},
        max_tool_calls=20,
        network_allowed=True,
        description="Sandboxed research agent",
    )
    kernel.register_manifest("scraper", manifest)

    # Remove constraints when done
    kernel.remove_manifest("scraper")
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class ManifestViolation(PermissionError):
    """
    Raised when an agent attempts to use a tool or perform an operation
    not permitted by its IntentManifest.  The call is always blocked.
    """


# ---------------------------------------------------------------------------
# Tool → operation category mapping
# (mirrors the categories in ToolManager's TOOL_PERMISSIONS dict)
# ---------------------------------------------------------------------------
_TOOL_CATEGORY: dict[str, str] = {
    # read
    "file_reader": "read", "directory_scanner": "read", "csv_tool": "read",
    "web_search": "read",  "code_analyzer": "read",     "code_search": "read",
    "system_info": "read", "calculator": "read",        "text_analyzer": "read",
    "json_tool": "read",   "diff_tool": "read",         "analytics_tool": "read",
    "note_taker": "read",
    # write
    "file_writer": "write",      "local_file_tool": "write",
    "pdf_tool": "write",         "github_tool": "write",
    "email_tool": "write",       "image_gen_tool": "write",
    # execute
    "code_runner": "execute",    "terminal_tool": "execute",
    "security_tool": "execute",
    # network
    "http_client": "network",    "browser_tool": "network",
    "web_scraper_pro": "network","slack_discord_tool": "network",
    "speech_tool": "network",    "vision_tool": "network",
    "playwright_tool": "network",
    # delete / infra
    "sql_db_tool": "delete",     "aws_gcp_tool": "delete",
    "kubernetes_tool": "delete",
}


# ---------------------------------------------------------------------------
# IntentManifest
# ---------------------------------------------------------------------------

@dataclass
class IntentManifest:
    """
    Declares the complete intent surface for a sub-agent.

    Attributes
    ----------
    allowed_tools      : Explicit allow-list of tool names.
                         Empty set = all tools allowed (only category & deny
                         rules apply).
    denied_tools       : Hard deny-list that always overrides allowed_tools.
    allowed_operations : Set of permitted operation categories:
                         "read", "write", "execute", "network", "delete".
                         Empty set = no category restriction.
    max_tool_calls     : Circuit-breaker — max tool invocations per task.
                         0 = unlimited.
    network_allowed    : Convenience toggle; if False, all "network" category
                         tools are blocked regardless of other settings.
    description        : Human-readable purpose statement, shown in audit logs.
    """

    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)
    allowed_operations: set[str] = field(default_factory=set)
    max_tool_calls: int = 0
    network_allowed: bool = True
    description: str = ""

    # ------------------------------------------------------------------
    # Preset factory methods
    # ------------------------------------------------------------------

    @classmethod
    def read_only(cls, extra_tools: set[str] | None = None) -> "IntentManifest":
        """Pre-built read-only manifest. Safe for research and analysis agents."""
        base = {
            "file_reader", "directory_scanner", "csv_tool", "web_search",
            "code_analyzer", "code_search", "system_info", "calculator",
            "datetime_tool", "hash_tool", "text_analyzer", "json_tool",
            "markdown_tool", "url_tool", "template_tool", "diff_tool",
            "analytics_tool", "note_taker",
        }
        return cls(
            allowed_tools=base | (extra_tools or set()),
            allowed_operations={"read", "network"},
            description="Read-only agent — no writes or code execution.",
        )

    @classmethod
    def no_network(cls, extra_tools: set[str] | None = None) -> "IntentManifest":
        """Pre-built air-gapped manifest — all network access blocked."""
        return cls(
            allowed_tools=extra_tools or set(),
            denied_tools={
                "web_search", "http_client", "browser_tool", "web_scraper_pro",
                "slack_discord_tool", "email_tool", "speech_tool", "vision_tool",
                "playwright_tool",
            },
            allowed_operations={"read", "write", "execute"},
            network_allowed=False,
            description="Air-gapped agent — no network access permitted.",
        )

    @classmethod
    def admin(cls) -> "IntentManifest":
        """Unrestricted manifest for fully-trusted admin agents."""
        return cls(description="Unrestricted admin manifest — all tools permitted.")

    @classmethod
    def sandboxed_coder(cls) -> "IntentManifest":
        """Pre-built manifest for a coding agent with no file-system write access."""
        return cls(
            allowed_tools={
                "code_runner", "code_analyzer", "code_search", "linter_tool",
                "code_formatter", "calculator", "web_search", "file_reader",
            },
            allowed_operations={"read", "execute", "network"},
            max_tool_calls=50,
            description="Sandboxed coder — reads and runs code, no writes.",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_tools": sorted(self.allowed_tools),
            "denied_tools": sorted(self.denied_tools),
            "allowed_operations": sorted(self.allowed_operations),
            "max_tool_calls": self.max_tool_calls,
            "network_allowed": self.network_allowed,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Per-agent call state (mutable, not part of the manifest)
# ---------------------------------------------------------------------------

@dataclass
class _CallState:
    call_count: int = 0


# ---------------------------------------------------------------------------
# ManifestGuard
# ---------------------------------------------------------------------------

class ManifestGuard:
    """
    Thread-safe guard that maps agent names → IntentManifest.

    Wire into ToolManager:
        tool_manager = ToolManager(manifest_guard=guard)

    ToolManager.call() will invoke guard.check(agent_name, tool_name)
    before any RBAC or approval-gate logic.
    """

    def __init__(self, audit_logger=None) -> None:
        self._manifests: dict[str, IntentManifest] = {}
        self._state: dict[str, _CallState] = {}
        self._lock = threading.Lock()
        self._audit = audit_logger

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, agent_name: str, manifest: IntentManifest) -> None:
        """Assign an IntentManifest to an agent."""
        with self._lock:
            self._manifests[agent_name] = manifest
            self._state[agent_name] = _CallState()
        logger.info(
            "ManifestGuard: manifest registered for '%s' — tools=%s, ops=%s, max_calls=%d.",
            agent_name,
            sorted(manifest.allowed_tools) if manifest.allowed_tools else "ALL",
            sorted(manifest.allowed_operations) if manifest.allowed_operations else "ALL",
            manifest.max_tool_calls,
        )

    def deregister(self, agent_name: str) -> None:
        """Remove a manifest (reverts to RBAC-only enforcement for that agent)."""
        with self._lock:
            self._manifests.pop(agent_name, None)
            self._state.pop(agent_name, None)
        logger.info("ManifestGuard: manifest removed for agent '%s'.", agent_name)

    def reset_call_count(self, agent_name: str) -> None:
        """Reset per-task call counter. Call at the start of each new task."""
        with self._lock:
            if agent_name in self._state:
                self._state[agent_name].call_count = 0

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def check(self, agent_name: str, tool_name: str) -> None:
        """
        Validate a tool call against the agent's manifest.
        Raises ManifestViolation if the call is not permitted.
        No-op for agents without a registered manifest.
        """
        with self._lock:
            manifest = self._manifests.get(agent_name)
            if manifest is None:
                return   # no manifest → RBAC-only
            state = self._state.setdefault(agent_name, _CallState())
            # take a snapshot of mutable state for the checks below
            call_count = state.call_count

        # ── Hard deny-list ────────────────────────────────────────────
        if tool_name in manifest.denied_tools:
            self._block(
                agent_name, tool_name,
                f"Tool '{tool_name}' is in this agent's deny list.",
            )

        # ── Network toggle ────────────────────────────────────────────
        if not manifest.network_allowed:
            if _TOOL_CATEGORY.get(tool_name) == "network":
                self._block(
                    agent_name, tool_name,
                    "Network access is disabled in this agent's manifest.",
                )

        # ── Allow-list (non-empty = strict) ───────────────────────────
        if manifest.allowed_tools and tool_name not in manifest.allowed_tools:
            self._block(
                agent_name, tool_name,
                f"Tool '{tool_name}' is not in this agent's allowed_tools list.",
            )

        # ── Operation category check ──────────────────────────────────
        if manifest.allowed_operations:
            category = _TOOL_CATEGORY.get(tool_name, "")
            if category and category not in manifest.allowed_operations:
                self._block(
                    agent_name, tool_name,
                    f"Operation '{category}' is not permitted "
                    f"(allowed: {sorted(manifest.allowed_operations)}).",
                )

        # ── Circuit-breaker ───────────────────────────────────────────
        if manifest.max_tool_calls > 0:
            with self._lock:
                state = self._state.setdefault(agent_name, _CallState())
                state.call_count += 1
                new_count = state.call_count
            if new_count > manifest.max_tool_calls:
                self._block(
                    agent_name, tool_name,
                    f"Tool call limit ({manifest.max_tool_calls}) exceeded for this task.",
                )
        else:
            with self._lock:
                self._state.setdefault(agent_name, _CallState()).call_count += 1

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------

    def has_manifest(self, agent_name: str) -> bool:
        return agent_name in self._manifests

    def get_manifest(self, agent_name: str) -> IntentManifest | None:
        return self._manifests.get(agent_name)

    def list_manifests(self) -> dict[str, dict]:
        """Return a summary dict of all registered manifests."""
        return {name: m.to_dict() for name, m in self._manifests.items()}

    def call_stats(self) -> dict[str, int]:
        """Return current call counts per agent."""
        with self._lock:
            return {name: s.call_count for name, s in self._state.items()}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _block(self, agent_name: str, tool_name: str, reason: str) -> None:
        msg = (
            f"[MANIFEST VIOLATION] Agent '{agent_name}' blocked from calling "
            f"'{tool_name}': {reason}"
        )
        logger.error(msg)
        if self._audit is not None:
            try:
                self._audit.log({
                    "event": "manifest_violation",
                    "agent": agent_name,
                    "tool": tool_name,
                    "reason": reason,
                })
            except Exception:
                pass
        raise ManifestViolation(msg)
