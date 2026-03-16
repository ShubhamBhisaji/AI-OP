"""
AgentFactory — Dynamically creates and registers AI agents.
Supports built-in presets and fully custom agent configurations.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# Built-in agent presets (role → default skills + tools)
AGENT_PRESETS: dict[str, dict[str, Any]] = {
    "research_agent": {
        "role": "Research Agent",
        "tools": ["web_search", "file_writer"],
        "skills": ["summarization", "fact_checking", "web_research"],
    },
    "coding_agent": {
        "role": "Coding Agent",
        "tools": ["file_writer", "code_runner"],
        "skills": ["python", "debugging", "code_review", "refactoring"],
    },
    "marketing_agent": {
        "role": "Marketing Agent",
        "tools": ["file_writer", "web_search"],
        "skills": ["copywriting", "seo", "social_media", "campaign_planning"],
    },
    "automation_agent": {
        "role": "Automation Agent",
        "tools": ["file_writer", "web_search", "code_runner"],
        "skills": ["scripting", "workflow_design", "process_automation"],
    },
    "data_analysis_agent": {
        "role": "Data Analysis Agent",
        "tools": ["file_writer", "code_runner"],
        "skills": ["data_cleaning", "statistics", "visualization", "reporting"],
    },
    "chatbot_agent": {
        "role": "Chatbot Agent",
        "tools": [],
        "skills": ["conversation", "intent_detection", "empathy"],
    },
    "api_agent": {
        "role": "API Agent",
        "tools": ["web_search", "file_writer"],
        "skills": ["rest_api", "json_parsing", "authentication"],
    },
    "business_agent": {
        "role": "Business Agent",
        "tools": ["web_search", "file_writer"],
        "skills": ["strategy", "financial_analysis", "reporting", "planning"],
    },
}


class AgentFactory:
    """
    Creates BaseAgent instances either from built-in presets or
    from a fully custom specification dict/YAML config.
    """

    def __init__(self, registry, tool_manager, ai_adapter):
        self.registry = registry
        self.tool_manager = tool_manager
        self.ai_adapter = ai_adapter

    def create(
        self,
        name: str,
        role: str | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        permission_level: int = 1,
    ) -> BaseAgent:
        """
        Create an agent.

        If `name` matches a preset key, preset defaults are used unless
        overridden by explicit `role`, `tools`, or `skills` arguments.
        `permission_level` sets the agent's RBAC level (0–3, default 1).
        """
        preset = AGENT_PRESETS.get(name, {})
        resolved_role = role or preset.get("role", name.replace("_", " ").title())
        resolved_tools = tools if tools is not None else preset.get("tools", [])
        resolved_skills = skills if skills is not None else preset.get("skills", [])

        # Validate that requested tools are registered
        for tool in resolved_tools:
            if not self.tool_manager.has(tool):
                logger.warning(
                    "Tool '%s' requested by agent '%s' is not registered in ToolManager.", tool, name
                )

        agent = BaseAgent(
            name=name,
            role=resolved_role,
            tools=resolved_tools,
            skills=resolved_skills,
            permission_level=permission_level,
        )
        self.registry.register(agent)
        logger.info(
            "AgentFactory: created and registered agent '%s' (%s) level=%d.",
            name, resolved_role, permission_level,
        )
        return agent

    def create_from_config(self, config: dict[str, Any]) -> BaseAgent:
        """
        Create an agent from a configuration dict (e.g. parsed from JSON/YAML).

        Expected keys: name, role, tools (list), skills (list), permission_level (int)
        """
        name = config["name"]
        role = config.get("role")
        tools = config.get("tools", [])
        skills = config.get("skills", [])
        permission_level = int(config.get("permission_level", 1))
        return self.create(name=name, role=role, tools=tools, skills=skills, permission_level=permission_level)

    @staticmethod
    def list_presets() -> list[str]:
        """Return the names of all built-in agent presets."""
        return list(AGENT_PRESETS.keys())
