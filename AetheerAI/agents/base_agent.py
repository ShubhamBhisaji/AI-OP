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

import uuid
from datetime import datetime
from typing import Any

# Map permission level int → human-readable label
PERMISSION_LABELS: dict[int, str] = {
    0: "GUEST",
    1: "STANDARD",
    2: "ELEVATED",
    3: "ADMIN",
}


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
        self.name = name
        self.role = role
        self.id = str(uuid.uuid4())
        # Clamp permission level to valid range
        _level = max(0, min(3, int(permission_level)))
        self.profile: dict[str, Any] = {
            "id": self.id,
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

    def __repr__(self) -> str:
        return (
            f"<BaseAgent name={self.name!r} role={self.role!r} "
            f"level={self.permission_label} "
            f"version={self.profile['version']} "
            f"tools={self.tools} skills={self.skills}>"
        )
