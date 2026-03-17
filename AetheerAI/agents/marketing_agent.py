"""
MarketingAgent — Specialist for content creation, SEO, and campaign planning.

Uses: file_writer, web_search, text_analyzer, markdown_tool.
Permission level: 1 (STANDARD).
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Marketing AI agent in the AETHER OS platform.

Your responsibilities:
- Create compelling, audience-appropriate marketing content.
- Write blog posts, social media copy, email campaigns, and ad text.
- Apply SEO best practices: keyword placement, meta descriptions, headings.
- Develop campaign strategies aligned with the project's goals.
- Tailor tone and messaging to the target audience described in the task.
- Always produce content that is truthful and compliant (no false claims).

Output formats:
- Blog post: title, meta description, H2/H3 sections, CTA.
- Social post: platform tag + copy + hashtags.
- Email: Subject | Preview | Body | CTA.
- Campaign brief: Objective | Audience | Channels | KPIs | Budget estimate.
"""


class MarketingAgent(BaseAgent):
    """Marketing specialist: content creation, SEO, campaign planning."""

    DEFAULT_TOOLS: list[str] = [
        "file_writer",
        "web_search",
        "text_analyzer",
        "markdown_tool",
        "template_tool",
    ]
    DEFAULT_SKILLS: list[str] = [
        "copywriting", "seo", "social_media", "email_marketing",
        "campaign_planning", "brand_voice", "audience_targeting",
    ]

    def __init__(
        self,
        name: str,
        *,
        registry=None,
        tool_manager=None,
        ai_adapter=None,
        extra_tools: list[str] | None = None,
        extra_skills: list[str] | None = None,
        permission_level: int = 1,
    ) -> None:
        tools  = list(self.DEFAULT_TOOLS)  + (extra_tools  or [])
        skills = list(self.DEFAULT_SKILLS) + (extra_skills or [])
        super().__init__(
            name=name,
            role="Marketing Agent",
            tools=tools,
            skills=skills,
            permission_level=permission_level,
        )
        self._registry     = registry
        self._tool_manager = tool_manager
        self._ai_adapter   = ai_adapter
        self._system_prompt = _SYSTEM_PROMPT
        logger.info("[MarketingAgent] '%s' ready.", name)

    # ── Core helpers ──────────────────────────────────────────────────────────

    def run_task(self, task: str) -> str:
        if self._ai_adapter is None:
            return "[MarketingAgent] No AI adapter configured."
        return self._ai_adapter.chat([
            {"role": "system", "content": self._system_prompt},
            {"role": "user",   "content": task},
        ])

    def use_tool(self, tool_name: str, **kwargs) -> Any:
        if self._tool_manager is None:
            return {"error": "No ToolManager configured."}
        try:
            return self._tool_manager.call(
                tool_name,
                agent_name=self.name,
                agent_level=self.permission_level,
                **kwargs,
            )
        except Exception as exc:
            logger.warning("[MarketingAgent] Tool '%s' failed: %s", tool_name, exc)
            return {"error": str(exc)}

    # ── Convenience helpers ───────────────────────────────────────────────────

    def write_blog_post(self, topic: str, keywords: list[str], word_count: int = 800) -> str:
        """Generate and return a blog post draft."""
        prompt = (
            f"Write a {word_count}-word SEO-optimised blog post about '{topic}'. "
            f"Target keywords: {', '.join(keywords)}."
        )
        return self.run_task(prompt)

    def write_social_copy(self, platform: str, message: str, cta: str) -> str:
        """Generate platform-specific social copy."""
        prompt = (
            f"Write {platform} copy for this message: '{message}'. "
            f"CTA: {cta}. Include relevant hashtags."
        )
        return self.run_task(prompt)

    def create_campaign_brief(self, objective: str, audience: str, budget: str) -> str:
        """Draft a marketing campaign brief."""
        prompt = (
            f"Create a marketing campaign brief. "
            f"Objective: {objective}. Target audience: {audience}. Budget: {budget}."
        )
        return self.run_task(prompt)
