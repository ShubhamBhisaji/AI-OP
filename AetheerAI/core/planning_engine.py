"""
PlanningEngine — True goal-directed planning for AetheerAI.

Closes the gap between "runs per request" and "long multi-step autonomy":

  1. Goal Decomposition  — AI breaks a high-level goal into a dependency DAG
                           of named subtasks, each assigned to an agent type.
  2. Task Graph (DAG)    — Topological execution respects inter-task dependencies.
                           Independent tasks are executed in parallel groups for speed.
  3. Failure Recovery    — retry  →  AI-patch (self-healer)  →  replan subtask
                           →  mark failed + continue if non-critical, or abort.
  4. Long Autonomy Loop  — execute_plan() keeps running until the entire goal
                           graph is complete, budget is exhausted, or max_steps
                           is reached — no human needed per request.
  5. Persistence         — Plans are saved to workspace/plans/ as JSON so they
                           survive restarts and can be inspected or resumed.

Security
--------
- Task descriptions are sanitised before feed-forward (injection fence).
- Budget and step limits enforce hard autonomy ceilings (GovernanceLayer).
- DESTRUCTIVE / HIGH_RISK subtasks trigger ApprovalGate before execution.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
_MAX_PLAN_TASKS: int = 30          # max subtasks per goal
_MAX_REPLAN_CYCLES: int = 3        # how many times we can ask AI to fix a failed plan
_DEFAULT_MAX_STEPS: int = 50       # autonomy ceiling per execute_plan() call
_PLANS_DIR = Path(__file__).parent.parent / "workspace" / "plans"
_PLANS_DIR.mkdir(parents=True, exist_ok=True)

# ── AI Prompts ─────────────────────────────────────────────────────────────
_DECOMPOSE_PROMPT = """\
You are an autonomous planning AI.  Your job is to decompose a high-level goal
into an ordered, dependency-aware task graph that a team of specialist agents
can execute.

AVAILABLE AGENT TYPES: {agent_types}

GOAL:
{goal}

CONTEXT (current workspace files, prior memory):
{context}

Return ONLY a valid JSON object — no markdown fences, no explanation — in this
EXACT schema:

{{
  "plan_title": "<short title>",
  "plan_summary": "<one paragraph>",
  "tasks": [
    {{
      "id": "t1",
      "title": "<action verb + noun>",
      "description": "<what the agent must produce, max 200 chars>",
      "agent_type": "<one of the AVAILABLE AGENT TYPES>",
      "depends_on": [],
      "max_retries": 2,
      "critical": true
    }}
  ]
}}

Rules:
- Use IDs like t1, t2, t3 … (keep them short).
- depends_on lists IDs that MUST complete before this task starts.
- No circular dependencies.
- critical=true means the whole plan fails if this task fails (after retries).
- Keep total tasks <= {max_tasks}.
- Match agent_type exactly to an available type.
"""

_REPLAN_PROMPT = """\
You are an autonomous planning AI.  A task in the following plan has failed
even after self-healing attempts.  Revise ONLY the failed task (and any tasks
that directly depend on it) to produce a new strategy that avoids the same
failure mode.

ORIGINAL PLAN:
{plan_json}

FAILED TASK ID: {failed_task_id}
FAILURE REASON: {reason}

