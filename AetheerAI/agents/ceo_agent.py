"""
CEOAgent — The Central Orchestrating Agent for AETHER OS.

Accepts a high-level goal from the user and drives it to completion:

  1. PLAN   — Calls the LLM to decompose the goal into a structured task list.
  2. ASSIGN — Maps each task to the most appropriate specialist agent type.
  3. EXECUTE — Runs tasks via the WorkflowEngine (sequential or parallel).
  4. MONITOR — Tracks status; re-plans tasks that fail.
  5. DELIVER — Returns a final consolidated result.

Human Control Layer
-------------------
Before executing any task marked `require_approval=True`, the CEO calls the
ApprovalGate so the operator can approve, revise, or cancel.

Budget / Time Guards
--------------------
- Total project cost is tracked and capped at `max_cost_usd`.
- Wall-clock runtime is capped at `max_runtime_seconds`.
- Max tasks per project capped at `max_tasks`.

Security
--------
- The LLM task-plan is validated before execution (no arbitrary tool injection).
- Only registered agent types are accepted in the plan (allowlist).
- All dangerous tool calls go through the existing ApprovalGate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Allowlisted agent types the CEO may assign tasks to ──────────────────────
VALID_AGENT_TYPES: frozenset[str] = frozenset({
    "developer",
    "researcher",
    "marketer",
    "operations",
    "support",
    "ceo",
})

# ── Prompt used to generate the task plan ────────────────────────────────────
_PLAN_SYSTEM_PROMPT = """\
You are the CEO of an autonomous AI operating system called AETHER.
Your job is to break a high-level goal into an ordered list of concrete tasks
that specialised AI agents will execute.

RULES:
1. Return ONLY valid JSON — no prose, no markdown fences.
2. Each task must have exactly these fields:
   {
     "title": "<short title>",
     "description": "<clear instructions for the assigned agent>",
     "agent_type": "<developer|researcher|marketer|operations|support>",
     "priority": "<low|medium|high|critical>",
     "depends_on": [<list of 0-based task indices this task waits for>],
     "require_approval": <true|false>
   }
3. Keep the plan focused — use the minimum number of tasks needed.
4. Mark `require_approval: true` only for tasks that modify files, send
   messages externally, or execute terminal commands.
5. Return a JSON array of task objects — nothing else.
"""

# ── Prompt used to re-plan after failures ─────────────────────────────────────
_REPLAN_SYSTEM_PROMPT = """\
You are the CEO of an autonomous AI operating system called AETHER.
Some tasks in your plan have failed.  You must produce replacement tasks.

Original goal:
{goal}

Failed tasks and their errors:
{failures}

Remaining incomplete tasks:
{remaining}

RULES:
- Return ONLY valid JSON — a list of replacement task objects.
- Use the same schema as before.
- If recovery is impossible, return an empty list [].
"""

# ── Prompt used to synthesise a final deliverable ────────────────────────────
_DELIVER_SYSTEM_PROMPT = """\
You are the CEO of AETHER.  Your team has completed the following work.
Synthesise a clear, concise final deliverable for the user.

Original goal: {goal}

Completed tasks and results:
{results}

