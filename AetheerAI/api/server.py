"""FastAPI backend for AetheerAI autonomous multi-agent operations."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

# Ensure local package imports work when running the module directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.ceo_agent import CEOAgent, ProjectResult
from api.database import GoalRun, SessionLocal, SystemLog, Task, init_db
from api.db_router import router as db_router
from core.aetheerai_kernel import AetheerAiKernel
from core.env_loader import load_env
from use_cases import registry as use_case_registry


logger = logging.getLogger("aetheer.api")
# Root logger is configured by setup_logging() in the process entry point.
# Do not call basicConfig here — it would conflict with the central setup.


_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_env(_ENV)

_boot_time = time.time()
_projects: dict[str, dict[str, Any]] = {}
_projects_lock = threading.Lock()
_kernel: AetheerAiKernel | None = None
_ceo: CEOAgent | None = None
_ml_engine = None
_local_predictor = None
_sqlite_log_handler: logging.Handler | None = None


class _SQLiteLogHandler(logging.Handler):
    """Persist warning/error server logs into the system_logs SQLite table."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("sqlalchemy"):
            return

        db: Session | None = None
        try:
            context: dict[str, Any] | None = None
            if record.exc_info:
                formatter = logging.Formatter()
                context = {"traceback": formatter.formatException(record.exc_info)}

            db = SessionLocal()
            db.add(
                SystemLog(
                    level=record.levelname,
                    logger_name=record.name,
                    message=record.getMessage(),
                    context=context,
                )
            )
            db.commit()
        except Exception:
            self.handleError(record)
        finally:
            if db is not None:
                db.close()


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


def _get_ml_engine():
    """Lazy-load the ML engine so API boot remains fast when ML is unused."""
    global _ml_engine
    if _ml_engine is None:
        from core.ml_engine import MLEngine
        _ml_engine = MLEngine.load_or_create()
    return _ml_engine


def _get_local_predictor():
    """Lazy-load a local fallback model that always supports predict()."""
    global _local_predictor
    if _local_predictor is None:
        from core.local_predictor import LocalPredictor
        _local_predictor = LocalPredictor()
    return _local_predictor


def _run_nlp(action: str, text: str, labels=None, question: str = "", max_length: int = 150, target_lang: str = "en") -> str:
    from tools.nlp_tool import nlp_tool
    return nlp_tool(
        action=action,
        text=text,
        labels=labels,
        question=question,
        max_length=max_length,
        target_lang=target_lang,
    )


def _run_vision(
    action: str,
    image_path: str = "",
    image_url: str = "",
    image_b64: str = "",
    question: str = "",
    provider: str = "",
) -> str:
    from tools.vision_tool import vision_tool
    return vision_tool(
        action=action,
        image_path=image_path,
        image_url=image_url,
        image_b64=image_b64,
        question=question,
        provider=provider,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sqlite_log_handler

    logger.info("AetheerAI API startup")
    init_db()

    if _sqlite_log_handler is None:
        _sqlite_log_handler = _SQLiteLogHandler(level=logging.WARNING)
        logging.getLogger().addHandler(_sqlite_log_handler)

    _get_ceo()
    yield

    if _sqlite_log_handler is not None:
        logging.getLogger().removeHandler(_sqlite_log_handler)
        _sqlite_log_handler = None

    logger.info("AetheerAI API shutdown")


_API_DESCRIPTION = """
## AetheerAI REST API — v2.1

**AetheerAI** is an autonomous multi-agent AI Operating System.  
This API exposes the full runtime: submit high-level goals, manage agents,
stream live progress, chat directly with the LLM, inspect memory, and save/restore snapshots.

---

### Authentication

All endpoints (except `/`, `/docs`, `/redoc`, `/api/health`, and `/ui/*`) require an
`X-API-Key` header **only when** the `AETHER_API_KEYS` environment variable is set.
If that variable is unset the server runs in open dev mode.

```
X-API-Key: sk-aether-prod-abc123
```

---

### Tag groups

| Tag | What it covers |
|-----|----------------|
| **System** | Health check, runtime status, audit logs |
| **Goals** | Submit goals, poll progress, real-time SSE stream |
| **Projects** | Alias routes for Goals (backward-compatible) |
| **Agents** | Create / list / run / delete specialist agents |
| **Chat** | Direct single-turn or multi-turn LLM conversation |
| **Collaboration** | Multi-agent round-table sessions |
| **Memory** | Inspect and delete keys from the agent memory store |
| **State** | Save and restore full agent + memory snapshots |

---

### Real-time streaming

Two live-progress transports are available for any running goal:

| Transport | URL pattern | Notes |
|-----------|-------------|-------|
| **Server-Sent Events** | `GET /api/goals/{id}/stream` | Works with `EventSource`, curl `-N`, Postman |
| **WebSocket** | `ws://host/ws/goals/{id}` | Bidirectional; ideal for React / mobile |

Both emit incremental JSON diffs every ~800 ms and close with a terminal `done` event.
"""

_TAGS_METADATA = [
    {
        "name": "System",
        "description": "Health check, runtime status, and audit log endpoints. "
                       "Always public — no API key required.",
    },
    {
        "name": "Goals",
        "description": "Submit a high-level goal and let the CEO agent decompose it "
                       "into tasks, assign specialist sub-agents, and execute them. "
                       "Poll status or subscribe to live SSE/WebSocket progress.",
    },
    {
        "name": "Projects",
        "description": "Backward-compatible aliases for the Goals endpoints. "
                       "Identical behaviour — use Goals for new integrations.",
    },
    {
        "name": "Agents",
        "description": "Create, list, run individual tasks on, and delete "
                       "specialist AI agents. Supports both manual configuration "
                       "and AI-designed agents via `/api/agents/design`.",
    },
    {
        "name": "Chat",
        "description": "Direct single-turn or multi-turn conversation with the "
                       "configured LLM. No CEO planning or agent orchestration — "
                       "just a raw chat completion.",
    },
    {
        "name": "Collaboration",
        "description": "Run structured multi-agent round-table sessions where "
                       "multiple agents debate, refine, and synthesise a shared answer.",
    },
    {
        "name": "Memory",
        "description": "Read and delete keys from the agent memory store. "
                       "Supports multiple namespaces (default: `global`).",
    },
    {
        "name": "State",
        "description": "Save the current agent roster + global memory to a JSON "
                       "snapshot, list snapshots, restore from a snapshot, or delete one. "
                       "Snapshots are stored at `AetheerAI/memory/snapshots/`.",
    },
    {
        "name": "UseCases",
        "description": "Discover and run packaged workflow templates with structured inputs/outputs.",
    },
    {
        "name": "Inference",
        "description": "Low-level prediction endpoint for direct model calls with optional overrides.",
    },
    {
        "name": "Tasks",
        "description": "Execute one-off tasks directly against a named agent or the base AI adapter.",
    },
]

app = FastAPI(
    title="AetheerAI API",
    description=_API_DESCRIPTION,
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=_TAGS_METADATA,
    contact={
        "name": "TecBunny / AetheerAI",
        "url": "https://github.com/your-org/AetheerAI",
        "email": "support@aetheerai.dev",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
)

app.include_router(db_router)

# Serve built-in Web UI static files
_UI_DIR = Path(__file__).resolve().parents[1] / "ui"
if _UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR)), name="ui")

origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def custom_openapi() -> dict[str, Any]:
    """Inject API key security scheme so Swagger documents authenticated calls."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=_TAGS_METADATA,
    )
    components = schema.setdefault("components", {})
    components["securitySchemes"] = {
        "ApiKeyHeader": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Optional unless AETHER_API_KEYS is configured on the server.",
        }
    }
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/", include_in_schema=False)
def serve_ui():
    """Serve the built-in Web UI."""
    index = _UI_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index), media_type="text/html")
    return JSONResponse({"message": "AetheerAI API is running. See /docs for endpoints."})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled API error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"success": False, "error": "Internal server error"})


class APIResponse(BaseModel):
    """Standard envelope returned by every endpoint."""

    success: bool = Field(True, description="`true` on success, `false` on error.")
    data: Any = Field(None, description="Payload — shape varies per endpoint (see individual docs).")
    error: str | None = Field(None, description="Human-readable error detail when `success` is false.")
    message: str | None = Field(None, description="Optional informational message.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "data": {"id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "status": "completed"},
                "error": None,
                "message": None,
            }
        }
    }


class GoalRequest(BaseModel):
    """Payload to submit a new goal or project."""

    name: str = Field(
        ..., min_length=1, max_length=200,
        description="Short human-readable project name (used in listings).",
    )
    goal: str = Field(
        ..., min_length=1,
        description="Free-text description of what AetheerAI should accomplish. "
                    "Be as specific as you like — the CEO agent will decompose it.",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional key/value context injected into the CEO planning prompt.",
    )
    max_cost_usd: float | None = Field(
        None, ge=0,
        description="Hard spending cap in USD. Overrides the server default when set.",
    )
    max_runtime_seconds: int | None = Field(
        None, ge=1,
        description="Hard wall-clock timeout in seconds. Overrides the server default when set.",
    )
    background: bool = Field(
        False,
        description="When `true` the goal is queued and the API returns immediately with a "
                    "pending ID. Poll `GET /api/goals/{id}` or stream `/api/goals/{id}/stream`.",
    )
    parallel: bool = Field(
        True,
        description="Run independent sub-tasks in parallel threads (recommended).",
    )
    collaboration_mode: bool = Field(
        False,
        description="Enable multi-agent collaboration debate on the final plan.",
    )
    offline_local_mode: bool = Field(
        False,
        description="Force this goal to run on the local/offline provider defined by "
                    "`AETHEER_OFFLINE_PROVIDER` / `AETHEER_OFFLINE_MODEL`.",
    )
    fast_mode_collaboration: bool = Field(
        False,
        description="Use a lightweight collaboration strategy optimised for speed.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "saas-landing-page",
                "goal": "Build a professional SaaS landing page for TaskFlow with hero section, pricing table, and FAQ.",
                "background": True,
                "parallel": True,
                "max_cost_usd": 5.0,
                "max_runtime_seconds": 300,
            }
        }
    }


class AgentRequest(BaseModel):
    """Payload to manually configure a new agent."""

    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Unique agent identifier. Used as the agent's key in the registry.",
    )
    role: str | None = Field(
        None,
        description="Short human-readable role title, e.g. `\"Senior Python Developer\"`.",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="List of tool names to enable for this agent, e.g. `[\"web_search\", \"code_executor\"]`.",
    )
    skills: list[str] = Field(default_factory=list, description="Skill catalog entries to attach.")
    objectives: list[str] = Field(default_factory=list, description="Standing objectives baked into the system prompt.")
    permissions: list[str] = Field(default_factory=list, description="Explicit permission grants (e.g. `read_files`).")
    permission_level: int = Field(
        default=1, ge=0, le=5,
        description="Numeric permission tier (0 = read-only, 5 = full system access). Default: 1.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "frontend-dev",
                "role": "Senior Frontend Developer",
                "tools": ["web_search", "code_executor", "file_writer"],
                "permission_level": 2,
            }
        }
    }


class AgentRunRequest(BaseModel):
    """Single task to execute on an existing agent."""

    task: str = Field(
        ..., min_length=1,
        description="Free-text task description. The agent will execute it and return the result.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {"task": "Write a Python function that validates an email address using regex."}
        }
    }


class AgentDesignRequest(BaseModel):
    """Let the AI design a new agent from a role description and goal."""

    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Unique agent identifier to register the newly designed agent under.",
    )
    role_description: str = Field(
        ..., min_length=1, max_length=200,
        description="One-sentence description of the agent's expertise, "
                    "e.g. `\"Senior data analyst specialising in Python and pandas\"`.",
    )
    goal: str = Field(
        ..., min_length=1,
        description="What this agent should accomplish. Used to select tools and draft objectives.",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional extra context passed to the AI designer prompt.",
    )
    permission_level: int | None = Field(
        default=None, ge=1, le=5,
        description="Override the AI-suggested permission level (1–5).",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "data-analyst",
                "role_description": "Senior data analyst specialising in Python and pandas",
                "goal": "Analyse Q1 sales data and produce an executive summary with charts.",
                "permission_level": 2,
            }
        }
    }


class CollaborationRequest(BaseModel):
    """Start a multi-agent collaboration session."""

    goal: str = Field(
        ..., min_length=1,
        description="Topic or question the agents should collectively solve.",
    )
    team_name: str | None = Field(
        None,
        description="Name of a pre-defined team. Mutually exclusive with `agent_names`.",
    )
    agent_names: list[str] = Field(
        default_factory=list,
        description="Explicit list of agent names to invite. Mutually exclusive with `team_name`.",
    )
    rounds: int = Field(
        default=2, ge=1, le=6,
        description="Number of debate/refinement rounds (1–6). More rounds → better synthesis, more tokens.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "goal": "What is the best architecture for a real-time notification system at 1 M users/day?",
                "agent_names": ["backend-dev", "devops-engineer", "data-analyst"],
                "rounds": 3,
            }
        }
    }


class ChatRequest(BaseModel):
    """Single-turn or multi-turn direct LLM chat (no CEO planning)."""

    message: str = Field(
        ..., min_length=1,
        description="The user message to send to the LLM.",
    )
    system_prompt: str | None = Field(
        None,
        description="Optional system prompt to prepend. Overrides the default assistant persona.",
    )
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Prior conversation turns as `[{\"role\": \"user\"|\"assistant\", \"content\": \"...\"}]`. "
                    "Last 20 entries are sent.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Explain the difference between REST and GraphQL in 3 bullet points.",
                "history": [
                    {"role": "user", "content": "Hi, I'm building an API."},
                    {"role": "assistant", "content": "Great! What kind of API are you building?"},
                ],
            }
        }
    }


class UseCaseRunRequest(BaseModel):
    """Run a packaged use case with simple key/value inputs."""

    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Input payload for the selected use case.",
    )


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


def _as_utc_datetime(value: Any) -> datetime.datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.datetime.utcfromtimestamp(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _persist_project_to_db(project_id: str, name: str, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        row = db.query(GoalRun).filter(GoalRun.id == project_id).first()
        if row is None:
            row = GoalRun(id=project_id, name=name, goal=str(payload.get("goal", "")))
            db.add(row)

        row.name = name
        row.goal = str(payload.get("goal", ""))
        row.status = str(payload.get("status", "pending"))
        row.plan_summary = payload.get("plan_summary")
        row.total_tasks = int(payload.get("total_tasks") or 0)
        row.completed_tasks = int(payload.get("completed_tasks") or 0)
        row.failed_tasks = int(payload.get("failed_tasks") or 0)
        row.spent_usd = payload.get("spent_usd")
        row.elapsed_seconds = payload.get("elapsed_seconds")
        row.error = payload.get("error")
        row.replanned = bool(payload.get("replanned", False))
        row.started_at = _as_utc_datetime(payload.get("started_at"))

        if row.status in {"completed", "failed", "cancelled"}:
            row.completed_at = _as_utc_datetime(payload.get("completed_at")) or datetime.datetime.utcnow()

        db.query(Task).filter(Task.goal_id == project_id).delete(synchronize_session=False)
        for task in payload.get("tasks", []):
            db.add(
                Task(
                    task_uuid=task.get("task_id"),
                    goal_id=project_id,
                    task_index=int(task.get("index") or 0),
                    title=str(task.get("title") or ""),
                    description=task.get("description"),
                    agent_type=task.get("agent_type"),
                    role_description=task.get("role_description"),
                    priority=int(task.get("priority") or 1),
                    depends_on=task.get("depends_on") or [],
                    require_approval=bool(task.get("require_approval", False)),
                    status=str(task.get("status") or "pending"),
                    result=task.get("result"),
                    error=task.get("error"),
                    attempts=int(task.get("attempts") or 0),
                )
            )

        db.commit()
    finally:
        db.close()


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
                snapshot = dict(_projects[project_id])

            try:
                _persist_project_to_db(project_id, req.name, snapshot)
            except Exception as db_exc:
                logger.warning("Goal %s persisted in-memory but DB write failed: %s", project_id, db_exc)
        except Exception as exc:
            logger.error("Goal %s failed: %s", project_id, exc, exc_info=True)
            with _projects_lock:
                _projects[project_id]["status"] = "failed"
                _projects[project_id]["error"] = str(exc)
                snapshot = dict(_projects[project_id])

            try:
                _persist_project_to_db(project_id, req.name, snapshot)
            except Exception as db_exc:
                logger.warning("Goal %s failure state could not be persisted: %s", project_id, db_exc)
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


@app.get("/api/health", tags=["System"], response_model=APIResponse,
         summary="Health check",
         description="Lightweight liveness probe. Always returns `200 OK` with the active "
                     "provider and model. **No API key required.**")
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


@app.get("/api/system/status", tags=["System"], response_model=APIResponse,
         summary="Full runtime status",
         description="Returns live counters for projects, agents, tools, and memory keys. "
                     "Use this as a rich dashboard data source.")
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


@app.get("/api/logs", tags=["System"], response_model=APIResponse,
         summary="Audit log",
         description="Returns the last `limit` entries from the append-only JSONL audit log "
                     "(`memory/audit_log.jsonl`). Every tool call and agent action is recorded here.")
def list_logs(limit: int = 200):
    return APIResponse(data=_read_audit_logs(limit=limit))


@app.get("/api/usecases", tags=["UseCases"], response_model=APIResponse,
         summary="List packaged use cases",
         description="Returns all packaged workflow templates available in this runtime.")
def list_usecases():
    """List all packaged use-case workflows available in this runtime."""
    return APIResponse(data=use_case_registry.list())


@app.post("/api/usecases/{usecase_name}/run", tags=["UseCases"], response_model=APIResponse,
          summary="Run a packaged use case",
          description="Executes a named use-case workflow with provided inputs and returns summary, "
                      "structured outputs, and generated file paths.")
def run_usecase(usecase_name: str, req: UseCaseRunRequest):
    """Run a named packaged use case and return files/summary."""
    kernel = _get_kernel()
    result = use_case_registry.run(usecase_name, req.inputs or {}, kernel)
    if not result.success:
        return APIResponse(success=False, error=result.error or "Use case failed.")
    payload = {
        "summary": result.summary,
        "outputs": result.outputs,
        "output_files": [
            {"label": label, "path": path} for (label, path) in result.output_files
        ],
    }
    return APIResponse(data=payload)


@app.post("/api/goals", tags=["Goals"], response_model=APIResponse, status_code=201,
          summary="Submit a goal",
          description="""
