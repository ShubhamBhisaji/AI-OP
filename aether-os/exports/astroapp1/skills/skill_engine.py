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

    def __init__(self, registry, ai_adapter=None):
        self.registry = registry
        self.ai_adapter = ai_adapter  # optional — enables AI-researched upgrades

    def ai_upgrade(self, agent_name: str) -> dict[str, Any]:
        """
        Ask the AI to research the best skills for this agent's role.
        Returns suggested skills + research reason WITHOUT adding anything.
        Caller decides which skills to actually apply (via apply_skills).
        """
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found in registry.")

        if self.ai_adapter:
            existing = ", ".join(agent.skills) or "none"
            prompt = (
                f"You are an expert AI agent designer.\n"
                f"Agent name    : {agent_name}\n"
                f"Agent role    : {agent.role}\n"
                f"Current skills: {existing}\n\n"
                f"Research and identify the TOP 8 most valuable skills this agent "
                f"should have to excel at its role in 2026.\n"
                f"Focus on skills the agent does NOT already have.\n"
                f"Rules:\n"
                f"  1. Output a JSON object with exactly two keys:\n"
                f"     \"skills\": [list of 8 skill names, snake_case, no spaces]\n"
                f"     \"reason\": \"one paragraph explaining why these skills matter\"\n"
                f"  2. Skill names must be concise (1-3 words), lowercase, underscored.\n"
                f"  3. No markdown, no extra text — pure JSON only."
            )
            try:
                import json as _json
                raw = self.ai_adapter.chat([{"role": "user", "content": prompt}])
                raw_clean = raw.strip()
                if raw_clean.startswith("```"):
                    raw_clean = raw_clean.split("```")[1]
                    if raw_clean.startswith("json"):
                        raw_clean = raw_clean[4:]
                parsed = _json.loads(raw_clean)
                suggested = [s.strip().lower().replace(" ", "_") for s in parsed.get("skills", [])]
                research = parsed.get("reason", "")
                logger.info("AI suggested skills for '%s': %s", agent_name, suggested)
            except Exception as exc:
                logger.warning("AI skill research failed (%s); using static map.", exc)
                suggested = self._determine_new_skills(agent)
                research = "(AI unavailable — showing built-in suggestions)"
        else:
            suggested = self._determine_new_skills(agent)
            research = "(No AI adapter — showing built-in suggestions)"

        # Filter out already-owned skills
        suggested = [s for s in suggested if s and s not in agent.skills]
        return {
            "agent": agent_name,
            "role": agent.role,
            "suggested": suggested,
            "research": research,
            "current_skills": list(agent.skills),
        }

    def apply_skills(self, agent_name: str, skills_to_add: list[str]) -> dict[str, Any]:
        """Add a provided list of skills to an agent and save."""
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found in registry.")
        added = []
        for skill in skills_to_add:
            skill = skill.strip().lower().replace(" ", "_")
            if skill and skill not in agent.skills:
                agent.add_skill(skill)
                added.append(skill)
        if added:
            agent.bump_version()
            self.registry._save()
        logger.info("Applied skills to '%s': %s", agent_name, added)
        return {
            "agent": agent_name,
            "version": agent.profile["version"],
            "skills_added": added,
            "all_skills": list(agent.skills),
        }

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
