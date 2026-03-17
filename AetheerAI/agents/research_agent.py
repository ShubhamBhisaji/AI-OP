"""
ResearchAgent — Specialist for web research, fact-finding, and summarisation.

Uses: web_search, web_scraper_pro, http_client, file_writer, text_analyzer.
Permission level: 1 (STANDARD) — no code execution needed.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Research AI agent in the AETHER OS platform.

Your responsibilities:
- Find accurate, up-to-date information from multiple sources.
- Cross-check facts before reporting them.
- Summarise findings concisely and cite sources (URL + date accessed).
- Flag uncertain or conflicting information clearly.
- Deliver structured reports: Executive Summary → Key Findings → Sources.

NEVER fabricate URLs, statistics, or citations.
If you cannot verify a claim, state: "Unverified — further research needed."
"""


class ResearchAgent(BaseAgent):
    """Research specialist: web search, data gathering, fact-checking."""

    DEFAULT_TOOLS: list[str] = [
        "web_search",
        "web_scraper_pro",
        "http_client",
        "file_writer",
        "text_analyzer",
        "url_tool",
    ]
    DEFAULT_SKILLS: list[str] = [
        "web_research", "summarisation", "fact_checking",
        "report_writing", "source_evaluation",
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
            role="Research Agent",
            tools=tools,
            skills=skills,
            permission_level=permission_level,
        )
        self._registry     = registry
        self._tool_manager = tool_manager
        self._ai_adapter   = ai_adapter
        self._system_prompt = _SYSTEM_PROMPT
        logger.info("[ResearchAgent] '%s' ready.", name)

    # ── Core helpers ──────────────────────────────────────────────────────────

    def run_task(self, task: str) -> str:
        if self._ai_adapter is None:
            return "[ResearchAgent] No AI adapter configured."
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
            logger.warning("[ResearchAgent] Tool '%s' failed: %s", tool_name, exc)
            return {"error": str(exc)}

    # ── Convenience helpers ───────────────────────────────────────────────────

    def search(self, query: str, num_results: int = 5) -> list[dict[str, Any]]:
        """Run a web search and return result list."""
        result = self.use_tool("web_search", query=query, num_results=num_results)
        if isinstance(result, list):
            return result
        return [{"content": str(result)}]

    def scrape(self, url: str) -> str:
        """Scrape a web page and return cleaned text."""
        result = self.use_tool("web_scraper_pro", url=url)
        return result.get("text", "") if isinstance(result, dict) else str(result)

    def save_report(self, filename: str, content: str) -> dict[str, Any]:
        """Save research findings to a file."""
        return self.use_tool("file_writer", filename=filename, content=content)