The primary entry point. Send a high-level natural-language goal and AetheerAI will:

1. **Plan** — the CEO agent decomposes the goal into ordered sub-tasks.
2. **Assign** — specialist agents (Developer, Researcher, Marketer, Ops, …) are assigned.
3. **Execute** — tasks run in parallel (if enabled) with HITL approval gates for risky actions.
4. **Deliver** — a consolidated summary and per-task results are returned.

Set `background: true` to return immediately with a goal ID and stream progress via
`GET /api/goals/{id}/stream` (SSE) or `ws://host/ws/goals/{id}` (WebSocket).
""")
async def submit_goal(req: GoalRequest, background_tasks: BackgroundTasks):
    return await _submit_goal(req, background_tasks)


@app.get("/api/goals", tags=["Goals"], response_model=APIResponse,
         summary="List all goals",
         description="Returns all goals sorted newest-first. Each item includes `status`, "
                     "`progress`, `spent_usd`, and a task breakdown.")
def list_goals():
    with _projects_lock:
        items = sorted(_projects.values(), key=lambda p: p.get("started_at", 0), reverse=True)
        return APIResponse(data=list(items))


@app.get("/api/goals/{goal_id}", tags=["Goals"], response_model=APIResponse,
         summary="Get goal by ID",
         description="Returns the full goal record including all task results, cost, "
                     "elapsed time, and the CEO's plan summary.")
def get_goal(goal_id: str):
    with _projects_lock:
        project = _projects.get(goal_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found.")
        return APIResponse(data=dict(project))


@app.get("/api/goals/{goal_id}/tasks", tags=["Goals"], response_model=APIResponse,
         summary="List tasks for a goal",
         description="Returns the ordered list of sub-tasks created by the CEO agent. "
                     "Each task has `status`, `result`, `agent_type`, `priority`, and `attempts`.")
def get_goal_tasks(goal_id: str):
    with _projects_lock:
        project = _projects.get(goal_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found.")
        return APIResponse(data=project.get("tasks", []))


@app.get("/api/tasks/{task_id}", tags=["Goals"], response_model=APIResponse,
         summary="Get a single task",
         description="Look up one sub-task by its UUID across all goals.")
def get_task(task_id: str):
    task = _find_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return APIResponse(data=task)


@app.post("/api/collaborations", tags=["Collaboration"], response_model=APIResponse, status_code=201,
          summary="Start a collaboration session",
          description="""
