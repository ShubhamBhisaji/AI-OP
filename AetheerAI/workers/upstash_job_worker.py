"""Persistent worker that consumes Upstash Redis jobs and updates Supabase status."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any

# Ensure project-local imports resolve when executed as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.ceo_agent import CEOAgent, ProjectResult
from api.async_jobs import SupabaseJobStore
from core.aetheerai_kernel import AetheerAiKernel
from core.env_loader import load_env
from integrations.upstash_redis_queue import UpstashRedisQueue
from utils.log_config import setup_logging

logger = logging.getLogger("aetheer.worker.upstash")


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _resolve_ai_runtime() -> tuple[str, str]:
    provider = (
        (os.getenv("AETHEERAI_DEFAULT_PROVIDER") or "").strip().lower()
        or (os.getenv("AI_PROVIDER") or "").strip().lower()
        or "openai"
    )
    model = (
        (os.getenv("AETHEERAI_DEFAULT_MODEL") or "").strip()
        or (os.getenv("AI_MODEL") or "").strip()
        or "gpt-4o"
    )
    return provider, model


def _serialize_project_result(result: ProjectResult) -> dict[str, Any]:
    total = max(1, result.total_tasks)
    return {
        "workflow_id": result.workflow_id,
        "goal": result.goal,
        "status": result.status,
        "plan_summary": result.final_summary,
        "spent_usd": result.spent_usd,
        "progress": {
            "completed": result.completed_tasks,
            "failed": result.failed_tasks,
            "total": result.total_tasks,
            "percent": round((result.completed_tasks / total) * 100.0, 2),
        },
        "tasks": [
            {
                "task_id": t.task_id,
                "index": t.index,
                "title": t.title,
                "description": t.description,
                "agent_type": t.agent_type,
                "role_description": t.role_description,
                "priority": t.priority,
                "depends_on": t.depends_on,
                "require_approval": t.require_approval,
                "status": t.status,
                "result": t.result,
                "error": t.error,
                "attempts": t.attempts,
            }
            for t in result.tasks
        ],
        "elapsed_seconds": result.elapsed_seconds,
        "replanned": result.replanned,
        "events": result.events,
    }


class AIJobRunner:
    """Execute task payloads consumed from the queue."""

    def __init__(self) -> None:
        self._kernel: AetheerAiKernel | None = None
        self._ceo: CEOAgent | None = None

    def _kernel_instance(self) -> AetheerAiKernel:
        if self._kernel is None:
            provider, model = _resolve_ai_runtime()
            self._kernel = AetheerAiKernel(ai_provider=provider, model=model)
            logger.info("Worker kernel booted (provider=%s model=%s)", provider, model)
        return self._kernel

    def _ceo_instance(self) -> CEOAgent:
        if self._ceo is None:
            kernel = self._kernel_instance()
            self._ceo = CEOAgent(
                kernel,
                max_tasks=_env_int("MAX_TASKS_PER_PROJECT", 50, minimum=1),
                max_cost_usd=_env_float("MAX_COST_USD", 10.0, minimum=0.0),
                max_runtime_seconds=_env_int("MAX_RUNTIME_SECONDS", 600, minimum=10),
                max_retries=_env_int("MAX_RETRIES", 3, minimum=0),
            )
        return self._ceo

    def execute(self, *, task_type: str, task_data: dict[str, Any]) -> Any:
        normalized = (task_type or "").strip().lower()
        if not normalized:
            normalized = "goal"

        if normalized == "goal":
            return self._execute_goal(task_data)
        if normalized == "agent_task":
            return self._execute_agent_task(task_data)
        if normalized == "chat":
            return self._execute_chat(task_data)

        raise ValueError(f"Unsupported task_type '{task_type}'.")

    def _execute_goal(self, task_data: dict[str, Any]) -> dict[str, Any]:
        goal = str(task_data.get("goal") or "").strip()
        if not goal:
            raise ValueError("goal task requires task_data.goal")

        context = task_data.get("context") if isinstance(task_data.get("context"), dict) else {}
        parallel = bool(task_data.get("parallel", True))
        collaboration_mode = bool(task_data.get("collaboration_mode", False))
        offline_local_mode = bool(task_data.get("offline_local_mode", False))
        fast_mode_collaboration = bool(task_data.get("fast_mode_collaboration", False))

        result = self._ceo_instance().run(
            goal,
            context=context,
            parallel=parallel,
            collaboration_mode=collaboration_mode,
            offline_local_mode=offline_local_mode,
            fast_mode_collaboration=fast_mode_collaboration,
        )
        return _serialize_project_result(result)

    def _execute_agent_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        agent_name = str(task_data.get("agent_name") or "").strip()
        task = str(task_data.get("task") or "").strip()
        if not agent_name or not task:
            raise ValueError("agent_task requires task_data.agent_name and task_data.task")

        result = self._kernel_instance().run_agent(agent_name, task)
        return {
            "agent_name": agent_name,
            "task": task,
            "result": result,
        }

    def _execute_chat(self, task_data: dict[str, Any]) -> dict[str, Any]:
        message = str(task_data.get("message") or "").strip()
        if not message:
            raise ValueError("chat task requires task_data.message")

        history = task_data.get("history") if isinstance(task_data.get("history"), list) else []
        reply = self._kernel_instance().chat(message=message, history=history)
        return {
            "message": message,
            "reply": reply,
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upstash Redis worker for AetheerAI async jobs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pop-timeout",
        type=int,
        default=_env_int("UPSTASH_REDIS_POP_TIMEOUT_SECONDS", 30, minimum=1),
        help="BRPOP timeout in seconds.",
    )
    parser.add_argument(
        "--idle-sleep",
        type=float,
        default=_env_float("AETHEER_WORKER_IDLE_SLEEP_SECONDS", 0.25, minimum=0.05),
        help="Sleep interval when no job is popped.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single job then exit.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Worker log level.",
    )
    return parser.parse_args()


def run_worker(*, pop_timeout: int, idle_sleep: float, run_once: bool) -> None:
    queue = UpstashRedisQueue()
    store = SupabaseJobStore()
    runner = AIJobRunner()

    logger.info(
        "Worker online: queue=%s pop_timeout=%ss run_once=%s",
        queue.queue_name,
        pop_timeout,
        run_once,
    )

    handled = 0
    while True:
        try:
            payload = queue.blocking_pop(timeout_seconds=pop_timeout)
        except KeyboardInterrupt:
            logger.info("Worker interrupted. Shutting down.")
            break
        except Exception as exc:
            logger.error("Queue pop error: %s", exc, exc_info=True)
            time.sleep(min(5.0, idle_sleep * 2.0))
            continue

        if payload is None:
            time.sleep(idle_sleep)
            if run_once:
                logger.info("No jobs available; exiting due to --once.")
                break
            continue

        job_id = str(payload.get("jobId") or "").strip()
        task_type = str(payload.get("taskType") or "goal")
        task_data = payload.get("task")

        if not job_id or not isinstance(task_data, dict):
            logger.error("Invalid queue payload discarded: %s", payload)
            continue

        try:
            store.mark_running(job_id)
        except Exception as exc:
            logger.warning("Failed to mark job %s running before execution: %s", job_id, exc)

        try:
            result = runner.execute(task_type=task_type, task_data=task_data)
            store.mark_completed(job_id, result)
            handled += 1
            logger.info("Job %s completed", job_id)
        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
            try:
                store.mark_failed(job_id, str(exc))
            except Exception as update_exc:
                logger.error("Could not persist failed status for %s: %s", job_id, update_exc, exc_info=True)

        if run_once and handled >= 1:
            logger.info("Processed one job; exiting due to --once.")
            break


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    load_env(env_path)

    args = _parse_args()
    setup_logging(level=str(args.log_level).upper())

    run_worker(
        pop_timeout=max(1, int(args.pop_timeout)),
        idle_sleep=max(0.05, float(args.idle_sleep)),
        run_once=bool(args.once),
    )


if __name__ == "__main__":
    main()
