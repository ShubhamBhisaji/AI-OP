"""FastAPI backend for AetheerAI autonomous multi-agent operations."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Ensure local package imports work when running the module directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agents.ceo_agent import CEOAgent, ProjectResult
from core.aetheerai_kernel import AetheerAiKernel
from core.env_loader import load_env


logger = logging.getLogger("aetheer.api")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_env(_ENV)

_boot_time = time.time()
_projects: dict[str, dict[str, Any]] = {}
_projects_lock = threading.Lock()
_kernel: AetheerAiKernel | None = None
_ceo: CEOAgent | None = None


def _get_kernel() -> AetheerAiKernel:
    global _kernel
    if _kernel is None:
        provider = os.getenv("AI_PROVIDER", "openai")
        model = os.getenv("AI_MODEL", "gpt-4o")
        _kernel = AetheerAiKernel(ai_provider=provider, model=model)
        logger.info("Kernel booted (provider=%s model=%s)", provider, model)
    return _kernel


def _get_ceo() -> CEOAgent:
    global _ceo
    if _ceo is None:
        kernel = _get_kernel()
        _ceo = CEOAgent(
            kernel,
            max_tasks=int(os.getenv("MAX_TASKS_PER_PROJECT", "50")),
            max_cost_usd=float(os.getenv("MAX_COST_USD", "10.0")),
            max_runtime_seconds=int(os.getenv("MAX_RUNTIME_SECONDS", "600")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
        )
    return _ceo


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AetheerAI API startup")
    _get_ceo()
    yield
    logger.info("AetheerAI API shutdown")


app = FastAPI(
    title="AetheerAI API",
    description="Autonomous multi-agent AI operating system backend",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── v2 routers: planning, scheduling, risk, lifecycle ─────────────────────────
from api.routes_v2 import router as _v2_router  # noqa: E402
app.include_router(_v2_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled API error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"success": False, "error": "Internal server error"})



class APIResponse(BaseModel):
    success: bool = True
    data: Any = None
    error: str | None = None
    message: str | None = None


class GoalRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    max_cost_usd: float | None = None
    max_runtime_seconds: int | None = None
    background: bool = False
    parallel: bool = True
    collaboration_mode: bool = False
    offline_local_mode: bool = False
    fast_mode_collaboration: bool = False


class AgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: str | None = None
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    permission_level: int = Field(default=1, ge=0, le=5)


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1)


class AgentDesignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role_description: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    permission_level: int | None = Field(default=None, ge=1, le=5)


class CollaborationRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    team_name: str | None = None
    agent_names: list[str] = Field(default_factory=list)
    rounds: int = Field(default=2, ge=1, le=6)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    system_prompt: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)


def _serialize_project_result(project_id: str, name: str, result: ProjectResult) -> dict[str, Any]:
    total = max(1, result.total_tasks)
    return {
        "id": project_id,
        "workflow_id": result.workflow_id,
        "name": name,
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
        "total_tasks": result.total_tasks,
        "completed_tasks": result.completed_tasks,
        "failed_tasks": result.failed_tasks,
        "elapsed_seconds": result.elapsed_seconds,
        "replanned": result.replanned,
        "events": result.events,
    }


def _read_audit_logs(limit: int = 200) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[1]
    log_path = root / "memory" / "audit_log.jsonl"
    if not log_path.exists() or limit <= 0:
        return []

    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []

    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"raw": line})
    return out


def _find_task(task_id: str) -> dict[str, Any] | None:
    with _projects_lock:
        projects = list(_projects.values())

    for project in projects:
        for task in project.get("tasks", []):
            if str(task.get("task_id", "")) == task_id:
                return {
                    "project_id": project.get("id"),
                    "project_name": project.get("name"),
                    **task,
                }
    return None


async def _submit_goal(req: GoalRequest, background_tasks: BackgroundTasks) -> APIResponse:
    project_id = str(uuid.uuid4())
    with _projects_lock:
        _projects[project_id] = {
            "id": project_id,
            "name": req.name,
            "goal": req.goal,
            "status": "pending",
            "started_at": time.time(),
            "offline_local_mode": req.offline_local_mode,
            "fast_mode_collaboration": req.fast_mode_collaboration,
        }

    def _run_goal() -> None:
        kernel = None
        restore_provider_model: tuple[str, str] | None = None
        try:
            kernel = _get_kernel()
            ceo = _get_ceo()
            if req.max_cost_usd is not None:
                ceo.max_cost_usd = req.max_cost_usd
            if req.max_runtime_seconds is not None:
                ceo.max_runtime_seconds = req.max_runtime_seconds

            if req.offline_local_mode:
                target_provider = os.getenv("AETHEER_OFFLINE_PROVIDER", "ollama").strip().lower() or "ollama"
                target_model = os.getenv("AETHEER_OFFLINE_MODEL", "llama3.2:1b").strip() or "llama3.2:1b"
                current = (kernel.ai_adapter.provider, kernel.ai_adapter.model)
                if current != (target_provider, target_model):
                    try:
                        kernel.ai_adapter.switch(target_provider, target_model)
                        restore_provider_model = current
                        logger.info(
                            "Goal %s running in offline_local_mode using %s/%s",
                            project_id,
                            target_provider,
                            target_model,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Goal %s requested offline_local_mode but provider switch failed: %s",
                            project_id,
                            exc,
                        )

            with _projects_lock:
                _projects[project_id]["status"] = "running"

            result = ceo.run(
                req.goal,
                context=req.context or None,
                parallel=req.parallel,
                collaboration_mode=req.collaboration_mode,
                offline_local_mode=req.offline_local_mode,
                fast_mode_collaboration=req.fast_mode_collaboration,
            )
            payload = _serialize_project_result(project_id, req.name, result)
            payload["started_at"] = _projects[project_id].get("started_at")
            with _projects_lock:
                _projects[project_id].update(payload)
                _projects[project_id]["status"] = result.status
        except Exception as exc:
            logger.error("Goal %s failed: %s", project_id, exc, exc_info=True)
            with _projects_lock:
                _projects[project_id]["status"] = "failed"
                _projects[project_id]["error"] = str(exc)
        finally:
            if restore_provider_model is not None and kernel is not None:
                try:
                    kernel.ai_adapter.switch(restore_provider_model[0], restore_provider_model[1])
                except Exception as exc:
                    logger.warning("Failed to restore provider/model after goal %s: %s", project_id, exc)

    if req.background:
        background_tasks.add_task(_run_goal)
        return APIResponse(
            data={"id": project_id, "status": "pending"},
            message="Goal accepted. Poll /api/goals/{id} for updates.",
        )

    _run_goal()
    with _projects_lock:
        return APIResponse(data=dict(_projects[project_id]))


@app.get("/api/health", tags=["System"], response_model=APIResponse)
def health_check():
    return APIResponse(
        data={
            "status": "ok",
            "version": "2.0.0",
            "provider": os.getenv("AI_PROVIDER", "openai"),
            "model": os.getenv("AI_MODEL", "gpt-4o"),
            "offline_local_mode_default": os.getenv("AETHEER_OFFLINE_LOCAL_MODE", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            "fast_mode_collaboration_default": os.getenv("AETHEER_FAST_MODE_COLLABORATION", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            "offline_provider": os.getenv("AETHEER_OFFLINE_PROVIDER", "ollama"),
            "offline_model": os.getenv("AETHEER_OFFLINE_MODEL", "llama3.2:1b"),
        }
    )


@app.get("/api/system/status", tags=["System"], response_model=APIResponse)
def system_status():
    kernel = _get_kernel()
    with _projects_lock:
        projects = list(_projects.values())

    data = {
        "status": "ok",
        "uptime_seconds": round(time.time() - _boot_time, 3),
        "provider": os.getenv("AI_PROVIDER", "openai"),
        "model": os.getenv("AI_MODEL", "gpt-4o"),
        "offline_local_mode_default": os.getenv("AETHEER_OFFLINE_LOCAL_MODE", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        "fast_mode_collaboration_default": os.getenv("AETHEER_FAST_MODE_COLLABORATION", "false")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        "offline_provider": os.getenv("AETHEER_OFFLINE_PROVIDER", "ollama"),
        "offline_model": os.getenv("AETHEER_OFFLINE_MODEL", "llama3.2:1b"),
        "projects": {
            "total": len(projects),
            "running": len([p for p in projects if p.get("status") == "running"]),
            "completed": len([p for p in projects if p.get("status") == "completed"]),
            "partial": len([p for p in projects if p.get("status") == "partial"]),
            "failed": len([p for p in projects if p.get("status") == "failed"]),
            "cancelled": len([p for p in projects if p.get("status") == "cancelled"]),
        },
        "agents_registered": len(kernel.registry.list_names()),
        "tools_registered": len(kernel.tool_manager.list_tools()),
        "memory_keys": len(kernel.memory.keys()),
        "collaboration_sessions": len(kernel.collaboration_sessions(limit=1000)),
    }
    return APIResponse(data=data)


@app.get("/api/logs", tags=["System"], response_model=APIResponse)
def list_logs(limit: int = 200):
    return APIResponse(data=_read_audit_logs(limit=limit))


@app.post("/api/goals", tags=["Goals"], response_model=APIResponse, status_code=201)
async def submit_goal(req: GoalRequest, background_tasks: BackgroundTasks):
    return await _submit_goal(req, background_tasks)


@app.get("/api/goals", tags=["Goals"], response_model=APIResponse)
def list_goals():
    with _projects_lock:
        items = sorted(_projects.values(), key=lambda p: p.get("started_at", 0), reverse=True)
        return APIResponse(data=list(items))


@app.get("/api/goals/{goal_id}", tags=["Goals"], response_model=APIResponse)
def get_goal(goal_id: str):
    with _projects_lock:
        project = _projects.get(goal_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found.")
        return APIResponse(data=dict(project))


@app.get("/api/goals/{goal_id}/tasks", tags=["Goals"], response_model=APIResponse)
def get_goal_tasks(goal_id: str):
    with _projects_lock:
        project = _projects.get(goal_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found.")
        return APIResponse(data=project.get("tasks", []))


@app.get("/api/tasks/{task_id}", tags=["Goals"], response_model=APIResponse)
def get_task(task_id: str):
    task = _find_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return APIResponse(data=task)


@app.post("/api/collaborations", tags=["Collaboration"], response_model=APIResponse, status_code=201)
def run_collaboration(req: CollaborationRequest):
    kernel = _get_kernel()

    if req.team_name and req.agent_names:
        raise HTTPException(
            status_code=400,
            detail="Provide either team_name or agent_names, not both.",
        )
    if not req.team_name and not req.agent_names:
        raise HTTPException(
            status_code=400,
            detail="Provide team_name or at least one agent name.",
        )

    try:
        payload = kernel.collaborate(
            goal=req.goal,
            team_name=req.team_name,
            agent_names=req.agent_names or None,
            rounds=req.rounds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return APIResponse(data=payload)


@app.get("/api/collaborations", tags=["Collaboration"], response_model=APIResponse)
def list_collaborations(limit: int = 50):
    kernel = _get_kernel()
    return APIResponse(data=kernel.collaboration_sessions(limit=limit))


@app.get("/api/collaborations/{session_id}", tags=["Collaboration"], response_model=APIResponse)
def get_collaboration(session_id: str):
    kernel = _get_kernel()
    session = kernel.collaboration_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Collaboration session '{session_id}' not found.")
    return APIResponse(data=session)


# Backward-compatible project routes.
@app.post("/api/projects", tags=["Projects"], response_model=APIResponse, status_code=201)
async def create_project(req: GoalRequest, background_tasks: BackgroundTasks):
    return await _submit_goal(req, background_tasks)


@app.get("/api/projects", tags=["Projects"], response_model=APIResponse)
def list_projects():
    return list_goals()


@app.get("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse)
def get_project(project_id: str):
    return get_goal(project_id)


@app.delete("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse)
def delete_project(project_id: str):
    with _projects_lock:
        if project_id not in _projects:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
        del _projects[project_id]
    return APIResponse(message=f"Project '{project_id}' deleted.")


@app.post("/api/agents", tags=["Agents"], response_model=APIResponse, status_code=201)
def create_agent(req: AgentRequest):
    kernel = _get_kernel()
    if kernel.registry.get(req.name):
        raise HTTPException(status_code=409, detail=f"Agent '{req.name}' already exists.")

    try:
        agent = kernel.factory.create(
            name=req.name,
            role=req.role,
            tools=req.tools or None,
            skills=req.skills or None,
            objectives=req.objectives or None,
            permissions=req.permissions or None,
            permission_level=req.permission_level,
        )
        if hasattr(agent, "attach_runtime"):
            agent.attach_runtime(
                ai_adapter=kernel.ai_adapter,
                workflow_engine=kernel.workflow_engine,
                tool_manager=kernel.tool_manager,
            )
        if hasattr(agent, "attach_memory"):
            agent.attach_memory(kernel.memory)
        return APIResponse(data=agent.to_dict(), message=f"Agent '{req.name}' created.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/agents/design", tags=["Agents"], response_model=APIResponse, status_code=201)
def design_agent(req: AgentDesignRequest):
    kernel = _get_kernel()
    if kernel.registry.get(req.name):
        raise HTTPException(status_code=409, detail=f"Agent '{req.name}' already exists.")

    try:
        agent = kernel.factory.design_agent(
            name=req.name,
            role_description=req.role_description,
            goal=req.goal,
            context=req.context,
            permission_level=req.permission_level,
        )
        if hasattr(agent, "attach_runtime"):
            agent.attach_runtime(
                ai_adapter=kernel.ai_adapter,
                workflow_engine=kernel.workflow_engine,
                tool_manager=kernel.tool_manager,
            )
        if hasattr(agent, "attach_memory"):
            agent.attach_memory(kernel.memory)
        return APIResponse(data=agent.to_dict(), message=f"Agent '{req.name}' designed and created.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/agents", tags=["Agents"], response_model=APIResponse)
def list_agents():
    kernel = _get_kernel()
    return APIResponse(data=kernel.registry.list_all())


@app.get("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse)
def get_agent(agent_name: str):
    kernel = _get_kernel()
    agent = kernel.registry.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return APIResponse(data=agent.to_dict())


@app.delete("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse)
def delete_agent(agent_name: str):
    kernel = _get_kernel()
    if not kernel.registry.remove(agent_name):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return APIResponse(message=f"Agent '{agent_name}' removed.")


@app.post("/api/agents/{agent_name}/run", tags=["Agents"], response_model=APIResponse)
def run_agent_task(agent_name: str, req: AgentRunRequest):
    kernel = _get_kernel()
    agent = kernel.registry.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

    try:
        if hasattr(agent, "attach_runtime"):
            agent.attach_runtime(
                ai_adapter=kernel.ai_adapter,
                workflow_engine=kernel.workflow_engine,
                tool_manager=kernel.tool_manager,
            )
        if hasattr(agent, "attach_memory"):
            agent.attach_memory(kernel.memory)

        result = agent.execute_task(req.task)
        return APIResponse(data={"agent": agent_name, "result": result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/chat", tags=["Chat"], response_model=APIResponse)
def chat(req: ChatRequest):
    kernel = _get_kernel()
    messages: list[dict[str, str]] = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    messages.extend(req.history[-20:])
    messages.append({"role": "user", "content": req.message})

    try:
        reply = kernel.ai_adapter.chat(messages)
        return APIResponse(data={"reply": reply})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/memory", tags=["Memory"], response_model=APIResponse)
def get_memory(namespace: str = "global"):
    kernel = _get_kernel()
    try:
        data = kernel.memory.all(namespace=namespace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return APIResponse(data=data)


@app.delete("/api/memory/{key}", tags=["Memory"], response_model=APIResponse)
def delete_memory_key(key: str, namespace: str = "global"):
    kernel = _get_kernel()
    try:
        deleted = kernel.memory.delete(key, namespace=namespace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in namespace '{namespace}'.")
    return APIResponse(message=f"Key '{key}' deleted from namespace '{namespace}'.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.server:app",
        host=os.getenv("AETHER_HOST", "0.0.0.0"),
        port=int(os.getenv("AETHER_PORT", "8000")),
        reload=os.getenv("AETHER_RELOAD", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
