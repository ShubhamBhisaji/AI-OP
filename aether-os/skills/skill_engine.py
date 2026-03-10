"""
SkillEngine — Upgrades agent skills, prompts, and tools over time.
Tracks performance history and applies improvement strategies.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maps a role keyword to additional skills unlocked on upgrade
_UPGRADE_MAP: dict[str, list[str]] = {
    "research": ["deep_research", "citation_management", "trend_analysis"],
    "coding": ["testing", "ci_cd", "architecture_design", "security_review"],
    "marketing": ["a_b_testing", "analytics", "brand_strategy", "paid_ads"],
    "automation": ["error_handling", "scheduling", "event_driven_design"],
    "data": ["machine_learning", "predictive_modeling", "etl_pipeline"],
    "chatbot": ["multilingual", "context_memory", "sentiment_analysis"],
    "api": ["rate_limiting", "oauth2", "graphql", "webhook_handling"],
    "business": ["market_research", "risk_assessment", "competitive_analysis"],
}


class SkillEngine:
    """
    Handles skill upgrades for registered agents.
    """

    def __init__(self, registry):
        self.registry = registry

    def upgrade(self, agent_name: str) -> dict[str, Any]:
        """
        Upgrade an agent's skills based on its role and performance history.
        Returns a summary of what was added.
        """
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found in registry.")

        new_skills = self._determine_new_skills(agent)
        added: list[str] = []
        for skill in new_skills:
            if skill not in agent.skills:
                agent.add_skill(skill)
                added.append(skill)

        agent.bump_version()
        logger.info(
            "SkillEngine: upgraded agent '%s' to v%s — added skills: %s",
            agent_name,
            agent.profile["version"],
            added or "none (already at max for this role)",
        )
        return {
            "agent": agent_name,
            "version": agent.profile["version"],
            "skills_added": added,
            "all_skills": agent.skills,
        }

    def add_tool(self, agent_name: str, tool: str) -> None:
        """Dynamically add a tool to an existing agent."""
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found in registry.")
        agent.add_tool(tool)
        agent.bump_version()
        logger.info("SkillEngine: added tool '%s' to agent '%s'.", tool, agent_name)

    def get_performance_report(self, agent_name: str) -> dict[str, Any]:
        """Return the performance metrics for an agent."""
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found in registry.")
        return {
            "agent": agent_name,
            "role": agent.role,
            "version": agent.profile["version"],
            "performance": agent.profile["performance"],
            "skills": agent.skills,
            "tools": agent.tools,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _determine_new_skills(self, agent) -> list[str]:
        role_lower = agent.role.lower()
        for keyword, skills in _UPGRADE_MAP.items():
            if keyword in role_lower:
                return skills
        # Generic upgrade for unknown roles
        return ["problem_solving", "critical_thinking", "communication"]
