"""
OperationsAgent — Specialist for task execution, automation, and workflow management.

Handles: file operations, terminal commands (sandboxed), API calls,
data processing, scripting, and business process automation.

Permission level: 3 (ADMIN) — may run code and terminal commands.
All dangerous calls go through the existing ApprovalGate.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an Operations AI agent in the AETHER OS platform.

Your responsibilities:
- Execute tasks precisely as instructed.
- Automate repetitive processes and batch operations.
- Run terminal commands safely in the sandboxed environment.
- Make HTTP / REST API calls to external services when authorised.
- Process and transform data (CSV, JSON, files).
- Report outcomes clearly: what was done, what changed, any errors.

Execution rules:
- NEVER run destructive commands (rm -rf, DROP TABLE, etc.) without explicit instruction.
- NEVER execute commands that touch resources outside the project workspace.
- Log every action you take so the operator can audit it.
- If a step fails, report the exact error and suggest an alternative approach.
"""


class OperationsAgent(BaseAgent):
    """Operations specialist: task execution, automation, API calls."""

    DEFAULT_TOOLS: list[str] = [
        "file_writer",
        "file_reader",
        "local_file_tool",
        "terminal_tool",
        "http_client",
        "code_runner",
        "csv_tool",
        "json_tool",
        "directory_scanner",
        "datetime_tool",
        "system_info",
    ]
    DEFAULT_SKILLS: list[str] = [
        "scripting", "workflow_design", "process_automation",
        "rest_api", "data_processing", "system_administration",
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
        permission_level: int = 3,
    ) -> None:
        tools  = list(self.DEFAULT_TOOLS)  + (extra_tools  or [])
        skills = list(self.DEFAULT_SKILLS) + (extra_skills or [])
        super().__init__(
            name=name,
            role="Operations Agent",
            tools=tools,
            skills=skills,
            permission_level=permission_level,
        )
        self._registry     = registry
        self._tool_manager = tool_manager
        self._ai_adapter   = ai_adapter
        self._system_prompt = _SYSTEM_PROMPT
        logger.info("[OperationsAgent] '%s' ready.", name)

    # ── Core helpers ──────────────────────────────────────────────────────────

    def run_task(self, task: str) -> str:
        if self._ai_adapter is None:
            return "[OperationsAgent] No AI adapter configured."
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
            logger.warning("[OperationsAgent] Tool '%s' failed: %s", tool_name, exc)
            return {"error": str(exc)}

    # ── Convenience helpers ───────────────────────────────────────────────────

    def run_command(self, command: str) -> dict[str, Any]:
        """Execute a sandboxed terminal command via the terminal_tool."""
        return self.use_tool("terminal_tool", command=command)

    def call_api(self, url: str, method: str = "GET", **kwargs) -> dict[str, Any]:
        """Make an HTTP request via the http_client tool."""
        return self.use_tool("http_client", url=url, method=method, **kwargs)

    def process_csv(self, filepath: str, operation: str) -> dict[str, Any]:
        """Read and process a CSV file."""
        return self.use_tool("csv_tool", filepath=filepath, operation=operation)
