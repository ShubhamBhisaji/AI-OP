"""Central orchestrator (CEO agent) for autonomous multi-agent execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.governance_layer import GovernanceContext, GovernanceLayer
from core.task_execution_engine import ExecutionTask, TaskExecutionEngine
from core.workflow_engine import HITLAction, WorkflowCheckpoint, WorkflowFeedback
from security.policy_engine import PermissionLevel

logger = logging.getLogger(__name__)


VALID_AGENT_TYPES: frozenset[str] = frozenset(
    {
        "developer",
        "researcher",
        "marketer",
        "operations",
        "support",
        "ceo",
    }
)


_PLAN_SYSTEM_PROMPT = """You are the CEO orchestrator of AetheerAI.
Break the user goal into an ordered list of executable tasks.

Return ONLY valid JSON array. Each item must contain:
{
  "title": "short title",
  "description": "clear instructions",
    "agent_type": "short role slug, e.g. developer, researcher, seo_specialist",
    "role_description": "optional human description for custom roles",
  "priority": "low|medium|high|critical",
  "depends_on": [0, 1],
  "require_approval": true
}

Rules:
- Keep tasks minimal and outcome-focused.
- Prefer known roles (developer/researcher/marketer/operations/support/ceo), but custom roles are allowed.
- Set require_approval true for file writes, terminal actions, external APIs, or messaging.
- Use valid dependency indices only.
"""


_REPLAN_SYSTEM_PROMPT = """You are the CEO orchestrator of AetheerAI.
Some tasks failed. Create replacement tasks that recover the workflow.

Goal:
{goal}

Failed tasks:
{failures}

Remaining tasks:
{remaining}

Return ONLY valid JSON array using the same task schema. If no safe recovery exists, return [].
"""


_DELIVER_SYSTEM_PROMPT = """You are the CEO orchestrator of AetheerAI.
Synthesize a final report for the user.

Goal:
{goal}

Task outcomes:
{results}

