"""
SkillEngine — Upgrades agent skills, prompts, and tools over time.
Tracks performance history and applies improvement strategies.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Universal foundation skills every proper agent should have ─────────────
_FOUNDATION_SKILLS: list[str] = [
    "task_planning",
    "context_retention",
    "output_formatting",
    "error_recovery",
    "self_reflection",
    "tool_use_optimization",
    "result_verification",
    "prompt_engineering",
]

# ── Tiered skill catalog per role ──────────────────────────────────────────
# Each role has three tiers: foundation → intermediate → advanced
_SKILL_CATALOG: dict[str, dict[str, list[str]]] = {
    "research": {
        "foundation":    ["source_evaluation", "fact_checking", "note_taking", "summarization"],
        "intermediate":  ["citation_management", "trend_analysis", "comparative_analysis",
                          "keyword_extraction", "academic_search"],
        "advanced":      ["deep_research", "hypothesis_generation", "literature_review",
                          "meta_analysis", "expert_synthesis", "bias_detection"],
        "tools":         ["web_search", "pdf_reader", "citation_formatter", "knowledge_graph"],
    },
    "coding": {
        "foundation":    ["code_reading", "debugging", "version_control", "documentation"],
        "intermediate":  ["testing", "code_review", "refactoring", "api_design",
                          "system_design", "security_review"],
        "advanced":      ["architecture_design", "ci_cd", "performance_optimization",
                          "infrastructure_as_code", "distributed_systems", "design_patterns"],
        "tools":         ["linter", "static_analyzer", "test_runner", "profiler", "git"],
    },
    "marketing": {
        "foundation":    ["copywriting", "audience_research", "brand_voice", "seo_basics"],
        "intermediate":  ["a_b_testing", "analytics", "email_campaigns",
                          "social_media_strategy", "content_calendar"],
        "advanced":      ["brand_strategy", "paid_ads", "conversion_optimization",
                          "growth_hacking", "funnel_design", "influencer_coordination"],
        "tools":         ["seo_analyzer", "email_builder", "ad_platform", "analytics_dashboard"],
    },
    "automation": {
        "foundation":    ["workflow_design", "scripting", "scheduling", "logging"],
        "intermediate":  ["error_handling", "event_driven_design", "pipeline_building",
                          "retry_logic", "idempotency"],
        "advanced":      ["distributed_automation", "self_healing_pipelines",
                          "intelligent_routing", "real_time_processing", "orchestration"],
        "tools":         ["task_queue", "cron_manager", "webhook_handler", "monitoring"],
    },
    "data": {
        "foundation":    ["data_cleaning", "exploratory_analysis", "visualization", "sql"],
        "intermediate":  ["statistical_modeling", "feature_engineering", "etl_pipeline",
                          "data_validation", "dashboarding"],
        "advanced":      ["machine_learning", "predictive_modeling", "deep_learning",
                          "real_time_analytics", "mlops", "causal_inference"],
        "tools":         ["pandas", "sql_engine", "visualization_library", "ml_framework"],
    },
    "chatbot": {
        "foundation":    ["conversation_design", "intent_recognition", "fallback_handling",
                          "tone_adaptation"],
        "intermediate":  ["context_memory", "multi_turn_dialogue", "sentiment_analysis",
                          "entity_extraction", "persona_consistency"],
        "advanced":      ["multilingual", "emotional_intelligence", "proactive_suggestions",
                          "long_term_user_modeling", "self_improvement_loop"],
        "tools":         ["nlu_engine", "dialogue_manager", "translation_api", "memory_store"],
    },
    "api": {
        "foundation":    ["rest_principles", "authentication", "request_validation",
                          "response_formatting"],
        "intermediate":  ["rate_limiting", "oauth2", "error_codes", "versioning",
                          "openapi_spec"],
        "advanced":      ["graphql", "webhook_handling", "event_sourcing",
                          "api_gateway_design", "async_apis", "zero_downtime_deployment"],
        "tools":         ["http_client", "openapi_generator", "mock_server", "api_tester"],
    },
    "business": {
        "foundation":    ["requirement_analysis", "stakeholder_communication",
                          "report_writing", "kpi_tracking"],
        "intermediate":  ["market_research", "risk_assessment", "project_management",
                          "cost_benefit_analysis", "competitive_analysis"],
        "advanced":      ["strategic_planning", "financial_modeling", "scenario_planning",
                          "change_management", "executive_briefing", "m_and_a_analysis"],
        "tools":         ["spreadsheet", "project_tracker", "presentation_builder", "crm"],
    },
    "web": {
        "foundation":    ["html_css", "responsive_design", "accessibility",
                          "cross_browser_compat"],
        "intermediate":  ["javascript_es6", "component_architecture", "state_management",
                          "rest_api_integration", "performance_budgets"],
        "advanced":      ["progressive_web_app", "web_animation", "service_workers",
                          "frontend_security", "micro_frontends", "web_assembly"],
        "tools":         ["bundler", "css_preprocessor", "browser_devtools", "lighthouse"],
    },
    "devops": {
        "foundation":    ["linux_basics", "containerization", "ci_cd", "monitoring"],
        "intermediate":  ["kubernetes", "infrastructure_as_code", "secret_management",
                          "incident_response", "log_aggregation"],
        "advanced":      ["chaos_engineering", "zero_trust_security", "gitops",
                          "cost_optimization", "multi_cloud_strategy", "platform_engineering"],
        "tools":         ["docker", "terraform", "prometheus", "grafana", "vault"],
    },
}

# ── Performance thresholds ─────────────────────────────────────────────────
_LEVEL_THRESHOLDS = {
    "foundation":   0,     # always eligible
    "intermediate": 5,     # 5+ tasks completed
    "advanced":     20,    # 20+ tasks completed
}

# Legacy alias kept for compatibility
_UPGRADE_MAP: dict[str, list[str]] = {
    k: v["foundation"] + v["intermediate"]
    for k, v in _SKILL_CATALOG.items()
}


class SkillEngine:
    """
    Handles skill upgrades for registered agents.
    Supports tiered skill catalogs, performance-aware upgrades, and AI research.
    """

    def __init__(self, registry, ai_adapter=None):
        self.registry = registry
        self.ai_adapter = ai_adapter

    # ── Public API ─────────────────────────────────────────────────────────

    def ai_upgrade(self, agent_name: str) -> dict[str, Any]:
        """
        Ask the AI to research the best skills for this agent's role.
        Returns suggested skills + research reason WITHOUT adding anything.
        Caller decides which skills to actually apply (via apply_skills).
        """
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found in registry.")

        catalog_skills = self._catalog_suggestions(agent)
        missing_foundation = [s for s in _FOUNDATION_SKILLS if s not in agent.skills]

        if self.ai_adapter:
            existing = ", ".join(agent.skills) or "none"
            tasks_done = agent.profile["performance"].get("tasks_completed", 0)
            success_rate = agent.profile["performance"].get("success_rate", 1.0)
            level = self._agent_level(agent)

            catalog_hint = ""
            role_key = self._role_key(agent)
            if role_key:
                cat = _SKILL_CATALOG[role_key]
                catalog_hint = (
                    f"\nSkill catalog for this role:\n"
                    f"  Foundation   : {', '.join(cat['foundation'])}\n"
                    f"  Intermediate : {', '.join(cat['intermediate'])}\n"
                    f"  Advanced     : {', '.join(cat['advanced'])}\n"
                    f"  Recommended tools: {', '.join(cat['tools'])}\n"
                )

            prompt = (
                f"You are an expert AI agent architect specialising in building "
                f"production-ready autonomous agents.\n\n"
                f"AGENT PROFILE\n"
                f"  Name         : {agent_name}\n"
                f"  Role         : {agent.role}\n"
                f"  Level        : {level}  ({tasks_done} tasks, "
                f"{success_rate * 100:.0f}% success)\n"
                f"  Current skills: {existing}\n"
                f"  Missing foundation skills: "
                f"{', '.join(missing_foundation) or 'none'}\n"
                f"{catalog_hint}\n"
                f"TASK\n"
                f"Recommend exactly 20 skills most relevant to a '{agent.role}' agent.\n"
                f"Every skill must be directly tied to what a {agent.role} does in practice.\n"
                f"Rules:\n"
                f"  1. Prioritise missing foundation skills first if any exist.\n"
                f"  2. Match level: beginner → foundation, intermediate → role skills,\n"
                f"     advanced → specialised/cross-domain.\n"
                f"  3. If success rate < 70%, include error_recovery and self_reflection.\n"
                f"  4. All 20 skills must relate specifically to the role description — "
                f"no generic filler skills.\n"
                f"  5. Output pure JSON only — no markdown, no extra text:\n"
                f"     {{\"skills\": [\"skill_name\", ...],\n"
                f"      \"tier\": \"foundation|intermediate|advanced\",\n"
                f"      \"reason\": \"one paragraph\",\n"
                f"      \"tools\": [\"tool1\", \"tool2\"]}}\n"
                f"  6. Skill names: snake_case, 1–3 words, all lowercase.\n"
                f"  7. Exclude skills the agent already has."
            )
            try:
                import json as _json
                raw = self.ai_adapter.chat([{"role": "user", "content": prompt}])
                raw_clean = raw.strip()
                if raw_clean.startswith("```"):
                    raw_clean = raw_clean.split("```")[1]
                    if raw_clean.lower().startswith("json"):
                        raw_clean = raw_clean[4:]
                parsed = _json.loads(raw_clean)
                suggested = [
                    s.strip().lower().replace(" ", "_")
                    for s in parsed.get("skills", [])
                ]
                research  = parsed.get("reason", "")
                tier      = parsed.get("tier", level)
                rec_tools = parsed.get("tools", [])
                logger.info("AI suggested skills for '%s': %s", agent_name, suggested)
            except Exception as exc:
                logger.warning("AI skill research failed (%s); using catalog.", exc)
                suggested  = catalog_skills
                research   = "(AI unavailable — using skill catalog)"
                tier       = level
                rec_tools  = []
        else:
            suggested  = catalog_skills
            research   = "(No AI adapter — using skill catalog)"
            tier       = self._agent_level(agent)
            rec_tools  = []

        # Always surface missing foundation skills
        for s in missing_foundation:
            if s not in suggested:
                suggested.insert(0, s)

        # Filter already-owned
        suggested = [s for s in suggested if s and s not in agent.skills]

        return {
            "agent":          agent_name,
            "role":           agent.role,
            "level":          tier,
            "suggested":      suggested,
            "research":       research,
            "recommended_tools": rec_tools,
            "current_skills": list(agent.skills),
            "missing_foundation": missing_foundation,
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
            "agent":      agent_name,
            "version":    agent.profile["version"],
            "skills_added": added,
            "all_skills": list(agent.skills),
        }

    def upgrade(self, agent_name: str) -> dict[str, Any]:
        """Static catalog-based upgrade (no AI call). Always available."""
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found in registry.")

        new_skills = self._catalog_suggestions(agent)
        # Always add missing foundation skills
        for s in _FOUNDATION_SKILLS:
            if s not in agent.skills and s not in new_skills:
                new_skills.insert(0, s)

        added: list[str] = []
        for skill in new_skills:
            if skill and skill not in agent.skills:
                agent.add_skill(skill)
                added.append(skill)

        agent.bump_version()
        logger.info(
            "SkillEngine: upgraded '%s' to v%s — added: %s",
            agent_name, agent.profile["version"], added or "none",
        )
        return {
            "agent":      agent_name,
            "version":    agent.profile["version"],
            "skills_added": added,
            "all_skills": list(agent.skills),
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
        level = self._agent_level(agent)
        missing_foundation = [s for s in _FOUNDATION_SKILLS if s not in agent.skills]
        return {
            "agent":              agent_name,
            "role":               agent.role,
            "level":              level,
            "version":            agent.profile["version"],
            "performance":        agent.profile["performance"],
            "skills":             agent.skills,
            "tools":              agent.tools,
            "missing_foundation": missing_foundation,
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _agent_level(self, agent) -> str:
        tasks = agent.profile["performance"].get("tasks_completed", 0)
        if tasks >= _LEVEL_THRESHOLDS["advanced"]:
            return "advanced"
        if tasks >= _LEVEL_THRESHOLDS["intermediate"]:
            return "intermediate"
        return "foundation"

    def _role_key(self, agent) -> str | None:
        role_lower = agent.role.lower()
        for keyword in _SKILL_CATALOG:
            if keyword in role_lower:
                return keyword
        return None

    def _catalog_suggestions(self, agent) -> list[str]:
        """Return skill suggestions from the catalog based on agent level."""
        role_key = self._role_key(agent)
        level    = self._agent_level(agent)
        existing = set(agent.skills)

        if role_key:
            cat = _SKILL_CATALOG[role_key]
            if level == "advanced":
                pool = cat["foundation"] + cat["intermediate"] + cat["advanced"]
            elif level == "intermediate":
                pool = cat["foundation"] + cat["intermediate"]
            else:
                pool = cat["foundation"]
        else:
            pool = _FOUNDATION_SKILLS[:]

        return [s for s in pool if s not in existing]

    # Legacy helper — kept for backward compat
    def _determine_new_skills(self, agent) -> list[str]:
        return self._catalog_suggestions(agent) or ["problem_solving", "critical_thinking"]



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
                f"Research and identify exactly 20 highly specific skills this agent "
                f"should have to excel at its role in 2026.\n"
                f"Every skill must be directly relevant to what a '{agent.role}' does — "
                f"no generic filler.\n"
                f"Focus only on skills the agent does NOT already have.\n"
                f"Rules:\n"
                f"  1. Output a JSON object with exactly two keys:\n"
                f"     \"skills\": [list of exactly 20 skill names, snake_case, no spaces]\n"
                f"     \"reason\": \"one paragraph explaining why these 20 skills matter "
                f"for a {agent.role}\"\n"
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
