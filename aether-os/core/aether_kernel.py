"""
AetherKernel — Central controller and orchestrator of AetherAi-A Master AI.
Manages all subsystems: agents, workflows, tools, memory, and AI adapters.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import BaseAgent
from factory.agent_factory import AgentFactory
from registry.agent_registry import AgentRegistry
from skills.skill_engine import SkillEngine
from core.workflow_engine import (
    WorkflowEngine,
    WorkflowCancelled,
    WorkflowCheckpoint,
    WorkflowFeedback,
    HITLAction,
)
from core.team_manager import TeamManager
from core.orchestrator import Orchestrator
from tools.tool_manager import ToolManager
from ai.ai_adapter import AIAdapter
from memory.memory_manager import MemoryManager
from utils.json_parser import extract_json, ParseError

logging.basicConfig(level=logging.INFO, format="[AetherAi] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class AetherKernel:
    """
    The central kernel of AetherAi-A Master AI.
    All subsystems are initialized and coordinated here.
    """

    def __init__(self, ai_provider: str = "openai", model: str = "gpt-4o"):
        logger.info("Booting AetherAi-A Master AI kernel...")
        self.ai_adapter = AIAdapter(provider=ai_provider, model=model)
        self.memory = MemoryManager()
        self.registry = AgentRegistry()
        self.tool_manager = ToolManager()
        self.skill_engine = SkillEngine(registry=self.registry, ai_adapter=None)  # ai_adapter set below
        self.factory = AgentFactory(
            registry=self.registry,
            tool_manager=self.tool_manager,
            ai_adapter=self.ai_adapter,
        )
        self.workflow_engine = WorkflowEngine(
            registry=self.registry,
            ai_adapter=self.ai_adapter,
            memory=self.memory,
            tool_manager=self.tool_manager,
        )
        self.team_manager = TeamManager(registry=self.registry)
        self.orchestrator = Orchestrator(
            registry=self.registry,
            ai_adapter=self.ai_adapter,
            workflow_engine=self.workflow_engine,
        )
        # Wire AI adapter into skill engine after creation
        self.skill_engine.ai_adapter = self.ai_adapter
        logger.info("AetherAi-A Master AI kernel ready.")

    # ------------------------------------------------------------------
    # HITL control (Fix 8)
    # ------------------------------------------------------------------

    def set_hitl(
        self,
        enabled: bool = True,
        callback=None,
    ) -> None:
        """
        Enable or disable the Human-in-the-Loop checkpoint gate.

        Parameters
        ----------
        enabled  : True to activate HITL; False to disable (default auto-mode).
        callback : Optional callable ``(WorkflowCheckpoint) -> WorkflowFeedback``.
                   When None the default interactive console prompt is used.
                   Pass a custom function to integrate with a GUI / REST API.

        Example — silent auto-approve (for unit tests)::

            kernel.set_hitl(
                enabled=True,
                callback=lambda cp: WorkflowFeedback(action=HITLAction.APPROVE),
            )
        """
        from core.workflow_engine import _default_hitl_callback
        self.workflow_engine.hitl_mode = enabled
        self.workflow_engine.feedback_callback = callback or _default_hitl_callback
        state = "ENABLED" if enabled else "DISABLED"
        logger.info("HITL mode %s (callback=%s).", state, callback.__name__ if callback else "console")

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def create_agent(self, name: str, role: str, tools: list[str] | None = None, permission_level: int = 1) -> BaseAgent:
        """Create a new agent and register it (fast path, no AI research)."""
        agent = self.factory.create(name=name, role=role, tools=tools or [], permission_level=permission_level)
        logger.info("Agent '%s' created with role: %s, permission_level: %d", name, role, permission_level)
        return agent

    def build_agent(
        self,
        name: str,
        role: str,
        context: str = "",
        progress=None,
        permission_level: int = 1,
    ) -> BaseAgent:
        """
        Smart agent builder — three-step AI research pipeline:
          1. Research the agent's core function and responsibilities
          2. Gather skill & tool requirements
          3. Write a detailed system prompt / instructions

        Returns the fully configured BaseAgent (registered in the registry).
        """
        from factory.agent_factory import AGENT_PRESETS

        def _prog(step: int, total: int, msg: str) -> None:
            if progress:
                progress(step, total, msg)

        # ── Step 1: Research core function ───────────────────────────
        _prog(1, 4, f"Researching core function for '{name}'...")
        research_prompt = (
            f"You are an expert AI system designer.\n"
            f"Research the core function and responsibilities of the following AI agent:\n\n"
            f"Agent Name : {name}\n"
            f"Agent Role : {role}\n"
            + (f"Context    : {context}\n" if context else "")
            + f"\nProvide a thorough analysis covering:\n"
            f"1. Primary functions — what this agent mainly does day-to-day\n"
            f"2. Key responsibilities and deliverables it produces\n"
            f"3. Important behavioural guidelines and constraints\n"
            f"4. How it interacts with other agents or systems\n"
            f"5. What makes this agent uniquely effective at its role\n\n"
            f"Be specific and practical — focus on real-world usage."
        )
        research = self.ai_adapter.chat([{"role": "user", "content": research_prompt}])

        # ── Step 2: Gather skill & tool requirements ──────────────────
        _prog(2, 4, f"Gathering skill requirements for '{name}'...")
        skills_prompt = (
            f"Based on this role analysis, determine the exact skills and tools needed.\n\n"
            f"Agent : {name} ({role})\n"
            f"Analysis:\n{research}\n\n"
            f"Output ONLY valid JSON — no markdown, no extra text:\n"
            f'{{"skills": ["skill1", "skill2", "..."], "tools": ["tool1", "..."]}}\n\n'
            f"Available tools (ONLY choose from this list):\n"
            f"  web_search, file_writer, file_reader, code_runner, calculator,\n"
            f"  json_tool, csv_tool, text_analyzer, regex_tool, hash_tool,\n"
            f"  datetime_tool, note_taker, template_tool, markdown_tool,\n"
            f"  url_tool, security_tool, code_search, linter_tool\n\n"
            f"Rules:\n"
            f"- Include 10-20 highly relevant skills (specific, not vague)\n"
            f"- Only include tools this agent genuinely needs"
        )
        skills_raw = self.ai_adapter.chat([{"role": "user", "content": skills_prompt}])
        # Fix 3 — use robust structured JSON parser instead of fragile regex
        skills_data: dict = extract_json(skills_raw, safe=True, default={})

        skills: list[str] = [str(s) for s in skills_data.get("skills", [])]
        tools:  list[str] = [str(t) for t in skills_data.get("tools",  [])]

        # Fallback to preset if AI returned nothing useful
        preset_key = name.lower().replace(" ", "_")
        if not skills:
            skills = list(AGENT_PRESETS.get(preset_key, {}).get("skills", []))
        if not tools:
            tools  = list(AGENT_PRESETS.get(preset_key, {}).get("tools",  []))

        # ── Step 3: Write instructions (system prompt) ───────────────
        _prog(3, 4, f"Writing instructions for '{name}'...")
        instr_prompt = (
            f"Write a detailed system prompt for this AI agent.\n\n"
            f"Agent : {name}\n"
            f"Role  : {role}\n"
            f"Skills: {', '.join(skills[:12])}\n"
            + (f"Context: {context}\n" if context else "")
            + f"Core function analysis:\n{research}\n\n"
            f"Write a comprehensive system prompt (4-6 sentences) that:\n"
            f"1. Clearly defines the agent's identity and role\n"
            f"2. States its primary objectives and responsibilities\n"
            f"3. Outlines key behavioural guidelines and constraints\n"
            f"4. Describes how it should approach and complete tasks\n"
            f"5. Sets quality standards and output expectations\n\n"
            f"Output ONLY the system prompt text — no headers, no commentary."
        )
        instructions = self.ai_adapter.chat([{"role": "user", "content": instr_prompt}])

        # ── Step 4: Evaluation — test-driven agent validation (Fix 5) ─
        _prog(3, 4, f"Evaluating '{name}' with a mock task...")
        MAX_EVAL_RETRIES = 2
        for eval_attempt in range(MAX_EVAL_RETRIES + 1):
            # 4a. Build a temporary agent (not yet persisted)
            _tmp_agent = self.factory.create(
                name=name, role=role, tools=tools, skills=skills,
                permission_level=permission_level,
            )
            _tmp_agent.profile["instructions"] = instructions

            # 4b. Generate a representative mock task for this role
            mock_task_prompt = (
                f"Generate a single, realistic test task for the following AI agent.\n\n"
                f"Agent: {name}\nRole: {role}\n"
                f"Skills: {', '.join(skills[:8])}\n\n"
                f"The task should be self-contained, achievable without external tools, "
                f"and representative of the agent's day-to-day work.\n"
                f"Output ONLY the task text — no intro, no explanation."
            )
            mock_task = self.ai_adapter.chat([{"role": "user", "content": mock_task_prompt}])

            # 4c. Run the agent on the mock task (no side-effects — sandbox result)
            trial_result = self.workflow_engine.execute(agent=_tmp_agent, task=mock_task)

            # 4d. Ask an Evaluator AI to score and optionally rewrite the instructions
            eval_prompt = (
                f"You are an expert AI system evaluator.\n\n"
                f"AGENT: {name} ({role})\n"
                f"SYSTEM PROMPT:\n{instructions}\n\n"
                f"MOCK TASK:\n{mock_task}\n\n"
                f"AGENT RESPONSE:\n{trial_result}\n\n"
                f"Evaluate this response strictly. Output ONLY valid JSON:\n"
                f'{{"passed": true/false, "score": 0-10, "issues": ["..."], '
                f'"improved_instructions": "rewritten prompt or empty string if passed"}}\n\n'
                f"passed=true if score >= 7 AND the response is relevant, coherent, and "
                f"addresses the task without hallucination or generic filler.\n"
                f"If passed=false, write a complete improved_instructions string."
            )
            eval_raw = self.ai_adapter.chat([{"role": "user", "content": eval_prompt}])
            eval_data: dict = extract_json(eval_raw, safe=True, default={"passed": True})

            passed = bool(eval_data.get("passed", True))
            score  = eval_data.get("score", 7)
            issues = eval_data.get("issues", [])
            improved = (eval_data.get("improved_instructions") or "").strip()

            logger.info(
                "build_agent eval [attempt %d/%d]: agent='%s' score=%s passed=%s issues=%s",
                eval_attempt + 1, MAX_EVAL_RETRIES + 1, name, score, passed, issues,
            )

            if passed or not improved:
                break  # Accept the current instructions

            # Rewrite and retry
            logger.info("build_agent: eval failed — rewriting instructions and retrying.")
            instructions = improved

        _prog(4, 4, f"Agent '{name}' validated (score={score}).")

        # ── Build and register the agent ─────────────────────────────
        agent = self.factory.create(name=name, role=role, tools=tools, skills=skills, permission_level=permission_level)
        agent.profile["instructions"]     = instructions
        agent.profile["research_summary"] = research[:600]
        agent.profile["eval_score"]       = score
        self.registry.register(agent)   # persist updated profile

        logger.info(
            "build_agent: '%s' — %d skills, %d tools, eval_score=%s.",
            name, len(skills), len(tools), score,
        )
        return agent

    def upgrade_agent(self, name: str) -> None:
        """Upgrade the skills and prompt of an existing agent."""
        self.skill_engine.upgrade(name)
        logger.info("Agent '%s' upgraded.", name)

    def run_agent(self, name: str, task: str) -> Any:
        """Run a named agent on a given task and save token usage to memory."""
        agent = self.registry.get(name)
        if agent is None:
            raise KeyError(f"Agent '{name}' not found in registry.")
        logger.info(
            "Running agent '%s' (permission=%s) on task: %s",
            name, agent.permission_level, task,
        )
        result = self.workflow_engine.execute(agent=agent, task=task)
        self.memory.save(key=f"{name}:last_result", value=result)
        # Persist token usage so it can be queried later
        usage = self.ai_adapter.usage
        if usage.get("total_tokens"):
            self.memory.save(key=f"{name}:last_token_usage", value=usage)
            self.memory.save(
                key="session:total_tokens",
                value=self.ai_adapter.total_tokens,
            )
        return result

    async def run_agent_async(self, name: str, task: str) -> Any:
        """Non-blocking async version of run_agent."""
        agent = self.registry.get(name)
        if agent is None:
            raise KeyError(f"Agent '{name}' not found in registry.")
        logger.info(
            "Running agent '%s' async (permission=%s) on task: %s",
            name, agent.permission_level, task,
        )
        result = await self.workflow_engine.execute_async(agent=agent, task=task)
        self.memory.save(key=f"{name}:last_result", value=result)
        usage = self.ai_adapter.usage
        if usage.get("total_tokens"):
            self.memory.save(key=f"{name}:last_token_usage", value=usage)
        return result

    async def run_pipeline_async(self, agent_names: list[str], task: str) -> str:
        """Async sequential pipeline — each agent's output feeds the next."""
        agents = [self.registry.get(n) for n in agent_names]
        missing = [n for n, a in zip(agent_names, agents) if a is None]
        if missing:
            raise KeyError(f"Agents not found: {missing}")
        return await self.workflow_engine.run_pipeline_async(agents=agents, task=task)

    async def broadcast_async(self, agent_names: list[str], task: str) -> list[dict]:
        """Run all agents concurrently on the same task."""
        import asyncio
        agents = [self.registry.get(n) for n in agent_names]
        missing = [n for n, a in zip(agent_names, agents) if a is None]
        if missing:
            raise KeyError(f"Agents not found: {missing}")
        raw = await self.workflow_engine.run_broadcast_async(agents=agents, task=task)
        return [
            {"agent": name, "result": res}
            for name, res in zip(agent_names, raw)
        ]

    def run_tool(self, agent_name: str, tool_name: str, *args, **kwargs) -> Any:
        """
        Explicit RBAC-enforced tool call from outside the workflow.
        Useful for CLI / API endpoints that want to invoke a tool on
        behalf of a registered agent.
        """
        agent = self.registry.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent '{agent_name}' not found.")
        return self.workflow_engine.call_tool(agent, tool_name, *args, **kwargs)

    def list_agents(self) -> list[str]:
        """Return a list of all registered agent names."""
        return self.registry.list_names()

    def delete_agent(self, name: str) -> bool:
        """Remove an agent from the registry permanently."""
        removed = self.registry.remove(name)
        if removed:
            logger.info("Agent '%s' deleted.", name)
        return removed

    def delete_all_agents(self) -> list[str]:
        """Remove every agent from the registry. Returns list of deleted names."""
        names = self.registry.list_names()
        for name in names:
            self.registry.remove(name)
        logger.info("All agents deleted: %s", names)
        return names

    # ------------------------------------------------------------------
    # Team management  (delegates to TeamManager)
    # ------------------------------------------------------------------

    def create_team(self, name: str, agent_names: list[str]) -> dict:
        """Create a named team of agents."""
        return self.team_manager.create_team(name, agent_names)

    def delete_team(self, name: str) -> bool:
        return self.team_manager.delete_team(name)

    def list_teams(self) -> list[str]:
        return self.team_manager.list_teams()

    # ------------------------------------------------------------------
    # Multi-agent orchestration  (delegates to Orchestrator)
    # ------------------------------------------------------------------

    def run_pipeline(self, agent_names: list[str], task: str) -> list[dict]:
        """Run agents sequentially — each output feeds the next."""
        return self.orchestrator.run_pipeline(agent_names, task)

    def broadcast(self, agent_names: list[str], task: str) -> list[dict]:
        """Send the same task to every agent independently."""
        return self.orchestrator.broadcast(agent_names, task)

    def vote(self, agent_names: list[str], question: str) -> dict:
        """All agents answer; AI synthesizes consensus."""
        return self.orchestrator.vote(agent_names, question)

    def best_of(self, agent_names: list[str], task: str) -> dict:
        """All agents attempt; AI picks the best response."""
        return self.orchestrator.best_of(agent_names, task)

    def agent_debate(
        self, agent1: str, agent2: str, topic: str, rounds: int = 2
    ) -> dict:
        """Two agents debate a topic for N rounds."""
        return self.orchestrator.debate(agent1, agent2, topic, rounds)

    def orchestrate(self, task: str) -> dict:
        """AI auto-selects the best agents + mode for the task."""
        return self.orchestrator.orchestrate(task)

    # ------------------------------------------------------------------
    # AI System builder  (design + create a multi-agent system from text)
    # ------------------------------------------------------------------

    def _systems_dir(self):
        from pathlib import Path
        d = Path(__file__).parent.parent / "systems"
        d.mkdir(exist_ok=True)
        return d

    def create_ai_system(self, name: str, description: str,
                         progress=None) -> dict:
        """
        Smart AI System builder — full research pipeline:
          1. Research the system's core function and architecture
          2. Design the agent roster (names, roles, responsibilities)
          3. For EACH sub-agent: research core function → gather skills → write instructions
          4. Compile into a team + manifest; all sub-agents are marked non-exportable

        progress(step, total, message) — optional progress callback.
        Returns dict with 'system_name', 'agents', 'manifest_path', 'error'.
        """
        import json
        from datetime import datetime

        def _prog(step: int, total: int, msg: str) -> None:
            if progress:
                progress(step, total, msg)

        # ── Step 1: Research the system's core function ───────────────
        _prog(1, 5, "Researching system architecture & core function...")
        sys_research_prompt = (
            f"You are an expert AI System Architect.\n"
            f"Research and analyse the following AI system requirement:\n\n"
            f"System Name : {name}\n"
            f"Description : {description}\n\n"
            f"Provide a thorough technical analysis covering:\n"
            f"1. The system's primary purpose and what it must accomplish\n"
            f"2. Key functional domains this system must cover end-to-end\n"
            f"3. What types of specialised sub-agents would make it most effective\n"
            f"4. How data and tasks should flow between agents\n"
            f"5. Critical success factors — what must the system get right\n\n"
            f"Be specific and technical. This analysis will drive the design of every agent."
        )
        system_research = self.ai_adapter.chat(
            messages=[{"role": "user", "content": sys_research_prompt}]
        )

        # ── Step 2: Design the agent roster ──────────────────────────
        _prog(2, 5, "Designing agent roster...")
        roster_prompt = (
            f"Based on the system analysis below, design the agent roster.\n\n"
            f"System      : {name}\n"
            f"Description : {description}\n"
            f"Analysis:\n{system_research}\n\n"
            f"Output ONLY valid JSON — no markdown fences, no extra text:\n"
            f"{{\n"
            f'  "system_name": "{name}",\n'
            f'  "description": "one-sentence description",\n'
            f'  "purpose": "what this system accomplishes",\n'
            f'  "routing_rules": "how tasks are routed between agents",\n'
            f'  "agents": [\n'
            f'    {{\n'
            f'      "name": "AgentName",\n'
            f'      "role": "specific role title",\n'
            f'      "responsibilities": "2 sentences — what this agent owns",\n'
            f'      "handles": ["task type 1", "task type 2"]\n'
            f'    }}\n'
            f'  ]\n'
            f'}}\n\n'
            f"REQUIREMENTS:\n"
            f"- Create 5-10 agents (no fewer than 5)\n"
            f"- Each agent must have a DISTINCT specialised role — no overlap\n"
            f"- Agent names: PascalCase (e.g. ResearchAgent, WriterAgent)\n"
            f"- Together they must cover ALL aspects of: {description}\n"
        )
        raw = self.ai_adapter.chat(messages=[{"role": "user", "content": roster_prompt}])
        # Fix 3 — robust JSON parsing instead of regex
        try:
            blueprint = extract_json(raw)
        except ParseError as e:
            return {"error": f"AI did not return valid JSON for agent roster: {e}", "raw": raw}

        agent_defs = blueprint.get("agents", [])
        if len(agent_defs) < 3:
            return {"error": f"AI returned only {len(agent_defs)} agents — need 5-10. Try again."}

        # ── Steps 3+: Per-agent research → skills → instructions ──────
        # Total steps: 2 (system research + roster) + len*3 (per agent) + 2 (compile + save)
        per_agent_steps = len(agent_defs) * 3
        total_steps = 2 + per_agent_steps + 2
        step_counter = [2]   # mutable counter shared across iterations

        def _next(msg: str) -> None:
            step_counter[0] += 1
            _prog(step_counter[0], total_steps, msg)

        built_agents: list[dict] = []
        for adef in agent_defs:
            aname  = str(adef.get("name", "Agent")).strip()
            arole  = str(adef.get("role", aname)).strip()
            aresps = str(adef.get("responsibilities", ""))
            ahandles = adef.get("handles", [])

            # ── 3a: Research this agent's core function ───────────────
            _next(f"[{aname}] Researching core function...")
            agent_research_prompt = (
                f"Research the core function of this sub-agent within an AI system:\n\n"
                f"Agent  : {aname}\n"
                f"Role   : {arole}\n"
                f"System : {name}  ({description})\n"
                f"Responsibilities: {aresps}\n"
                f"Handles: {', '.join(ahandles)}\n\n"
                f"Analyse in detail:\n"
                f"1. What this agent's primary day-to-day functions are\n"
                f"2. Key outputs and deliverables it produces\n"
                f"3. Decision-making approach and behavioural guidelines\n"
                f"4. How it collaborates with the other agents in {name}\n"
                f"5. What expertise makes this agent uniquely effective\n\n"
                f"Be specific and focused on this agent's distinct role."
            )
            agent_research = self.ai_adapter.chat(
                messages=[{"role": "user", "content": agent_research_prompt}]
            )

            # ── 3b: Gather skill & tool requirements ──────────────────
            _next(f"[{aname}] Gathering skill requirements...")
            skills_prompt = (
                f"Based on this agent role analysis, determine the exact skills and tools.\n\n"
                f"Agent  : {aname} ({arole})\n"
                f"System : {name}\n"
                f"Analysis:\n{agent_research}\n\n"
                f"Output ONLY valid JSON — no markdown, no extra text:\n"
                f'{{"skills": ["skill1", "skill2"], "tools": ["tool1"]}}\n\n'
                f"Available tools (ONLY choose from this list):\n"
                f"  web_search, file_writer, file_reader, code_runner, calculator,\n"
                f"  json_tool, csv_tool, text_analyzer, regex_tool, hash_tool,\n"
                f"  datetime_tool, note_taker, template_tool, markdown_tool,\n"
                f"  url_tool, security_tool, code_search, linter_tool\n\n"
                f"- Include 10-20 relevant skills (specific, not vague)\n"
                f"- Only pick tools this agent genuinely needs"
            )
            skills_raw = self.ai_adapter.chat(
                messages=[{"role": "user", "content": skills_prompt}]
            )
            # Fix 3 — robust JSON parsing
            skills_data_a: dict = extract_json(skills_raw, safe=True, default={})
            askills = [str(s) for s in skills_data_a.get("skills", [])]
            atools  = [str(t) for t in skills_data_a.get("tools",  [])]

            # ── 3c: Write instructions (system prompt) ────────────────
            _next(f"[{aname}] Writing instructions...")
            instr_prompt = (
                f"Write a detailed system prompt for this AI sub-agent.\n\n"
                f"Agent  : {aname}\n"
                f"Role   : {arole}\n"
                f"System : {name}  —  {description}\n"
                f"Skills : {', '.join(askills[:12])}\n"
                f"Core function analysis:\n{agent_research}\n\n"
                f"Write a comprehensive system prompt (4-6 sentences) that:\n"
                f"1. Defines the agent's identity and role within the {name} system\n"
                f"2. States its primary objectives and unique responsibilities\n"
                f"3. Outlines key behavioural guidelines and constraints\n"
                f"4. Describes how it collaborates with other agents in the system\n"
                f"5. Sets quality standards and output expectations\n\n"
                f"Output ONLY the system prompt text — no headers, no commentary."
            )
            ainstr = self.ai_adapter.chat(
                messages=[{"role": "user", "content": instr_prompt}]
            )

            built_agents.append({
                "name":             aname,
                "role":             arole,
                "skills":           askills,
                "tools":            atools,
                "instructions":     ainstr,
                "handles":          ahandles,
                "research_summary": agent_research[:500],
            })

        # ── Compile: create agents, form team ─────────────────────────
        _next(f"Compiling {len(built_agents)} sub-agents...")
        created_names: list[str] = []
        for bdef in built_agents:
            aname = bdef["name"]
            agent = self.factory.create(
                name=aname, role=bdef["role"],
                tools=bdef["tools"], skills=bdef["skills"],
            )
            agent.profile["instructions"]     = bdef["instructions"]
            agent.profile["handles"]          = bdef["handles"]
            agent.profile["system"]           = name
            agent.profile["is_subagent"]      = True
            agent.profile["is_exportable"]    = False
            agent.profile["research_summary"] = bdef.get("research_summary", "")
            self.registry.register(agent)
            created_names.append(aname)
            logger.info("System '%s': built sub-agent '%s' (%s)", name, aname, bdef["role"])

        team_name = f"{name}_team"
        try:
            self.team_manager.create_team(team_name, created_names)
        except Exception:
            pass   # team may already exist on retry

        # ── Save manifest ─────────────────────────────────────────────
        _next("Saving system manifest...")
        manifest = {
            "system_name":     name,
            "description":     blueprint.get("description", description),
            "purpose":         blueprint.get("purpose", ""),
            "routing_rules":   blueprint.get("routing_rules", ""),
            "system_research": system_research[:800],
            "agents": [
                {
                    "name":          a["name"],
                    "role":          a["role"],
                    "skills":        a["skills"],
                    "tools":         a["tools"],
                    "instructions":  a["instructions"],
                    "handles":       a["handles"],
                    "is_subagent":   True,
                    "is_exportable": False,
                }
                for a in built_agents
            ],
            "team":       team_name,
            "created_at": datetime.utcnow().isoformat(),
        }
        manifest_path = self._systems_dir() / f"{name}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "system_name":   name,
            "agents":        created_names,
            "team":          team_name,
            "manifest_path": str(manifest_path),
            "purpose":       manifest["purpose"],
            "error":         None,
        }

    def ai_system_task(self, system_name: str, task: str) -> dict:
        """
        Run a task through an AI System.  The AI selects the best agent(s)
        from the system manifest, then executes using each agent's instructions
        as its system prompt.
        Returns dict with 'output', 'agents_used', 'error'.
        """
        import json

        # Load manifest
        manifest_path = self._systems_dir() / f"{system_name}.json"
        if not manifest_path.exists():
            return {"error": f"AI System '{system_name}' not found. "
                             f"Run create_ai_system first."}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        agents_info = manifest.get("agents", [])

        # ── Step 1: AI routes the task ────────────────────────────────
        agent_summaries = "\n".join(
            f"- {a['name']} ({a['role']}): handles {', '.join(a.get('handles', [a['role']]))}"
            for a in agents_info
        )
        routing_prompt = (
            f"You are the task router for the AI System: {system_name}\n"
            f"Purpose: {manifest.get('purpose', '')}\n"
            f"Routing rules: {manifest.get('routing_rules', '')}\n\n"
            f"Available agents:\n{agent_summaries}\n\n"
            f"Task: {task}\n\n"
            f"Select the best agent(s) to handle this task.\n"
            f"Output ONLY valid JSON, no extra text:\n"
            f'{{"agents": ["AgentName1"], "strategy": "single|pipeline|parallel", '
            f'"reason": "brief reason"}}'
        )
        routing_raw = self.ai_adapter.chat(
            messages=[{"role": "user", "content": routing_prompt}]
        )
        # Fix 3 — robust JSON parsing
        routing = extract_json(routing_raw, safe=True,
                               default={"agents": [agents_info[0]["name"]] if agents_info else [], "strategy": "single"})

        selected_names = routing.get("agents", [])
        strategy = routing.get("strategy", "single")

        # ── Step 2: Execute task with selected agent(s) ───────────────
        outputs = []
        previous_output = ""
        for aname in selected_names:
            # Find agent's instructions
            adef = next((a for a in agents_info if a["name"] == aname), None)
            if adef is None:
                # fallback: try registry agent
                adef = {"name": aname, "instructions": "", "role": aname}

            instructions = adef.get("instructions", "")
            if not instructions:
                instructions = f"You are {adef.get('role', aname)}. Complete the task thoroughly."

            # Build message chain
            msgs = [{"role": "system", "content": instructions}]
            if strategy == "pipeline" and previous_output:
                msgs.append({
                    "role": "user",
                    "content": (
                        f"Original task: {task}\n\n"
                        f"Previous agent output:\n{previous_output}\n\n"
                        f"Your job: continue/refine the above for your role."
                    )
                })
            else:
                msgs.append({"role": "user", "content": task})

            result = self.ai_adapter.chat(messages=msgs)
            outputs.append({"agent": aname, "role": adef.get("role", ""), "output": result})
            previous_output = result

        # ── Step 3: If multiple agents, synthesise final output ───────
        if len(outputs) > 1 and strategy != "single":
            synthesis_parts = "\n\n".join(
                f"=== {o['agent']} ({o['role']}) ===\n{o['output']}"
                for o in outputs
            )
            synthesis_prompt = (
                f"You are the output coordinator for AI System: {system_name}\n"
                f"Task given to the system: {task}\n\n"
                f"The following agents have contributed:\n{synthesis_parts}\n\n"
                f"Synthesise a single, coherent, complete final response "
                f"that combines the best of all contributions."
            )
            final = self.ai_adapter.chat(
                messages=[{"role": "user", "content": synthesis_prompt}]
            )
        else:
            final = outputs[-1]["output"] if outputs else "No output produced."

        # Update task counts for each used agent
        for aname in selected_names:
            ag = self.registry.get(aname)
            if ag:
                ag.profile["performance"]["tasks_completed"] += 1
                self.registry.register(ag)

        return {
            "output": final,
            "agents_used": selected_names,
            "strategy": strategy,
            "routing_reason": routing.get("reason", ""),
            "detail": outputs,
            "error": None,
        }

    def list_ai_systems(self) -> list[dict]:
        """Return summary list of all saved AI Systems."""
        import json
        results = []
        for p in self._systems_dir().glob("*.json"):
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
                results.append({
                    "name":        m.get("system_name", p.stem),
                    "description": m.get("description", ""),
                    "agents":      [a["name"] for a in m.get("agents", [])],
                    "created_at":  m.get("created_at", ""),
                })
            except Exception:
                pass
        return results

    def get_ai_system_info(self, system_name: str) -> dict:
        """Return full manifest for an AI System."""
        import json
        p = self._systems_dir() / f"{system_name}.json"
        if not p.exists():
            return {"error": f"AI System '{system_name}' not found."}
        return json.loads(p.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Dynamic export requirements (Fix 4)
    # ------------------------------------------------------------------

    # Map from tool name → pip packages required at runtime.
    _TOOL_DEPENDENCIES: dict[str, list[str]] = {
        "web_search":      ["requests", "beautifulsoup4"],
        "http_client":     ["requests"],
        "browser_tool":    ["playwright"],
        "pdf_tool":        ["pypdf2"],
        "csv_tool":        ["pandas"],
        "analytics_tool":  ["pandas", "numpy"],
        "media_tool":      ["pillow"],
        "code_runner":     ["docker"],
        "url_tool":        ["requests"],
        "security_tool":   ["cryptography"],
        "linter_tool":     ["pylint"],
        "code_formatter":  ["black"],
    }

    # Base packages always needed for any exported agent
    _BASE_REQUIREMENTS: list[str] = [
        "openai", "anthropic", "ollama", "python-dotenv", "pyyaml", "chromadb",
    ]

    def _build_requirements(self, tool_names: list[str]) -> str:
        """
        Build a requirements.txt string for the given tool set.
        Merges base packages with per-tool deps (Fix 4).
        """
        pkgs: set[str] = set(self._BASE_REQUIREMENTS)
        for tool in tool_names:
            pkgs.update(self._TOOL_DEPENDENCIES.get(tool, []))
        return "\n".join(sorted(pkgs)) + "\n"

    def export_agent(self, name: str) -> dict:
        """
        Export a self-contained runnable folder for the named agent under
        exports/<name>/.  Returns dict with 'output_dir', 'files', 'error'.
        Sub-agents belonging to an AI System are not exportable.
        """
        import json, shutil, textwrap
        from pathlib import Path

        agent = self.registry.get(name)
        if agent is None:
            return {"error": f"Agent '{name}' not found."}

        # Block export of internal sub-agents
        if agent.profile.get("is_subagent") or agent.profile.get("is_exportable") is False:
            system = agent.profile.get("system", "an AI System")
            return {
                "error": (
                    f"Agent '{name}' is an internal sub-agent of '{system}' "
                    f"and cannot be exported individually. "
                    f"Use export_system to export the whole system."
                )
            }

        project_root = Path(__file__).parent.parent
        export_dir = project_root / "exports" / name
        export_dir.mkdir(parents=True, exist_ok=True)

        files_written: list[str] = []

        # ── 1. agent_profile.json ────────────────────────────────────────
        profile_path = export_dir / "agent_profile.json"
        profile_path.write_text(
            json.dumps(agent.to_dict(), indent=2), encoding="utf-8"
        )
        files_written.append("agent_profile.json")

        # ── 2. Copy core Python source files needed to run independently ─
        dirs_to_copy = ["agents", "ai", "core", "factory", "memory",
                        "registry", "skills", "tools", "cli"]
        for d in dirs_to_copy:
            src = project_root / d
            dst = export_dir / d
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                files_written.append(f"{d}/")

        # ── 3. .env — blank template (exported agent uses its OWN keys) ──
        #         Never copy source .env — user must configure their own AI
        env_src     = project_root / ".env"
        env_dst     = export_dir / ".env"
        env_example = export_dir / ".env.example"
        # Write a clean .env with empty values
        blank_env = (
            "# AetherAi-A Master AI Agent — AI Configuration\n"
            "# Run python run_agent.py to configure interactively (first launch)\n\n"
            "AETHER_DEFAULT_PROVIDER=\n"
            "AETHER_DEFAULT_MODEL=\n\n"
            "# Paste your key for the provider you choose:\n"
            "GITHUB_TOKEN=\n"
            "OPENAI_API_KEY=\n"
            "GEMINI_API_KEY=\n"
            "ANTHROPIC_API_KEY=\n"
        )
        env_dst.write_text(blank_env, encoding="utf-8")
        files_written.append(".env")
        # .env.example is identical to blank .env in this case
        env_example.write_text(blank_env, encoding="utf-8")
        files_written.append(".env.example")

        # ── 4. requirements.txt (dynamic — Fix 4) ────────────────────────
        req = export_dir / "requirements.txt"
        agent_tools = agent.profile.get("tools", [])
        req.write_text(self._build_requirements(agent_tools), encoding="utf-8")
        files_written.append("requirements.txt")

        # ── 5. run_agent.py — standalone entry point ─────────────────────
        run_py = export_dir / "run_agent.py"
        run_py.write_text(
            textwrap.dedent(f"""\
            \"\"\"
            Standalone runner for agent: {name}
            Role: {agent.role}
            Skills: {', '.join(agent.profile.get('skills', []))}

            Usage:
                python run_agent.py
                python run_agent.py --provider github --model gpt-4.1
            \"\"\"
            from __future__ import annotations
            import argparse, os, sys
            _ROOT = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, _ROOT)
            from core.env_loader import load_env as _lenv
            _lenv(os.path.join(_ROOT, ".env"))

            # ── First-time AI setup wizard ────────────────────────────────
            def _first_time_setup():
                \"\"\"Interactive wizard to configure AI provider on first launch.\"\"\"
                _env_path = os.path.join(_ROOT, ".env")
                print("\\n" + "="*60)
                print("  {name} — AetherAi-A Master AI Agent  |  First-time Setup")
                print("="*60)
                print("  Choose your AI provider:\\n")
                _providers = [
                    ("github",      "GitHub Models (free, needs GitHub account PAT)"),
                    ("openai",      "OpenAI  (GPT-4o / GPT-4.1)"),
                    ("gemini",      "Google Gemini"),
                    ("claude",      "Anthropic Claude"),
                    ("ollama",      "Ollama  (local, no API key needed)"),
                ]
                _models = {{
                    "github":  "gpt-4.1",
                    "openai":  "gpt-4o",
                    "gemini":  "gemini-1.5-flash",
                    "claude":  "claude-sonnet-4.6",
                    "ollama":  "qwen2.5-coder:7b",
                }}
                _key_env = {{
                    "github": "GITHUB_TOKEN",
                    "openai": "OPENAI_API_KEY",
                    "gemini": "GEMINI_API_KEY",
                    "claude": "ANTHROPIC_API_KEY",
                    "ollama": None,
                }}
                _ollama_models = [
                    ("qwen2.5-coder:7b",      "Qwen2.5-Coder 7B   — best code/agents  (8GB VRAM)"),
                    ("qwen2.5-coder:14b",     "Qwen2.5-Coder 14B  — higher quality   (12GB VRAM)"),
                    ("qwen2.5-coder:32b",     "Qwen2.5-Coder 32B  — top quality      (20GB+)"),
                    ("deepseek-coder-v2:16b", "DeepSeek-Coder-V2 16B — Python/agents (16GB VRAM)"),
                    ("qwen3:30b",             "Qwen3 30B  — 128k ctx, tool calling   (20GB+)"),
                    ("minimax-m2",            "MiniMax-M2 — 1M context, agentic      (high VRAM)"),
                    ("llama3.3:70b",          "Llama 3.3 70B — general, 128k ctx     (40GB+)"),
                    ("wizardlm2:7b",          "WizardLM2 7B — fast, low-resource     (8GB VRAM)"),
                    ("llama3.2:3b",           "Llama 3.2 3B  — ultra-fast, minimal   (4GB VRAM)"),
                ]
                for i, (p, desc) in enumerate(_providers, 1):
                    print(f"  {{i}}. {{desc}}")
                print()
                while True:
                    _choice = input("  Enter number (1-5): ").strip()
                    if _choice.isdigit() and 1 <= int(_choice) <= 5:
                        break
                    print("  Please enter a number between 1 and 5.")
                _provider = _providers[int(_choice)-1][0]
                _default_model = _models[_provider]
                _key_name = _key_env[_provider]

                _api_key = ""
                if _key_name:
                    print(f"\\n  Enter your {{_key_name}}:")
                    print(f"  (Get it from the provider's website)")
                    _api_key = input(f"  {{_key_name}}: ").strip()
                    if not _api_key:
                        print("  No key entered — you can edit .env manually later.")

                if _provider == "ollama":
                    print(f"\\n  Recommended Ollama models:")
                    for _oi, (_om, _od) in enumerate(_ollama_models, 1):
                        print(f"  {{_oi:2}}. {{_od}}")
                    _oc = input(f"\\n  Enter number or model name [{{_default_model}}]: ").strip()
                    if _oc.isdigit() and 1 <= int(_oc) <= len(_ollama_models):
                        _model = _ollama_models[int(_oc)-1][0]
                    elif _oc:
                        _model = _oc
                    else:
                        _model = _default_model
                else:
                    _model = input(f"\\n  Model name [{{_default_model}}]: ").strip() or _default_model

                # Write to .env
                _lines = [
                    "# AetherAi-A Master AI Agent — AI Configuration\\n",
                    f"AETHER_DEFAULT_PROVIDER={{_provider}}\\n",
                    f"AETHER_DEFAULT_MODEL={{_model}}\\n",
                ]
                if _key_name and _api_key:
                    _lines.append(f"{{_key_name}}={{_api_key}}\\n")
                with open(_env_path, "w", encoding="utf-8") as _f:
                    _f.writelines(_lines)
                # Reload env
                _lenv(_env_path)
                print(f"\\n  ✓ Configured: {{_provider}} / {{_model}}")
                print(f"  ✓ Saved to .env\\n")
                return _provider, _model

            def main():
                parser = argparse.ArgumentParser(
                    description="AetherAi-A Master AI Agent: {name} ({agent.role})"
                )
                parser.add_argument("--task",     default=None)
                parser.add_argument("--provider", default=None)
                parser.add_argument("--model",    default=None)
                args = parser.parse_args()

                provider = args.provider or os.environ.get("AETHER_DEFAULT_PROVIDER", "").strip()
                model    = args.model    or os.environ.get("AETHER_DEFAULT_MODEL", "").strip() or None

                # Run first-time setup if no provider configured yet
                if not provider:
                    provider, model = _first_time_setup()

                from cli.agent_window import run_agent_window
                run_agent_window("{name}", provider, model)

            if __name__ == "__main__":
                main()
            """),
            encoding="utf-8",
        )
        files_written.append("run_agent.py")

        # ── 6. launch_agent.bat ──────────────────────────────────────────
        bat = export_dir / "launch_agent.bat"
        bat.write_text(
            textwrap.dedent(f"""\
            @echo off
            title {name} — AetherAi-A Master AI Agent
            color 0B
            cd /d "%~dp0"

            :: Load provider from .env if present
            set PROVIDER=github
            set MODEL=
            if exist ".env" (
                for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
                    if /i "%%A"=="AETHER_DEFAULT_PROVIDER" set PROVIDER=%%B
                    if /i "%%A"=="AETHER_DEFAULT_MODEL"    set MODEL=%%B
                )
            )

            set PY=
            if exist "%LOCALAPPDATA%\\Programs\\Python\\Python310\\python.exe" (
                set PY="%LOCALAPPDATA%\\Programs\\Python\\Python310\\python.exe"
                goto :run
            )
            if exist "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe" (
                set PY="%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe"
                goto :run
            )
            if exist "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe" (
                set PY="%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe"
                goto :run
            )
            where python >nul 2>&1
            if %errorlevel%==0 ( set PY=python & goto :run )
            echo Python not found. Install from https://www.python.org/downloads/
            pause & exit /b 1

            :run
            if defined MODEL (
                %PY% run_agent.py --provider %PROVIDER% --model %MODEL% %*
            ) else (
                %PY% run_agent.py --provider %PROVIDER% %*
            )
            pause
            """),
            encoding="utf-8",
        )
        files_written.append("launch_agent.bat")

        # ── 7. README.md ─────────────────────────────────────────────────
        readme = export_dir / "README.md"
        readme.write_text(
            textwrap.dedent(f"""\
            # AetherAi-A Master AI Agent: {name}

            **Role:** {agent.role}
            **Skills:** {', '.join(agent.profile.get('skills', []))}
            **Tools:** {', '.join(agent.profile.get('tools', []))}
            **Version:** {agent.profile.get('version', '1.0.0')}

            ## Quick Start

            1. Double-click `launch_agent.bat`  (or run `python run_agent.py`)
            2. On first launch an interactive setup wizard will ask you to choose
               your AI provider and paste your API key — takes about 30 seconds.
            3. Your choice is saved to `.env` and used on every future launch.

            ## Supported AI Providers

            | Provider      | Key needed          | Free tier |
            |---------------|---------------------|-----------|
            | github        | GitHub PAT          | ✓         |
            | openai        | OPENAI_API_KEY      | paid      |
            | gemini        | GEMINI_API_KEY      | ✓         |
            | claude        | ANTHROPIC_API_KEY   | paid      |
            | ollama        | none (local)        | ✓         |

            ## Switch provider later

            Edit `.env` and change `AETHER_DEFAULT_PROVIDER` / `AETHER_DEFAULT_MODEL`,
            or run: `python run_agent.py --provider github --model gpt-4.1`

            ## Reconfigure from scratch

            Delete `.env` and re-run — the setup wizard will appear again.
            """),
            encoding="utf-8",
        )
        files_written.append("README.md")

        # ── 8. index.html — Tailwind CSS chat UI ─────────────────────────
        #    Served by server.py at GET / and bundled into the UI .exe.
        _html_tpl = (
            "<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "  <meta charset=\"UTF-8\" />\n"
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
            "  <title>__AGENT_NAME__ \u2014 AetherAi-A Master AI</title>\n"
            "  <script src=\"https://cdn.tailwindcss.com\"></script>\n"
            "  <style>\n"
            "    body { font-family: system-ui, sans-serif; }\n"
            "    #messages { scroll-behavior: smooth; }\n"
            "    .msg-user { background: #1d4ed8; color: #fff; }\n"
            "    .msg-ai   { background: #1e293b; color: #e2e8f0; }\n"
            "    .thinking { animation: pulse 1.2s ease-in-out infinite; }\n"
            "    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }\n"
            "  </style>\n"
            "</head>\n"
            "<body class=\"bg-gray-950 text-gray-100 min-h-screen flex flex-col\">\n"
            "\n"
            "  <!-- Header -->\n"
            "  <header class=\"bg-gray-900 border-b border-gray-700 px-6 py-4 flex items-center gap-3 shadow-lg\">\n"
            "    <div class=\"w-9 h-9 rounded-full bg-blue-600 flex items-center justify-center font-bold text-white text-sm\">AI</div>\n"
            "    <div>\n"
            "      <h1 class=\"font-semibold text-white text-base\">__AGENT_NAME__</h1>\n"
            "      <p class=\"text-xs text-gray-400\">__AGENT_ROLE__ &mdash; AetherAi-A Master AI</p>\n"
            "    </div>\n"
            "    <span id=\"status-dot\" class=\"ml-auto w-2.5 h-2.5 rounded-full bg-green-400\" title=\"Online\"></span>\n"
            "  </header>\n"
            "\n"
            "  <!-- Chat window -->\n"
            "  <main class=\"flex-1 overflow-y-auto px-4 py-6 space-y-4\" id=\"messages\">\n"
            "    <div class=\"flex gap-3\">\n"
            "      <div class=\"w-8 h-8 rounded-full bg-blue-700 flex-shrink-0 flex items-center justify-center text-xs font-bold\">AI</div>\n"
            "      <div class=\"msg-ai rounded-2xl rounded-tl-sm px-4 py-3 max-w-3xl text-sm leading-relaxed shadow\">\n"
            "        Hello! I'm <strong>__AGENT_NAME__</strong>. How can I help you today?\n"
            "      </div>\n"
            "    </div>\n"
            "  </main>\n"
            "\n"
            "  <!-- Input bar -->\n"
            "  <footer class=\"bg-gray-900 border-t border-gray-700 px-4 py-4\">\n"
            "    <form id=\"chat-form\" class=\"flex gap-3 max-w-4xl mx-auto\">\n"
            "      <input id=\"task-input\" type=\"text\" placeholder=\"Type your message\u2026\"\n"
            "             autocomplete=\"off\"\n"
            "             class=\"flex-1 bg-gray-800 border border-gray-600 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500\" />\n"
            "      <button type=\"submit\"\n"
            "              class=\"bg-blue-600 hover:bg-blue-700 active:scale-95 transition text-white font-semibold px-5 py-3 rounded-xl text-sm shadow\"\n"
            "      >Send</button>\n"
            "    </form>\n"
            "    <p class=\"text-center text-xs text-gray-600 mt-2\">Powered by AetherAi-A Master AI &bull; Running locally</p>\n"
            "  </footer>\n"
            "\n"
            "<script>\n"
            "const messagesEl = document.getElementById('messages');\n"
            "const form       = document.getElementById('chat-form');\n"
            "const inp        = document.getElementById('task-input');\n"
            "\n"
            "function appendMsg(role, text) {\n"
            "  const isUser = role === 'user';\n"
            "  const avatar = isUser ? 'You' : 'AI';\n"
            "  const row = document.createElement('div');\n"
            "  row.className = 'flex gap-3' + (isUser ? ' flex-row-reverse' : '');\n"
            "  const bubble = document.createElement('div');\n"
            "  bubble.className = (isUser ? 'msg-user rounded-tr-sm' : 'msg-ai rounded-tl-sm')\n"
            "    + ' rounded-2xl px-4 py-3 max-w-3xl text-sm leading-relaxed shadow whitespace-pre-wrap';\n"
            "  bubble.textContent = text;\n"
            "  const av = document.createElement('div');\n"
            "  av.className = 'w-8 h-8 rounded-full ' + (isUser ? 'bg-indigo-600' : 'bg-blue-700')\n"
            "    + ' flex-shrink-0 flex items-center justify-center text-xs font-bold';\n"
            "  av.textContent = avatar;\n"
            "  row.appendChild(av); row.appendChild(bubble);\n"
            "  messagesEl.appendChild(row);\n"
            "  messagesEl.scrollTop = messagesEl.scrollHeight;\n"
            "  return bubble;\n"
            "}\n"
            "\n"
            "form.addEventListener('submit', async (e) => {\n"
            "  e.preventDefault();\n"
            "  const task = inp.value.trim();\n"
            "  if (!task) return;\n"
            "  inp.value = '';\n"
            "  appendMsg('user', task);\n"
            "  const thinking = appendMsg('ai', 'Thinking\u2026');\n"
            "  try {\n"
            "    const res  = await fetch('/run', {\n"
            "      method: 'POST',\n"
            "      headers: {'Content-Type': 'application/json'},\n"
            "      body: JSON.stringify({ task }),\n"
            "    });\n"
            "    const data = await res.json();\n"
            "    thinking.textContent = data.result || data.detail || 'No response.';\n"
            "  } catch (err) {\n"
            "    thinking.textContent = 'Error: could not reach the agent server.';\n"
            "  }\n"
            "});\n"
            "</script>\n"
            "</body>\n"
            "</html>\n"
        )
        index_html = export_dir / "index.html"
        index_html.write_text(
            _html_tpl.replace("__AGENT_NAME__", name).replace("__AGENT_ROLE__", agent.role),
            encoding="utf-8",
        )
        files_written.append("index.html")

        # ── 9. server.py — FastAPI "black box" server (Method 1) ─────────
        server_py = export_dir / "server.py"
        server_requirements = sorted(
            set(self._BASE_REQUIREMENTS)
            | {"fastapi", "uvicorn[standard]"}
            | {p for t in agent_tools for p in self._TOOL_DEPENDENCIES.get(t, [])}
        )
        server_py.write_text(
            textwrap.dedent(f"""\
            \"\"\"
            FastAPI server wrapper for agent: {name}
            Exposes the agent as a REST API so callers never see source code.

            Start:
                pip install fastapi \"uvicorn[standard]\"
                uvicorn server:app --host 0.0.0.0 --port 8000

            Endpoints:
                GET  /health          — liveness probe
                GET  /agent           — agent metadata
                POST /run             — run a task  {{\"task\": \"...\"}}
                GET  /history         — last 50 results
            \"\"\"
            from __future__ import annotations
            import os, sys, json, logging
            from datetime import datetime
            from collections import deque
            _ROOT = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, _ROOT)

            from fastapi import FastAPI, HTTPException
            from fastapi.middleware.cors import CORSMiddleware
            from pydantic import BaseModel
            from core.env_loader import load_env as _lenv
            _lenv(os.path.join(_ROOT, ".env"))

            from core.aether_kernel import AetherKernel
            from agents.base_agent import BaseAgent as _BA

            logging.basicConfig(level=logging.INFO, format="[server] %(levelname)s: %(message)s")
            logger = logging.getLogger(__name__)

            # ── Boot kernel & load agent profile ─────────────────────────
            _provider = os.environ.get("AETHER_DEFAULT_PROVIDER", "github")
            _model    = os.environ.get("AETHER_DEFAULT_MODEL") or None
            kernel    = AetherKernel(ai_provider=_provider, model=_model or "gpt-4.1")

            with open(os.path.join(_ROOT, "agent_profile.json"), encoding="utf-8") as _f:
                _profile = json.load(_f)

            _agent_name = _profile["name"]
            _agent = kernel.factory.create(
                name        = _agent_name,
                role        = _profile["role"],
                tools       = _profile.get("tools", []),
                skills      = _profile.get("skills", []),
                permission_level = _profile.get("permission_level", 1),
            )
            _agent.profile["instructions"] = _profile.get("instructions", "")
            kernel.registry.register(_agent)

            _history: deque[dict] = deque(maxlen=50)

            # ── FastAPI app ───────────────────────────────────────────────
            app = FastAPI(title="{name}", description="{agent.role}", version="1.0.0")
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
            )

            class TaskRequest(BaseModel):
                task: str

            @app.get("/health")
            def health():
                return {{"status": "ok", "agent": _agent_name}}

            @app.get("/agent")
            def agent_info():
                return {{
                    "name":   _agent_name,
                    "role":   _profile["role"],
                    "skills": _profile.get("skills", []),
                    "tools":  _profile.get("tools", []),
                }}

            @app.post("/run")
            def run_task(body: TaskRequest):
                if not body.task.strip():
                    raise HTTPException(status_code=400, detail="task must not be empty")
                logger.info("Task received: %s", body.task[:120])
                result = kernel.run_agent(_agent_name, body.task)
                entry = {{"task": body.task, "result": result, "ts": datetime.utcnow().isoformat()}}
                _history.appendleft(entry)
                return {{"result": result}}

            @app.get("/history")
            def history():
                return list(_history)

            # ── UI route — serves index.html for the browser UI ───────────
            from fastapi.responses import HTMLResponse

            def get_resource_path(relative_path: str) -> str:
                \"\"\"Resolve a bundled resource path, whether running as script or .exe.\"\"\"
                if hasattr(sys, "_MEIPASS"):
                    return os.path.join(sys._MEIPASS, relative_path)
                return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

            @app.get("/", response_class=HTMLResponse)
            def serve_ui():
                \"\"\"Serves the frontend chat UI (index.html).\"\"\"
                html_path = get_resource_path("index.html")
                with open(html_path, "r", encoding="utf-8") as _hf:
                    return _hf.read()

            if __name__ == "__main__":
                import uvicorn
                uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
            """),
            encoding="utf-8",
        )
        files_written.append("server.py")

        # server_requirements.txt (superset of main requirements + FastAPI)
        (export_dir / "server_requirements.txt").write_text(
            "\n".join(server_requirements) + "\n", encoding="utf-8"
        )
        files_written.append("server_requirements.txt")

        # ── 9. build_exe.bat — Windows build script (Method 2) ──────────
        #    Offers PyInstaller (fast) OR Nuitka (harder to decompile).
        #    Handles Windows Defender warnings and code-signing guidance.
        safe_name = name.replace(" ", "-")
        hidden_imports = " ^\n                --hidden-import ".join([
            "chromadb", "chromadb.api", "chromadb.db",
            "openai", "anthropic", "yaml", "dotenv",
            "tiktoken", "tiktoken_ext", "tiktoken_ext.openai_public",
        ])
        build_bat = export_dir / "build_exe.bat"
        build_bat.write_text(
            textwrap.dedent(f"""\
            @echo off
            :: ================================================================
            :: Build standalone Windows .exe  —  Agent: {name}
            :: ================================================================
            :: Choose your compiler:
            ::   1 = PyInstaller  (fast build,  ~50MB,  basic obfuscation)
            ::   2 = Nuitka       (slow build,  ~30MB,  C compilation — much
            ::                     harder to decompile than PyInstaller)
            ::
            :: Windows Defender note:
            ::   Unsigned .exe files may trigger SmartScreen / Defender.
            ::   To suppress this for trusted testers:
            ::     a) Submit to Microsoft:  https://www.microsoft.com/en-us/wdsi/filesubmission
            ::     b) Sign with a code-signing cert (signtool.exe — see SIGNING section below)
            ::     c) Ask tester to right-click → Properties → Unblock
            :: ================================================================
            title Build  —  {name}
            cd /d "%~dp0"
            set NAME={safe_name}

            echo.
            echo  ============================================================
            echo    Build: %NAME%
            echo  ============================================================
            echo.
            echo  Choose compiler:
            echo    [1]  PyInstaller  (recommended for quick distribution)
            echo    [2]  Nuitka       (C-compiled, significantly harder to
            echo                       reverse-engineer; requires a C compiler)
            echo.
            set /p CHOICE=  Enter 1 or 2 [default: 1]: 
            if "%CHOICE%"=="2" goto :nuitka
            goto :pyinstaller

            :: ── PyInstaller ──────────────────────────────────────────────
            :pyinstaller
            echo.
            echo  Installing PyInstaller...
            pip install pyinstaller --quiet
            echo  Building (this takes 1-3 minutes)...
            echo.

            pyinstaller ^
                --onefile ^
                --name "%NAME%" ^
                --add-data "agent_profile.json;." ^
                --add-data ".env.example;." ^
                --hidden-import {hidden_imports} ^
                --collect-submodules chromadb ^
                --collect-submodules tiktoken_ext ^
                --strip ^
                --noupx ^
                run_agent.py

            if %errorlevel%==0 (
                echo.
                echo  ✓ PyInstaller build successful!
                echo  Output:  dist\\%NAME%.exe
                echo.
                echo  -----------------------------------------------------------
                echo  WINDOWS DEFENDER  —  if the .exe is flagged as suspicious:
                echo    Option A: Right-click the .exe → Properties → click Unblock
                echo    Option B: Submit for analysis:
                echo              https://www.microsoft.com/en-us/wdsi/filesubmission
                echo    Option C: Sign the binary (see SIGNING section in this file)
                echo  -----------------------------------------------------------
            ) else (
                echo.
                echo  ✗ Build failed. See output above.
            )
            goto :signing_info

            :: ── Nuitka ───────────────────────────────────────────────────
            :nuitka
            echo.
            echo  Installing Nuitka (requires a C compiler — MinGW or MSVC)...
            pip install nuitka ordered-set --quiet
            echo  Building with Nuitka (this takes 5-15 minutes on first run)...
            echo  Nuitka compiles Python to C then to native machine code.
            echo  The result is significantly harder to reverse-engineer.
            echo.

            python -m nuitka ^
                --standalone ^
                --onefile ^
                --output-filename="%NAME%.exe" ^
                --include-data-file=agent_profile.json=agent_profile.json ^
                --include-data-file=.env.example=.env.example ^
                --include-package=chromadb ^
                --include-package=openai ^
                --include-package=anthropic ^
                --include-package=yaml ^
                --include-package=dotenv ^
                --remove-output ^
                --assume-yes-for-downloads ^
                run_agent.py

            if %errorlevel%==0 (
                echo.
                echo  ✓ Nuitka build successful!
                echo  Output:  %NAME%.exe
                echo.
                echo  Nuitka note: your Python logic is compiled to native C code.
                echo  Decompiling requires reverse-engineering compiled binaries,
                echo  not just .pyc files.
            ) else (
                echo.
                echo  ✗ Nuitka build failed.
                echo  Ensure a C compiler is installed:
                echo    MinGW: https://www.mingw-w64.org/
                echo    MSVC:  https://visualstudio.microsoft.com/visual-cpp-build-tools/
            )

            :: ── Code-signing guidance ────────────────────────────────────
            :signing_info
            echo.
            echo  -----------------------------------------------------------
            echo  OPTIONAL CODE SIGNING  (removes Defender / SmartScreen alerts)
            echo  -----------------------------------------------------------
            echo  1. Get a code-signing certificate:
            echo       Cheap (~$70/yr):  Sectigo, DigiCert, Comodo
            echo       Free (EV needed for instant trust, expensive)
            echo.
            echo  2. Sign the binary with signtool.exe (ships with Windows SDK):
            echo       signtool sign /fd sha256 /f MyCert.pfx /p YourPassword
            echo                     /t http://timestamp.digicert.com
            echo                     dist\\%NAME%.exe
            echo.
            echo  3. Verify the signature:
            echo       signtool verify /pa dist\\%NAME%.exe
            echo  -----------------------------------------------------------
            echo.
            pause
            """),
            encoding="utf-8",
        )
        files_written.append("build_exe.bat")

        # ── build_exe.sh — macOS / Linux build script (Method 2) ─────────
        hidden_imports_sh = " \\\n                --hidden-import ".join([
            "chromadb", "chromadb.api", "chromadb.db",
            "openai", "anthropic", "yaml", "dotenv",
            "tiktoken", "tiktoken_ext", "tiktoken_ext.openai_public",
        ])
        build_sh = export_dir / "build_exe.sh"
        build_sh.write_text(
            textwrap.dedent(f"""\
            #!/usr/bin/env bash
            # =================================================================
            # Build standalone binary  —  Agent: {name}
            # Targets: macOS (.app / binary) and Linux (ELF binary)
            # =================================================================
            # Choose compiler:
            #   1 = PyInstaller  (fast, basic obfuscation)
            #   2 = Nuitka       (C-compiled, harder to decompile)
            #
            # macOS note: code-signing with Apple Developer ID removes
            # Gatekeeper warnings.  See SIGNING section at bottom of script.
            # =================================================================
            set -e
            cd "$(dirname "$0")"
            NAME="{safe_name}"
            OS="$(uname -s)"

            echo ""
            echo "============================================================"
            echo "  Build: $NAME  |  Platform: $OS"
            echo "============================================================"
            echo ""
            echo "Choose compiler:"
            echo "  [1]  PyInstaller  (recommended for quick distribution)"
            echo "  [2]  Nuitka       (C-compiled, significantly harder to"
            echo "                     reverse-engineer; requires gcc/clang)"
            echo ""
            read -rp "  Enter 1 or 2 [default: 1]: " CHOICE
            CHOICE="${{CHOICE:-1}}"

            if [ "$CHOICE" = "2" ]; then
                # ── Nuitka ────────────────────────────────────────────────
                echo ""
                echo "  Installing Nuitka..."
                pip install nuitka ordered-set --quiet

                echo "  Building with Nuitka (5-15 minutes on first run)..."
                python -m nuitka \\
                    --standalone \\
                    --onefile \\
                    --output-filename="$NAME" \\
                    --include-data-file=agent_profile.json=agent_profile.json \\
                    --include-data-file=.env.example=.env.example \\
                    --include-package=chromadb \\
                    --include-package=openai \\
                    --include-package=anthropic \\
                    --include-package=yaml \\
                    --include-package=dotenv \\
                    --remove-output \\
                    --assume-yes-for-downloads \\
                    run_agent.py

                echo ""
                echo "  ✓ Nuitka build successful! Binary: ./$NAME"
                echo "  Your logic is compiled to native C — not Python bytecode."
            else
                # ── PyInstaller ───────────────────────────────────────────
                echo ""
                echo "  Installing PyInstaller..."
                pip install pyinstaller --quiet

                echo "  Building (1-3 minutes)..."
                pyinstaller \\
                    --onefile \\
                    --name "$NAME" \\
                    --add-data "agent_profile.json:." \\
                    --add-data ".env.example:." \\
                    --hidden-import {hidden_imports_sh} \\
                    --collect-submodules chromadb \\
                    --collect-submodules tiktoken_ext \\
                    --strip \\
                    run_agent.py

                echo ""
                echo "  ✓ PyInstaller build successful! Binary: dist/$NAME"
            fi

            # ── macOS code-signing guidance ───────────────────────────────
            if [ "$OS" = "Darwin" ]; then
                echo ""
                echo "  -----------------------------------------------------------"
                echo "  macOS CODE SIGNING  (removes Gatekeeper 'cannot be opened')"
                echo "  -----------------------------------------------------------"
                echo "  1. Enrol in Apple Developer Program (\$99/yr)"
                echo "     https://developer.apple.com/programs/"
                echo ""
                echo "  2. Sign the binary:"
                echo "     codesign --deep --force --verify --verbose"
                echo "              --sign 'Developer ID Application: Your Name (TEAMID)'"
                echo "              dist/$NAME"
                echo ""
                echo "  3. Notarize (required for macOS 10.15+):"
                echo "     xcrun notarytool submit dist/$NAME"
                echo "          --apple-id you@example.com --team-id TEAMID"
                echo "          --password APP_SPECIFIC_PASSWORD --wait"
                echo ""
                echo "  4. Staple the notarization ticket:"
                echo "     xcrun stapler staple dist/$NAME"
                echo "  -----------------------------------------------------------"
            fi

            # ── Linux AppImage (optional convenience wrapper) ─────────────
            if [ "$OS" = "Linux" ]; then
                echo ""
                echo "  TIP: Wrap the binary in an AppImage for universal Linux distro support:"
                echo "    https://appimage.org/"
            fi

            echo ""
            """),
            encoding="utf-8",
        )
        files_written.append("build_exe.sh")

        # ── 10. gui_launcher.py — desktop UI launcher (Method 4) ─────────
        #    Starts the FastAPI server in a background thread and opens the
        #    agent UI automatically in the user's default web browser.
        #    Compile with build_ui_exe.bat for a true double-click .exe.
        gui_launcher_py = export_dir / "gui_launcher.py"
        gui_launcher_py.write_text(
            textwrap.dedent(f"""\
            \"\"\"
            gui_launcher.py — Desktop launcher for agent: {name}

            Starts the FastAPI server in a background thread and automatically
            opens the browser to the Tailwind chat UI (GET /).

            Compile to a standalone .exe with:  build_ui_exe.bat
            \"\"\"
            from __future__ import annotations
            import threading
            import webbrowser
            import uvicorn
            import time
            import sys
            import os

            _ROOT = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, _ROOT)

            from core.env_loader import load_env as _lenv
            _lenv(os.path.join(_ROOT, ".env"))

            from server import app  # noqa: E402  (import after path setup)

            _PORT = 8000
            _HOST = "127.0.0.1"
            _URL  = f"http://{{_HOST}}:{{_PORT}}"


            def _start_server() -> None:
                \"\"\"Run the FastAPI server silently in a background thread.\"\"\"
                uvicorn.run(app, host=_HOST, port=_PORT, log_level="critical")


            if __name__ == "__main__":
                print("\u26a1 Starting AetherAi-A Master AI Agent Environment...")
                print("Please wait while the AI loads into memory...")

                # 1. Start the API server in a daemon thread
                server_thread = threading.Thread(target=_start_server, daemon=True)
                server_thread.start()

                # 2. Give the server a moment to bind the port
                time.sleep(2)

                # 3. Open the UI in the user's default browser
                webbrowser.open(_URL)

                print(f"\n\u2705 UI launched in your web browser!  ({{_URL}})")
                print("\u26a0\ufe0f  DO NOT CLOSE THIS WINDOW. Closing it will turn off the AI Agent.")

                # 4. Keep the process alive so the daemon server thread stays up
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\nShutting down AetherAi-A Master AI Agent...")
                    sys.exit(0)
            """),
            encoding="utf-8",
        )
        files_written.append("gui_launcher.py")

        # ── 11. build_ui_exe.bat — compiles gui_launcher → AetherAgent_UI.exe
        safe_ui_name = name.replace(" ", "-") + "_UI"
        build_ui_bat = export_dir / "build_ui_exe.bat"
        build_ui_bat.write_text(
            textwrap.dedent(f"""\
            @echo off
            :: ================================================================
            :: Build standalone Windows UI .exe  — Agent: {name}
            :: Produces a double-clickable .exe that opens the Tailwind chat UI
            :: automatically in Chrome/Edge (no server knowledge needed).
            :: ================================================================
            title Build UI EXE  —  {name}
            cd /d "%~dp0"

            echo.
            echo  Installing required packages...
            pip install pyinstaller uvicorn fastapi pydantic --quiet

            echo.
            echo  Compiling {name} with browser UI...
            echo  (This may take 1-3 minutes — please wait)
            echo.

            pyinstaller --onefile ^
                --name "{safe_ui_name}" ^
                --add-data "index.html;." ^
                --add-data "agent_profile.json;." ^
                --add-data "registry/registry_store.json;registry" ^
                --hidden-import chromadb ^
                --hidden-import chromadb.api ^
                --hidden-import openai ^
                --hidden-import anthropic ^
                --hidden-import yaml ^
                --hidden-import pydantic ^
                --hidden-import uvicorn ^
                --hidden-import uvicorn.logging ^
                --hidden-import uvicorn.loops ^
                --hidden-import uvicorn.loops.auto ^
                --hidden-import uvicorn.protocols ^
                --hidden-import uvicorn.protocols.http ^
                --hidden-import uvicorn.protocols.http.auto ^
                --collect-submodules chromadb ^
                --collect-submodules tiktoken_ext ^
                gui_launcher.py

            if %errorlevel%==0 (
                echo.
                echo  ============================================================
                echo   ^[OK^]  Build complete!
                echo.
                echo   Your UI executable is in the  dist\  folder:
                echo     dist\{safe_ui_name}.exe
                echo.
                echo   HOW TO USE:
                echo     1. Copy dist\{safe_ui_name}.exe to your client / tester
                echo     2. They must place a .env file in the SAME folder
                echo        containing their AI provider API key
                echo        (e.g.  GITHUB_TOKEN=ghp_...)
                echo     3. Double-click the .exe — Chrome/Edge will open the UI
                echo.
                echo   TIP: Right-click exe ^> Properties ^> Unblock if Windows
                echo        Defender shows a SmartScreen warning
                echo  ============================================================
            ) else (
                echo.
                echo  [FAIL]  Build failed — check the output above for errors.
            )
            echo.
            pause
            """),
            encoding="utf-8",
        )
        files_written.append("build_ui_exe.bat")

        # ── 12. Dockerfile — bytecode-only Docker image (Method 3) ──────
        dockerfile = export_dir / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent(f"""\
            # Dockerfile for agent: {name}
            # Compiles Python source to bytecode and removes .py files so the
            # operator's source code and prompts are never visible to the user.
            #
            # Build:  docker build -t {name.lower().replace(" ", "-")} .
            # Run:    docker run -it --env-file .env {name.lower().replace(" ", "-")}
            # Server: docker run -p 8000:8000 --env-file .env {name.lower().replace(" ", "-")} uvicorn server:app --host 0.0.0.0 --port 8000

            FROM python:3.11-slim

            # Install system deps
            RUN apt-get update && apt-get install -y --no-install-recommends \\
                    gcc build-essential && \\
                rm -rf /var/lib/apt/lists/*

            WORKDIR /app

            # Install Python dependencies first (layer-cached)
            COPY requirements.txt .
            RUN pip install --no-cache-dir -r requirements.txt

            # Copy all source files
            COPY . .

            # Compile every .py file to .pyc bytecode in-place (-b = beside source)
            # then delete the readable .py sources to protect IP.
            RUN python -m compileall -b -q . && \\
                find . -name "*.py" -not -name "*.pyc" -type f -delete && \\
                find . -name "__pycache__" -type d -exec rm -rf {{}} + 2>/dev/null || true

            # Non-root user for security
            RUN useradd -m agentuser
            USER agentuser

            # Default: interactive CLI mode
            # Override CMD when running the server:
            #   docker run ... uvicorn server:app --host 0.0.0.0 --port 8000
            CMD ["python", "run_agent.pyc"]
            """),
            encoding="utf-8",
        )
        files_written.append("Dockerfile")

        # .dockerignore — exclude build artefacts and secrets from the image
        dockerignore = export_dir / ".dockerignore"
        dockerignore.write_text(
            textwrap.dedent("""\
            __pycache__/
            *.pyc
            *.pyo
            .env
            dist/
            build/
            *.spec
            memory/memory_store.json
            memory/chroma_store/
            """),
            encoding="utf-8",
        )
        files_written.append(".dockerignore")

        return {"output_dir": str(export_dir), "files": files_written, "error": None}

    def export_system(self, system_name: str, agent_names: list[str]) -> dict:
        """
        Export multiple agents as one self-contained AI System under
        exports/<system_name>/  with a shared launcher and per-agent subfolders.
        Returns dict with 'output_dir', 'agents', 'error'.
        """
        import json, shutil, textwrap
        from pathlib import Path

        # Validate all agents exist first
        missing = [n for n in agent_names if self.registry.get(n) is None]
        if missing:
            return {"error": f"Agents not found: {', '.join(missing)}"}

        agents = [self.registry.get(n) for n in agent_names]

        project_root = Path(__file__).parent.parent
        sys_dir = project_root / "exports" / system_name
        sys_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Copy shared source once at system root ────────────────────
        dirs_to_copy = ["agents", "ai", "core", "factory", "memory",
                        "registry", "skills", "tools", "cli"]
        for d in dirs_to_copy:
            src = project_root / d
            dst = sys_dir / d
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)

        # ── 2. Blank shared .env ─────────────────────────────────────────
        blank_env = (
            f"# {system_name} — AI System Configuration\n"
            "# Run python run_system.py to configure interactively (first launch)\n\n"
            "AETHER_DEFAULT_PROVIDER=\n"
            "AETHER_DEFAULT_MODEL=\n\n"
            "# Paste your key for the provider you choose:\n"
            "GITHUB_TOKEN=\n"
            "OPENAI_API_KEY=\n"
            "GEMINI_API_KEY=\n"
            "ANTHROPIC_API_KEY=\n"
        )
        (sys_dir / ".env").write_text(blank_env, encoding="utf-8")
        (sys_dir / ".env.example").write_text(blank_env, encoding="utf-8")

        # ── 3. Per-agent profile JSONs ───────────────────────────────────
        agents_dir = sys_dir / "agent_profiles"
        agents_dir.mkdir(exist_ok=True)
        for agent in agents:
            (agents_dir / f"{agent.name}.json").write_text(
                json.dumps(agent.to_dict(), indent=2), encoding="utf-8"
            )

        # ── 4. run_system.py — multi-agent launcher ──────────────────────
        agent_list_repr = repr(agent_names)
        agent_roles = {a.name: a.role for a in agents}

        run_py = sys_dir / "run_system.py"
        run_py.write_text(
            textwrap.dedent(f"""\
            \"\"\"
            {system_name} — Aether AI System
            Agents: {', '.join(agent_names)}
            Created by AetherAi-A Master AI
            \"\"\"
            from __future__ import annotations
            import os, sys, argparse
            _ROOT = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, _ROOT)
            from core.env_loader import load_env as _lenv
            _lenv(os.path.join(_ROOT, ".env"))

            _AGENTS     = {agent_list_repr}
            _AGENT_ROLES = {repr(agent_roles)}

            # ── First-time AI setup wizard ────────────────────────────────
            def _first_time_setup():
                _env_path = os.path.join(_ROOT, ".env")
                print("\\n" + "="*60)
                print("  {system_name} — AI System  |  First-time Setup")
                print("="*60)
                print("  Choose your AI provider:\\n")
                _providers = [
                    ("github",  "GitHub Models  (free, needs GitHub account PAT)"),
                    ("openai",  "OpenAI         (GPT-4o / GPT-4.1)"),
                    ("gemini",  "Google Gemini"),
                    ("claude",  "Anthropic Claude"),
                    ("ollama",  "Ollama         (local, no API key needed)"),
                ]
                _models   = {{"github":"gpt-4.1","openai":"gpt-4o",
                               "gemini":"gemini-1.5-flash","claude":"claude-sonnet-4.6",
                               "ollama":"qwen2.5-coder:7b"}}
                _key_envs = {{"github":"GITHUB_TOKEN","openai":"OPENAI_API_KEY",
                               "gemini":"GEMINI_API_KEY","claude":"ANTHROPIC_API_KEY","ollama":None}}
                _ollama_rec = [
                    ("qwen2.5-coder:7b",      "Qwen2.5-Coder 7B   — best code/agents  (8GB)"),
                    ("qwen2.5-coder:14b",     "Qwen2.5-Coder 14B  — higher quality   (12GB)"),
                    ("qwen2.5-coder:32b",     "Qwen2.5-Coder 32B  — top quality      (20GB+)"),
                    ("deepseek-coder-v2:16b", "DeepSeek-Coder-V2 16B — Python/agents (16GB)"),
                    ("qwen3:30b",             "Qwen3 30B  — 128k ctx, tool calling   (20GB+)"),
                    ("minimax-m2",            "MiniMax-M2 — 1M context, agentic      (high)"),
                    ("llama3.3:70b",          "Llama 3.3 70B — general, 128k ctx     (40GB+)"),
                    ("wizardlm2:7b",          "WizardLM2 7B — fast, low-resource     (8GB)"),
                    ("llama3.2:3b",           "Llama 3.2 3B  — ultra-fast, minimal   (4GB)"),
                ]
                for i,(p,desc) in enumerate(_providers,1):
                    print(f"  {{i}}. {{desc}}")
                print()
                while True:
                    c = input("  Enter number (1-5): ").strip()
                    if c.isdigit() and 1 <= int(c) <= 5:
                        break
                _provider = _providers[int(c)-1][0]
                _key_name = _key_envs[_provider]
                _api_key  = ""
                if _key_name:
                    print(f"\\n  Enter your {{_key_name}}:")
                    _api_key = input(f"  {{_key_name}}: ").strip()
                _def_model = _models[_provider]
                if _provider == "ollama":
                    print(f"\\n  Recommended Ollama models:")
                    for _oi,(_om,_od) in enumerate(_ollama_rec,1):
                        print(f"  {{_oi:2}}. {{_od}}")
                    _oc = input(f"\\n  Enter number or model name [{{_def_model}}]: ").strip()
                    if _oc.isdigit() and 1 <= int(_oc) <= len(_ollama_rec):
                        _model = _ollama_rec[int(_oc)-1][0]
                    elif _oc:
                        _model = _oc
                    else:
                        _model = _def_model
                else:
                    _model = input(f"\\n  Model name [{{_def_model}}]: ").strip() or _def_model
                _lines = [
                    f"# {system_name} — AI System\\n",
                    f"AETHER_DEFAULT_PROVIDER={{_provider}}\\n",
                    f"AETHER_DEFAULT_MODEL={{_model}}\\n",
                ]
                if _key_name and _api_key:
                    _lines.append(f"{{_key_name}}={{_api_key}}\\n")
                with open(_env_path, "w", encoding="utf-8") as _f:
                    _f.writelines(_lines)
                _lenv(_env_path)
                print(f"\\n  ✓ Configured: {{_provider}} / {{_model}}")
                print(f"  ✓ Saved to .env\\n")
                return _provider, _model

            def _print_menu():
                print("\\n" + "="*60)
                print(f"  {system_name}")
                print(f"  Aether AI System  —  {{len(_AGENTS)}} agent(s)")
                print("="*60)
                for i, name in enumerate(_AGENTS, 1):
                    role = _AGENT_ROLES.get(name, "")
                    print(f"  {{i}}. {{name:<20}} {{role}}")
                print(f"  {{len(_AGENTS)+1}}. Exit")
                print("="*60)

            def main():
                parser = argparse.ArgumentParser()
                parser.add_argument("--agent",    default=None)
                parser.add_argument("--provider", default=None)
                parser.add_argument("--model",    default=None)
                args = parser.parse_args()

                provider = args.provider or os.environ.get("AETHER_DEFAULT_PROVIDER","").strip()
                model    = args.model    or os.environ.get("AETHER_DEFAULT_MODEL","").strip() or None

                if not provider:
                    provider, model = _first_time_setup()

                from cli.agent_window import run_agent_window

                if args.agent:
                    if args.agent not in _AGENTS:
                        print(f"Unknown agent '{{args.agent}}'. Available: {{', '.join(_AGENTS)}}")
                        sys.exit(1)
                    run_agent_window(args.agent, provider, model)
                    return

                # Interactive agent picker
                while True:
                    _print_menu()
                    choice = input("\\n  Select agent: ").strip()
                    if choice.isdigit():
                        idx = int(choice) - 1
                        if idx == len(_AGENTS):
                            print("  Goodbye.")
                            break
                        if 0 <= idx < len(_AGENTS):
                            run_agent_window(_AGENTS[idx], provider, model)
                        else:
                            print("  Invalid choice.")
                    elif choice.lower() in (a.lower() for a in _AGENTS):
                        match = next(a for a in _AGENTS if a.lower() == choice.lower())
                        run_agent_window(match, provider, model)
                    elif choice.lower() in ("exit","quit","q"):
                        print("  Goodbye.")
                        break
                    else:
                        print("  Type a number or agent name.")

            if __name__ == "__main__":
                main()
            """),
            encoding="utf-8",
        )

        # ── 5. launch_system.bat ─────────────────────────────────────────
        bat = sys_dir / "launch_system.bat"
        bat.write_text(
            textwrap.dedent(f"""\
            @echo off
            title {system_name} — AI System
            color 0B
            cd /d "%~dp0"

            set PROVIDER=
            set MODEL=
            if exist ".env" (
                for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
                    if /i "%%A"=="AETHER_DEFAULT_PROVIDER" set PROVIDER=%%B
                    if /i "%%A"=="AETHER_DEFAULT_MODEL"    set MODEL=%%B
                )
            )

            set PY=
            for %%V in (Python312 Python311 Python310) do (
                if exist "%LOCALAPPDATA%\\Programs\\Python\\%%V\\python.exe" (
                    set PY="%LOCALAPPDATA%\\Programs\\Python\\%%V\\python.exe"
                    goto :run
                )
            )
            where python >nul 2>&1
            if %errorlevel%==0 ( set PY=python & goto :run )
            echo Python not found. Install from https://www.python.org/downloads/
            pause & exit /b 1

            :run
            if defined MODEL (
                %PY% run_system.py --provider %PROVIDER% --model %MODEL% %*
            ) else if defined PROVIDER (
                %PY% run_system.py --provider %PROVIDER% %*
            ) else (
                %PY% run_system.py %*
            )
            pause
            """),
            encoding="utf-8",
        )

        # ── 6. Per-agent .bat shortcuts ──────────────────────────────────
        for agent in agents:
            abat = sys_dir / f"launch_{agent.name}.bat"
            abat.write_text(
                textwrap.dedent(f"""\
                @echo off
                title {agent.name} — {agent.role}
                color 0B
                cd /d "%~dp0"
                set PROVIDER=
                set MODEL=
                if exist ".env" (
                    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
                        if /i "%%A"=="AETHER_DEFAULT_PROVIDER" set PROVIDER=%%B
                        if /i "%%A"=="AETHER_DEFAULT_MODEL"    set MODEL=%%B
                    )
                )
                set PY=
                for %%V in (Python312 Python311 Python310) do (
                    if exist "%LOCALAPPDATA%\\Programs\\Python\\%%V\\python.exe" (
                        set PY="%LOCALAPPDATA%\\Programs\\Python\\%%V\\python.exe"
                        goto :run
                    )
                )
                where python >nul 2>&1
                if %errorlevel%==0 ( set PY=python & goto :run )
                echo Python not found. & pause & exit /b 1
                :run
                if defined MODEL (
                    %PY% run_system.py --agent {agent.name} --provider %PROVIDER% --model %MODEL%
                ) else if defined PROVIDER (
                    %PY% run_system.py --agent {agent.name} --provider %PROVIDER%
                ) else (
                    %PY% run_system.py --agent {agent.name}
                )
                pause
                """),
                encoding="utf-8",
            )

        # ── 7. requirements.txt (dynamic — Fix 4) ────────────────────────
        all_tools: list[str] = []
        for a in agents:
            all_tools.extend(a.profile.get("tools", []))
        (sys_dir / "requirements.txt").write_text(
            self._build_requirements(all_tools), encoding="utf-8"
        )

        # ── 8. README.md ─────────────────────────────────────────────────
        agent_table = "\n".join(
            f"| {a.name:<20} | {a.role:<30} | launch_{a.name}.bat |"
            for a in agents
        )
        (sys_dir / "README.md").write_text(
            textwrap.dedent(f"""\
            # {system_name}
            **Aether AI System** — {len(agents)} agent(s)

            ## Agents

            | Name                 | Role                           | Quick Launch        |
            |----------------------|--------------------------------|---------------------|
            {agent_table}

            ## Quick Start

            1. Double-click `launch_system.bat` — shows agent picker menu
            2. Or launch a specific agent directly: `launch_<AgentName>.bat`
            3. First launch runs a 30-second AI setup wizard (provider + API key)

            ## Supported AI Providers

            | Provider | Key Needed        | Free |
            |----------|-------------------|------|
            | github   | GitHub PAT        | ✓    |
            | openai   | OPENAI_API_KEY    |      |
            | gemini   | GEMINI_API_KEY    | ✓    |
            | claude   | ANTHROPIC_API_KEY |      |
            | ollama   | none (local)      | ✓    |

            ## Reconfigure AI provider

            Delete `.env` and relaunch — the setup wizard will run again.
            Or edit `.env` directly and change `AETHER_DEFAULT_PROVIDER`.
            """),
            encoding="utf-8",
        )

        return {
            "output_dir": str(sys_dir),
            "agents": agent_names,
            "error": None,
        }



    def chat(self, message: str, history: list[dict] | None = None) -> str:
        """Send a message directly to the underlying AI model."""
        messages = history or []
        messages.append({"role": "user", "content": message})
        response = self.ai_adapter.chat(messages=messages)
        self.memory.append(key="chat_history", value={"role": "assistant", "content": response})
        return response

    # ------------------------------------------------------------------
    # Application builder
    # ------------------------------------------------------------------

    def build_application(self, app_name: str, progress=None) -> dict:
        """
        Ask the AI to generate a complete application, parse the response
        into individual files, write them to agent_output/<app_name>/,
        and return a summary dict with keys 'output_dir' and 'files'.

        Args:
            progress: optional callable(step, total, filename, status)
                      called after each file is written.
        """
        import os, re
        from pathlib import Path
        from tools.file_writer import file_writer

        logger.info("Building application: %s", app_name)

        prompt = (
            f"You are an expert software engineer.\n"
            f"Generate a complete, working '{app_name}' application.\n"
            f"Output EVERY file using EXACTLY this format — no extra commentary outside the blocks:\n\n"
            f"=== FILE: <relative/path/filename.ext> ===\n"
            f"<full file content here>\n"
            f"=== END FILE ===\n\n"
            f"Include: all source files, a requirements.txt (if Python), "
            f"a README.md explaining how to run it, and any config files needed.\n"
            f"Make the code complete and runnable — no placeholders."
        )

        messages = [{"role": "user", "content": prompt}]
        raw = self.ai_adapter.chat(messages=messages)

        # Parse === FILE: path === ... === END FILE === blocks
        pattern = re.compile(
            r"=== FILE:\s*(.+?)\s*===\n(.*?)\n=== END FILE ===",
            re.DOTALL,
        )
        matches = pattern.findall(raw)

        output_dir = str(Path(__file__).parent.parent / "agent_output" / app_name.replace(" ", "_"))
        files_written = []

        if matches:
            total = len(matches)
            for i, (rel_path, content) in enumerate(matches, start=1):
                rel_path = rel_path.strip()
                result = file_writer(
                    filename=os.path.join(app_name.replace(" ", "_"), rel_path),
                    content=content,
                )
                files_written.append((rel_path, result))
                if progress:
                    ok = "successfully" in result
                    progress(i, total, rel_path, ok)
        else:
            # Fallback: save the raw response as a single plan file
            result = file_writer(
                filename=os.path.join(app_name.replace(" ", "_"), "plan.md"),
                content=raw,
            )
            files_written.append(("plan.md", result))
            if progress:
                progress(1, 1, "plan.md", "successfully" in result)

        self.memory.save(key=f"build:{app_name}:files", value=[f for f, _ in files_written])
        return {"output_dir": output_dir, "files": files_written, "raw": raw}