Produce:
1) What was completed
2) What failed or was skipped
3) Concrete outputs created
4) Next recommended actions
"""


@dataclass
class TaskRecord:
    index: int
    title: str
    description: str
    agent_type: str
    priority: str
    depends_on: list[int]
    require_approval: bool
    role_description: str = ""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "pending"
    result: str = ""
    error: str = ""
    attempts: int = 0


@dataclass
class ProjectResult:
    goal: str
    status: str
    tasks: list[TaskRecord]
    final_summary: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    elapsed_seconds: float
    replanned: bool = False
    workflow_id: str = ""
    spent_usd: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)


class CEOAgent:
    """High-level orchestrator that plans, executes, monitors, and replans tasks."""

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

        self.execution_engine = TaskExecutionEngine()
        self._last_result: ProjectResult | None = None

    def run(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        hitl_callback=None,
        parallel: bool = True,
        manual_override=None,
        collaboration_mode: bool | None = None,
        offline_local_mode: bool | None = None,
        fast_mode_collaboration: bool | None = None,
    ) -> ProjectResult:
        """Run a full autonomous goal lifecycle."""
        started_at = time.monotonic()
        workflow_id = uuid.uuid4().hex
        collab_mode_enabled = (
            collaboration_mode
            if collaboration_mode is not None
            else os.environ.get("AETHEER_CEO_COLLAB_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
        )
        offline_local_enabled = (
            offline_local_mode
            if offline_local_mode is not None
            else os.environ.get("AETHEER_OFFLINE_LOCAL_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
        )
        fast_collab_enabled = (
            fast_mode_collaboration
            if fast_mode_collaboration is not None
            else os.environ.get("AETHEER_FAST_MODE_COLLABORATION", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        governance = GovernanceLayer(manual_override=manual_override)
        governance_ctx = GovernanceContext(
            workflow_id=workflow_id,
            max_runtime_seconds=self.max_runtime_seconds,
            max_budget_usd=self.max_cost_usd,
        )

        logger.info("[CEO] Starting workflow %s", workflow_id)

        tasks = self._plan(goal=goal, context=context, fast_mode=offline_local_enabled)
        if not tasks:
            result = self._failed_result(
                goal=goal,
                reason="Planning failed: no valid tasks generated.",
                started_at=started_at,
                workflow_id=workflow_id,
                spent_usd=governance_ctx.spent_usd,
            )
            self._last_result = result
            return result

        self._run_red_team_gate(goal=goal, tasks=tasks)

        replanned = False
        while True:
            governance.check_limits(governance_ctx)
            runnable = self._runnable_tasks(tasks)
            if not runnable:
                break

            mode = "parallel" if parallel and not offline_local_enabled and len(runnable) > 1 else "sequential"
            batch = [
                ExecutionTask(
                    title=task.title,
                    task_id=task.task_id,
                    max_retries=max(1, 1 if offline_local_enabled else self.max_retries),
                    metadata={"index": task.index, "agent_type": task.agent_type},
                    runner=(
                        lambda current_task=task: self._run_single_task(
                            task=current_task,
                            goal=goal,
                            context=context,
                            hitl_callback=hitl_callback,
                            governance=governance,
                            governance_ctx=governance_ctx,
                            collaboration_mode=collab_mode_enabled,
                            fast_mode=offline_local_enabled,
                            fast_mode_collaboration=fast_collab_enabled,
                        )
                    ),
                )
                for task in runnable
            ]

            for item in runnable:
                item.status = "running"

            records = self.execution_engine.execute_batch(
                batch,
                mode=mode,
                max_workers=min(6, len(batch)),
            )

            self._apply_batch_records(tasks=tasks, records=records)
            governance.run_manual_override(
                event="batch_completed",
                payload={
                    "workflow_id": workflow_id,
                    "completed": len([t for t in tasks if t.status == "completed"]),
                    "failed": len([t for t in tasks if t.status == "failed"]),
                },
                ctx=governance_ctx,
            )
            governance.check_limits(governance_ctx)

            failed = [task for task in tasks if task.status == "failed"]
            pending = [task for task in tasks if task.status == "pending"]

            if failed and not replanned and not offline_local_enabled:
                replacements = self._replan(goal=goal, failures=failed, all_tasks=tasks)
                if replacements:
                    for old in failed:
                        old.status = "skipped"
                    tasks.extend(replacements)
                    replanned = True
                    continue

            if not pending:
                break

            # Pending tasks with unmet dependencies are considered blocked.
            for blocked in pending:
                blocked.status = "failed"
                blocked.error = "Blocked by unmet task dependencies."

        unresolved_pending = [task for task in tasks if task.status == "pending"]
        for blocked in unresolved_pending:
            blocked.status = "failed"
            blocked.error = "Blocked by unmet task dependencies."

        completed = [task for task in tasks if task.status == "completed"]
        failed = [task for task in tasks if task.status == "failed"]

        summary = self._deliver(goal=goal, tasks=tasks, fast_mode=offline_local_enabled)
        self._persist_result(goal=goal, tasks=tasks, summary=summary)

        if governance_ctx.cancelled:
            final_status = "cancelled"
        elif failed and completed:
            final_status = "partial"
        elif failed:
            final_status = "failed"
        else:
            final_status = "completed"

        result = ProjectResult(
            goal=goal,
            status=final_status,
            tasks=tasks,
            final_summary=summary,
            total_tasks=len(tasks),
            completed_tasks=len(completed),
            failed_tasks=len(failed),
            elapsed_seconds=round(time.monotonic() - started_at, 3),
            replanned=replanned,
            workflow_id=workflow_id,
            spent_usd=round(governance_ctx.spent_usd, 6),
            events=self.execution_engine.get_events(limit=500),
        )
        self._last_result = result
        return result

    async def run_async(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        hitl_callback=None,
        parallel: bool = True,
        manual_override=None,
        collaboration_mode: bool | None = None,
        offline_local_mode: bool | None = None,
        fast_mode_collaboration: bool | None = None,
    ) -> ProjectResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.run(
                goal,
                context=context,
                hitl_callback=hitl_callback,
                parallel=parallel,
                manual_override=manual_override,
                collaboration_mode=collaboration_mode,
                offline_local_mode=offline_local_mode,
                fast_mode_collaboration=fast_mode_collaboration,
            ),
        )

    def latest_result(self) -> ProjectResult | None:
        return self._last_result

    def _plan(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        fast_mode: bool = False,
    ) -> list[TaskRecord]:
        user_message = f"Goal: {goal}"
        if context:
            user_message += f"\n\nContext:\n{json.dumps(context, indent=2, default=str)}"

        try:
            chat_kwargs = {"timeout": 25, "max_tokens": 420} if fast_mode else {}
            raw = self.ai.chat(
                [
                    {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                **chat_kwargs,
            )
        except Exception as exc:
            logger.error("[CEO] planning call failed: %s", exc)
            return self._fallback_plan(goal=goal, context=context)

        parsed = self._parse_plan(raw)
        if parsed:
            if fast_mode and len(parsed) > 3:
                trimmed = parsed[:3]
                for item in trimmed:
                    item.depends_on = [dep for dep in item.depends_on if dep < len(trimmed)]
                return trimmed
            return parsed

        logger.warning("[CEO] planner returned no valid tasks; using fallback single-task plan.")
        return self._fallback_plan(goal=goal, context=context)

    def _parse_plan(self, raw: str) -> list[TaskRecord]:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if len(lines) > 1 else text

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("[CEO] invalid plan JSON: %s", exc)
            return []

        if not isinstance(payload, list):
            return []

        tasks: list[TaskRecord] = []
        for index, item in enumerate(payload[: self.max_tasks]):
            if not isinstance(item, dict):
                continue

            raw_agent_type = str(item.get("agent_type", "operations")).strip().lower()
            agent_type = re.sub(r"[^a-z0-9_\-]+", "_", raw_agent_type).strip("_") or "operations"
            role_description = str(item.get("role_description", "")).strip()
            if not role_description and agent_type in VALID_AGENT_TYPES:
                role_description = f"{agent_type.title()} Specialist"

            priority = str(item.get("priority", "medium")).strip().lower()
            if priority not in {"low", "medium", "high", "critical"}:
                priority = "medium"

            depends_on_raw = item.get("depends_on", [])
            depends_on: list[int] = []
            if isinstance(depends_on_raw, list):
                for dep in depends_on_raw:
                    try:
                        dep_idx = int(dep)
                    except (TypeError, ValueError):
                        continue
                    if 0 <= dep_idx < index:
                        depends_on.append(dep_idx)

            task = TaskRecord(
                index=index,
                title=str(item.get("title", f"Task {index + 1}")).strip() or f"Task {index + 1}",
                description=str(item.get("description", "")).strip(),
                agent_type=agent_type,
                role_description=role_description,
                priority=priority,
                depends_on=depends_on,
                require_approval=bool(item.get("require_approval", False)),
            )
            tasks.append(task)

        return tasks

    def _fallback_plan(self, *, goal: str, context: dict[str, Any] | None = None) -> list[TaskRecord]:
        context_hint = ""
        if context:
            context_hint = f"\nContext: {json.dumps(context, default=str)[:1200]}"
        return [
            TaskRecord(
                index=0,
                title="Direct goal execution",
                description=(
                    "Deliver the requested goal directly with concise, actionable output.\n"
                    f"Goal: {goal}{context_hint}"
                ),
                agent_type="operations",
                role_description="Operations Specialist",
                priority="medium",
                depends_on=[],
                require_approval=False,
            )
        ]

    def _run_single_task(
        self,
        *,
        task: TaskRecord,
        goal: str,
        context: dict[str, Any] | None,
        hitl_callback,
        governance: GovernanceLayer,
        governance_ctx: GovernanceContext,
        collaboration_mode: bool,
        fast_mode: bool,
        fast_mode_collaboration: bool,
    ) -> str:
        governance.check_limits(governance_ctx)

        agent = self._get_or_create_agent(
            task.agent_type,
            role_description=task.role_description,
            goal=goal,
            context=context,
        )
        if agent is None:
            raise RuntimeError(f"No agent available for type '{task.agent_type}'.")

        prompt = self._build_task_prompt(task=task, goal=goal, context=context, fast_mode=fast_mode)
        prompt = self._apply_pre_execute_hitl(task=task, agent=agent, prompt=prompt, hitl_callback=hitl_callback)

        if governance.is_risky_task(task.require_approval, prompt):
            governance.require_risky_approval(
                agent_name=agent.name,
                summary=f"{task.title}: {task.description[:240]}",
            )

        if collaboration_mode and self._should_trigger_collaboration(
            task,
            fast_mode=fast_mode,
            fast_mode_collaboration=fast_mode_collaboration,
        ):
            collab_context = self._run_internal_collaboration(
                goal=goal,
                task=task,
                primary_agent_name=agent.name,
                fast_mode=fast_mode,
            )
            if collab_context:
                prompt = (
                    f"{prompt}\n\n"
                    "INTERNAL COLLABORATION BRIEF (pre-task):\n"
                    f"{collab_context[:2200]}"
                )

        token_before = int(getattr(self.ai, "total_tokens", 0) or 0)
        if fast_mode:
            plan = {
                "task": prompt,
                "strategy": "Fast local mode: direct execution without extra planning pass.",
            }
            fast_system = (
                f"You are {agent.role} named {agent.name}. "
                "Produce concise, practical output under 220 words. "
                "If uncertain, state assumptions briefly and continue."
            )
            result = self.ai.chat(
                [
                    {"role": "system", "content": fast_system},
                    {"role": "user", "content": prompt[:2200]},
                ],
                timeout=70,
                max_tokens=380,
            )
        else:
            try:
                plan = agent.plan_task(task=prompt, context={"goal": goal, **(context or {})})
            except Exception as exc:
                logger.warning("[CEO] plan_task failed for '%s'; using direct execution fallback: %s", task.title, exc)
                plan = {
                    "task": prompt,
                    "strategy": "Direct execution fallback (planning unavailable).",
                }
            result = agent.execute_task(task=plan.get("task", prompt), context={"plan": plan.get("strategy", "")})
        token_after = int(getattr(self.ai, "total_tokens", 0) or 0)

        delta_tokens = max(0, token_after - token_before)
        governance.add_spend(governance_ctx, self._estimate_cost_usd(delta_tokens))

        result_text = str(result)
        success = not result_text.strip().lower().startswith(("error", "[error]", "beyond_scope"))
        self._persist_task_memory(
            agent_name=agent.name,
            task=task,
            result=result_text,
            success=success,
            extra={"plan": plan.get("strategy", "")},
        )
        if not success:
            raise RuntimeError(result_text)

        return result_text

    def _apply_batch_records(self, tasks: list[TaskRecord], records) -> None:
        by_id = {task.task_id: task for task in tasks}
        for record in records:
            task = by_id.get(record.task_id)
            if task is None:
                continue
            task.attempts = int(record.attempts)
            if record.status == "completed":
                task.status = "completed"
                task.result = record.result
                task.error = ""
            else:
                task.status = "failed"
                task.error = record.error or "Task execution failed."

    def _runnable_tasks(self, tasks: list[TaskRecord]) -> list[TaskRecord]:
        completed = {task.index for task in tasks if task.status == "completed"}
        return [
            task
            for task in tasks
            if task.status == "pending" and all(dep in completed for dep in task.depends_on)
        ]

    def _replan(
        self,
        *,
        goal: str,
        failures: list[TaskRecord],
        all_tasks: list[TaskRecord],
    ) -> list[TaskRecord]:
        failure_text = "\n".join(
            f"- [{task.index}] {task.title}: {task.error or 'unknown failure'}" for task in failures
        )
        remaining_text = "\n".join(
            f"- [{task.index}] {task.title}" for task in all_tasks if task.status == "pending"
        )

        prompt = _REPLAN_SYSTEM_PROMPT.format(
            goal=goal,
            failures=failure_text or "(none)",
            remaining=remaining_text or "(none)",
        )

        try:
            raw = self.ai.chat(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate recovery tasks."},
                ]
            )
        except Exception as exc:
            logger.error("[CEO] replan call failed: %s", exc)
            return []

        replanned = self._parse_plan(raw)
        if not replanned:
            return []

        offset = max((task.index for task in all_tasks), default=-1) + 1
        for i, task in enumerate(replanned):
            task.index = offset + i
            task.depends_on = [dep for dep in task.depends_on if dep < task.index]
        return replanned

    def _deliver(self, *, goal: str, tasks: list[TaskRecord], fast_mode: bool = False) -> str:
        task_summary = []
        for task in tasks:
            body = task.result if task.status == "completed" else (task.error or task.status)
            task_summary.append(
                f"[{task.status.upper()}] {task.title} ({task.agent_type})\n{body[:1500]}"
            )

        payload = "\n\n".join(task_summary)
        if fast_mode:
            return self._deterministic_delivery(goal=goal, tasks=tasks)

        try:
            return self.ai.chat(
                [
                    {
                        "role": "system",
                        "content": _DELIVER_SYSTEM_PROMPT.format(goal=goal, results=payload),
                    },
                    {"role": "user", "content": "Generate the final deliverable report."},
                ],
                timeout=45,
                max_tokens=800,
            )
        except Exception as exc:
            logger.warning("[CEO] delivery synthesis failed: %s", exc)
            return payload

    def _build_task_prompt(
        self,
        *,
        task: TaskRecord,
        goal: str,
        context: dict[str, Any] | None,
        fast_mode: bool = False,
    ) -> str:
        context_blob = json.dumps(context or {}, indent=2, default=str)
        context_limit = 1200 if fast_mode else 2500
        return (
            f"PROJECT GOAL: {goal}\n\n"
            f"TASK TITLE: {task.title}\n"
            f"TASK DESCRIPTION: {task.description}\n"
            f"ASSIGNED ROLE: {task.role_description or task.agent_type}\n"
            f"PRIORITY: {task.priority}\n\n"
            f"CONTEXT:\n{context_blob[:context_limit]}"
        )

    def _apply_pre_execute_hitl(self, *, task: TaskRecord, agent, prompt: str, hitl_callback):
        if hitl_callback is None:
            return prompt

        checkpoint = WorkflowCheckpoint(
            agent_name=agent.name,
            task=prompt,
            result="[pending execution]",
            step=task.index + 1,
            total_steps=None,
        )

        feedback: WorkflowFeedback = hitl_callback(checkpoint)
        if feedback.action == HITLAction.CANCEL:
            raise RuntimeError("Task cancelled by operator.")
        if feedback.action == HITLAction.REVISE and feedback.revised_task.strip():
            return feedback.revised_task.strip()
        return prompt

    def _get_or_create_agent(
        self,
        agent_type: str,
        *,
        role_description: str = "",
        goal: str = "",
        context: dict[str, Any] | None = None,
    ):
        mapping = {
            "developer": ("coding_agent", PermissionLevel.ELEVATED),
            "researcher": ("research_agent", PermissionLevel.STANDARD),
            "marketer": ("marketing_agent", PermissionLevel.STANDARD),
            "operations": ("automation_agent", PermissionLevel.PRIVILEGED),
            "support": ("chatbot_agent", PermissionLevel.STANDARD),
            "ceo": ("business_agent", PermissionLevel.ADMIN),
        }
        safe_agent_type = re.sub(r"[^a-z0-9_\-]+", "_", agent_type.strip().lower()).strip("_")
        safe_agent_type = safe_agent_type or "operations"
        agent_name = f"aether_{safe_agent_type}_agent"

        existing = self.registry.get(agent_name)
        if existing is not None:
            try:
                existing.attach_runtime(
                    ai_adapter=self.ai,
                    workflow_engine=self.workflow,
                    tool_manager=getattr(self.kernel, "tool_manager", None),
                )
                existing.attach_memory(self.memory)
            except Exception:
                pass
            return existing

        try:
            if safe_agent_type in mapping:
                preset, permission = mapping[safe_agent_type]
                agent = self.factory.create(
                    name=agent_name,
                    role=preset,
                    permission_level=permission,
                )
            else:
                agent = self.factory.design_agent(
                    name=agent_name,
                    role_description=role_description or safe_agent_type.replace("_", " ").title(),
                    goal=goal or f"Support tasks for role '{safe_agent_type}'.",
                    context=context,
                    permission_level=PermissionLevel.STANDARD,
                )
            agent.attach_runtime(
                ai_adapter=self.ai,
                workflow_engine=self.workflow,
                tool_manager=getattr(self.kernel, "tool_manager", None),
            )
            agent.attach_memory(self.memory)
            return agent
        except Exception as exc:
            logger.error("[CEO] failed to create agent '%s': %s", agent_name, exc)
            return None

    def _persist_task_memory(
        self,
        *,
        agent_name: str,
        task: TaskRecord,
        result: str,
        success: bool,
        extra: dict[str, Any] | None = None,
    ) -> None:
        try:
            if hasattr(self.memory, "register_namespace"):
                self.memory.register_namespace(agent_name)
            if hasattr(self.memory, "remember_task"):
                self.memory.remember_task(
                    namespace=agent_name,
                    task=task.description,
                    output=result,
                    success=success,
                    metadata={
                        "task_id": task.task_id,
                        "task_title": task.title,
                        "priority": task.priority,
                        **(extra or {}),
                    },
                )
        except Exception as exc:
            logger.debug("[CEO] memory persist failed for %s: %s", agent_name, exc)

    def _persist_result(self, *, goal: str, tasks: list[TaskRecord], summary: str) -> None:
        history_entry = {
            "goal": goal,
            "tasks": [
                {
                    "id": task.task_id,
                    "index": task.index,
                    "title": task.title,
                    "agent_type": task.agent_type,
                    "role_description": task.role_description,
                    "status": task.status,
                    "attempts": task.attempts,
                }
                for task in tasks
            ],
            "summary": summary[:3000],
            "timestamp": time.time(),
        }
        try:
            self.memory.append("project_history", history_entry, namespace="global")
            self.memory.save("last_project", history_entry, namespace="global")
        except Exception as exc:
            logger.warning("[CEO] failed to persist project history: %s", exc)

    def _estimate_cost_usd(self, delta_tokens: int) -> float:
        """Simple cost estimate for governance budget checks.

        Uses env var AETHEERAI_EST_COST_PER_1K_TOKENS when present.
        """
        if delta_tokens <= 0:
            return 0.0
        per_1k = float(os.environ.get("AETHEERAI_EST_COST_PER_1K_TOKENS", "0.003"))
        return (delta_tokens / 1000.0) * per_1k

    def _run_red_team_gate(self, *, goal: str, tasks: list[TaskRecord]) -> None:
        risky_tasks = [task for task in tasks if task.require_approval]
        if not risky_tasks:
            return

        red_team = getattr(self.kernel, "red_team", None)
        if red_team is None:
            logger.info("[CEO] RedTeam gate unavailable; continuing with approval checks.")
            return

        description = (
            f"Goal: {goal}. "
            f"Risky tasks: "
            + "; ".join(f"{task.title} ({task.agent_type})" for task in risky_tasks[:8])
        )
        try:
            report = red_team.run(target_description=description)
            severity = getattr(report, "severity", "LOW")
            if severity in {"HIGH", "CRITICAL"}:
                raise RuntimeError(f"RedTeam blocked workflow with severity {severity}.")
            if severity == "MEDIUM":
                logger.warning("[CEO] RedTeam warning (MEDIUM): proceeding with caution.")
        except Exception as exc:
            # Fail safe for explicit block, otherwise keep execution available.
            if "blocked workflow" in str(exc).lower():
                raise
            logger.warning("[CEO] RedTeam check failed or unavailable: %s", exc)

    def _should_trigger_collaboration(
        self,
        task: TaskRecord,
        *,
        fast_mode: bool = False,
        fast_mode_collaboration: bool = False,
    ) -> bool:
        if fast_mode:
            if not fast_mode_collaboration:
                return task.priority == "critical"
            if task.priority in {"high", "critical"}:
                return True
            text = f"{task.title} {task.description}".lower()
            return any(keyword in text for keyword in ("design", "architecture", "strategy", "go-to-market"))
        if task.priority in {"high", "critical"}:
            return True
        text = f"{task.title} {task.description}".lower()
        return any(keyword in text for keyword in ("design", "architecture", "strategy", "go-to-market"))

    def _run_internal_collaboration(
        self,
        *,
        goal: str,
        task: TaskRecord,
        primary_agent_name: str,
        fast_mode: bool = False,
    ) -> str:
        if fast_mode:
            return self._run_fast_collaboration_brief(
                goal=goal,
                task=task,
                primary_agent_name=primary_agent_name,
            )

        collab = getattr(self.kernel, "collaboration_engine", None)
        if collab is None:
            return ""

        team: list[str] = [primary_agent_name]
        support_roles = ["researcher", "marketer", "developer"]
        max_team_size = 2 if fast_mode else 3
        for role in support_roles:
            if len(team) >= max_team_size:
                break
            helper = self._get_or_create_agent(
                role,
                role_description=f"{role.title()} Support",
                goal=goal,
                context={"task": task.title, "phase": "internal_collaboration"},
            )
            if helper is None:
                continue
            if helper.name not in team:
                team.append(helper.name)

        try:
            session = collab.run(
                goal=(
                    f"Project goal: {goal}\n"
                    f"Focused task: {task.title}\n"
                    f"Task details: {task.description}"
                ),
                agent_names=team,
                rounds=1,
            )
            return str(session.get("final_synthesis") or session.get("shared_context") or "")
        except Exception as exc:
            logger.warning("[CEO] internal collaboration skipped for '%s': %s", task.title, exc)
            return ""

    def _run_fast_collaboration_brief(
        self,
        *,
        goal: str,
        task: TaskRecord,
        primary_agent_name: str,
    ) -> str:
        helper = self._get_or_create_agent(
            "researcher",
            role_description="Fast Collaboration Support",
            goal=goal,
            context={"task": task.title, "phase": "fast_collaboration"},
        )
        if helper is None:
            return ""

        prompt = (
            f"Primary agent: {primary_agent_name}\n"
            f"Goal: {goal}\n"
            f"Focused task: {task.title}\n"
            f"Task details: {task.description}\n\n"
            "Provide a concise teammate brief with:\n"
            "1) two actionable suggestions\n"
            "2) one risk to watch\n"
            "3) one improvement idea\n"
            "Keep total response under 140 words."
        )
        try:
            return str(
                self.ai.chat(
                    [
                        {
                            "role": "system",
                            "content": f"You are {helper.role} assisting a teammate quickly and precisely.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    timeout=35,
                    max_tokens=220,
                )
            )[:1200]
        except Exception as exc:
            logger.warning("[CEO] fast collaboration brief skipped for '%s': %s", task.title, exc)
            return ""

    def _deterministic_delivery(self, *, goal: str, tasks: list[TaskRecord]) -> str:
        completed = [task for task in tasks if task.status == "completed"]
        failed = [task for task in tasks if task.status == "failed"]

        lines: list[str] = [
            f"Goal: {goal}",
            f"Completed tasks: {len(completed)}/{len(tasks)}",
            f"Failed tasks: {len(failed)}",
            "",
            "Completed outputs:",
        ]
        if completed:
            for task in completed[:8]:
                snippet = (task.result or "").strip().replace("\n", " ")[:280]
                lines.append(f"- {task.title}: {snippet or 'Completed with no result payload.'}")
        else:
            lines.append("- None")

        lines.append("")
        lines.append("Failures or skips:")
        if failed:
            for task in failed[:8]:
                reason = (task.error or "failed").strip().replace("\n", " ")[:240]
                lines.append(f"- {task.title}: {reason}")
        else:
            lines.append("- None")

        lines.append("")
        lines.append("Next actions:")
        lines.append("- Review completed outputs and refine missing pieces in a focused follow-up goal.")
        lines.append("- Re-run failed tasks with tighter scope and explicit expected output format.")
        return "\n".join(lines)[:6000]

    @staticmethod
    def _failed_result(
        *,
        goal: str,
        reason: str,
        started_at: float,
        workflow_id: str,
        spent_usd: float,
    ) -> ProjectResult:
        return ProjectResult(
            goal=goal,
            status="failed",
            tasks=[],
            final_summary=reason,
            total_tasks=0,
            completed_tasks=0,
            failed_tasks=0,
            elapsed_seconds=round(time.monotonic() - started_at, 3),
            workflow_id=workflow_id,
            spent_usd=round(spent_usd, 6),
            events=[],
        )
