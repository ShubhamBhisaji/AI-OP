"""
FastAPI server wrapper for agent: __AGENT_NAME__
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import deque
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from core.env_loader import load_env as _lenv

_lenv(os.path.join(_ROOT, ".env"))

from core.aether_kernel import AetherKernel

logging.basicConfig(level=logging.INFO, format="[server] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_provider = os.environ.get("AETHER_DEFAULT_PROVIDER", "github")
_model = os.environ.get("AETHER_DEFAULT_MODEL") or None
kernel = AetherKernel(ai_provider=_provider, model=_model)

with open(os.path.join(_ROOT, "agent_profile.json"), encoding="utf-8") as _f:
    _profile = json.load(_f)

_agent_name = _profile["name"]
_agent = kernel.factory.create(
    name=_agent_name,
    role=_profile["role"],
    tools=_profile.get("tools", []),
    skills=_profile.get("skills", []),
    permission_level=_profile.get("permission_level", 1),
)
_agent.profile["instructions"] = _profile.get("instructions", "")
kernel.registry.register(_agent)

_history: deque[dict] = deque(maxlen=50)

app = FastAPI(title="__AGENT_NAME__", description="__AGENT_ROLE__", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TaskRequest(BaseModel):
    task: str


@app.get("/health")
def health():
    return {"status": "ok", "agent": _agent_name}


@app.get("/agent")
def agent_info():
    return {
        "name": _agent_name,
        "role": _profile["role"],
        "skills": _profile.get("skills", []),
        "tools": _profile.get("tools", []),
    }


@app.post("/run")
def run_task(body: TaskRequest):
    if not body.task.strip():
        raise HTTPException(status_code=400, detail="task must not be empty")
    logger.info("Task received: %s", body.task[:120])
    result = kernel.run_agent(_agent_name, body.task)
    _history.appendleft({"task": body.task, "result": result, "ts": datetime.utcnow().isoformat()})
    return {"result": result}


@app.get("/history")
def history():
    return list(_history)


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    with open(os.path.join(_ROOT, "index.html"), "r", encoding="utf-8") as hf:
        return hf.read()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