Runs a structured multi-agent round-table debate. Each agent produces an answer, then
agents read each other's responses and refine their own over `rounds` iterations.
The session result contains every agent's final answer plus a synthesised conclusion.

Provide **either** `team_name` (a pre-defined team) **or** `agent_names` (an explicit list)—not both.
""")
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


@app.get("/api/collaborations", tags=["Collaboration"], response_model=APIResponse,
         summary="List collaboration sessions",
         description="Returns the most recent `limit` collaboration sessions (default: 50).")
def list_collaborations(limit: int = 50):
    kernel = _get_kernel()
    return APIResponse(data=kernel.collaboration_sessions(limit=limit))


@app.get("/api/collaborations/{session_id}", tags=["Collaboration"], response_model=APIResponse,
         summary="Get collaboration session",
         description="Returns the full record for a specific collaboration session by ID.")
def get_collaboration(session_id: str):
    kernel = _get_kernel()
    session = kernel.collaboration_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Collaboration session '{session_id}' not found.")
    return APIResponse(data=session)


# Backward-compatible project routes.
@app.post("/api/projects", tags=["Projects"], response_model=APIResponse, status_code=201,
          summary="Submit a project (alias for POST /api/goals)",
          description="Identical to `POST /api/goals`. Provided for backward-compatibility.")
async def create_project(req: GoalRequest, background_tasks: BackgroundTasks):
    return await _submit_goal(req, background_tasks)


@app.get("/api/projects", tags=["Projects"], response_model=APIResponse,
         summary="List projects (alias for GET /api/goals)",
         description="Identical to `GET /api/goals`.")
def list_projects():
    return list_goals()


@app.get("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse,
         summary="Get project by ID (alias)",
         description="Identical to `GET /api/goals/{goal_id}`.")
def get_project(project_id: str):
    return get_goal(project_id)


@app.delete("/api/projects/{project_id}", tags=["Projects"], response_model=APIResponse,
            summary="Delete a project",
            description="Removes the project record from the in-memory store. "
                        "This does not cancel a currently running goal.")
def delete_project(project_id: str):
    with _projects_lock:
        if project_id not in _projects:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
        del _projects[project_id]
    return APIResponse(message=f"Project '{project_id}' deleted.")


@app.post("/api/agents", tags=["Agents"], response_model=APIResponse, status_code=201,
          summary="Create an agent",
          description="""
