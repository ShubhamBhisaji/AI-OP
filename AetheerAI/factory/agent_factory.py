"""AgentFactory for dynamic, reusable agent creation.

Capabilities:
- Create agents from built-in presets
- Save and reuse project-independent agent templates
- Create agents from custom config dictionaries
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from security.policy_engine import PermissionLevel
from utils.json_parser import extract_json

logger = logging.getLogger(__name__)

_TEMPLATE_STORE = Path(__file__).parent / "agent_templates.json"


_DESIGN_SYSTEM_PROMPT = """You are designing a production AI specialist agent.
Return ONLY JSON object with keys:
{
    "role": "Human readable role title",
    "objectives": ["clear objective"],
    "skills": ["skill_name"],
    "tools": ["registered_tool_name"],
    "permissions": ["permission:scope"],
    "permission_level": 1
}

Rules:
- Use concise actionable objectives.
- Prefer existing registered tools.
- Keep permission_level between 1 and 5.
"""

# Built-in agent presets (role → default skills + tools)
AGENT_PRESETS: dict[str, dict[str, Any]] = {
    "research_agent": {
        "role": "Research Agent",
        "objectives": [
            "Gather verifiable information",
            "Produce concise, sourced reports",
        ],
        "tools": ["web_search", "file_writer"],
        "skills": ["summarization", "fact_checking", "web_research"],
        "permissions": ["read:web", "write:workspace"],
    },
    "coding_agent": {
        "role": "Coding Agent",
        "objectives": [
            "Build and refactor production quality code",
            "Validate outputs with tests and linting",
        ],
        "tools": ["file_writer", "code_runner"],
        "skills": ["python", "debugging", "code_review", "refactoring"],
        "permissions": ["read:workspace", "write:workspace", "execute:code"],
    },
    "marketing_agent": {
        "role": "Marketing Agent",
        "objectives": [
            "Create persuasive audience-aligned messaging",
            "Improve SEO and campaign quality",
        ],
        "tools": ["file_writer", "web_search"],
        "skills": ["copywriting", "seo", "social_media", "campaign_planning"],
        "permissions": ["read:web", "write:workspace"],
    },
    "automation_agent": {
        "role": "Automation Agent",
        "objectives": [
            "Automate repetitive tasks safely",
            "Execute workflows with clear logs",
        ],
        "tools": ["file_writer", "web_search", "code_runner"],
        "skills": ["scripting", "workflow_design", "process_automation"],
        "permissions": ["read:workspace", "write:workspace", "execute:code"],
    },
    "data_analysis_agent": {
        "role": "Data Analysis Agent",
        "objectives": [
            "Transform raw data into decisions",
            "Produce accurate reproducible summaries",
        ],
        "tools": ["file_writer", "code_runner"],
        "skills": ["data_cleaning", "statistics", "visualization", "reporting"],
        "permissions": ["read:data", "write:workspace", "execute:code"],
    },
    "chatbot_agent": {
        "role": "Chatbot Agent",
        "objectives": [
            "Answer user questions helpfully",
            "Escalate ambiguous issues responsibly",
        ],
        "tools": [],
        "skills": ["conversation", "intent_detection", "empathy"],
        "permissions": ["read:knowledge"],
    },
    "api_agent": {
        "role": "API Agent",
        "objectives": [
            "Integrate external APIs reliably",
            "Handle authentication and schema validation",
        ],
        "tools": ["web_search", "file_writer"],
        "skills": ["rest_api", "json_parsing", "authentication"],
        "permissions": ["read:web", "write:workspace"],
    },
    "business_agent": {
        "role": "Business Agent",
        "objectives": [
            "Align plans with business outcomes",
            "Prioritize ROI and operational feasibility",
        ],
        "tools": ["web_search", "file_writer"],
        "skills": ["strategy", "financial_analysis", "reporting", "planning"],
        "permissions": ["read:web", "write:workspace"],
    },
}


class AgentFactory:
    """
    Creates BaseAgent instances either from built-in presets or
    from a fully custom specification dict/YAML config.
    """

    def __init__(self, registry, tool_manager, ai_adapter, template_store_path: str | None = None):
        self.registry = registry
        self.tool_manager = tool_manager
        self.ai_adapter = ai_adapter
        self._template_store = Path(template_store_path) if template_store_path else _TEMPLATE_STORE
        self._templates: dict[str, dict[str, Any]] = {}
        self._load_templates()

    @staticmethod
    def _normalize_permission_level(permission_level: int | PermissionLevel | None) -> int:
        if permission_level is None:
            return 1
        if isinstance(permission_level, PermissionLevel):
            return int(permission_level)
        try:
            return int(permission_level)
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _merge_unique(primary: list[str] | None, secondary: list[str] | None) -> list[str]:
        merged: list[str] = []
        for item in (primary or []) + (secondary or []):
            if item and item not in merged:
                merged.append(item)
        return merged

    @staticmethod
    def _coerce_str_list(value: Any, *, max_items: int = 12) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            candidate = str(item).strip()
            if candidate and candidate not in out:
                out.append(candidate)
            if len(out) >= max_items:
                break
        return out

    def design_agent(
        self,
        *,
        name: str,
        role_description: str,
        goal: str,
        context: dict[str, Any] | None = None,
        permission_level: int | PermissionLevel | None = None,
    ) -> BaseAgent:
        """Design and create an agent dynamically from goal + role description."""
        if not name.strip():
            raise ValueError("Agent name is required.")

        if self.registry.get(name):
            raise ValueError(f"Agent '{name}' already exists.")

        available_tools = self.tool_manager.list_tools()
        design_prompt = (
            f"Goal: {goal}\n"
            f"Requested role description: {role_description}\n"
            f"Known tools: {', '.join(available_tools) or '(none)'}\n"
            f"Context: {json.dumps(context or {}, default=str)}"
        )

        raw_design = ""
        spec: dict[str, Any] = {}
        try:
            raw_design = str(
                self.ai_adapter.chat(
                    [
                        {"role": "system", "content": _DESIGN_SYSTEM_PROMPT},
                        {"role": "user", "content": design_prompt},
                    ]
                )
            )
            parsed = extract_json(raw_design, safe=True, default={})
            if isinstance(parsed, dict):
                spec = parsed
        except Exception as exc:
            logger.warning("AgentFactory: dynamic design failed, using fallback profile: %s", exc)

        role = str(spec.get("role", "")).strip() or role_description.strip().title() or "Specialist Agent"
        objectives = self._coerce_str_list(spec.get("objectives"))
        skills = self._coerce_str_list(spec.get("skills"))
        requested_tools = self._coerce_str_list(spec.get("tools"))
        permissions = self._coerce_str_list(spec.get("permissions"))

        if not objectives:
            objectives = [f"Advance goal: {goal[:120]}", "Produce reliable, auditable outcomes"]

        available_tool_set = set(available_tools)
        tools = [tool for tool in requested_tools if tool in available_tool_set]
        if not tools and "file_writer" in available_tool_set:
            tools = ["file_writer"]

        resolved_level = (
            self._normalize_permission_level(permission_level)
            if permission_level is not None
            else self._normalize_permission_level(spec.get("permission_level", PermissionLevel.STANDARD))
        )

        if not permissions:
            permissions = ["read:workspace"]
            if resolved_level >= int(PermissionLevel.ELEVATED):
                permissions.append("write:workspace")

        logger.info("AgentFactory: dynamically designed agent '%s' (%s).", name, role)
        if raw_design:
            logger.debug("AgentFactory: design raw payload for '%s': %s", name, raw_design[:1200])

        return self.create(
            name=name,
            role=role,
            tools=tools,
            skills=skills,
            objectives=objectives,
            permissions=permissions,
            permission_level=resolved_level,
        )

    def create(
        self,
        name: str,
        role: str | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        objectives: list[str] | None = None,
        permissions: list[str] | None = None,
        permission_level: int | PermissionLevel = PermissionLevel.STANDARD,
        template: str | None = None,
    ) -> BaseAgent:
        """
        Create and register an agent from a preset, template, or custom config.

        Resolution order:
        1) Explicit template argument
        2) Built-in preset matching name
        3) Built-in preset matching role (backward compatibility path)
        4) Free-form role with custom inputs
        """
        preset: dict[str, Any] = {}
        if template:
            preset = self._templates.get(template, {})
            if not preset:
                raise ValueError(f"Template '{template}' not found.")
        elif name in AGENT_PRESETS:
            preset = AGENT_PRESETS[name]
        elif role in AGENT_PRESETS:
            # Some legacy callers passed a preset key through `role`.
            preset = AGENT_PRESETS[role]

        resolved_role = role
        if role in AGENT_PRESETS:
            resolved_role = AGENT_PRESETS[role]["role"]
        if not resolved_role:
            resolved_role = preset.get("role", name.replace("_", " ").title())

        resolved_tools = list(tools) if tools is not None else list(preset.get("tools", []))
        resolved_skills = list(skills) if skills is not None else list(preset.get("skills", []))
        resolved_objectives = list(objectives) if objectives is not None else list(preset.get("objectives", []))
        resolved_permissions = list(permissions) if permissions is not None else list(preset.get("permissions", []))
        resolved_permission_level = self._normalize_permission_level(permission_level)

        if template:
            logger.info("AgentFactory: creating agent '%s' from template '%s'.", name, template)

        # Validate that requested tools are registered
        for tool in resolved_tools:
            if not self.tool_manager.has(tool):
                logger.warning(
                    "Tool '%s' requested by agent '%s' is not registered in ToolManager.", tool, name
                )

        agent = BaseAgent(
            name=name,
            role=resolved_role,
            objectives=resolved_objectives,
            tools=resolved_tools,
            skills=resolved_skills,
            permissions=resolved_permissions,
            permission_level=resolved_permission_level,
            ai_adapter=self.ai_adapter,
            tool_manager=self.tool_manager,
        )
        self.registry.register(agent)
        logger.info(
            "AgentFactory: created and registered agent '%s' (%s) level=%d.",
            name, resolved_role, resolved_permission_level,
        )
        return agent

    def create_from_config(self, config: dict[str, Any]) -> BaseAgent:
        """
        Create an agent from a configuration dict (e.g. parsed from JSON/YAML).

        Expected keys include:
        - name, role, tools, skills, objectives, permissions
        - permission_level
        - template (optional)
        """
        name = config["name"]
        role = config.get("role")
        tools = config.get("tools", [])
        skills = config.get("skills", [])
        objectives = config.get("objectives", [])
        permissions = config.get("permissions", [])
        permission_level = self._normalize_permission_level(config.get("permission_level", 1))
        template = config.get("template")
        return self.create(
            name=name,
            role=role,
            tools=tools,
            skills=skills,
            objectives=objectives,
            permissions=permissions,
            permission_level=permission_level,
            template=template,
        )

    # ------------------------------------------------------------------
    # Template lifecycle
    # ------------------------------------------------------------------

    def register_template(
        self,
        template_name: str,
        *,
        role: str,
        objectives: list[str] | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        permissions: list[str] | None = None,
        permission_level: int | PermissionLevel = PermissionLevel.STANDARD,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if template_name in self._templates and not overwrite:
            raise ValueError(
                f"Template '{template_name}' already exists. Use overwrite=True to replace it."
            )

        payload = {
            "role": role,
            "objectives": list(objectives or []),
            "tools": list(tools or []),
            "skills": list(skills or []),
            "permissions": list(permissions or []),
            "permission_level": self._normalize_permission_level(permission_level),
        }
        self._templates[template_name] = payload
        self._save_templates()
        logger.info("AgentFactory: template '%s' saved.", template_name)
        return {"template": template_name, **payload}

    def list_templates(self) -> dict[str, dict[str, Any]]:
        return {name: dict(data) for name, data in self._templates.items()}

    def delete_template(self, template_name: str) -> bool:
        if template_name not in self._templates:
            return False
        del self._templates[template_name]
        self._save_templates()
        logger.info("AgentFactory: template '%s' deleted.", template_name)
        return True

    def create_from_template(
        self,
        *,
        template_name: str,
        name: str,
        role: str | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        objectives: list[str] | None = None,
        permissions: list[str] | None = None,
        permission_level: int | PermissionLevel | None = None,
    ) -> BaseAgent:
        tpl = self._templates.get(template_name)
        if tpl is None:
            raise ValueError(f"Template '{template_name}' not found.")

        return self.create(
            name=name,
            role=role or tpl.get("role"),
            tools=self._merge_unique(tpl.get("tools", []), tools),
            skills=self._merge_unique(tpl.get("skills", []), skills),
            objectives=self._merge_unique(tpl.get("objectives", []), objectives),
            permissions=self._merge_unique(tpl.get("permissions", []), permissions),
            permission_level=(
                self._normalize_permission_level(permission_level)
                if permission_level is not None
                else self._normalize_permission_level(tpl.get("permission_level", 1))
            ),
        )

    def _load_templates(self) -> None:
        if not self._template_store.exists():
            self._templates = {}
            return
        try:
            data = json.loads(self._template_store.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._templates = {k: v for k, v in data.items() if isinstance(v, dict)}
            else:
                self._templates = {}
            logger.info("AgentFactory: loaded %d template(s).", len(self._templates))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("AgentFactory: failed to load templates: %s", exc)
            self._templates = {}

    def _save_templates(self) -> None:
        self._template_store.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._template_store.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(json.dumps(self._templates, indent=2), encoding="utf-8")
            tmp_path.replace(self._template_store)
        except OSError as exc:
            logger.error("AgentFactory: failed to save templates: %s", exc)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    @staticmethod
    def list_presets() -> list[str]:
        """Return the names of all built-in agent presets."""
        return list(AGENT_PRESETS.keys())
