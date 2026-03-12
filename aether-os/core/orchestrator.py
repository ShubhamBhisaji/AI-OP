"""
Orchestrator — Multi-agent coordination strategies for AetherAi-A Master AI.

Modes
-----
pipeline   : Sequential chain.  Agent[i]'s output becomes Agent[i+1]'s input.
broadcast  : All agents process the same task independently.
vote       : All agents answer; AI synthesizes a consensus.
best_of    : All agents attempt; AI picks the single best response.
debate     : Two agents exchange arguments on a topic (N rounds each).
orchestrate: AI auto-selects agents + mode, then executes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Orchestrator:
    """Multi-agent coordination engine."""

    def __init__(self, registry, ai_adapter, workflow_engine) -> None:
        self.registry = registry
        self.ai_adapter = ai_adapter
        self.workflow_engine = workflow_engine

    # ------------------------------------------------------------------
    # Pipeline  —  sequential, each output feeds next
    # ------------------------------------------------------------------

    def run_pipeline(self, agent_names: list[str], task: str) -> list[dict]:
        """
        Run agents in sequence.  Each agent's output becomes the next
        agent's input.

        Returns a list of step dicts:
            {"step": int, "agent": str, "input": str, "output": str, "success": bool}
        """
        results: list[dict] = []
        current_input = task

        for step, name in enumerate(agent_names, start=1):
            agent = self.registry.get(name)
            if agent is None:
                results.append({
                    "step": step, "agent": name,
                    "input": current_input,
                    "output": f"[Error] Agent '{name}' not found in registry.",
                    "success": False,
                })
                break   # abort pipeline — next inputs are undefined

            try:
                output = self.workflow_engine.execute(agent=agent, task=current_input)
                results.append({
                    "step": step, "agent": name,
                    "input": current_input, "output": output, "success": True,
                })
                current_input = output   # feed forward
            except Exception as exc:
                results.append({
                    "step": step, "agent": name,
                    "input": current_input,
                    "output": f"[Error] {exc}",
                    "success": False,
                })
                break   # abort on first failure

        return results

    # ------------------------------------------------------------------
    # Broadcast  —  all agents, same task, independent
    # ------------------------------------------------------------------

    def broadcast(self, agent_names: list[str], task: str) -> list[dict]:
        """
        Send the same task to every agent independently.

        Returns a list of:
            {"agent": str, "output": str, "success": bool}
        """
        results: list[dict] = []
        for name in agent_names:
            agent = self.registry.get(name)
            if agent is None:
                results.append({
                    "agent": name,
                    "output": f"[Error] Agent '{name}' not found.",
                    "success": False,
                })
                continue
            try:
                output = self.workflow_engine.execute(agent=agent, task=task)
                results.append({"agent": name, "output": output, "success": True})
            except Exception as exc:
                results.append({"agent": name, "output": f"[Error] {exc}", "success": False})

        return results

    # ------------------------------------------------------------------
    # Vote  —  collect answers, AI synthesizes consensus
    # ------------------------------------------------------------------

    def vote(self, agent_names: list[str], question: str) -> dict:
        """
        Each agent answers the question; the AI synthesizes a consensus.

        Returns:
            {
                "question": str,
                "responses": [{"agent": str, "output": str, "success": bool}, ...],
                "consensus": str,
            }
        """
        responses = self.broadcast(agent_names, question)
        successful = [r for r in responses if r["success"]]

        if not successful:
            return {
                "question": question,
                "responses": responses,
                "consensus": "No agents produced a valid response.",
            }

        formatted = "\n\n".join(
            f"[{r['agent']}]:\n{r['output']}" for r in successful
        )
        synthesis_prompt = (
            f"The following AI agents were asked:\n\"{question}\"\n\n"
            f"Their responses:\n{formatted}\n\n"
            f"Synthesize these into a single best consensus answer. "
            f"Note areas of strong agreement or disagreement. Be concise."
        )
        consensus = self.ai_adapter.chat([{"role": "user", "content": synthesis_prompt}])
        return {"question": question, "responses": responses, "consensus": consensus}

    # ------------------------------------------------------------------
    # Best-of  —  AI picks the single strongest response
    # ------------------------------------------------------------------

    def best_of(self, agent_names: list[str], task: str) -> dict:
        """
        All agents attempt the task; AI judge picks the best response.

        Returns:
            {
                "task": str,
                "winner": str | None,
                "response": str,
                "verdict": str,
                "all": [{"agent": str, "output": str, "success": bool}, ...],
            }
        """
        responses = self.broadcast(agent_names, task)
        successful = [r for r in responses if r["success"]]

        if not successful:
            return {
                "task": task, "winner": None,
                "response": "No agent completed the task.",
                "verdict": "", "all": responses,
            }

        formatted = "\n\n".join(
            f"[Option {i + 1} — {r['agent']}]:\n{r['output']}"
            for i, r in enumerate(successful)
        )
        judge_prompt = (
            f"Task: \"{task}\"\n\n"
            f"These AI agents each attempted the task:\n\n{formatted}\n\n"
            f"Which gave the BEST, most complete, most accurate response?\n"
            f"Reply in EXACTLY this format:\n"
            f"WINNER: <agent_name>\n"
            f"REASON: <one sentence>"
        )
        verdict = self.ai_adapter.chat([{"role": "user", "content": judge_prompt}])

        # Parse winner name from verdict
        winner: str | None = None
        for line in verdict.splitlines():
            if line.upper().startswith("WINNER:"):
                winner = line.split(":", 1)[1].strip()
                break

        winner_response = next(
            (r["output"] for r in successful if r["agent"] == winner),
            successful[0]["output"],   # fallback to first
        )
        return {
            "task": task,
            "winner": winner or successful[0]["agent"],
            "response": winner_response,
            "verdict": verdict,
            "all": responses,
        }

    # ------------------------------------------------------------------
    # Debate  —  two agents argue topic for N rounds
    # ------------------------------------------------------------------

    def debate(
        self, agent1_name: str, agent2_name: str, topic: str, rounds: int = 2
    ) -> dict:
        """
        Two agents exchange arguments on a topic.

        Returns:
            {
                "topic": str,
                "participants": [agent1_name, agent2_name],
                "transcript": [{"round": int, "agent": str, "argument": str}, ...],
                "summary": str,
            }
        """
        agent1 = self.registry.get(agent1_name)
        agent2 = self.registry.get(agent2_name)
        missing = [n for n, a in [(agent1_name, agent1), (agent2_name, agent2)] if a is None]
        if missing:
            return {"error": f"Agent(s) not found: {', '.join(missing)}"}

        transcript: list[dict] = []
        history = ""

        for round_num in range(1, rounds + 1):
            for agent, name in [(agent1, agent1_name), (agent2, agent2_name)]:
                if history:
                    prompt = (
                        f"Topic: {topic}\n\n"
                        f"Debate so far:\n{history}\n\n"
                        f"You are {name} (role: {agent.role}). "
                        f"Give your Round {round_num} argument. "
                        f"Be specific and concise (2-4 sentences)."
                    )
                else:
                    prompt = (
                        f"Topic: {topic}\n\n"
                        f"You are {name} (role: {agent.role}). "
                        f"Give your opening argument. "
                        f"Be specific and concise (2-4 sentences)."
                    )
                try:
                    argument = self.workflow_engine.execute(agent=agent, task=prompt)
                except Exception as exc:
                    argument = f"[Error: {exc}]"

                transcript.append({"round": round_num, "agent": name, "argument": argument})
                history += f"\n[{name}]: {argument}\n"

        summary_prompt = (
            f"Topic: \"{topic}\"\n\n"
            f"Debate transcript:\n{history}\n\n"
            f"Summarize the key arguments from each side and identify "
            f"any consensus reached or which side made stronger points."
        )
        summary = self.ai_adapter.chat([{"role": "user", "content": summary_prompt}])
        return {
            "topic": topic,
            "participants": [agent1_name, agent2_name],
            "transcript": transcript,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Auto-orchestrate  —  AI chooses agents + mode
    # ------------------------------------------------------------------

    def orchestrate(self, task: str) -> dict:
        """
        Let the AI decide which registered agents to use and in which
        coordination mode (pipeline/broadcast/vote/best_of), then execute.

        Returns:
            {
                "mode": str,
                "agents": list[str],
                "reason": str,
                "results": ...,   # structure depends on mode
            }
        """
        all_names = self.registry.list_names()
        if not all_names:
            return {"error": "No agents registered. Create agents first."}

        agent_lines = []
        for name in all_names:
            agent = self.registry.get(name)
            skills_str = ", ".join(agent.profile.get("skills", [])[:5])
            agent_lines.append(f"  • {name} — role: {agent.role}, skills: {skills_str}")

        plan_prompt = (
            f"You are an AI orchestration system. Available agents:\n"
            + "\n".join(agent_lines)
            + f"\n\nTask: \"{task}\"\n\n"
            f"Choose the best agents and coordination mode for this task.\n"
            f"Modes:\n"
            f"  pipeline  — sequential chain where each output feeds the next\n"
            f"  broadcast — all agents work independently on the same task\n"
            f"  vote      — agents answer, then AI synthesizes consensus\n"
            f"  best_of   — agents all try, AI picks the best answer\n\n"
            f"Reply in EXACTLY this format (no extra text):\n"
            f"MODE: <pipeline|broadcast|vote|best_of>\n"
            f"AGENTS: <agent1,agent2,...>\n"
            f"REASON: <one sentence>"
        )
        plan_text = self.ai_adapter.chat([{"role": "user", "content": plan_prompt}])

        # Parse AI plan
        mode = "broadcast"
        chosen: list[str] = list(all_names)
        reason = "(auto)"

        for line in plan_text.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("MODE:"):
                mode = stripped.split(":", 1)[1].strip().lower()
            elif upper.startswith("AGENTS:"):
                raw = stripped.split(":", 1)[1].strip()
                chosen = [a.strip() for a in raw.split(",") if a.strip()]
            elif upper.startswith("REASON:"):
                reason = stripped.split(":", 1)[1].strip()

        # Sanitize — drop any unknown agent names the AI hallucinated
        chosen = [a for a in chosen if self.registry.get(a) is not None] or list(all_names)

        # Validate mode
        valid_modes = {"pipeline", "broadcast", "vote", "best_of"}
        if mode not in valid_modes:
            mode = "broadcast"

        # Execute
        base = {"mode": mode, "agents": chosen, "reason": reason, "plan": plan_text}
        if mode == "pipeline":
            base["results"] = self.run_pipeline(chosen, task)
        elif mode == "vote":
            base.update(self.vote(chosen, task))
        elif mode == "best_of":
            base.update(self.best_of(chosen, task))
        else:   # broadcast
            base["results"] = self.broadcast(chosen, task)

        return base
