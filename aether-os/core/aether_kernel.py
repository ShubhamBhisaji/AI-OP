"""
AetherKernel — Central controller and orchestrator of the Aether AI OS.
Manages all subsystems: agents, workflows, tools, memory, and AI adapters.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent
from factory.agent_factory import AgentFactory
from registry.agent_registry import AgentRegistry
from skills.skill_engine import SkillEngine
from core.workflow_engine import WorkflowEngine
from tools.tool_manager import ToolManager
from ai.ai_adapter import AIAdapter
from memory.memory_manager import MemoryManager

logging.basicConfig(level=logging.INFO, format="[Aether] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class AetherKernel:
    """
    The central kernel of the Aether AI Operating System.
    All subsystems are initialized and coordinated here.
    """

    def __init__(self, ai_provider: str = "openai", model: str = "gpt-4o"):
        logger.info("Booting Aether OS kernel...")
        self.ai_adapter = AIAdapter(provider=ai_provider, model=model)
        self.memory = MemoryManager()
        self.registry = AgentRegistry()
        self.tool_manager = ToolManager()
        self.skill_engine = SkillEngine(registry=self.registry)
        self.factory = AgentFactory(
            registry=self.registry,
            tool_manager=self.tool_manager,
            ai_adapter=self.ai_adapter,
        )
        self.workflow_engine = WorkflowEngine(
            registry=self.registry,
            ai_adapter=self.ai_adapter,
            memory=self.memory,
        )
        logger.info("Aether OS kernel ready.")

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def create_agent(self, name: str, role: str, tools: list[str] | None = None) -> BaseAgent:
        """Create a new agent and register it."""
        agent = self.factory.create(name=name, role=role, tools=tools or [])
        logger.info("Agent '%s' created with role: %s", name, role)
        return agent

    def upgrade_agent(self, name: str) -> None:
        """Upgrade the skills and prompt of an existing agent."""
        self.skill_engine.upgrade(name)
        logger.info("Agent '%s' upgraded.", name)

    def run_agent(self, name: str, task: str) -> Any:
        """Run a named agent on a given task."""
        agent = self.registry.get(name)
        if agent is None:
            raise KeyError(f"Agent '{name}' not found in registry.")
        logger.info("Running agent '%s' on task: %s", name, task)
        result = self.workflow_engine.execute(agent=agent, task=task)
        self.memory.save(key=f"{name}:last_result", value=result)
        return result

    def list_agents(self) -> list[str]:
        """Return a list of all registered agent names."""
        return self.registry.list_names()

    # ------------------------------------------------------------------
    # Direct AI chat
    # ------------------------------------------------------------------

    def chat(self, message: str, history: list[dict] | None = None) -> str:
        """Send a message directly to the underlying AI model."""
        messages = history or []
        messages.append({"role": "user", "content": message})
        response = self.ai_adapter.chat(messages=messages)
        self.memory.append(key="chat_history", value={"role": "assistant", "content": response})
        return response

    # ------------------------------------------------------------------
    # Application builder shortcut
    # ------------------------------------------------------------------

    def build_application(self, app_name: str) -> str:
        """High-level command: spin up a team of agents to build an application."""
        logger.info("Building application: %s", app_name)
        task = f"Plan, scaffold, and implement a complete {app_name} application."
        coder = self.create_agent("coder", role="Coding Agent", tools=["file_writer"])
        researcher = self.create_agent("researcher", role="Research Agent", tools=["web_search"])
        plan = self.workflow_engine.run_pipeline(
            agents=[researcher, coder],
            task=task,
        )
        return plan
