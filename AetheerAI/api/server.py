"""
AETHER OS — FastAPI Backend
===========================
Production-ready REST API that exposes the full AETHER multi-agent platform.

Endpoints
---------
  POST   /api/projects            Create & immediately run a project
  GET    /api/projects            List all projects
  GET    /api/projects/{id}       Get project detail + task results
  DELETE /api/projects/{id}       Delete a project from history

  POST   /api/agents              Create a custom agent
  GET    /api/agents              List all registered agents
  GET    /api/agents/{name}       Get agent profile
  DELETE /api/agents/{name}       Unregister an agent
  POST   /api/agents/{name}/run   Run a single task on a specific agent

  POST   /api/chat                Single-turn AI assistant (no CEO planning)

  GET    /api/health              Health / version check
  GET    /api/memory              Inspect global memory keys
  DELETE /api/memory/{key}        Delete a memory key

Run
---
  # From the AetheerAI/ directory:
  uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
  # Or:
  python -m api.server
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
except ImportError as exc:
    raise ImportError(
        "FastAPI is required.  Install with: pip install fastapi uvicorn"
    ) from exc

from pydantic import BaseModel, Field

from core.env_loader import load_env
from core.aetheerai_kernel import AetheerAiKernel
from agents.ceo_agent import CEOAgent, ProjectResult

# ── Load environment variables ─────────────────────────────────────────────
_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_env(_ENV)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aether.api")

# ── In-process project store (swap for a real DB in production) ────────────
_projects: dict[str, dict] = {}

# ── Kernel singleton ────────────────────────────────────────────────────────
_kernel: AetheerAiKernel | None = None
_ceo: CEOAgent | None = None


def _get_kernel() -> AetheerAiKernel:
    global _kernel
    if _kernel is None:
        provider = os.getenv("AI_PROVIDER", "openai")
        model    = os.getenv("AI_MODEL", "gpt-4o")
        _kernel  = AetheerAiKernel(ai_provider=provider, model=model)
        logger.info("AETHER kernel booted (provider=%s model=%s)", provider, model)
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


# ── Lifespan (startup / shutdown) ──────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AETHER OS starting up...")
    _get_ceo()  # warm the kernel at boot
    yield
    logger.info("AETHER OS shutting down.")


# ── FastAPI application ─────────────────────────────────────────────────────
app = FastAPI(
    title="AETHER OS",
    description="Autonomous Multi-Agent AI Operating System",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────
_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ───────────────────────────────────────────────
@app.exception_handler(Exception)
async def _global_exc_handler(request: Request, exc: Exception):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# Pydantic request / response schemas
# ═══════════════════════════════════════════════════════════════════════════

class ProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Short project name")
    goal: str = Field(..., min_length=1, description="High-level goal for the CEO agent")
    context: dict[str, Any] = Field(default_factory=dict, description="Optional extra context")
    max_cost_usd: float | None = None
    max_runtime_seconds: int | None = None
    background: bool = Field(default=False, description="Run asynchronously; poll for results")


class AgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: str | None = None
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    permission_level: int = Field(default=1, ge=0, le=3)


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    system_prompt: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)


class APIResponse(BaseModel):
    success: bool = True
    data: Any = None
    error: str | None = None
    message: str | None = None


# ── Helpers ─────────────────────────────────────────────────────────────────

def _project_result_to_dict(pid: str, name: str, result: ProjectResult) -> dict:
    return {
        "id": pid,
        "name": name,
        "goal": result.goal,
        "status": result.status,
        "plan_summary": result.final_summary,
        "tasks": [
            {
                "index": t.index,
                "title": t.title,
                "agent_type": t.agent_type,
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
    }


# ═══════════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/health", tags=["System"])
def health_check():
    """Returns API status and configuration summary."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "provider": os.getenv("AI_PROVIDER", "openai"),
        "model": os.getenv("AI_MODEL", "gpt-4o"),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Projects
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/projects", tags=["Projects"], response_model=APIResponse, status_code=201)
async def create_project(req: ProjectRequest, background_tasks: BackgroundTasks):
    """
    Submit a high-level goal. The CEO Agent plans, assigns, and runs tasks.

    Set `background: true` to return immediately and poll GET /api/projects/{id}.
    """
    project_id = str(uuid.uuid4())
    _projects[project_id] = {
        "id": project_id,
        "name": req.name,
        "goal": req.goal,
        "status": "pending",
        "started_at": time.time(),
    }

    def _run():
        try:
            ceo = _get_ceo()
            # Override limits per-project if provided
            if req.max_cost_usd is not None:
                ceo.max_cost_usd = req.max_cost_usd
            if req.max_runtime_seconds is not None:
                ceo.max_runtime_seconds = req.max_runtime_seconds

            _projects[project_id]["status"] = "running"
            result: ProjectResult = ceo.run(req.goal, context=req.context or None)
            _projects[project_id].update(_project_result_to_dict(project_id, req.name, result))
            _projects[project_id]["status"] = result.status
        except Exception as exc:
            logger.error("Project %s failed: %s", project_id, exc, exc_info=True)
            _projects[project_id]["status"] = "failed"
            _projects[project_id]["error"] = str(exc)

    if req.background:
        background_tasks.add_task(_run)
        return APIResponse(
            data={"id": project_id, "status": "pending"},
            message="Project queued — poll GET /api/projects/{id} for results.",
        )

    # Run synchronously (blocks until complete)
    _run()
    return APIResponse(data=_projects[project_id])


