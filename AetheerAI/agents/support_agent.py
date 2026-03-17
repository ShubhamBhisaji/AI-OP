"""
SupportAgent — Specialist for Q&A, customer support, and knowledge retrieval.

Handles: answering questions, explaining features, troubleshooting user issues,
knowledge base queries, and escalation routing.

Permission level: 1 (STANDARD) — read-only access to knowledge base and web.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a Customer Support AI agent in the AETHER OS platform.

Your responsibilities:
- Answer user questions accurately and empathetically.
- Explain technical concepts in plain, accessible language.
- Troubleshoot issues step-by-step: ask clarifying questions if needed.
- Search the knowledge base and product documentation before answering.
- If you don't know the answer, say so honestly and suggest escalation paths.
- Keep responses concise but complete — respect the user's time.

Response format for support tickets:
- Greeting
- Understanding (restate the issue in your own words)
- Solution / Steps
- Verification (ask if this resolves the issue)
- Escalation path (if needed)

NEVER promise features that don't exist.
NEVER share other users' data.
"""


class SupportAgent(BaseAgent):
    """Support specialist: Q&A, troubleshooting, and knowledge retrieval."""

    DEFAULT_TOOLS: list[str] = [
        "web_search",
        "file_reader",
        "text_analyzer",
        "note_taker",
    ]
    DEFAULT_SKILLS: list[str] = [
        "conversation", "intent_detection", "empathy",
        "troubleshooting", "knowledge_retrieval", "escalation_routing",
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
        knowledge_base_path: str | None = None,
    ) -> None:
        tools  = list(self.DEFAULT_TOOLS)  + (extra_tools  or [])
        skills = list(self.DEFAULT_SKILLS) + (extra_skills or [])
        super().__init__(
            name=name,
            role="Support Agent",
            tools=tools,
            skills=skills,
            permission_level=permission_level,
        )
        self._registry     = registry
        self._tool_manager = tool_manager
        self._ai_adapter   = ai_adapter
        self._system_prompt = _SYSTEM_PROMPT
        self._kb_path = knowledge_base_path
        logger.info("[SupportAgent] '%s' ready.", name)

    # ── Core helpers ──────────────────────────────────────────────────────────

    def run_task(self, task: str) -> str:
        if self._ai_adapter is None:
            return "[SupportAgent] No AI adapter configured."
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
            logger.warning("[SupportAgent] Tool '%s' failed: %s", tool_name, exc)
            return {"error": str(exc)}

    # ── Convenience helpers ───────────────────────────────────────────────────

    def answer(self, question: str, *, user_context: str = "") -> str:
        """Answer a support question, optionally with user context."""
        task = f"Support question: {question}"
        if user_context:
            task += f"\n\nUser context: {user_context}"
        return self.run_task(task)

    def search_kb(self, query: str) -> str:
        """Search the knowledge base file (if configured)."""
        if not self._kb_path:
            return "(No knowledge base configured.)"
        result = self.use_tool("file_reader", filename=self._kb_path)
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        # Ask the agent to pull the relevant answer from the content
        task = f"In this knowledge base:\n\n{content[:4000]}\n\nAnswer: {query}"
        return self.run_task(task)

    def escalate(self, issue: str, priority: str = "medium") -> dict[str, Any]:
        """Log an escalation note."""
        return self.use_tool(
            "note_taker",
            title=f"ESCALATION [{priority.upper()}]",
            content=issue,
        )
