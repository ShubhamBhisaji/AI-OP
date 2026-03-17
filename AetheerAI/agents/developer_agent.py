"""
DeveloperAgent — Specialist for writing, analysing, and debugging code.

Extends BaseAgent with developer-centric system prompt, tools, and helper
methods. Works with: file_writer, file_reader, code_runner, code_analyzer,
linter_tool, code_formatter.

Permission level: 2 (ELEVATED) — can read and write files, run linter.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior Software Developer AI agent in the AETHER OS platform.

Your responsibilities:
- Write clean, production-quality code in the required language/framework.
- Read existing files to understand context before modifying them.
- Debug errors thoroughly: read the traceback, identify root cause, then fix.
- Follow the project's existing style, naming conventions, and patterns.
- Always include brief inline comments for non-obvious logic.
- After writing code, check for security issues (injection, XSS, auth failures, etc.).

When writing files:
- State the file path at the top of your response.
- Write the complete file — never omit sections with "... existing code ...".

When returning code blocks, wrap them in triple backticks with the language tag.
"""


class DeveloperAgent(BaseAgent):
    """Developer specialist: code generation, debugging, refactoring."""

    # Default tools made available to this agent type
    DEFAULT_TOOLS: list[str] = [
        "file_writer",
        "file_reader",
        "code_runner",
        "code_analyzer",
        "linter_tool",
        "code_formatter",
        "directory_scanner",
        "diff_tool",
    ]
    DEFAULT_SKILLS: list[str] = [
        "python", "javascript", "typescript", "html", "css",
        "debugging", "code_review", "refactoring", "security_review",
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
        permission_level: int = 2,
    ) -> None:
        tools  = list(self.DEFAULT_TOOLS)  + (extra_tools  or [])
        skills = list(self.DEFAULT_SKILLS) + (extra_skills or [])
        super().__init__(
            name=name,
            role="Developer Agent",
            tools=tools,
            skills=skills,
            permission_level=permission_level,
        )
        # Store kernel components for direct tool/AI calls
        self._registry     = registry
        self._tool_manager = tool_manager
        self._ai_adapter   = ai_adapter
        self._system_prompt = _SYSTEM_PROMPT
        logger.info("[DeveloperAgent] '%s' ready.", name)

    # ── Core helpers ──────────────────────────────────────────────────────────

    def run_task(self, task: str) -> str:
        """Run a task using this agent's system prompt via the AI adapter."""
        if self._ai_adapter is None:
            return "[DeveloperAgent] No AI adapter configured."
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user",   "content": task},
        ]
        return self._ai_adapter.chat(messages)

    def use_tool(self, tool_name: str, **kwargs) -> Any:
        """Invoke a registered tool through the ToolManager."""
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
            logger.warning("[DeveloperAgent] Tool '%s' failed: %s", tool_name, exc)
            return {"error": str(exc)}

    # ── Convenience helpers ───────────────────────────────────────────────────

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        """Direct helper: write a file using the file_writer tool."""
        return self.use_tool("file_writer", filename=path, content=content)

    def read_file(self, path: str) -> str:
        """Direct helper: read a file and return its contents."""
        result = self.use_tool("file_reader", filename=path)
        return result.get("content", "") if isinstance(result, dict) else str(result)

    def run_code(self, code: str, language: str = "python") -> dict[str, Any]:
        """Direct helper: execute code in a sandboxed subprocess."""
        return self.use_tool("code_runner", code=code, language=language)

    def lint(self, path: str) -> dict[str, Any]:
        """Run the linter on a file path."""
        return self.use_tool("linter_tool", filename=path)
