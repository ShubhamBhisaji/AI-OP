"""Reusable base class for all AetheerAI agents.

This class provides a stable contract for autonomous multi-agent workflows:
- Identity and role metadata (name, role, objectives)
- Tool and permission metadata
- Memory access (scoped namespace support)
- Core lifecycle methods: plan_task, execute_task, report_status
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# Map permission level int → human-readable label
PERMISSION_LABELS: dict[int, str] = {
    0: "GUEST",
    1: "STANDARD",
    2: "ELEVATED",
    3: "ADMIN",
    4: "PRIVILEGED",
    5: "SYSTEM",
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
    objectives: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    permission_level: int = Field(default=1, ge=0, le=5)
    performance: _PerformanceModel = Field(default_factory=_PerformanceModel)
    version: str = "1.0.0"
    created_by: str = "AetheerAI"
    created_at: str = ""
    history: list[dict] = Field(default_factory=list)
    last_status: str = "idle"
    last_task: str = ""
    last_result: str = ""
    last_error: str = ""
    memory_namespace: str = ""

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

    @field_validator("objectives", "tools", "skills", "permissions", mode="before")
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

    The constructor keeps backward compatibility with the original signature,
    while adding optional fields required by the autonomous system contracts.
    """

    def __init__(
        self,
        name: str,
        role: str,
        tools: list[str],
        objectives: list[str] | None = None,
        skills: list[str] | None = None,
        permissions: list[str] | None = None,
        permission_level: int = 1,
        memory_manager: Any | None = None,
        ai_adapter: Any | None = None,
        workflow_engine: Any | None = None,
        tool_manager: Any | None = None,
    ):
        # Clamp permission level to a safe range before validation.
        _level = max(0, min(5, int(permission_level)))
        _raw_profile: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "name": name,
            "role": role,
            "objectives": objectives or [],
            "tools": tools,
            "skills": skills or [],
            "permissions": permissions or [],
            "permission_level": _level,
            "performance": {
                "tasks_completed": 0,
                "tasks_failed": 0,
                "success_rate": 0.0,
            },
            "version": "1.0.0",
            "created_by": "AetheerAI",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "history": [],
            "last_status": "idle",
            "last_task": "",
            "last_result": "",
            "last_error": "",
            "memory_namespace": name,
        }
        validated = AgentProfileModel(**_raw_profile)
        self.profile: dict[str, Any] = validated.model_dump()
        self.name = self.profile["name"]
        self.role = self.profile["role"]
        self.id = self.profile["id"]

        self._memory_scope = None
        self._ai_adapter = ai_adapter
        self._workflow_engine = workflow_engine
        self._tool_manager = tool_manager
        if memory_manager is not None:
            self.attach_memory(memory_manager)

    # ------------------------------------------------------------------
    # Profile access helpers
    # ------------------------------------------------------------------

    @property
    def objectives(self) -> list[str]:
        return self.profile["objectives"]

    @objectives.setter
    def objectives(self, value: list[str]) -> None:
        self.profile["objectives"] = list(value or [])

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
        self.profile["permission_level"] = max(0, min(5, int(value)))

    @property
    def permission_label(self) -> str:
        return PERMISSION_LABELS.get(self.permission_level, "STANDARD")

    @property
    def permissions(self) -> list[str]:
        return self.profile.get("permissions", [])

    @permissions.setter
    def permissions(self, value: list[str]) -> None:
        self.profile["permissions"] = list(value or [])

    @property
    def status(self) -> str:
        return self.profile.get("last_status", "idle")

    @status.setter
    def status(self, value: str) -> None:
        self.profile["last_status"] = value

    def add_skill(self, skill: str) -> None:
        if skill not in self.profile["skills"]:
            self.profile["skills"].append(skill)

    def add_objective(self, objective: str) -> None:
        if objective and objective not in self.profile["objectives"]:
            self.profile["objectives"].append(objective)

    def add_tool(self, tool: str) -> None:
        if tool not in self.profile["tools"]:
            self.profile["tools"].append(tool)

    def add_permission(self, permission: str) -> None:
        if permission and permission not in self.profile["permissions"]:
            self.profile["permissions"].append(permission)

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
            {"timestamp": datetime.now(timezone.utc).isoformat(), "success": success}
        )

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    def bump_version(self) -> None:
        parts = self.profile["version"].split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        self.profile["version"] = ".".join(parts)

    # ------------------------------------------------------------------
    # Runtime wiring and memory
    # ------------------------------------------------------------------

    def attach_runtime(
        self,
        *,
        ai_adapter: Any | None = None,
        workflow_engine: Any | None = None,
        tool_manager: Any | None = None,
    ) -> None:
        if ai_adapter is not None:
            self._ai_adapter = ai_adapter
        if workflow_engine is not None:
            self._workflow_engine = workflow_engine
        if tool_manager is not None:
            self._tool_manager = tool_manager

    def attach_memory(self, memory_manager: Any) -> None:
        namespace = self.name
        try:
            if hasattr(memory_manager, "register_namespace"):
                memory_manager.register_namespace(namespace)
        except Exception as exc:
            logger.debug("BaseAgent '%s': namespace registration skipped: %s", self.name, exc)

        try:
            if hasattr(memory_manager, "scoped"):
                self._memory_scope = memory_manager.scoped(namespace)
                self.profile["memory_namespace"] = namespace
            else:
                self._memory_scope = memory_manager
        except Exception as exc:
            logger.warning("BaseAgent '%s': failed to attach memory scope: %s", self.name, exc)
            self._memory_scope = None

    # ------------------------------------------------------------------
    # Core autonomous methods
    # ------------------------------------------------------------------

    def plan_task(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        memory_hits: int = 3,
    ) -> dict[str, Any]:
        """Create a task plan using role context and relevant long-term memory."""
        self.status = "planning"
        memory_context = self._memory_snippets(task, n_results=memory_hits)

        if self._ai_adapter is None:
            strategy = "No AI adapter configured; execute the task directly."
        else:
            prompt = (
                f"You are {self.role} (agent: {self.name}).\n"
                f"Objectives: {', '.join(self.objectives) or 'none'}\n"
                f"Task: {task}\n"
                f"Context: {json.dumps(context or {}, default=str)}\n"
                f"Relevant memory:\n{memory_context or '(none)'}\n\n"
                "Return a concise execution plan with steps and expected output."
            )
            strategy = self._ai_adapter.chat([{"role": "user", "content": prompt}]).strip()

        plan = {
            "agent": self.name,
            "role": self.role,
            "task": task,
            "objectives": list(self.objectives),
            "strategy": strategy,
            "context": context or {},
            "memory_used": bool(memory_context),
        }
        self.profile["last_task"] = task
        return plan

    def execute_task(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Execute a task through the workflow engine when available."""
        self.status = "running"
        self.profile["last_task"] = task
        prepared_task = self._merge_context(task, context)
        try:
            if self._workflow_engine is not None:
                result = self._workflow_engine.execute(agent=self, task=prepared_task)
            elif self._ai_adapter is not None:
                system_prompt = self._system_prompt_block(context)
                result = self._ai_adapter.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prepared_task},
                    ]
                )
            else:
                result = "No execution runtime attached to this agent."

            success = not str(result).strip().lower().startswith(("error", "[error]", "beyond_scope"))
            self.record_result(success=success)
            self.profile["last_result"] = str(result)
            self.profile["last_error"] = "" if success else str(result)
            self.status = "completed" if success else "failed"
            self._persist_task_memory(task=task, result=str(result), success=success)
            return str(result)
        except Exception as exc:
            self.record_result(success=False)
            self.profile["last_error"] = str(exc)
            self.profile["last_result"] = ""
            self.status = "failed"
            self._persist_task_memory(task=task, result=str(exc), success=False)
            raise

    def report_status(self) -> dict[str, Any]:
        """Return structured status for orchestration and API monitoring."""
        perf = self.profile.get("performance", {})
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "status": self.status,
            "permission_level": self.permission_level,
            "permission_label": self.permission_label,
            "objectives": list(self.objectives),
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "tasks_completed": int(perf.get("tasks_completed", 0)),
            "tasks_failed": int(perf.get("tasks_failed", 0)),
            "success_rate": float(perf.get("success_rate", 0.0)),
            "last_task": self.profile.get("last_task", ""),
            "last_error": self.profile.get("last_error", ""),
        }

    def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        if self._tool_manager is None:
            raise RuntimeError(f"Agent '{self.name}' has no tool manager attached.")
        return self._tool_manager.call(
            tool_name,
            agent_name=self.name,
            agent_level=self.permission_level,
            **kwargs,
        )

    def _merge_context(self, task: str, context: dict[str, Any] | None) -> str:
        if not context:
            return task
        return f"{task}\n\nContext:\n{json.dumps(context, indent=2, default=str)[:4000]}"

    def _system_prompt_block(self, context: dict[str, Any] | None) -> str:
        objectives = ", ".join(self.objectives) or "none"
        tools = ", ".join(self.tools) or "none"
        context_str = json.dumps(context or {}, default=str)
        return (
            f"You are {self.role} named {self.name}.\n"
            f"Objectives: {objectives}.\n"
            f"Allowed tools: {tools}.\n"
            f"Execution context: {context_str}."
        )

    def _memory_snippets(self, task: str, n_results: int = 3) -> str:
        if self._memory_scope is None or not hasattr(self._memory_scope, "semantic_search"):
            return ""
        try:
            hits = self._memory_scope.semantic_search(task, n_results=max(1, n_results))
        except Exception as exc:
            logger.debug("BaseAgent '%s': memory search failed: %s", self.name, exc)
            return ""

        lines: list[str] = []
        for i, hit in enumerate(hits[:n_results], start=1):
            key = hit.get("key", "")
            value = str(hit.get("value", ""))
            lines.append(f"{i}. {key}: {value[:300]}")
        return "\n".join(lines)

    def _persist_task_memory(self, task: str, result: str, success: bool) -> None:
        if self._memory_scope is None:
            return
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task": task,
            "result": result[:4000],
            "success": success,
            "agent": self.name,
            "role": self.role,
        }
        try:
            if hasattr(self._memory_scope, "append"):
                self._memory_scope.append("task_history", entry)
            if hasattr(self._memory_scope, "save"):
                self._memory_scope.save("last_task_result", entry)
        except Exception as exc:
            logger.debug("BaseAgent '%s': memory persist skipped: %s", self.name, exc)

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
            f"tools={self.tools} skills={self.skills} objectives={self.objectives}>"
        )
