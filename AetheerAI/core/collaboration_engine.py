"""Autonomous multi-agent collaboration engine.

This module upgrades execution from isolated per-agent tasks to coordinated,
round-based collaboration with peer delegation via SwarmBus.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from utils.json_parser import extract_json

logger = logging.getLogger(__name__)


_MAX_TOPIC_LEN = 64
_MAX_REQUESTS_PER_TURN = 2
_MAX_TURNS_STORED = 300
_SYNTHESIS_TIMEOUT_SECONDS = 45


@dataclass
class CollaborationTurn:
    round_index: int
    agent_name: str
    contribution: str
    blockers: list[str] = field(default_factory=list)
    requests: list[dict[str, str]] = field(default_factory=list)
    delegated_responses: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_index,
            "agent": self.agent_name,
            "contribution": self.contribution,
            "blockers": self.blockers,
            "requests": self.requests,
            "delegated_responses": self.delegated_responses,
        }


@dataclass
class CollaborationSession:
    session_id: str
    goal: str
    team: list[str]
    rounds_requested: int
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    shared_context: str = ""
    final_synthesis: str = ""
    turns: list[CollaborationTurn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal": self.goal,
            "team": self.team,
            "rounds_requested": self.rounds_requested,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": (
                round(self.finished_at - self.started_at, 3)
                if self.finished_at is not None
                else round(time.time() - self.started_at, 3)
            ),
            "shared_context": self.shared_context,
            "final_synthesis": self.final_synthesis,
            "turns": [turn.to_dict() for turn in self.turns],
        }


class CollaborationEngine:
    """Runs collaborative sessions where agents actively help each other."""

    def __init__(self, registry, workflow_engine, ai_adapter, swarm_bus, memory) -> None:
        self.registry = registry
        self.workflow_engine = workflow_engine
        self.ai_adapter = ai_adapter
        self.swarm_bus = swarm_bus
        self.memory = memory

        self._sessions: dict[str, CollaborationSession] = {}
        self._lock = threading.RLock()

    def run(
        self,
        *,
        goal: str,
        agent_names: list[str],
        rounds: int = 2,
    ) -> dict[str, Any]:
        """Run a collaboration session and return the full session payload."""
        clean_agents = [name.strip() for name in agent_names if name and name.strip()]
        clean_agents = list(dict.fromkeys(clean_agents))
        if not clean_agents:
            raise ValueError("Collaboration requires at least one valid agent.")

        resolved_agents = [self.registry.get(name) for name in clean_agents]
        missing = [name for name, agent in zip(clean_agents, resolved_agents) if agent is None]
        if missing:
            raise ValueError(f"Collaboration agents not found: {', '.join(missing)}")

        bounded_rounds = max(1, min(int(rounds), 6))
        session = CollaborationSession(
            session_id=uuid.uuid4().hex,
            goal=goal,
            team=clean_agents,
            rounds_requested=bounded_rounds,
            shared_context="No shared context yet.",
        )

        self._register_capabilities(clean_agents)
        self._save_session(session)

        try:
            for round_index in range(1, bounded_rounds + 1):
                for agent_name in clean_agents:
                    agent = self.registry.get(agent_name)
                    if agent is None:
                        continue

                    turn = self._run_turn(
                        session=session,
                        round_index=round_index,
                        agent=agent,
                    )
                    session.turns.append(turn)
                    if len(session.turns) > _MAX_TURNS_STORED:
                        session.turns = session.turns[-_MAX_TURNS_STORED:]

                session.shared_context = self._synthesize_round_context(session=session, round_index=round_index)
                self._save_session(session)

            session.final_synthesis = self._final_synthesis(session)
            session.status = "completed"
        except Exception as exc:
            session.status = "failed"
            session.final_synthesis = f"Collaboration failed: {exc}"
            logger.error("CollaborationEngine: session %s failed: %s", session.session_id, exc)
            raise
        finally:
            session.finished_at = time.time()
            self._persist_session_memory(session)
            self._save_session(session)

        return session.to_dict()

    async def run_async(
        self,
        *,
        goal: str,
        agent_names: list[str],
        rounds: int = 2,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.run(goal=goal, agent_names=agent_names, rounds=rounds),
        )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.to_dict() if session else None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())[-max(1, limit):]
        return [item.to_dict() for item in sessions]

    def _run_turn(self, *, session: CollaborationSession, round_index: int, agent) -> CollaborationTurn:
        inbox_messages = self.swarm_bus.get_messages(agent.name, unread_only=True, max_messages=8)
        inbox_text = "\n".join(
            f"- [{msg.topic}] from {msg.sender}: {msg.payload[:300]}"
            for msg in inbox_messages
        ) or "(no peer messages)"

        prompt = (
            f"You are collaborating as agent '{agent.name}' ({agent.role}).\n"
            f"Goal: {session.goal}\n"
            f"Round: {round_index}/{session.rounds_requested}\n"
            f"Shared context:\n{session.shared_context[:3000]}\n\n"
            f"Unread peer messages:\n{inbox_text}\n\n"
            "Respond as JSON with keys:\n"
            "- contribution: short, concrete progress update\n"
            "- blockers: list of blockers\n"
            "- requests: list of objects {topic, request} when peer help is needed\n"
            "Keep requests short and specific."
        )

        raw = str(self.workflow_engine.execute(agent=agent, task=prompt))
        parsed = extract_json(raw, safe=True, default={})

        if isinstance(parsed, dict):
            contribution = str(parsed.get("contribution", "")).strip() or raw[:1200]
            blockers = parsed.get("blockers", []) if isinstance(parsed.get("blockers", []), list) else []
            raw_requests = parsed.get("requests", []) if isinstance(parsed.get("requests", []), list) else []
        else:
            contribution = raw[:1200]
            blockers = []
            raw_requests = []

        requests = self._normalize_requests(raw_requests)[:_MAX_REQUESTS_PER_TURN]
        delegated_responses: list[dict[str, str]] = []

        for req in requests:
            volunteer = self.swarm_bus.request_help(
                topic=req["topic"],
                payload=req["request"],
                sender=agent.name,
            )
            if not volunteer.resolved or not volunteer.volunteer:
                # Topic names from LLM output can be overly specific. Fall back
                # to a shared collaboration channel so peers can still assist.
                volunteer = self.swarm_bus.request_help(
                    topic="general",
                    payload=f"[{req['topic']}] {req['request']}",
                    sender=agent.name,
                )
            if not volunteer.resolved or not volunteer.volunteer:
                delegated_responses.append(
                    {
                        "topic": req["topic"],
                        "request": req["request"],
                        "volunteer": "",
                        "response": "No volunteer available.",
                    }
                )
                continue

            helper = self.registry.get(volunteer.volunteer)
            if helper is None:
                delegated_responses.append(
                    {
                        "topic": req["topic"],
                        "request": req["request"],
                        "volunteer": volunteer.volunteer,
                        "response": "Volunteer was not found in registry.",
                    }
                )
                continue

            helper_task = (
                f"Peer support request from {agent.name} for goal '{session.goal}'.\n"
                f"Topic: {req['topic']}\n"
                f"Request: {req['request']}\n"
                "Respond with concise actionable help."
            )
            helper_response = str(self.workflow_engine.execute(agent=helper, task=helper_task))
            self.swarm_bus.direct_message(
                payload=(
                    f"Peer response from {helper.name} on topic '{req['topic']}':\n"
                    f"{helper_response[:1000]}"
                ),
                sender=helper.name,
                recipient=agent.name,
                topic="peer_response",
            )

            delegated_responses.append(
                {
                    "topic": req["topic"],
                    "request": req["request"],
                    "volunteer": helper.name,
                    "response": helper_response[:1200],
                }
            )

        return CollaborationTurn(
            round_index=round_index,
            agent_name=agent.name,
            contribution=contribution,
            blockers=[str(item)[:200] for item in blockers[:5]],
            requests=requests,
            delegated_responses=delegated_responses,
        )

    def _synthesize_round_context(self, *, session: CollaborationSession, round_index: int) -> str:
        round_turns = [turn for turn in session.turns if turn.round_index == round_index]
        if not round_turns:
            return session.shared_context

        report = "\n\n".join(
            (
                f"Agent: {turn.agent_name}\n"
                f"Contribution: {turn.contribution}\n"
                f"Blockers: {', '.join(turn.blockers) if turn.blockers else '(none)'}\n"
                f"Delegations: "
                + (
                    "; ".join(
                        f"{item['topic']}->{item['volunteer'] or 'none'}" for item in turn.delegated_responses
                    )
                    if turn.delegated_responses
                    else "(none)"
                )
            )
            for turn in round_turns
        )

        prompt = (
            f"Goal: {session.goal}\n"
            f"Current shared context:\n{session.shared_context[:3000]}\n\n"
            f"Round {round_index} collaboration updates:\n{report[:5000]}\n\n"
            "Produce an updated shared context with:"
            " decisions made, resolved blockers, open issues, and next focus."
        )
        try:
            return str(
                self.ai_adapter.chat(
                    [{"role": "user", "content": prompt}],
                    timeout=_SYNTHESIS_TIMEOUT_SECONDS,
                    max_tokens=500,
                )
            )[:5000]
        except Exception as exc:
            logger.warning("CollaborationEngine: round synthesis fallback used: %s", exc)
            highlights = "\n".join(
                f"- {turn.agent_name}: {turn.contribution[:180]}"
                for turn in round_turns[:8]
            )
            return (
                f"Round {round_index} fallback summary.\n"
                f"Goal: {session.goal}\n"
                f"Highlights:\n{highlights or '- no contributions captured'}\n"
                "Next focus: continue resolving blockers and align on concrete deliverables."
            )[:5000]

    def _final_synthesis(self, session: CollaborationSession) -> str:
        transcript = "\n\n".join(
            (
                f"Round {turn.round_index} | {turn.agent_name}\n"
                f"Contribution: {turn.contribution}\n"
                f"Blockers: {', '.join(turn.blockers) if turn.blockers else '(none)'}"
            )
            for turn in session.turns
        )
        prompt = (
            f"Goal: {session.goal}\n"
            f"Final shared context:\n{session.shared_context[:4000]}\n\n"
            f"Collaboration transcript:\n{transcript[:12000]}\n\n"
            "Write a final team synthesis with: outcome, major contributions by role,"
            " unresolved risks, and concrete next actions."
        )
        try:
            return str(
                self.ai_adapter.chat(
                    [{"role": "user", "content": prompt}],
                    timeout=_SYNTHESIS_TIMEOUT_SECONDS,
                    max_tokens=700,
                )
            )[:6000]
        except Exception as exc:
            logger.warning("CollaborationEngine: final synthesis fallback used: %s", exc)
            return self._deterministic_final_synthesis(session)

    def _deterministic_final_synthesis(self, session: CollaborationSession) -> str:
        by_agent: dict[str, list[str]] = {}
        for turn in session.turns:
            by_agent.setdefault(turn.agent_name, []).append(turn.contribution)

        lines = [
            f"Outcome: Collaboration session for goal '{session.goal}' completed in fallback mode.",
            "Major contributions by role:",
        ]
        for agent_name, contributions in by_agent.items():
            lines.append(f"- {agent_name}: {contributions[-1][:220] if contributions else 'No contribution'}")

        unresolved: list[str] = []
        for turn in session.turns:
            unresolved.extend(turn.blockers)
        unresolved = [item for item in unresolved if item]

        lines.append(
            "Unresolved risks: "
            + (", ".join(unresolved[:6]) if unresolved else "None explicitly reported.")
        )
        lines.append("Next actions: finalize draft artifacts, validate assumptions, and run a review pass.")
        return "\n".join(lines)[:6000]

    def _register_capabilities(self, agent_names: list[str]) -> None:
        for name in agent_names:
            agent = self.registry.get(name)
            if agent is None:
                continue
            skills = [self._normalize_topic(skill) for skill in agent.profile.get("skills", []) if skill]
            role_topic = self._normalize_topic(agent.role)
            topics = list(dict.fromkeys(["general", role_topic, *skills]))
            self.swarm_bus.register_capabilities(
                agent_name=name,
                topics=topics,
                description=f"{agent.role} collaboration profile",
                priority=60,
            )

    def _persist_session_memory(self, session: CollaborationSession) -> None:
        entry = {
            "session_id": session.session_id,
            "goal": session.goal,
            "team": session.team,
            "status": session.status,
            "shared_context": session.shared_context,
            "final_synthesis": session.final_synthesis,
            "turn_count": len(session.turns),
            "timestamp": time.time(),
        }
        try:
            self.memory.append("collaboration_history", entry, namespace="global")
            self.memory.save(f"collaboration:{session.session_id}", entry, namespace="global")
        except Exception as exc:
            logger.debug("CollaborationEngine: memory persist skipped: %s", exc)

    def _save_session(self, session: CollaborationSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    @staticmethod
    def _normalize_topic(value: str) -> str:
        candidate = re.sub(r"[^a-z0-9_\-]+", "_", value.strip().lower())
        candidate = candidate.strip("_")
        if not candidate:
            return "general"
        return candidate[:_MAX_TOPIC_LEN]

    def _normalize_requests(self, raw_requests: list[Any]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in raw_requests:
            if not isinstance(item, dict):
                continue
            topic = self._normalize_topic(str(item.get("topic", "general")))
            request = str(item.get("request", "")).strip()
            if not request:
                continue
            normalized.append({"topic": topic, "request": request[:500]})
        return normalized