@app.get("/api/projects", tags=["Projects"], response_model=APIResponse)
def list_projects():
    """List all projects (most recent first)."""
    items = sorted(_projects.values(), key=lambda p: p.get("started_at", 0), reverse=True)
    return APIResponse(data=items)


@app.get("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse)
def get_project(project_id: str):
    """Get full detail for a project including all task results."""
    proj = _projects.get(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    return APIResponse(data=proj)


@app.delete("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse)
def delete_project(project_id: str):
    """Remove a project from the in-process store."""
    if project_id not in _projects:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
    del _projects[project_id]
    return APIResponse(message=f"Project '{project_id}' deleted.")


# ═══════════════════════════════════════════════════════════════════════════
# Agents
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/agents", tags=["Agents"], response_model=APIResponse, status_code=201)
def create_agent(req: AgentRequest):
    """Create and register a custom agent."""
    kernel = _get_kernel()
    if kernel.registry.get(req.name):
        raise HTTPException(status_code=409, detail=f"Agent '{req.name}' already exists.")
    try:
        agent = kernel.factory.create(
            name=req.name,
            role=req.role,
            tools=req.tools or None,
            skills=req.skills or None,
            permission_level=req.permission_level,
        )
        return APIResponse(data=agent.to_dict(), message=f"Agent '{req.name}' created.", )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/agents", tags=["Agents"], response_model=APIResponse)
def list_agents():
    """List all registered agents."""
    kernel = _get_kernel()
    agents = kernel.registry.list_all()   # already returns list[dict]
    return APIResponse(data=agents)


@app.get("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse)
def get_agent(agent_name: str):
    """Get an agent's full profile."""
    kernel = _get_kernel()
    agent = kernel.registry.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return APIResponse(data=agent.to_dict())


@app.delete("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse)
def delete_agent(agent_name: str):
    """Unregister an agent."""
    kernel = _get_kernel()
    if not kernel.registry.get(agent_name):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    kernel.registry.remove(agent_name)
    return APIResponse(message=f"Agent '{agent_name}' removed.")


@app.post("/api/agents/{agent_name}/run", tags=["Agents"], response_model=APIResponse)
def run_agent_task(agent_name: str, req: AgentRunRequest):
    """Run a single task directly on a named agent (bypasses CEO planning)."""
    kernel = _get_kernel()
    agent = kernel.registry.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    try:
        result = kernel.workflow_engine.execute(agent, req.task)
        return APIResponse(data={"agent": agent_name, "result": result})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# Chat (direct assistant — no CEO planning)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/chat", tags=["Chat"], response_model=APIResponse)
def chat(req: ChatRequest):
    """
    Single-turn AI assistant endpoint.
    Useful for quick Q&A without spinning up a full project.
    """
    kernel = _get_kernel()
    messages = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    messages.extend(req.history[-20:])      # keep last 20 turns (context guard)
    messages.append({"role": "user", "content": req.message})
    try:
        reply = kernel.ai_adapter.chat(messages)
        return APIResponse(data={"reply": reply})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# Memory
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/memory", tags=["Memory"], response_model=APIResponse)
def get_memory(namespace: str = "global"):
    """Inspect the current in-memory key-value store."""
    kernel = _get_kernel()
    try:
        data = kernel.memory.all(namespace=namespace) if hasattr(kernel.memory, "all") else {}
    except Exception:
        data = {}
    return APIResponse(data=data)


@app.delete("/api/memory/{key}", tags=["Memory"], response_model=APIResponse)
def delete_memory_key(key: str, namespace: str = "global"):
    """Delete a key from memory."""
    kernel = _get_kernel()
    try:
        deleted = kernel.memory.delete(key, namespace=namespace) if hasattr(kernel.memory, "delete") else False
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found in namespace '{namespace}'.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(message=f"Key '{key}' deleted from '{namespace}'.")


# ═══════════════════════════════════════════════════════════════════════════
# CLI entrypoint
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required.  Install with: pip install uvicorn")
        sys.exit(1)

    uvicorn.run(
        "api.server:app",
        host=os.getenv("AETHER_HOST", "0.0.0.0"),
        port=int(os.getenv("AETHER_PORT", "8000")),
        reload=os.getenv("AETHER_RELOAD", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