Manually configure and register a new specialist agent.

For AI-designed agents (where the LLM selects tools and writes objectives for you),
use `POST /api/agents/design` instead.

Returns 409 if an agent with the same name already exists.
""")
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


@app.post("/api/agents/design", tags=["Agents"], response_model=APIResponse, status_code=201,
          summary="AI-design an agent",
          description="""
Use the LLM to automatically design a specialist agent. Provide a `role_description` and a `goal`;
the AI will select the best tools, write standing objectives, and configure permissions.

The resulting agent is registered and ready to use immediately.
""")
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


@app.get("/api/agents", tags=["Agents"], response_model=APIResponse,
         summary="List agents",
         description="Returns all registered agents with their tools, skills, objectives, and permission level.")
def list_agents():
    kernel = _get_kernel()
    return APIResponse(data=kernel.registry.list_all())


@app.get("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse,
         summary="Get agent details",
         description="Returns the full configuration of a named agent.")
def get_agent(agent_name: str):
    kernel = _get_kernel()
    agent = kernel.registry.get(agent_name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return APIResponse(data=agent.to_dict())


@app.delete("/api/agents/{agent_name}", tags=["Agents"], response_model=APIResponse,
            summary="Delete an agent",
            description="Removes the agent from the registry. Running tasks are not interrupted.")
def delete_agent(agent_name: str):
    kernel = _get_kernel()
    if not kernel.registry.remove(agent_name):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")
    return APIResponse(message=f"Agent '{agent_name}' removed.")


@app.post("/api/agents/{agent_name}/run", tags=["Agents"], response_model=APIResponse,
          summary="Run a task on an agent",
          description="""
Execute a single free-text task on a named agent and return the result synchronously.

The agent's configured tools and memory are available during execution.
For long-running tasks consider using `POST /api/goals` and polling instead.
""")
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


@app.post("/api/chat", tags=["Chat"], response_model=APIResponse,
          summary="Direct LLM chat",
          description="""
Send a message directly to the configured LLM and get a reply.

