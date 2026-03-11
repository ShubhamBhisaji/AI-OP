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
from core.team_manager import TeamManager
from core.orchestrator import Orchestrator
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
        )
        self.team_manager = TeamManager(registry=self.registry)
        self.orchestrator = Orchestrator(
            registry=self.registry,
            ai_adapter=self.ai_adapter,
            workflow_engine=self.workflow_engine,
        )
        # Wire AI adapter into skill engine after creation
        self.skill_engine.ai_adapter = self.ai_adapter
        logger.info("Aether OS kernel ready.")

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def create_agent(self, name: str, role: str, tools: list[str] | None = None) -> BaseAgent:
        """Create a new agent and register it (fast path, no AI research)."""
        agent = self.factory.create(name=name, role=role, tools=tools or [])
        logger.info("Agent '%s' created with role: %s", name, role)
        return agent

    def build_agent(
        self,
        name: str,
        role: str,
        context: str = "",
        progress=None,
    ) -> BaseAgent:
        """
        Smart agent builder — three-step AI research pipeline:
          1. Research the agent's core function and responsibilities
          2. Gather skill & tool requirements
          3. Write a detailed system prompt / instructions

        Returns the fully configured BaseAgent (registered in the registry).
        """
        import json, re
        from factory.agent_factory import AGENT_PRESETS

        def _prog(step: int, total: int, msg: str) -> None:
            if progress:
                progress(step, total, msg)

        # ── Step 1: Research core function ───────────────────────────
        _prog(1, 3, f"Researching core function for '{name}'...")
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
        _prog(2, 3, f"Gathering skill requirements for '{name}'...")
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
        skills_clean = re.sub(r"```(?:json)?|```", "", skills_raw).strip()
        sm = re.search(r"\{.*\}", skills_clean, re.DOTALL)
        skills_data: dict = {}
        if sm:
            try:
                skills_data = json.loads(sm.group())
            except json.JSONDecodeError:
                pass

        skills: list[str] = [str(s) for s in skills_data.get("skills", [])]
        tools:  list[str] = [str(t) for t in skills_data.get("tools",  [])]

        # Fallback to preset if AI returned nothing useful
        preset_key = name.lower().replace(" ", "_")
        if not skills:
            skills = list(AGENT_PRESETS.get(preset_key, {}).get("skills", []))
        if not tools:
            tools  = list(AGENT_PRESETS.get(preset_key, {}).get("tools",  []))

        # ── Step 3: Write instructions (system prompt) ───────────────
        _prog(3, 3, f"Writing instructions for '{name}'...")
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

        # ── Build and register the agent ─────────────────────────────
        agent = self.factory.create(name=name, role=role, tools=tools, skills=skills)
        agent.profile["instructions"]     = instructions
        agent.profile["research_summary"] = research[:600]
        self.registry.register(agent)   # persist updated profile

        logger.info(
            "build_agent: '%s' — %d skills, %d tools, instructions written.",
            name, len(skills), len(tools),
        )
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
        import json, re
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
        raw_clean = re.sub(r"```(?:json)?|```", "", raw).strip()
        m = re.search(r"\{.*\}", raw_clean, re.DOTALL)
        if not m:
            return {"error": "AI did not return valid JSON for agent roster.", "raw": raw}
        try:
            blueprint = json.loads(m.group())
        except json.JSONDecodeError as e:
            return {"error": f"JSON parse error: {e}", "raw": raw}

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
            skills_clean = re.sub(r"```(?:json)?|```", "", skills_raw).strip()
            sm = re.search(r"\{.*\}", skills_clean, re.DOTALL)
            skills_data: dict = {}
            if sm:
                try:
                    skills_data = json.loads(sm.group())
                except json.JSONDecodeError:
                    pass
            askills = [str(s) for s in skills_data.get("skills", [])]
            atools  = [str(t) for t in skills_data.get("tools",  [])]

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
        import json, re

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
        routing_clean = re.sub(r"```(?:json)?|```", "", routing_raw).strip()
        rm = re.search(r"\{.*\}", routing_clean, re.DOTALL)
        if rm:
            try:
                routing = json.loads(rm.group())
            except json.JSONDecodeError:
                routing = {"agents": [agents_info[0]["name"]], "strategy": "single"}
        else:
            routing = {"agents": [agents_info[0]["name"]], "strategy": "single"}

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
            "# Aether Agent — AI Configuration\n"
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

        # ── 4. requirements.txt ──────────────────────────────────────────
        req = export_dir / "requirements.txt"
        req.write_text(
            "openai\nanthropic\nollama\npython-dotenv\npyyaml\n",
            encoding="utf-8",
        )
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
                print("  {name} — Aether Agent  |  First-time Setup")
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
                    "# Aether Agent — AI Configuration\\n",
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
                    description="Aether Agent: {name} ({agent.role})"
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
            title {name} — Aether Agent
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
            # Aether Agent: {name}

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
            Created by Aether OS
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

        # ── 7. requirements.txt ──────────────────────────────────────────
        (sys_dir / "requirements.txt").write_text(
            "openai\nanthropic\nollama\npython-dotenv\npyyaml\n",
            encoding="utf-8",
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