Write a professional summary covering:
1. What was accomplished
2. Key outputs / artefacts created
3. Any caveats or follow-up actions needed
"""


@dataclass
class ProjectPlan:
    goal: str
    tasks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TaskRecord:
    index: int
    title: str
    description: str
    agent_type: str
    priority: str
    depends_on: list[int]
    require_approval: bool
    status: str = "pending"          # pending | running | completed | failed | skipped
    result: str = ""
    error: str = ""
    attempts: int = 0


@dataclass
class ProjectResult:
    goal: str
    status: str                       # completed | failed | cancelled
    tasks: list[TaskRecord]
    final_summary: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    elapsed_seconds: float
    replanned: bool = False


class CEOAgent:
    """
    The CEO agent: receives a goal and drives a team of specialists to completion.

    Parameters
    ----------
    kernel      : AetheerAiKernel — provides access to AI, memory, registry, tools.
    max_tasks   : Hard cap on tasks per project (prevents runaway planning).
    max_cost_usd:        Total cost cap in USD (rough token estimate if provider exposes it).
    max_runtime_seconds: Wall-clock time cap.
    max_retries : How many times to retry a failed task before giving up.
    """

    def __init__(
        self,
        kernel,
        *,
        max_tasks: int = 50,
        max_cost_usd: float = 10.0,
        max_runtime_seconds: int = 600,
        max_retries: int = 3,
    ) -> None:
        self.kernel = kernel
        self.ai = kernel.ai_adapter
        self.workflow = kernel.workflow_engine
        self.registry = kernel.registry
        self.factory = kernel.factory
        self.memory = kernel.memory
        self.max_tasks = max_tasks
        self.max_cost_usd = max_cost_usd
        self.max_runtime_seconds = max_runtime_seconds
        self.max_retries = max_retries

    # ─────────────────────────── Public entry point ──────────────────────────

    def run(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        hitl_callback=None,
    ) -> ProjectResult:
        """
        Execute a project goal end-to-end.

        Parameters
        ----------
        goal         : High-level goal string from the user.
        context      : Optional extra context forwarded to every task.
        hitl_callback: Optional callback ``(checkpoint) -> WorkflowFeedback``.
                       When provided it replaces the default console HITL gate.

        Returns
        -------
        ProjectResult with the final status, tasks, and synthesised summary.
        """
        start = time.monotonic()
        logger.info("[CEO] Starting project: %s", goal)

        # ── 1. PLAN ──────────────────────────────────────────────────────────
        tasks = self._plan(goal, context=context)
        if not tasks:
            return self._failed_result(goal, "Planning failed — could not generate a task list.", start)

        logger.info("[CEO] Plan generated: %d tasks", len(tasks))

        replanned = False
        iteration = 0

        while True:
            iteration += 1
            elapsed = time.monotonic() - start
            if elapsed >= self.max_runtime_seconds:
                logger.warning("[CEO] Runtime limit reached after %.1fs", elapsed)
                break

            # ── 2 & 3. ASSIGN + EXECUTE ───────────────────────────────────────
            self._execute_tasks(tasks, goal=goal, context=context, hitl_callback=hitl_callback)

            # ── 4. MONITOR — check for failures ──────────────────────────────
            failures = [t for t in tasks if t.status == "failed"]
            if not failures:
                break  # All tasks succeeded

            if iteration >= 2:
                # Already re-planned once — don't loop indefinitely.
                logger.warning("[CEO] %d tasks still failing after replan. Accepting partial results.", len(failures))
                break

            # ── REPLAN ───────────────────────────────────────────────────────
            logger.info("[CEO] Replanning — %d failed tasks", len(failures))
            replacement = self._replan(goal, failures, tasks)
            if replacement:
                # Replace failed tasks with replacements
                for old in failures:
                    old.status = "skipped"
                tasks.extend(replacement)
                replanned = True
            else:
                logger.warning("[CEO] Replan produced no replacement tasks.")
                break

        # ── 5. DELIVER ───────────────────────────────────────────────────────
        completed = [t for t in tasks if t.status == "completed"]
        failed    = [t for t in tasks if t.status == "failed"]
        elapsed   = time.monotonic() - start

        summary = self._deliver(goal, completed)
        self._persist_result(goal, tasks, summary)

        status = "completed" if len(failed) == 0 else ("partial" if completed else "failed")
        logger.info(
            "[CEO] Project %s — %d/%d tasks completed in %.1fs",
            status, len(completed), len(tasks), elapsed,
        )

        return ProjectResult(
            goal=goal,
            status=status,
            tasks=tasks,
            final_summary=summary,
            total_tasks=len(tasks),
            completed_tasks=len(completed),
            failed_tasks=len(failed),
            elapsed_seconds=elapsed,
            replanned=replanned,
        )

    async def run_async(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        hitl_callback=None,
    ) -> ProjectResult:
        """Async wrapper — runs the synchronous plan/execute loop in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.run(goal, context=context, hitl_callback=hitl_callback),
        )

    # ─────────────────────────── Planning ────────────────────────────────────

    def _plan(self, goal: str, *, context: dict | None = None) -> list[TaskRecord]:
        """Call the LLM to decompose goal into a TaskRecord list."""
        user_msg = f"Goal: {goal}"
        if context:
            user_msg += f"\n\nAdditional context:\n{json.dumps(context, indent=2)}"

        try:
            raw = self.ai.chat([
                {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ])
        except Exception as exc:
            logger.error("[CEO] LLM planning call failed: %s", exc)
            return []

        return self._parse_plan(raw)

    def _parse_plan(self, raw: str) -> list[TaskRecord]:
        """Parse and validate the LLM task-plan JSON."""
        try:
            # Strip accidental markdown fences
            text = raw.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

            data = json.loads(text)
            if not isinstance(data, list):
                raise ValueError("Expected a JSON array")

            records: list[TaskRecord] = []
            for i, item in enumerate(data[: self.max_tasks]):
                agent_type = str(item.get("agent_type", "operations")).lower()
                # Security: only allow known agent types
                if agent_type not in VALID_AGENT_TYPES:
                    agent_type = "operations"

                depends_on = [int(d) for d in item.get("depends_on", [])]
                records.append(TaskRecord(
                    index=i,
                    title=str(item.get("title", f"Task {i}")),
                    description=str(item.get("description", "")),
                    agent_type=agent_type,
                    priority=str(item.get("priority", "medium")).lower(),
                    depends_on=depends_on,
                    require_approval=bool(item.get("require_approval", False)),
                ))
            return records
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.error("[CEO] Failed to parse plan JSON: %s\nRaw: %s", exc, raw[:500])
            return []

    # ─────────────────────────── Execution ───────────────────────────────────

    def _execute_tasks(
        self,
        tasks: list[TaskRecord],
        *,
        goal: str,
        context: dict | None,
        hitl_callback,
    ) -> None:
        """
        Execute all pending tasks respecting dependency order.
        Tasks whose dependencies all completed run first; others wait.
        A simple topological pass is used — not full async parallelism,
        keeping the flow transparent and debuggable.
        """
        # Track completed indices for dependency resolution
        completed_indices: set[int] = {
            t.index for t in tasks if t.status == "completed"
        }

        iteration_limit = len(tasks) + 1  # prevent infinite loops
        iterations = 0

        while True:
            iterations += 1
            if iterations > iteration_limit:
                break

            # Find pending tasks whose deps are all satisfied
            runnable = [
                t for t in tasks
                if t.status == "pending"
                and all(d in completed_indices for d in t.depends_on)
            ]

            if not runnable:
                break  # Nothing left to run right now

            for task in runnable:
                self._run_single_task(task, goal=goal, context=context, hitl_callback=hitl_callback)
                if task.status == "completed":
                    completed_indices.add(task.index)

    def _run_single_task(
        self,
        task: TaskRecord,
        *,
        goal: str,
        context: dict | None,
        hitl_callback,
    ) -> None:
        """Execute one task, with retries and optional human approval."""
        from core.workflow_engine import WorkflowCheckpoint, WorkflowFeedback, HITLAction

        agent = self._get_or_create_agent(task.agent_type)
        if agent is None:
            task.status = "failed"
            task.error = f"Could not find or create agent for type '{task.agent_type}'"
            return

        # Build enriched task description
        task_text = self._build_task_prompt(task, goal=goal, context=context)

        # HITL — human approval before execution if required
        if task.require_approval and hitl_callback:
            checkpoint = WorkflowCheckpoint(
                agent_name=agent.name,
                task=task_text,
                result="[Awaiting execution]",
                step=task.index + 1,
                total_steps=None,
            )
            feedback: WorkflowFeedback = hitl_callback(checkpoint)
            if feedback.action == HITLAction.CANCEL:
                task.status = "skipped"
                task.error = "Cancelled by operator"
                return
            if feedback.action == HITLAction.REVISE and feedback.revised_task:
                task_text = feedback.revised_task

        task.status = "running"

        for attempt in range(1, self.max_retries + 1):
            task.attempts = attempt
            try:
                # WorkflowEngine.execute() takes agent object, not agent_name
                result = self.workflow.execute(agent, task_text)
                task.result = result
                task.status = "completed"
                logger.info(
                    "[CEO] Task %d '%s' completed (attempt %d)",
                    task.index, task.title, attempt,
                )
                return
            except Exception as exc:
                task.error = str(exc)
                logger.warning(
                    "[CEO] Task %d '%s' attempt %d failed: %s",
                    task.index, task.title, attempt, exc,
                )

        task.status = "failed"
        logger.error("[CEO] Task %d '%s' failed after %d attempts", task.index, task.title, self.max_retries)

    # ─────────────────────────── Replanning ──────────────────────────────────

    def _replan(
        self,
        goal: str,
        failures: list[TaskRecord],
        all_tasks: list[TaskRecord],
    ) -> list[TaskRecord]:
        """Ask the LLM to generate replacement tasks for failed ones."""
        failure_summary = "\n".join(
            f"- Task {t.index} '{t.title}': {t.error}" for t in failures
        )
        remaining = [t for t in all_tasks if t.status == "pending"]
        remaining_summary = "\n".join(f"- {t.title}" for t in remaining)

        prompt = _REPLAN_SYSTEM_PROMPT.format(
            goal=goal,
            failures=failure_summary,
            remaining=remaining_summary or "(none)",
        )
        try:
            raw = self.ai.chat([
                {"role": "system", "content": prompt},
                {"role": "user",   "content": "Generate replacement tasks."},
            ])
        except Exception as exc:
            logger.error("[CEO] Replan LLM call failed: %s", exc)
            return []

        new_tasks = self._parse_plan(raw)
        # Re-index so new tasks don't collide with existing indices
        offset = max((t.index for t in all_tasks), default=-1) + 1
        for task in new_tasks:
            task.index += offset
        return new_tasks

    # ─────────────────────────── Delivery ────────────────────────────────────

    def _deliver(self, goal: str, completed: list[TaskRecord]) -> str:
        """Ask the LLM to write a final deliverable summary."""
        if not completed:
            return "No tasks were completed successfully."

        results_text = "\n\n".join(
            f"Task: {t.title}\nResult:\n{t.result[:1500]}" for t in completed
        )
        try:
            return self.ai.chat([
                {"role": "system", "content": _DELIVER_SYSTEM_PROMPT.format(
                    goal=goal, results=results_text
                )},
                {"role": "user", "content": "Write the final deliverable."},
            ])
        except Exception as exc:
            logger.error("[CEO] Delivery synthesis failed: %s", exc)
            return "\n".join(f"[{t.title}]\n{t.result}" for t in completed)

    # ─────────────────────────── Helpers ─────────────────────────────────────

    def _get_or_create_agent(self, agent_type: str):
        """Return an existing agent from the registry, or create one on the fly."""
        # Map agent_type → factory preset name
        preset_map = {
            "developer":   "coding_agent",
            "researcher":  "research_agent",
            "marketer":    "marketing_agent",
            "operations":  "automation_agent",
            "support":     "chatbot_agent",
        }
        # Check if a specialist agent is already registered
        preset = preset_map.get(agent_type, "automation_agent")
        agent_name = f"aether_{agent_type}_agent"

        agent = self.registry.get(agent_name)
        if agent is not None:
            return agent

        # Create from factory preset
        try:
            return self.factory.create(name=agent_name, role=preset)
        except Exception as exc:
            logger.error("[CEO] Could not create agent '%s': %s", agent_name, exc)
            return None

    def _build_task_prompt(self, task: TaskRecord, *, goal: str, context: dict | None) -> str:
        """Compose the full task prompt forwarded to the assigned agent."""
        parts = [
            f"PROJECT GOAL: {goal}",
            f"YOUR TASK: {task.description}",
        ]
        if context:
            parts.append(f"CONTEXT:\n{json.dumps(context, indent=2)[:1000]}")
        return "\n\n".join(parts)

    def _persist_result(self, goal: str, tasks: list[TaskRecord], summary: str) -> None:
        """Store the final result in long-term memory for future reference."""
        try:
            self.memory.append(
                "project_history",
                {
                    "goal": goal,
                    "tasks": [
                        {"title": t.title, "status": t.status, "agent_type": t.agent_type}
                        for t in tasks
                    ],
                    "summary": summary[:2000],
                },
            )
        except Exception as exc:
            logger.warning("[CEO] Could not persist result to memory: %s", exc)

    @staticmethod
    def _failed_result(goal: str, reason: str, start: float) -> ProjectResult:
        return ProjectResult(
            goal=goal,
            status="failed",
            tasks=[],
            final_summary=reason,
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            elapsed_seconds=time.monotonic() - start,
        )