No CEO planning, no agents, no tools — just a raw chat completion.
Optional `history` lets you maintain multi-turn context (last 20 turns are sent).
Optional `system_prompt` overrides the default assistant persona for this request.
""")
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


@app.get("/api/memory", tags=["Memory"], response_model=APIResponse,
         summary="Read memory namespace",
         description="Returns all key/value pairs in the specified memory namespace. "
                     "Default namespace is `global`. Agent-specific namespaces use the agent name.")
def get_memory(namespace: str = "global"):
    kernel = _get_kernel()
    try:
        data = kernel.memory.all(namespace=namespace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return APIResponse(data=data)


@app.delete("/api/memory/{key}", tags=["Memory"], response_model=APIResponse,
            summary="Delete a memory key",
            description="Deletes a single key from the specified namespace. "
                        "Returns 404 if the key does not exist.")
def delete_memory_key(key: str, namespace: str = "global"):
    kernel = _get_kernel()
    try:
        deleted = kernel.memory.delete(key, namespace=namespace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in namespace '{namespace}'.")
    return APIResponse(message=f"Key '{key}' deleted from namespace '{namespace}'.")


# ── Snapshots directory ─────────────────────────────────────────────────────
_SNAPSHOTS_DIR = Path(__file__).resolve().parents[1] / "memory" / "snapshots"
_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Real-time: SSE stream for goal progress ──────────────────────────────────
@app.get("/api/goals/{goal_id}/stream", tags=["Goals"], include_in_schema=True,
         summary="Live SSE stream",
         description="Server-Sent Events stream — pushes JSON progress diffs until the goal is terminal.")
async def stream_goal_sse(goal_id: str, request: Request):
    async def _generate() -> AsyncGenerator[str, None]:
        last_sig: str | None = None
        while True:
            if await request.is_disconnected():
                break
            with _projects_lock:
                project = _projects.get(goal_id)
            if project is None:
                yield 'event: error\ndata: {"error": "Goal not found"}\n\n'
                break
            sig = f"{project.get('status')}:{project.get('completed_tasks',0)}:{project.get('total_tasks',0)}"
            if sig != last_sig:
                last_sig = sig
                payload = json.dumps({
                    "id": goal_id,
                    "status": project.get("status"),
                    "progress": project.get("progress", {}),
                    "completed_tasks": project.get("completed_tasks", 0),
                    "total_tasks": project.get("total_tasks", 0),
                    "failed_tasks": project.get("failed_tasks", 0),
                    "spent_usd": project.get("spent_usd", 0),
                    "plan_summary": project.get("plan_summary"),
                    "events": (project.get("events") or [])[-20:],
                })
                yield f"data: {payload}\n\n"
            if project.get("status") in ("completed", "failed", "partial", "cancelled"):
                status_val = project.get("status")
                yield f'event: done\ndata: {{"__done__": true, "status": "{status_val}"}}\n\n'
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Real-time: WebSocket stream for goal progress ────────────────────────────
@app.websocket("/ws/goals/{goal_id}")
async def ws_goal_stream(websocket: WebSocket, goal_id: str):
    """WebSocket — pushes goal progress diffs until the goal reaches a terminal state."""
    await websocket.accept()
    try:
        last_sig: str | None = None
        while True:
            with _projects_lock:
                project = _projects.get(goal_id)
            if project is None:
                await websocket.send_json({"error": "Goal not found"})
                break
            sig = f"{project.get('status')}:{project.get('completed_tasks',0)}:{project.get('total_tasks',0)}"
            if sig != last_sig:
                last_sig = sig
                await websocket.send_json({
                    "id": goal_id,
                    "status": project.get("status"),
                    "progress": project.get("progress", {}),
                    "completed_tasks": project.get("completed_tasks", 0),
                    "total_tasks": project.get("total_tasks", 0),
                    "failed_tasks": project.get("failed_tasks", 0),
                    "spent_usd": project.get("spent_usd", 0),
                    "plan_summary": project.get("plan_summary"),
                })
            if project.get("status") in ("completed", "failed", "partial", "cancelled"):
                await websocket.send_json({"__done__": True, "status": project.get("status")})
                break
            await asyncio.sleep(0.8)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── State: save / load / list / delete snapshots ─────────────────────────────
class SaveStateRequest(BaseModel):
    name: str = Field(default="snapshot", min_length=1, max_length=60)

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "milestone_release_candidate",
            }
        }
    }


@app.post("/api/state/save", tags=["State"], response_model=APIResponse,
          summary="Save state snapshot",
          description="Serialise the current agent roster and global memory to a JSON file on disk.")
def save_state(req: SaveStateRequest):
    kernel = _get_kernel()
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in req.name if c.isalnum() or c in "-_")[:50] or "snapshot"
    filename = f"{safe_name}_{ts}.json"
    filepath = _SNAPSHOTS_DIR / filename
    try:
        agents = kernel.registry.list_all()
        try:
            memory = kernel.memory.all(namespace="global")
        except Exception:
            memory = {}
        state = {
            "version": "2.0",
            "saved_at": time.time(),
            "name": safe_name,
            "agents": agents,
            "memory": memory,
            "provider": os.getenv("AI_PROVIDER", "openai"),
            "model": os.getenv("AI_MODEL", "gpt-4o"),
        }
        filepath.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        return APIResponse(
            data={"filename": filename, "agents": len(agents), "memory_keys": len(memory)},
            message=f"State saved \u2192 {filename}",
        )
    except Exception as exc:
        logger.error("save_state failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/state/snapshots", tags=["State"], response_model=APIResponse,
         summary="List snapshots",
         description="List all available state snapshot files with metadata.")
def list_snapshots():
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshots: list[dict] = []
    for f in sorted(_SNAPSHOTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            snapshots.append({
                "filename": f.name,
                "name": meta.get("name", f.stem),
                "saved_at": meta.get("saved_at"),
                "agent_count": len(meta.get("agents", [])),
                "memory_keys": len(meta.get("memory", {})),
                "provider": meta.get("provider"),
                "model": meta.get("model"),
                "version": meta.get("version"),
            })
        except Exception:
            snapshots.append({"filename": f.name, "name": f.stem, "saved_at": None})
    return APIResponse(data=snapshots)


@app.post("/api/state/load", tags=["State"], response_model=APIResponse,
          summary="Restore snapshot",
          description="Re-register agents from a named snapshot (existing agents are skipped).")
def load_state(filename: str):
    safe_filename = Path(filename).name
    if not safe_filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Filename must end with .json")
    filepath = _SNAPSHOTS_DIR / safe_filename
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"Snapshot '{safe_filename}' not found.")
    try:
        state = json.loads(filepath.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid or corrupt snapshot file.")
    kernel = _get_kernel()
    loaded = 0
    skipped = 0
    for agent_data in state.get("agents", []):
        name = agent_data.get("name")
        if not name:
            continue
        if kernel.registry.get(name):
            skipped += 1
            continue
        try:
            agent = kernel.factory.create(
                name=name,
                role=agent_data.get("role"),
                tools=agent_data.get("tools") or None,
                permission_level=agent_data.get("permission_level", 1),
            )
            if hasattr(agent, "attach_runtime"):
                agent.attach_runtime(
                    ai_adapter=kernel.ai_adapter,
                    workflow_engine=kernel.workflow_engine,
                    tool_manager=kernel.tool_manager,
                )
            if hasattr(agent, "attach_memory"):
                agent.attach_memory(kernel.memory)
            loaded += 1
        except Exception as exc:
            logger.warning("load_state: could not restore agent '%s': %s", name, exc)
    return APIResponse(
        data={"loaded_agents": loaded, "skipped_agents": skipped, "filename": safe_filename},
        message=f"Restored {loaded} agents from '{safe_filename}' ({skipped} already existed).",
    )


@app.delete("/api/state/snapshots/{filename}", tags=["State"], response_model=APIResponse,
            summary="Delete snapshot",
            description="Permanently delete a state snapshot file from disk.")
def delete_snapshot(filename: str):
    safe_filename = Path(filename).name
    if not safe_filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Filename must end with .json")
    filepath = _SNAPSHOTS_DIR / safe_filename
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"Snapshot '{safe_filename}' not found.")
    try:
        filepath.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return APIResponse(message=f"Snapshot '{safe_filename}' deleted.")


# ── Predict / Status / Task ────────────────────────────────────────────────


class PredictRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="The prompt to send to the AI model.")
    system_prompt: str | None = Field(default=None, description="Optional system-level instruction.")
    model: str | None = Field(default=None, description="Override the active model for this request.")
    provider: str | None = Field(default=None, description="Override the active provider for this request.")
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Optional prior conversation turns [{role, content}, …].",
    )
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class TaskRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="Short title for the task.")
    description: str = Field(..., min_length=1, description="Full task description / instructions.")
    agent: str | None = Field(
        default=None,
        description="Name of a registered agent to run the task. If omitted, the kernel AI adapter is used.",
    )
    context: dict[str, Any] = Field(default_factory=dict, description="Optional key/value context passed to the agent.")
    background: bool = Field(default=False, description="Return immediately with a task ID and run in background.")


class MLTrainRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=120, description="Unique model identifier.")
    task: str = Field(default="classification", description="classification | regression | clustering")
    algorithm: str = Field(default="auto", description="Training algorithm override, e.g. random_forest, logistic_regression.")
    features: list[Any] = Field(..., min_length=1, description="Training feature rows (text, numeric, or dict records).")
    labels: list[Any] | None = Field(default=None, description="Target values. Required for classification/regression.")
    test_size: float = Field(default=0.2, ge=0.05, le=0.5, description="Holdout split ratio.")
    n_clusters: int = Field(default=5, ge=2, le=100, description="Number of clusters for clustering tasks.")
    auto_save: bool = Field(default=True, description="Persist trained model to .pkl immediately.")


class MLPredictRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=120, description="Trained model identifier.")
    features: list[Any] = Field(..., min_length=1, description="Input feature rows for prediction.")
    include_probabilities: bool = Field(
        default=False,
        description="For classification models, include class probability distributions.",
    )


class NLPRequest(BaseModel):
    action: str = Field(default="sentiment", description="sentiment | ner | classify | summarize | qa | translate | embed")
    text: str = Field(..., min_length=1, description="Input text.")
    labels: list[str] = Field(default_factory=list, description="Candidate labels for classify action.")
    question: str = Field(default="", description="Question for qa action.")
    max_length: int = Field(default=150, ge=30, le=512, description="Summary max length.")
    target_lang: str = Field(default="en", description="Target language (ISO 639-1) for translate action.")


class VisionRequest(BaseModel):
    action: str = Field(default="describe", description="describe | extract | analyze | code_ui | audit")
    image_path: str = Field(default="", description="Local image path (inside project sandbox).")
    image_url: str = Field(default="", description="Public HTTPS image URL.")
    image_b64: str = Field(default="", description="Raw base64 image data or data URI.")
    question: str = Field(default="", description="Question for analyze action.")
    provider: str = Field(default="", description="Optional provider override: openai | anthropic | gemini")


@app.post("/predict", tags=["Inference"], response_model=APIResponse,
          summary="Run direct prediction",
          description="Send a prompt directly to the active provider/model and return a reply. "
                      "Useful for lightweight inference without goal orchestration.")
def predict(req: PredictRequest, background_tasks: BackgroundTasks):
    """Run a single-shot AI completion/chat prediction and return the model reply."""
    kernel = _get_kernel()

    # Optionally switch provider/model just for this request
    restore: tuple[str, str] | None = None
    if req.provider or req.model:
        target_provider = (req.provider or kernel.ai_adapter.provider).strip().lower()
        target_model = (req.model or kernel.ai_adapter.model).strip()
        current = (kernel.ai_adapter.provider, kernel.ai_adapter.model)
        if (target_provider, target_model) != current:
            try:
                kernel.ai_adapter.switch(target_provider, target_model)
                restore = current
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Provider/model switch failed: {exc}")

    local_model = _get_local_predictor()
    local_result = local_model.predict(req.prompt)

    try:
        messages: list[dict[str, str]] = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        messages.extend(req.history[-20:])
        messages.append({"role": "user", "content": req.prompt})

        extra: dict[str, Any] = {}
        if req.max_tokens is not None:
            extra["max_tokens"] = req.max_tokens
        if req.temperature is not None:
            extra["temperature"] = req.temperature

        reply = kernel.ai_adapter.chat(messages, **extra) if extra else kernel.ai_adapter.chat(messages)

        return APIResponse(
            data={
                "reply": reply,
                "local_prediction": local_result,
                "provider": kernel.ai_adapter.provider,
                "model": kernel.ai_adapter.model,
                "prompt_length": len(req.prompt),
            }
        )
    except Exception as exc:
        # Keep /predict always usable, even without external AI credentials.
        logger.warning("/predict cloud inference failed; returning local fallback: %s", exc)
        return APIResponse(
            data={
                "reply": local_result,
                "local_prediction": local_result,
                "provider": "local",
                "model": local_model.version,
                "prompt_length": len(req.prompt),
                "fallback": True,
            },
            message="Cloud model unavailable; returned local predictor result.",
        )
    finally:
        if restore is not None:
            try:
                kernel.ai_adapter.switch(restore[0], restore[1])
            except Exception:
                pass


@app.post("/api/ml/train", tags=["Inference"], response_model=APIResponse,
          summary="Train an ML model",
          description="Train a local scikit-learn model (classification/regression/clustering) and persist it as .pkl.")
def ml_train(req: MLTrainRequest):
    try:
        engine = _get_ml_engine()
        report = engine.train(
            name=req.model_name,
            features=req.features,
            labels=req.labels,
            task=req.task,
            algorithm=req.algorithm,
            test_size=req.test_size,
            n_clusters=req.n_clusters,
            auto_save=req.auto_save,
        )
        return APIResponse(data=report, message=f"Model '{req.model_name}' trained successfully.")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ml/predict", tags=["Inference"], response_model=APIResponse,
          summary="Predict with a trained ML model",
          description="Run prediction through a trained .pkl model. Supports optional class probabilities.")
def ml_predict(req: MLPredictRequest):
    try:
        engine = _get_ml_engine()
        preds = engine.predict(req.model_name, req.features)
        payload: dict[str, Any] = {
            "model_name": req.model_name,
            "predictions": preds,
            "count": len(preds),
        }
        if req.include_probabilities:
            payload["probabilities"] = engine.predict_proba(req.model_name, req.features)
        return APIResponse(data=payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/ml/models", tags=["Inference"], response_model=APIResponse,
         summary="List trained ML models",
         description="Returns metadata for all trained models discovered in memory and on disk.")
def ml_models():
    try:
        engine = _get_ml_engine()
        return APIResponse(data=engine.list_models())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/ml/models/{model_name}", tags=["Inference"], response_model=APIResponse,
            summary="Delete a trained ML model",
            description="Deletes a model from memory and removes its .pkl/.meta files from disk.")
def ml_delete_model(model_name: str):
    try:
        engine = _get_ml_engine()
        if not engine.delete_model(model_name):
            raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found.")
        return APIResponse(message=f"Model '{model_name}' deleted.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/nlp", tags=["Inference"], response_model=APIResponse,
          summary="Run NLP inference",
          description="Run sentiment, NER, summarization, QA, translation, or embedding on text.")
def nlp_infer(req: NLPRequest):
    try:
        result = _run_nlp(
            action=req.action,
            text=req.text,
            labels=req.labels,
            question=req.question,
            max_length=req.max_length,
            target_lang=req.target_lang,
        )
        return APIResponse(data={"action": req.action, "result": result})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/vision", tags=["Inference"], response_model=APIResponse,
          summary="Run vision model inference",
          description="Analyze images via describe/OCR/QA/UI-code/audit modes using a vision-capable provider.")
def vision_infer(req: VisionRequest):
    try:
        result = _run_vision(
            action=req.action,
            image_path=req.image_path,
            image_url=req.image_url,
            image_b64=req.image_b64,
            question=req.question,
            provider=req.provider,
        )
        return APIResponse(data={"action": req.action, "result": result})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/status", tags=["System"], response_model=APIResponse,
         summary="Lightweight status",
         description="Compact service status endpoint with uptime and project/agent counters.")
def status():
    """Top-level service status — lightweight health + live counters."""
    try:
        kernel = _get_kernel()
        with _projects_lock:
            projects = list(_projects.values())

        running  = [p for p in projects if p.get("status") == "running"]
        pending  = [p for p in projects if p.get("status") == "pending"]
        done     = [p for p in projects if p.get("status") == "completed"]
        failed   = [p for p in projects if p.get("status") in {"failed", "cancelled"}]

        return APIResponse(
            data={
                "status": "ok",
                "version": "2.0.0",
                "uptime_seconds": round(time.time() - _boot_time, 3),
                "provider": kernel.ai_adapter.provider,
                "model": kernel.ai_adapter.model,
                "local_predictor": _get_local_predictor().version,
                "projects": {
                    "total": len(projects),
                    "running": len(running),
                    "pending": len(pending),
                    "completed": len(done),
                    "failed": len(failed),
                },
                "agents_registered": len(kernel.registry.list_names()),
                "tools_registered": len(kernel.tool_manager.list_tools()),
            }
        )
    except Exception as exc:
        logger.error("Status check error: %s", exc, exc_info=True)
        return APIResponse(
            success=False,
            data={"status": "degraded"},
            error=str(exc),
        )


@app.post("/task", tags=["Tasks"], response_model=APIResponse, status_code=201,
          summary="Create and run one task",
          description="Execute one task on a named agent or directly on the AI adapter. "
                      "Supports background mode for async execution.")
async def create_task(req: TaskRequest, background_tasks: BackgroundTasks):
    """Submit a task for execution by a named agent or the kernel AI adapter.

    - If *agent* is provided, the named agent's ``execute_task`` method is called.
    - Otherwise, the prompt is sent directly to the AI adapter (like ``/predict``).
    - Set *background=true* to get an immediate task-ID response and run async.
    """
    task_id = str(uuid.uuid4())

    def _run_task() -> dict[str, Any]:
        kernel = _get_kernel()
        if req.agent:
            agent = kernel.registry.get(req.agent)
            if agent is None:
                raise ValueError(f"Agent '{req.agent}' not found.")
            if hasattr(agent, "attach_runtime"):
                agent.attach_runtime(
                    ai_adapter=kernel.ai_adapter,
                    workflow_engine=kernel.workflow_engine,
                    tool_manager=kernel.tool_manager,
                )
            if hasattr(agent, "attach_memory"):
                agent.attach_memory(kernel.memory)
            result = agent.execute_task(req.description)
        else:
            messages = [{"role": "user", "content": req.description}]
            result = kernel.ai_adapter.chat(messages)

        return {
            "task_id": task_id,
            "title": req.title,
            "agent": req.agent,
            "result": str(result),
            "status": "completed",
        }

    if req.background:
        # Store placeholder and run in background
        with _projects_lock:
            _projects[task_id] = {
                "id": task_id,
                "name": req.title,
                "goal": req.description,
                "status": "pending",
                "started_at": time.time(),
            }

        def _bg():
            try:
                payload = _run_task()
                with _projects_lock:
                    _projects[task_id].update(payload)
            except Exception as exc:
                logger.error("Background task %s failed: %s", task_id, exc, exc_info=True)
                with _projects_lock:
                    _projects[task_id]["status"] = "failed"
                    _projects[task_id]["error"] = str(exc)

        background_tasks.add_task(_bg)
        return APIResponse(
            data={"task_id": task_id, "status": "pending"},
            message="Task accepted. Poll /api/goals/{task_id} for updates.",
        )

    try:
        result = _run_task()
        return APIResponse(data=result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def start_server() -> None:
    """Canonical FastAPI startup entrypoint used by main.py."""
    import uvicorn

    uvicorn.run(
        "api.server:app",
        host=os.getenv("AETHER_HOST", "0.0.0.0"),
        port=int(os.getenv("AETHER_PORT", "8000")),
        reload=os.getenv("AETHER_RELOAD", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    start_server()
