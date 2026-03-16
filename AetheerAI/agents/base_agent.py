"""
BaseAgent — The foundation class for all AetheerAI — An AI Master!! agents.
Every agent created by AgentFactory inherits from this class.

Fix 6 — RBAC:
    Each agent carries a `permission_level` (0–3) that gates which
    tools it can call.  The level is set at construction time and stored
    in `profile["permission_level"]`.

    0 = GUEST      (read-only utilities)
    1 = STANDARD   (default — file reading, web search, analysis)
    2 = ELEVATED   (file writing, code analysis)
    3 = ADMIN      (code runner, terminal, security tools)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# Map permission level int → human-readable label
PERMISSION_LABELS: dict[int, str] = {
    0: "GUEST",
    1: "STANDARD",
    2: "ELEVATED",
    3: "ADMIN",
}


# ---------------------------------------------------------------------------
# Pydantic schema for agent profile validation
# ---------------------------------------------------------------------------

class _PerformanceModel(BaseModel):
    tasks_completed: int = 0
    tasks_failed: int = 0
    success_rate: float = 0.0

    model_config = {"extra": "allow"}


class AgentProfileModel(BaseModel):
    """Validates the core fields of an agent profile dict."""
    id: str
    name: str
    role: str
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    permission_level: int = Field(default=1, ge=0, le=3)
    performance: _PerformanceModel = Field(default_factory=_PerformanceModel)
    version: str = "1.0.0"
    created_by: str = "AetheerAI — An AI Master!!"
    created_at: str = ""
    history: list[dict] = Field(default_factory=list)

    # Allow extra keys (e.g. 'instructions', 'system_prompt', 'tags')
    model_config = {"extra": "allow"}

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Agent name cannot be empty.")
        return v.strip()

    @field_validator("role")
    @classmethod
    def _role_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Agent role cannot be empty.")
        return v.strip()

    @field_validator("tools", "skills", mode="before")
    @classmethod
    def _ensure_list(cls, v: Any) -> list:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return list(v)

    @model_validator(mode="after")
    def _sync_success_rate(self) -> "AgentProfileModel":
        """Recompute success_rate if raw counts don't match stored rate."""
        p = self.performance
        total = p.tasks_completed + p.tasks_failed
        if total > 0:
            expected = round(p.tasks_completed / total, 4)
            if abs(p.success_rate - expected) > 0.0001:
                p.success_rate = expected
        return self


class BaseAgent:
    """
    A general-purpose AI agent within AetheerAI — An AI Master!!.

    Attributes:
        name             : Unique identifier name for this agent.
        role             : The agent's assigned role (e.g. 'Research Agent').
        tools            : List of tool names the agent can use.
        permission_level : Integer RBAC level (0–3). Defaults to 1 (STANDARD).
        profile          : Full agent profile including skills, metrics, history.
    """

    def __init__(
        self,
        name: str,
        role: str,
        tools: list[str],
        skills: list[str] | None = None,
        permission_level: int = 1,
    ):
        # Clamp permission level to valid range before validation
        _level = max(0, min(3, int(permission_level)))
        _raw_profile: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "name": name,
            "role": role,
            "tools": tools,
            "skills": skills or [],
            "permission_level": _level,
            "performance": {
                "tasks_completed": 0,
                "tasks_failed": 0,
                "success_rate": 0.0,
            },
            "version": "1.0.0",
            "created_by": "AetheerAI — An AI Master!!",
            "created_at": datetime.utcnow().isoformat(),
            "history": [],
        }
        # Validate via Pydantic schema; raises ValidationError on bad input
        validated = AgentProfileModel(**_raw_profile)
        self.profile: dict[str, Any] = validated.model_dump()
        self.name = self.profile["name"]
        self.role = self.profile["role"]
        self.id = self.profile["id"]

    # ------------------------------------------------------------------
    # Profile access helpers
    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[str]:
        return self.profile["tools"]

    @tools.setter
    def tools(self, value: list[str]) -> None:
        self.profile["tools"] = value

    @property
    def skills(self) -> list[str]:
        return self.profile["skills"]

    @skills.setter
    def skills(self, value: list[str]) -> None:
        self.profile["skills"] = value

    @property
    def permission_level(self) -> int:
        return self.profile.get("permission_level", 1)

    @permission_level.setter
    def permission_level(self, value: int) -> None:
        self.profile["permission_level"] = max(0, min(3, int(value)))

    @property
    def permission_label(self) -> str:
        return PERMISSION_LABELS.get(self.permission_level, "STANDARD")

    def add_skill(self, skill: str) -> None:
        if skill not in self.profile["skills"]:
            self.profile["skills"].append(skill)

    def add_tool(self, tool: str) -> None:
        if tool not in self.profile["tools"]:
            self.profile["tools"].append(tool)

    # ------------------------------------------------------------------
    # Performance tracking
    # ------------------------------------------------------------------

    def record_result(self, success: bool) -> None:
        perf = self.profile["performance"]
        if success:
            perf["tasks_completed"] += 1
        else:
            perf["tasks_failed"] += 1
        total = perf["tasks_completed"] + perf["tasks_failed"]
        perf["success_rate"] = round(perf["tasks_completed"] / total, 4) if total else 0.0
        self.profile["history"].append(
            {"timestamp": datetime.utcnow().isoformat(), "success": success}
        )

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    def bump_version(self) -> None:
        parts = self.profile["version"].split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        self.profile["version"] = ".".join(parts)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return self.profile.copy()

    @classmethod
    def validate_profile(cls, profile: dict[str, Any]) -> dict[str, Any]:
        """Validate a raw profile dict and return the normalised version.

        Raises ``pydantic.ValidationError`` if required fields are missing or
        invalid.  Used by :class:`~registry.agent_registry.AgentRegistry` when
        loading persisted agents from disk.
        """
        return AgentProfileModel(**profile).model_dump()

    def __repr__(self) -> str:
        return (
            f"<BaseAgent name={self.name!r} role={self.role!r} "
            f"level={self.permission_label} "
            f"version={self.profile['version']} "
            f"tools={self.tools} skills={self.skills}>"
        )
