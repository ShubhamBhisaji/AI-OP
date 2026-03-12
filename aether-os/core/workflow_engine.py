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

Fix 8 — Human-in-the-Loop (HITL) checkpoints:
    When hitl_mode=True the engine pauses after every completed agent step
    and presents the result to the operator for approval, revision, or
    cancellation before continuing.  A feedback_callback receives a
    WorkflowCheckpoint and must return a WorkflowFeedback object.  If no
    callback is provided a default interactive console prompt is used.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

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


# ---------------------------------------------------------------------------
# HITL types (Fix 8)
# ---------------------------------------------------------------------------

class HITLAction(str, Enum):
    """Human decision returned from a HITL checkpoint."""
    APPROVE  = "approve"   # accept the result and continue
    REVISE   = "revise"    # provide new instructions; agent will re-run
    CANCEL   = "cancel"    # abort the entire workflow


@dataclass
class WorkflowCheckpoint:
    """
    Snapshot presented to the human at a HITL gate.

    Attributes
    ----------
    agent_name  : Name of the agent that just finished.
    task        : The task that was given to the agent.
    result      : The agent's output.
    step        : 1-based pipeline step index (1 for single-agent flows).
    total_steps : Total number of steps in the workflow (None if unknown).
    """
    agent_name:  str
    task:        str
    result:      str
    step:        int = 1
    total_steps: Optional[int] = None


@dataclass
class WorkflowFeedback:
    """
    Human response returned from a HITL callback.

    Attributes
    ----------
    action       : One of HITLAction.APPROVE / REVISE / CANCEL.
    revised_task : Replacement task string when action == REVISE.
                   Ignored for other actions.
    """
    action:       HITLAction = HITLAction.APPROVE
    revised_task: str        = ""


class WorkflowCancelled(RuntimeError):
    """Raised when a human cancels the workflow at a HITL gate."""


def _default_hitl_callback(checkpoint: WorkflowCheckpoint) -> WorkflowFeedback:
    """
    Interactive console HITL gate used when no callback is registered.
    Prints the agent result and prompts the operator for a decision.
    """
    step_label = (
        f"Step {checkpoint.step}/{checkpoint.total_steps}"
        if checkpoint.total_steps
        else f"Step {checkpoint.step}"
    )
    print("\n" + "=" * 70)
    print(f"  ⏸  HITL Checkpoint — {step_label} | Agent: {checkpoint.agent_name}")
    print("=" * 70)
    print(f"\nTask:\n{checkpoint.task}\n")
    print(f"Agent output:\n{checkpoint.result}\n")
    print("-" * 70)
    print("  [A] Approve and continue")
    print("  [R] Revise — enter new instructions")
    print("  [C] Cancel workflow")
    print("-" * 70)
    while True:
        choice = input("  Your choice (A/R/C): ").strip().upper()
        if choice == "A":
            return WorkflowFeedback(action=HITLAction.APPROVE)
        if choice == "C":
            return WorkflowFeedback(action=HITLAction.CANCEL)
        if choice == "R":
            revised = input("  Enter revised instructions: ").strip()
            if revised:
                return WorkflowFeedback(action=HITLAction.REVISE, revised_task=revised)
            print("  Revised instructions cannot be empty.")


