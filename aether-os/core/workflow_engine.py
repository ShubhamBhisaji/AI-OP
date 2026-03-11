"""
WorkflowEngine — Manages task pipelines and multi-agent workflows.
Breaks tasks into subtasks, assigns them to agents, and collects results.

Fix 2 — Asynchronous execution:
    execute_async() and run_pipeline_async() use asyncio to run non-blocking
    LLM calls, allowing multiple agents to work concurrently.

Fix 5 — Self-correction loop:
    If an agent's result looks like an error/exception traceback, the engine
    feeds the error back to the agent and asks it to self-correct.  This
    retries up to MAX_SELF_CORRECT_RETRIES times before giving up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maximum self-correction attempts before returning the last error result
MAX_SELF_CORRECT_RETRIES: int = 3

# Heuristics used to detect an error result from an agent
_ERROR_PREFIXES: tuple[str, ...] = (
    "error:",
    "traceback",
    "syntaxerror",
    "typeerror",
    "valueerror",
    "runtimeerror",
    "exception",
    "nameerror",
    "attributeerror",
    "indexerror",
    "keyerror",
    "importerror",
    "[stderr]",
)


def _looks_like_error(text: str) -> bool:
    """Return True if the result string looks like a Python error/traceback."""
    lower = text.strip().lower()
    return any(lower.startswith(prefix) or f"\n{prefix}" in lower for prefix in _ERROR_PREFIXES)


class WorkflowEngine:
    """
    Orchestrates multi-step, multi-agent workflows.
    Supports single-agent execution (sync + async) and sequential pipelines.
    """

    def __init__(self, registry, ai_adapter, memory):
        self.registry = registry
        self.ai_adapter = ai_adapter
        self.memory = memory

    # ------------------------------------------------------------------
    # Single agent execution (synchronous)
    # ------------------------------------------------------------------

    def execute(self, agent, task: str) -> Any:
        """
        Execute a single agent on a task with self-correction (Fix 5).
        The agent's AI adapter and tools are used to produce a result.
        On error results the engine feeds the error back and retries.
        """
        logger.info("WorkflowEngine: executing agent '%s'", agent.name)
        prompt = self._build_prompt(agent=agent, task=task)
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
        result = self.ai_adapter.chat(messages=messages)

        # If AI flagged as out-of-scope, record a failure and surface cleanly
        if result.strip().startswith("BEYOND_SCOPE:"):
            reason = result.strip()[len("BEYOND_SCOPE:"):].strip()
            agent.record_result(success=False)
            return f"BEYOND_SCOPE: {reason}"

        # ── Self-correction loop (Fix 5) ──────────────────────────────
        for attempt in range(1, MAX_SELF_CORRECT_RETRIES + 1):
            if not _looks_like_error(result):
                break
            logger.warning(
                "WorkflowEngine: agent '%s' returned an error on attempt %d/%d — "
                "requesting self-correction.",
                agent.name, attempt, MAX_SELF_CORRECT_RETRIES,
            )
            messages.append({"role": "assistant", "content": result})
            correction_prompt = (
                f"The previous response contained an error:\n\n"
                f"```\n{result}\n```\n\n"
                f"Please analyse the error, identify the root cause, and provide "
                f"a corrected response.  Do NOT repeat the same mistake."
            )
            messages.append({"role": "user", "content": correction_prompt})
            result = self.ai_adapter.chat(messages=messages)

        if _looks_like_error(result):
            logger.error(
                "WorkflowEngine: agent '%s' failed after %d self-correction attempts.",
                agent.name, MAX_SELF_CORRECT_RETRIES,
            )
            agent.record_result(success=False)
            self.memory.save(key=f"workflow:{agent.name}:last_error", value=result)
            return result

        agent.record_result(success=True)
        self.memory.save(key=f"workflow:{agent.name}:last", value=result)
        return result

    # ------------------------------------------------------------------
    # Single agent execution (asynchronous — Fix 2)
    # ------------------------------------------------------------------

    async def execute_async(self, agent, task: str) -> Any:
        """
        Non-blocking async version of execute().
        Runs the synchronous AI chat call in a thread pool so the event loop
        is never blocked by a slow network call.
        """
        logger.info("WorkflowEngine[async]: executing agent '%s'", agent.name)
        loop = asyncio.get_event_loop()
        prompt = self._build_prompt(agent=agent, task=task)
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]

        # Run the blocking chat call off the main thread
        result = await loop.run_in_executor(
            None, lambda: self.ai_adapter.chat(messages=messages)
        )

        if result.strip().startswith("BEYOND_SCOPE:"):
            agent.record_result(success=False)
            return result

        # Self-correction loop (async)
        for attempt in range(1, MAX_SELF_CORRECT_RETRIES + 1):
            if not _looks_like_error(result):
                break
            logger.warning(
                "WorkflowEngine[async]: agent '%s' self-correcting (attempt %d/%d).",
                agent.name, attempt, MAX_SELF_CORRECT_RETRIES,
            )
            messages.append({"role": "assistant", "content": result})
            messages.append({
                "role": "user",
                "content": (
                    f"The previous response contained an error:\n\n```\n{result}\n```\n\n"
                    f"Please identify the root cause and provide a corrected response."
                ),
            })
            result = await loop.run_in_executor(
                None, lambda: self.ai_adapter.chat(messages=messages)
            )

        success = not _looks_like_error(result)
        agent.record_result(success=success)
        key = f"workflow:{agent.name}:last" if success else f"workflow:{agent.name}:last_error"
        self.memory.save(key=key, value=result)
        return result

    # ------------------------------------------------------------------
    # Multi-agent pipeline (synchronous)
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
    # Multi-agent pipeline (asynchronous — Fix 2)
    # ------------------------------------------------------------------

    async def run_pipeline_async(self, agents: list, task: str) -> str:
        """Async sequential pipeline — awaits each step before passing output forward."""
        context = task
        for agent in agents:
            logger.info("Pipeline[async] step: agent '%s'", agent.name)
            context = await self.execute_async(agent=agent, task=context)
        return context

    async def run_broadcast_async(self, agents: list, task: str) -> list[Any]:
        """
        Run all agents on the SAME task concurrently (Fix 2).
        Returns a list of results in the same order as *agents*.
        """
        coros = [self.execute_async(agent=a, task=task) for a in agents]
        return await asyncio.gather(*coros, return_exceptions=True)

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
        instructions = agent.profile.get("instructions", "")
        instr_block = f"\nInstructions:\n{instructions}\n" if instructions else ""
        return (
            f"You are a {agent.role}.{instr_block}\n"
            f"Your skills: {skills_str}.\n"
            f"Available tools: {tools_str}.\n\n"
            f"IMPORTANT RULE: You ONLY handle tasks that are directly related to "
            f"your role as a {agent.role}. "
            f"If the task is outside your role or expertise, respond with exactly:\n"
            f"BEYOND_SCOPE: <one-line reason>\n\n"
            f"Task:\n{task}"
        )
