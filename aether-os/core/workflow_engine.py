"""
WorkflowEngine — Manages task pipelines and multi-agent workflows.
Breaks tasks into subtasks, assigns them to agents, and collects results.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Orchestrates multi-step, multi-agent workflows.
    Supports single-agent execution and sequential agent pipelines.
    """

    def __init__(self, registry, ai_adapter, memory):
        self.registry = registry
        self.ai_adapter = ai_adapter
        self.memory = memory

    # ------------------------------------------------------------------
    # Single agent execution
    # ------------------------------------------------------------------

    def execute(self, agent, task: str) -> Any:
        """
        Execute a single agent on a task.
        The agent's AI adapter and tools are used to produce a result.
        """
        logger.info("WorkflowEngine: executing agent '%s'", agent.name)
        prompt = self._build_prompt(agent=agent, task=task)
        messages = [{"role": "user", "content": prompt}]
        result = self.ai_adapter.chat(messages=messages)
        agent.record_result(success=True)
        self.memory.save(key=f"workflow:{agent.name}:last", value=result)
        return result

    # ------------------------------------------------------------------
    # Multi-agent pipeline
    # ------------------------------------------------------------------

    def run_pipeline(self, agents: list, task: str) -> str:
        """
        Run a sequential pipeline where each agent's output feeds the next.
        Returns the final agent's output as the pipeline result.
        """
        context = task
        for agent in agents:
            logger.info("Pipeline step: agent '%s'", agent.name)
            context = self.execute(agent=agent, task=context)
        return context

    # ------------------------------------------------------------------
    # Autonomous task decomposition
    # ------------------------------------------------------------------

    def decompose_and_run(self, task: str) -> dict[str, Any]:
        """
        Use the AI adapter to decompose a complex task into subtasks,
        then assign each subtask to the most suitable registered agent.
        """
        decompose_prompt = (
            f"Break the following task into numbered subtasks, one per line:\n\n{task}"
        )
        raw = self.ai_adapter.chat(messages=[{"role": "user", "content": decompose_prompt}])
        subtasks = [line.strip() for line in raw.splitlines() if line.strip()]
        results: dict[str, Any] = {}
        agents = self.registry.list_names()
        for i, subtask in enumerate(subtasks):
            agent_name = agents[i % len(agents)] if agents else None
            if agent_name is None:
                logger.warning("No agents registered; skipping subtask: %s", subtask)
                continue
            agent = self.registry.get(agent_name)
            results[subtask] = self.execute(agent=agent, task=subtask)
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, agent, task: str) -> str:
        skills_str = ", ".join(agent.profile.get("skills", [])) or "general"
        tools_str = ", ".join(agent.profile.get("tools", [])) or "none"
        return (
            f"You are a {agent.role}.\n"
            f"Your skills: {skills_str}.\n"
            f"Available tools: {tools_str}.\n\n"
            f"Task:\n{task}"
        )