class WorkflowEngine:
    """
    Orchestrates multi-step, multi-agent workflows.
    Supports single-agent execution (sync + async) and sequential pipelines.
    """

    def __init__(
        self,
        registry,
        ai_adapter,
        memory,
        tool_manager=None,
        hitl_mode: bool = False,
        feedback_callback: Optional[Callable[[WorkflowCheckpoint], WorkflowFeedback]] = None,
    ):
        self.registry = registry
        self.ai_adapter = ai_adapter
        self.memory = memory
        self.tool_manager = tool_manager
        # HITL (Fix 8)
        self.hitl_mode = hitl_mode
        self.feedback_callback: Callable[[WorkflowCheckpoint], WorkflowFeedback] = (
            feedback_callback or _default_hitl_callback
        )

    # ------------------------------------------------------------------
    # HITL gate helper (Fix 8)
    # ------------------------------------------------------------------

    def _hitl_gate(
        self,
        agent,
        task: str,
        result: str,
        step: int = 1,
        total_steps: Optional[int] = None,
    ) -> str:
        """
        Present a WorkflowCheckpoint to the operator and act on the response.

        Returns the (possibly revised) task that should be re-run if the
        operator chose REVISE, or the original result if APPROVE.
        Raises WorkflowCancelled if the operator chose CANCEL.

        The calling execute/pipeline method must re-run the agent when this
        method returns a string that differs from *result*.
        """
        if not self.hitl_mode:
            return result  # fast-path: HITL disabled

        checkpoint = WorkflowCheckpoint(
            agent_name=agent.name,
            task=task,
            result=result,
            step=step,
            total_steps=total_steps,
        )

        MAX_REVISE_CYCLES = 3
        for _ in range(MAX_REVISE_CYCLES):
            feedback = self.feedback_callback(checkpoint)

            if feedback.action == HITLAction.APPROVE:
                logger.info("HITL: operator approved output of agent '%s'.", agent.name)
                return result

            if feedback.action == HITLAction.CANCEL:
                logger.warning("HITL: operator cancelled workflow at agent '%s'.", agent.name)
                raise WorkflowCancelled(
                    f"Workflow cancelled by operator at agent '{agent.name}'."
                )

            if feedback.action == HITLAction.REVISE:
                revised_task = feedback.revised_task.strip()
                logger.info(
                    "HITL: operator requested revision for agent '%s' — re-running.",
                    agent.name,
                )
                # Re-run the agent with the revised task
                prompt = self._build_prompt(agent=agent, task=revised_task)
                messages = [{"role": "user", "content": prompt}]
                result = self.ai_adapter.chat(messages=messages)
                checkpoint = WorkflowCheckpoint(
                    agent_name=agent.name,
                    task=revised_task,
                    result=result,
                    step=step,
                    total_steps=total_steps,
                )

        logger.warning(
            "HITL: max revision cycles (%d) reached for agent '%s'; accepting last result.",
            MAX_REVISE_CYCLES, agent.name,
        )
        return result

    async def _hitl_gate_async(
        self,
        agent,
        task: str,
        result: str,
        step: int = 1,
        total_steps: Optional[int] = None,
    ) -> str:
        """Async version of _hitl_gate — runs the blocking callback in a thread."""
        if not self.hitl_mode:
            return result
        loop = asyncio.get_event_loop()
        # The callback may block (console input) — run it off the event loop
        return await loop.run_in_executor(
            None,
            lambda: self._hitl_gate(agent, task, result, step, total_steps),
        )

    # ------------------------------------------------------------------
    # RBAC-enforced tool call (Fix 3 — RBAC wiring)
    # ------------------------------------------------------------------

    def call_tool(self, agent, tool_name: str, *args, **kwargs):
        """
        Invoke a tool on behalf of an agent, enforcing RBAC and the
        approval gate based on agent.permission_level.

        Always prefer this helper over calling tool_manager directly so that
        the agent's permission level is consistently applied.
        """
        if self.tool_manager is None:
            raise RuntimeError("WorkflowEngine: tool_manager not wired — cannot call tools.")
        return self.tool_manager.call(
            tool_name,
            *args,
            agent_name=getattr(agent, "name", "unknown"),
            agent_level=getattr(agent, "permission_level", 1),
            **kwargs,
        )

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

        # ── HITL checkpoint (Fix 8) ─────────────────────────────────────────
        result = self._hitl_gate(agent=agent, task=task, result=result)
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

        # ── HITL checkpoint (Fix 8) ─────────────────────────────────────────
        result = await self._hitl_gate_async(agent=agent, task=task, result=result)
        return result

    # ------------------------------------------------------------------
    # Multi-agent pipeline (synchronous)
    # ------------------------------------------------------------------

    def run_pipeline(self, agents: list, task: str) -> str:
        """
        Run a sequential pipeline where each agent's output feeds the next.
        Returns the final agent's output as the pipeline result.
        Pauses at each step for human review when hitl_mode=True (Fix 8).
        """
        context = task
        total = len(agents)
        for step, agent in enumerate(agents, start=1):
            logger.info("Pipeline step %d/%d: agent '%s'", step, total, agent.name)
            context = self.execute(agent=agent, task=context)
            # execute() already called _hitl_gate internally; no double-gate here
        return context

    # ------------------------------------------------------------------
    # Multi-agent pipeline (asynchronous — Fix 2)
    # ------------------------------------------------------------------

    async def run_pipeline_async(self, agents: list, task: str) -> str:
        """Async sequential pipeline — awaits each step; HITL gate between steps (Fix 8)."""
        context = task
        total = len(agents)
        for step, agent in enumerate(agents, start=1):
            logger.info("Pipeline[async] step %d/%d: agent '%s'", step, total, agent.name)
            context = await self.execute_async(agent=agent, task=context)
            # execute_async() already called _hitl_gate_async internally
        return context

    async def run_broadcast_async(self, agents: list, task: str) -> list[Any]:
        """
        Run all agents on the SAME task concurrently (Fix 2).
        Returns a list of results in the same order as *agents*.
        """
        coros = [self.execute_async(agent=a, task=task) for a in agents]
        return await asyncio.gather(*coros, return_exceptions=True)

    # ------------------------------------------------------------------
    # Autonomous task decomposition (synchronous — legacy)
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
    # Autonomous task decomposition (async + parallel — Fix 3)
    # ------------------------------------------------------------------

    async def decompose_and_run_async(self, task: str) -> dict[str, Any]:
        """
        Async parallel task decomposition (Fix 3).

        Steps:
          1. Ask the AI to decompose *task* into subtasks WITH a dependency
             graph (JSON).  Subtasks whose ``depends_on`` list is empty can
             run concurrently; others wait for their dependencies to finish.
          2. Execute dependency-free subtasks in parallel via asyncio.gather().
          3. Pass the accumulated results back to the AI to resolve any
             remaining dependent subtasks, repeating until all are done.

        Returns a dict mapping subtask descriptions to their results.
        """
        agents = self.registry.list_names()
        if not agents:
            return {"error": "No agents registered."}

        # ── Step 1: Ask AI for a dependency graph ─────────────────────
        decompose_prompt = (
            f"Break the following task into subtasks and produce a dependency graph.\n\n"
            f"Task: {task}\n\n"
            f"Output ONLY valid JSON — no markdown, no extra text.\n"
            f"Format:\n"
            f'{{"subtasks": [{{"id": "1", "description": "...", "depends_on": []}}, '
            f'{{"id": "2", "description": "...", "depends_on": ["1"]}}]}}\n\n'
            f"Rules:\n"
            f"- Use short numeric string IDs\n"
            f"- depends_on lists IDs of subtasks that MUST complete first\n"
            f"- Independent subtasks should have depends_on: []\n"
            f"- Aim for 3-8 subtasks total"
        )
        raw = self.ai_adapter.chat(messages=[{"role": "user", "content": decompose_prompt}])

        # Parse the dependency graph (robust fallback to flat list)
        try:
            from utils.json_parser import extract_json
            graph_data = extract_json(raw, safe=True, default={})
            subtask_list: list[dict] = graph_data.get("subtasks", [])
            if not subtask_list:
                raise ValueError("empty graph")
        except Exception:
            # Fallback: treat each non-empty line as an independent subtask
            logger.warning("decompose_and_run_async: AI did not return a valid dependency graph; falling back to flat list.")
            subtask_list = [
                {"id": str(i + 1), "description": line.strip(), "depends_on": []}
                for i, line in enumerate(raw.splitlines())
                if line.strip()
            ][:8]

        # ── Step 2: Topological execution with parallel batches ────────
        completed: dict[str, Any] = {}   # id → result
        remaining = {s["id"]: s for s in subtask_list}

        while remaining:
            # Find all tasks whose dependencies are already satisfied
            ready = [
                s for s in remaining.values()
                if all(dep in completed for dep in s.get("depends_on", []))
            ]
            if not ready:
                # Circular dependency or unresolvable graph — run what's left sequentially
                logger.warning(
                    "decompose_and_run_async: circular or unresolvable dependency detected; "
                    "running remaining subtasks sequentially."
                )
                for s in remaining.values():
                    agent_name = agents[0]
                    agent = self.registry.get(agent_name)
                    completed[s["id"]] = await self.execute_async(agent=agent, task=s["description"])
                break

            # Assign each ready subtask to an agent (round-robin)
            async def _run_subtask(subtask: dict, idx: int) -> tuple[str, Any]:
                agent_name = agents[idx % len(agents)]
                agent = self.registry.get(agent_name)
                result = await self.execute_async(agent=agent, task=subtask["description"])
                return subtask["id"], result

            coros = [_run_subtask(s, i) for i, s in enumerate(ready)]
            logger.info(
                "decompose_and_run_async: running %d subtask(s) in parallel: %s",
                len(coros), [s["description"][:60] for s in ready],
            )
            batch_results = await asyncio.gather(*coros, return_exceptions=True)

            for item in batch_results:
                if isinstance(item, BaseException):
                    logger.error("decompose_and_run_async: subtask raised: %s", item)
                    continue
                sid, sresult = item
                completed[sid] = sresult
                remaining.pop(sid, None)

        # Return results keyed by description for readability
        id_to_desc = {s["id"]: s["description"] for s in subtask_list}
        return {id_to_desc.get(sid, sid): result for sid, result in completed.items()}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, agent, task: str) -> str:
        skills_str = ", ".join(agent.profile.get("skills", [])) or "general"
        tools_str = ", ".join(agent.profile.get("tools", [])) or "none"
        instructions = agent.profile.get("instructions", "")
        instr_block = f"\nInstructions:\n{instructions}\n" if instructions else ""
        # Global system instructions — set via Train AI page or kernel.memory
        sys_instr = self.memory.load("system_instructions", default="", namespace="global")
        sys_block = f"\nGlobal System Instructions:\n{sys_instr}\n" if sys_instr else ""
        return (
            f"You are a {agent.role}.{sys_block}{instr_block}\n"
            f"Your skills: {skills_str}.\n"
            f"Available tools: {tools_str}.\n\n"
            f"IMPORTANT RULE: You ONLY handle tasks that are directly related to "
            f"your role as a {agent.role}. "
            f"If the task is outside your role or expertise, respond with exactly:\n"
            f"BEYOND_SCOPE: <one-line reason>\n\n"
            f"Task:\n{task}"
        )