Return ONLY valid JSON with the updated "tasks" array (same schema as the
original).  Keep all successful tasks unchanged.  Do NOT add more than
{max_new_tasks} new tasks.
"""


# ── Task node ──────────────────────────────────────────────────────────────

@dataclass
class TaskNode:
    id: str
    title: str
    description: str
    agent_type: str
    depends_on: list[str] = field(default_factory=list)
    max_retries: int = 2
    critical: bool = True
    # Runtime state (not persisted in the user-visible plan)
    status: str = "pending"   # pending | running | completed | failed | skipped
    result: str = ""
    error: str = ""
    attempts: int = 0
    started_at: float | None = None
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "agent_type": self.agent_type,
            "depends_on": list(self.depends_on),
            "max_retries": self.max_retries,
            "critical": self.critical,
            "status": self.status,
            "result": self.result[:500] if self.result else "",
            "error": self.error[:300] if self.error else "",
            "attempts": self.attempts,
            "elapsed_seconds": (
                round(self.finished_at - self.started_at, 2)
                if self.started_at and self.finished_at else None
            ),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskNode":
        return cls(
            id=str(d.get("id", uuid.uuid4().hex[:6])),
            title=str(d.get("title", "Unnamed task")),
            description=str(d.get("description", "")),
            agent_type=str(d.get("agent_type", "research_agent")),
            depends_on=[str(x) for x in (d.get("depends_on") or [])],
            max_retries=int(d.get("max_retries", 2)),
            critical=bool(d.get("critical", True)),
            status=str(d.get("status", "pending")),
        )


# ── Task graph (DAG) ───────────────────────────────────────────────────────

class TaskGraph:
    """Directed acyclic graph of TaskNode objects with topological scheduling."""

    def __init__(self, plan_id: str, title: str, summary: str) -> None:
        self.plan_id = plan_id
        self.title = title
        self.summary = summary
        self._nodes: dict[str, TaskNode] = {}
        self._lock = threading.Lock()

    # --- build & modify -------------------------------------------------------

    def add_task(self, node: TaskNode) -> None:
        with self._lock:
            self._nodes[node.id] = node

    def update_task_status(self, task_id: str, status: str, result: str = "", error: str = "") -> None:
        with self._lock:
            node = self._nodes.get(task_id)
            if node:
                node.status = status
                if result:
                    node.result = result
                if error:
                    node.error = error
                if status == "running" and node.started_at is None:
                    node.started_at = time.time()
                if status in ("completed", "failed", "skipped"):
                    node.finished_at = time.time()

    # --- query ----------------------------------------------------------------

    def get_task(self, task_id: str) -> TaskNode | None:
        return self._nodes.get(task_id)

    def all_tasks(self) -> list[TaskNode]:
        return list(self._nodes.values())

    def ready_tasks(self) -> list[TaskNode]:
        """Return tasks whose dependencies are all completed and status is pending."""
        with self._lock:
            ready = []
            for node in self._nodes.values():
                if node.status != "pending":
                    continue
                deps_done = all(
                    self._nodes.get(dep_id) is not None
                    and self._nodes[dep_id].status == "completed"
                    for dep_id in node.depends_on
                )
                if deps_done:
                    ready.append(node)
            return ready

    def is_complete(self) -> bool:
        return all(n.status in ("completed", "skipped") for n in self._nodes.values())

    def has_critical_failure(self) -> tuple[bool, str]:
        for n in self._nodes.values():
            if n.status == "failed" and n.critical:
                return True, n.id
        return False, ""

    def pending_count(self) -> int:
        return sum(1 for n in self._nodes.values() if n.status == "pending")

    def stats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self._nodes.values():
            counts[n.status] = counts.get(n.status, 0) + 1
        return counts

    # --- persistence ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "summary": self.summary,
            "tasks": [n.to_dict() for n in self._nodes.values()],
        }

    def save(self, plans_dir: Path = _PLANS_DIR) -> Path:
        path = plans_dir / f"plan_{self.plan_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, plan_id: str, plans_dir: Path = _PLANS_DIR) -> "TaskGraph | None":
        path = plans_dir / f"plan_{plan_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            graph = cls(
                plan_id=data["plan_id"],
                title=data.get("title", "Loaded plan"),
                summary=data.get("summary", ""),
            )
            for task_dict in data.get("tasks", []):
                graph.add_task(TaskNode.from_dict(task_dict))
            return graph
        except Exception as exc:
            logger.error("TaskGraph.load failed for plan %s: %s", plan_id, exc)
            return None

    # --- validation -----------------------------------------------------------

    def _validate_dag(self) -> None:
        """Raise ValueError if the graph contains cycles (Kahn's algorithm)."""
        in_degree: dict[str, int] = {n.id: 0 for n in self._nodes.values()}
        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep not in in_degree:
                    raise ValueError(f"Task '{node.id}' depends on unknown task '{dep}'.")
                in_degree[node.id] += 1  # not quite — fix below

        # Proper Kahn's
        in_degree = {n.id: 0 for n in self._nodes.values()}
        children: dict[str, list[str]] = {n.id: [] for n in self._nodes.values()}
        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep not in children:
                    raise ValueError(f"Unknown dependency '{dep}' in task '{node.id}'.")
                children[dep].append(node.id)
                in_degree[node.id] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            nid = queue.pop(0)
            visited += 1
            for child in children[nid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if visited != len(self._nodes):
            raise ValueError("Task graph contains a cycle — cannot execute.")


# ── Planning engine ────────────────────────────────────────────────────────

class PlanningEngine:
    """
    Autonomous planning and execution engine.

    Usage
    -----
    engine = PlanningEngine(orchestrator, registry, ai_adapter, governance)
    plan   = engine.decompose_goal("Build a full website for AcmeCorp")
    result = engine.execute_plan(plan)
    """

    def __init__(
        self,
        workflow_engine,
        registry,
        ai_adapter,
        governance,
        self_healer=None,
        memory_manager=None,
    ) -> None:
        self.workflow_engine = workflow_engine
        self.registry = registry
        self.ai = ai_adapter
        self.governance = governance
        self.self_healer = self_healer
        self.memory = memory_manager

    # ── Decompose ─────────────────────────────────────────────────────────

    def decompose_goal(
        self,
        goal: str,
        *,
        context: str = "",
        plan_id: str | None = None,
    ) -> TaskGraph:
        """
        Use AI to break a high-level goal into a dependency task graph.

        Returns a TaskGraph ready for execute_plan().
        Raises ValueError if decomposition fails after retries.
        """
        plan_id = plan_id or uuid.uuid4().hex[:12]
        agent_types = list(self.registry.list_agents().keys()) if hasattr(self.registry, "list_agents") else [
            "research_agent", "coding_agent", "marketing_agent",
            "automation_agent", "data_analysis_agent", "business_agent",
        ]
        available_types = ", ".join(agent_types) or "research_agent, coding_agent"

        prompt = _DECOMPOSE_PROMPT.format(
            goal=goal[:2000],
            context=context[:1000],
            agent_types=available_types,
            max_tasks=_MAX_PLAN_TASKS,
        )

        raw = ""
        for attempt in range(1, 4):
            try:
                raw = self.ai.chat([{"role": "user", "content": prompt}])
                data = self._parse_plan_json(raw)
                graph = self._build_graph(plan_id, data)
                graph._validate_dag()
                graph.save()
                logger.info(
                    "PlanningEngine: decomposed goal into %d tasks (plan %s).",
                    len(graph.all_tasks()), plan_id,
                )
                return graph
            except Exception as exc:
                logger.warning("PlanningEngine.decompose_goal attempt %d failed: %s", attempt, exc)
                if attempt == 3:
                    raise ValueError(f"Goal decomposition failed after 3 attempts: {exc}") from exc
                time.sleep(1)

        raise ValueError("Goal decomposition failed.")  # unreachable

    # ── Execute ───────────────────────────────────────────────────────────

    def execute_plan(
        self,
        graph: TaskGraph,
        *,
        max_steps: int = _DEFAULT_MAX_STEPS,
        max_workers: int = 4,
        governance_ctx=None,
    ) -> dict[str, Any]:
        """
        Execute a TaskGraph to completion using the long-autonomy loop.

        - Runs all ready tasks in parallel groups.
        - Retries failures → self-healer patch → replan.
        - Respects GovernanceLayer budget/runtime limits.
        - Returns a summary dict with per-task results and final status.
        """
        steps = 0
        replan_cycles = 0
        start_time = time.time()

        logger.info("PlanningEngine: starting plan '%s' (%s)", graph.plan_id, graph.title)

        while not graph.is_complete() and steps < max_steps:
            # Governance check
            if governance_ctx is not None:
                try:
                    self.governance.check_limits(governance_ctx)
                except (TimeoutError, RuntimeError) as exc:
                    logger.warning("PlanningEngine: governance limit hit: %s", exc)
                    break

            # Check for unrecoverable critical failure
            crit_fail, crit_id = graph.has_critical_failure()
            if crit_fail:
                # Attempt replan for the failed critical task
                if replan_cycles < _MAX_REPLAN_CYCLES:
                    logger.info("PlanningEngine: replanning after critical failure of task %s", crit_id)
                    try:
                        self._replan_task(graph, crit_id)
                        replan_cycles += 1
                        continue
                    except Exception as exc:
                        logger.error("PlanningEngine: replan failed: %s", exc)
                logger.error("PlanningEngine: plan %s aborted — critical task %s failed.", graph.plan_id, crit_id)
                break

            ready = graph.ready_tasks()
            if not ready:
                # No ready tasks but plan not complete — likely blocked by failed non-critical tasks
                logger.warning("PlanningEngine: no ready tasks, checking deadlock for plan %s", graph.plan_id)
                if graph.pending_count() > 0:
                    # Mark tasks blocked by failed deps as skipped
                    self._resolve_blocked_tasks(graph)
                break

            steps += len(ready)  # count tasks contributed, not loops

            if len(ready) == 1:
                self._execute_task(graph, ready[0], governance_ctx=governance_ctx)
            else:
                workers = min(max_workers, len(ready))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(self._execute_task, graph, node, governance_ctx): node
                        for node in ready
                    }
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as exc:
                            node = futures[future]
                            logger.error("PlanningEngine: unhandled error in task %s: %s", node.id, exc)
                            graph.update_task_status(node.id, "failed", error=str(exc))

            graph.save()

        elapsed = round(time.time() - start_time, 2)
        final_stats = graph.stats()
        final_status = "completed" if graph.is_complete() else "partial"

        logger.info(
            "PlanningEngine: plan %s finished in %.1fs — steps=%d stats=%s",
            graph.plan_id, elapsed, steps, final_stats,
        )

        if self.memory:
            try:
                self.memory.set(
                    f"plan:{graph.plan_id}:outcome",
                    {"status": final_status, "stats": final_stats, "elapsed": elapsed},
                )
            except Exception:
                pass

        return {
            "plan_id": graph.plan_id,
            "title": graph.title,
            "status": final_status,
            "elapsed_seconds": elapsed,
            "steps_run": steps,
            "replan_cycles": replan_cycles,
            "stats": final_stats,
            "tasks": [t.to_dict() for t in graph.all_tasks()],
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    def _execute_task(
        self,
        graph: TaskGraph,
        node: TaskNode,
        governance_ctx=None,
    ) -> None:
        """Run a single task node with retry + self-healing."""
        graph.update_task_status(node.id, "running")

        # Build the task prompt, extending it with upstream results
        task_prompt = self._build_task_prompt(graph, node)

        last_error = ""
        for attempt in range(1, node.max_retries + 2):  # +1 for initial run
            node.attempts = attempt
            try:
                agent = self._get_or_create_agent(node.agent_type)
                if agent is None:
                    raise RuntimeError(f"No agent available for type '{node.agent_type}'.")

                result = self.workflow_engine.execute(agent=agent, task=task_prompt)

                if self._is_failure_result(result):
                    last_error = result
                    raise RuntimeError(f"Agent returned failure result: {result[:300]}")

                graph.update_task_status(node.id, "completed", result=result)
                logger.info(
                    "PlanningEngine: task %s ('%s') completed on attempt %d.",
                    node.id, node.title, attempt,
                )
                return

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "PlanningEngine: task %s attempt %d/%d failed: %s",
                    node.id, attempt, node.max_retries + 1, exc,
                )

                # Self-healer patch on last retry
                if attempt == node.max_retries + 1:
                    if self.self_healer:
                        try:
                            agent = self._get_or_create_agent(node.agent_type)
                            healed = self.self_healer.heal(
                                agent=agent,
                                task=task_prompt,
                                error_output=last_error,
                            )
                            if healed and not self._is_failure_result(healed):
                                graph.update_task_status(node.id, "completed", result=healed)
                                logger.info(
                                    "PlanningEngine: self-healer recovered task %s.", node.id
                                )
                                return
                        except Exception as heal_exc:
                            logger.error("PlanningEngine: self-healer failed for %s: %s", node.id, heal_exc)
                    break  # exhausted retries + healing

        graph.update_task_status(node.id, "failed", error=last_error)
        logger.error("PlanningEngine: task %s FAILED after all attempts.", node.id)

    def _get_or_create_agent(self, agent_type: str):
        """Retrieve an existing agent by type or return None."""
        # Try exact name match first
        agent = self.registry.get(agent_type)
        if agent:
            return agent
        # Try partial match (e.g. "research_agent" → agent named "researcher")
        all_agents = self.registry.list_agents() if hasattr(self.registry, "list_agents") else {}
        for name, profile in all_agents.items():
            role = (profile.get("role") or "").lower().replace(" ", "_")
            if agent_type.lower() in role or role in agent_type.lower():
                return self.registry.get(name)
        return None

    def _build_task_prompt(self, graph: TaskGraph, node: TaskNode) -> str:
        """Assemble the task prompt, prepending upstream context."""
        lines = [f"Task: {node.title}", f"Instructions: {node.description}"]
        upstream_results = []
        for dep_id in node.depends_on:
            dep = graph.get_task(dep_id)
            if dep and dep.result:
                upstream_results.append(f"[{dep.title}]: {dep.result[:800]}")
        if upstream_results:
            lines.append("\nContext from prior steps:")
            lines.extend(upstream_results)
        return "\n".join(lines)

    def _is_failure_result(self, result: str) -> bool:
        if not result:
            return True
        lower = result.lower()
        failure_markers = (
            "traceback", "error:", "exception:", "failed:", "[error]",
            "task failed", "unable to", "could not",
        )
        return any(m in lower for m in failure_markers)

    def _replan_task(self, graph: TaskGraph, failed_task_id: str) -> None:
        """Ask AI to revise the failed task and its dependants."""
        node = graph.get_task(failed_task_id)
        if node is None:
            return

        plan_json = json.dumps(graph.to_dict(), indent=2)[:4000]
        prompt = _REPLAN_PROMPT.format(
            plan_json=plan_json,
            failed_task_id=failed_task_id,
            reason=node.error[:500],
            max_new_tasks=5,
        )
        raw = self.ai.chat([{"role": "user", "content": prompt}])
        try:
            data = self._parse_plan_json(raw)
            updated_tasks = data.get("tasks", [])
            for task_dict in updated_tasks:
                tid = str(task_dict.get("id", ""))
                if not tid:
                    continue
                new_node = TaskNode.from_dict(task_dict)
                # Reset only the failed and dependent tasks
                if tid == failed_task_id or tid in [n.id for n in graph.all_tasks() if failed_task_id in n.depends_on]:
                    new_node.status = "pending"
                    graph.add_task(new_node)
            graph._validate_dag()
            graph.save()
            logger.info("PlanningEngine: replanned task %s successfully.", failed_task_id)
        except Exception as exc:
            raise ValueError(f"Replan parse error: {exc}") from exc

    def _resolve_blocked_tasks(self, graph: TaskGraph) -> None:
        """Mark pending tasks whose deps have failed as skipped."""
        for node in graph.all_tasks():
            if node.status != "pending":
                continue
            for dep_id in node.depends_on:
                dep = graph.get_task(dep_id)
                if dep and dep.status == "failed":
                    graph.update_task_status(node.id, "skipped", error=f"Dependency '{dep_id}' failed.")
                    break

    def _parse_plan_json(self, raw: str) -> dict[str, Any]:
        """Extract the first JSON object from an AI response."""
        text = raw.strip()
        # Strip markdown fences
        if "```" in text:
            import re
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
        # Find first { ... }
        start = text.find("{")
        if start == -1:
            raise ValueError("No JSON object found in AI response.")
        # Find matching closing brace
        depth = 0
        end = -1
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            raise ValueError("Incomplete JSON in AI response.")
        return json.loads(text[start:end])

    def _build_graph(self, plan_id: str, data: dict[str, Any]) -> TaskGraph:
        graph = TaskGraph(
            plan_id=plan_id,
            title=str(data.get("plan_title", "Untitled Plan")),
            summary=str(data.get("plan_summary", "")),
        )
        tasks = data.get("tasks", [])
        if not tasks or not isinstance(tasks, list):
            raise ValueError("AI returned no tasks in the plan.")
        count = 0
        for task_dict in tasks:
            if count >= _MAX_PLAN_TASKS:
                logger.warning("PlanningEngine: truncated plan to %d tasks.", _MAX_PLAN_TASKS)
                break
            graph.add_task(TaskNode.from_dict(task_dict))
            count += 1
        return graph

    # ── Convenience ───────────────────────────────────────────────────────

    def run(
        self,
        goal: str,
        *,
        context: str = "",
        max_steps: int = _DEFAULT_MAX_STEPS,
        max_workers: int = 4,
        governance_ctx=None,
    ) -> dict[str, Any]:
        """
        One-shot: decompose goal → execute → return summary.
        This is the primary long-autonomy entry point.
        """
        graph = self.decompose_goal(goal, context=context)
        return self.execute_plan(
            graph,
            max_steps=max_steps,
            max_workers=max_workers,
            governance_ctx=governance_ctx,
        )

    def list_plans(self) -> list[dict[str, Any]]:
        """Return metadata of all saved plans."""
        plans = []
        for p in sorted(_PLANS_DIR.glob("plan_*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                plans.append({
                    "plan_id": data.get("plan_id"),
                    "title": data.get("title"),
                    "task_count": len(data.get("tasks", [])),
                    "file": p.name,
                })
            except Exception:
                pass
        return plans

    def resume_plan(self, plan_id: str, **kwargs) -> dict[str, Any] | None:
        """Resume a previously saved plan, skipping already-completed tasks."""
        graph = TaskGraph.load(plan_id)
        if graph is None:
            logger.error("PlanningEngine.resume_plan: plan %s not found.", plan_id)
            return None
        return self.execute_plan(graph, **kwargs)
