"""AgentRunner — Lightweight customer-side runtime for exported AetheerAI agents.

This is the entry point that runs on the customer's server/machine after they
receive an exported agent package from ExporterService.

It loads the agent profile, initializes minimal infrastructure (AI adapter,
memory, tools), and provides both a CLI task interface and an optional
HTTP server for remote task submission.

Usage
-----
    runner = AgentRunner("./exported_agent")
    runner.start()
    result = runner.handle_task("Generate a weekly sales report")
    runner.run_server(port=8080)  # optional HTTP API
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AgentRunner:
    """
    Load and run an exported AetheerAI agent package.

    The export directory should contain at minimum:
        agent_profile.json  — agent configuration (from ExporterService)
    """

    def __init__(self, export_dir: str | Path) -> None:
        self._export_dir = Path(export_dir).resolve()
        self._profile: dict[str, Any] = {}
        self._agent: Any = None
        self._ai_adapter: Any = None
        self._memory: Any = None
        self._started = False

    @property
    def name(self) -> str:
        return self._profile.get("name", "unknown")

    @property
    def role(self) -> str:
        return self._profile.get("role", "unknown")

    def start(self) -> dict[str, Any]:
        """Initialize the agent from the export bundle."""
        profile_path = self._export_dir / "agent_profile.json"
        if not profile_path.exists():
            raise FileNotFoundError(f"No agent_profile.json found in {self._export_dir}")

        self._profile = json.loads(profile_path.read_text(encoding="utf-8"))
        logger.info("AgentRunner: loading agent '%s' (%s)", self.name, self.role)

        # Add export dir to Python path for imports
        export_str = str(self._export_dir)
        if export_str not in sys.path:
            sys.path.insert(0, export_str)

        # Initialize AI adapter from environment
        self._ai_adapter = self._init_ai_adapter()

        # Initialize memory
        self._memory = self._init_memory()

        # Create the agent instance
        from agents.base_agent import BaseAgent
        self._agent = BaseAgent(
            name=self._profile["name"],
            role=self._profile["role"],
            tools=self._profile.get("tools", []),
            skills=self._profile.get("skills", []),
            objectives=self._profile.get("objectives", []),
            permissions=self._profile.get("permissions", []),
            permission_level=self._profile.get("permission_level", 1),
            ai_adapter=self._ai_adapter,
            memory_manager=self._memory,
        )
        self._agent.profile.update(self._profile)
        self._started = True

        logger.info("AgentRunner: agent '%s' ready.", self.name)
        return {
            "status": "started",
            "name": self.name,
            "role": self.role,
            "tools": self._profile.get("tools", []),
            "skills": self._profile.get("skills", []),
        }

    def handle_task(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Submit a task to the agent and return the result."""
        if not self._started or self._agent is None:
            raise RuntimeError("Agent not started. Call start() first.")

        logger.info("AgentRunner: handling task for '%s': %s", self.name, task[:100])
        return self._agent.execute_task(task, context=context)

    def run_server(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Start a minimal HTTP server for remote task submission."""
        try:
            from fastapi import FastAPI
            import uvicorn
        except ImportError:
            raise ImportError(
                "FastAPI and uvicorn are required for server mode. "
                "Install with: pip install fastapi uvicorn"
            )

        if not self._started:
            self.start()

        app = FastAPI(title=f"AetheerAI Agent: {self.name}")

        @app.get("/health")
        def health() -> dict[str, Any]:
            return {"status": "running", "agent": self.name, "role": self.role}

        @app.post("/task")
        def submit_task(body: dict[str, Any]) -> dict[str, Any]:
            task = body.get("task", "")
            context = body.get("context")
            if not task:
                return {"error": "Task is required."}
            try:
                result = self.handle_task(task, context=context)
                return {"status": "completed", "result": result}
            except Exception as exc:
                return {"status": "failed", "error": str(exc)}

        @app.get("/status")
        def status() -> dict[str, Any]:
            if self._agent is None:
                return {"status": "not started"}
            return self._agent.report_status()

        logger.info("AgentRunner: starting server on %s:%d", host, port)
        uvicorn.run(app, host=host, port=port, log_level="info")

    def stop(self) -> None:
        """Graceful shutdown."""
        self._started = False
        self._agent = None
        logger.info("AgentRunner: stopped.")

    # ── Infrastructure initialization ─────────────────────────────────────

    @staticmethod
    def _init_ai_adapter() -> Any:
        """Initialize AI adapter from environment variables."""
        try:
            from ai.ai_adapter import AIAdapter
            return AIAdapter()
        except Exception as exc:
            logger.warning("AgentRunner: AI adapter not available: %s", exc)
            return None

    def _init_memory(self) -> Any:
        """Initialize memory manager for the agent."""
        try:
            from memory.memory_manager import MemoryManager
            return MemoryManager()
        except Exception as exc:
            logger.warning("AgentRunner: memory manager not available: %s", exc)
            return None
