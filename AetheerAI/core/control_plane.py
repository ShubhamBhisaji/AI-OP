"""
Agentic Control Plane — Multi-Agent Orchestration & Conflict Resolution

As agent fleets scale to hundreds of autonomous workers, they inevitably
develop conflicting objectives.  The Control Plane is the centralised
"Supreme Court" — it registers every agent's goals, detects when two
agents pursue incompatible strategies, and mediates disputes using the
business's own KPIs as the constitution.

Architecture
------------
  AgentGoal          — an agent's registered objectives and KPIs
  Conflict           — a detected clash between two or more agents
  Resolution         — the Supreme Court verdict with binding policy
  EscalationTicket   — item the human must review
  ControlPlane       — main facade

Usage
-----
    cp = ControlPlane(ai_adapter)

    cp.register_agent("EfficiencyAgent", goals=["reduce cost"], kpis=["cost_per_unit"])
    cp.register_agent("GrowthAgent", goals=["increase ad spend"], kpis=["revenue"])

    conflicts = cp.detect_conflicts()
    for c in conflicts:
        resolution = cp.mediate(c, business_kpis={"primary": "net_profit"})
        print(resolution.verdict)          # binding policy
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class AgentGoal:
    agent_name: str
    goals: list[str]            # e.g. ["reduce cost by 20%", "minimise latency"]
    kpis: list[str]             # e.g. ["cost_per_unit", "p99_latency_ms"]
    priority: int = 5           # 1 (critical) – 10 (low)
    department: str = "general"
    constraints: list[str] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)


@dataclass
class Conflict:
    conflict_id: str
    agents: list[str]
    description: str
    conflicting_goals: dict[str, list[str]]  # agent_name -> goals that clash
    severity: str = "medium"    # low | medium | high | critical
    detected_at: float = field(default_factory=time.time)
    context: str = ""


@dataclass
class Resolution:
    conflict_id: str
    verdict: str                 # The binding policy decision
    winning_kpi: str             # KPI that broke the tie
    affected_agents: list[str]
    recommended_actions: list[str]
    reasoning: str
    override_map: dict[str, str] = field(default_factory=dict)  # agent → new directive
    resolved_at: float = field(default_factory=time.time)


@dataclass
class EscalationTicket:
    ticket_id: str
    agent_name: str
    issue: str
    context: str
    severity: str = "medium"
    status: str = "open"        # open | acknowledged | resolved
    created_at: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════════════
# Control Plane
# ═══════════════════════════════════════════════════════════════════════════


class ControlPlane:
    """
    Centralised governance layer for multi-agent fleets.

    Parameters
    ----------
    ai_adapter : AIAdapter  — used for AI-powered conflict mediation.
    """

    def __init__(self, ai_adapter):
        self.ai_adapter = ai_adapter
        self._registry:     dict[str, AgentGoal]     = {}
        self._conflicts:    list[Conflict]            = []
        self._resolutions:  list[Resolution]          = []
        self._escalations:  list[EscalationTicket]    = []
        # Collaboration graph: agent → list of agents it depends on
        self._collab_graph: dict[str, list[str]]      = {}

    # ──────────────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────────────

    def register_agent(
        self,
        agent_name: str,
        goals: list[str],
        kpis: list[str],
        priority: int = 5,
        department: str = "general",
        constraints: list[str] | None = None,
        depends_on: list[str] | None = None,
    ) -> AgentGoal:
        """Register an agent and its objectives with the Control Plane."""
        goal = AgentGoal(
            agent_name=agent_name,
            goals=goals,
            kpis=kpis,
            priority=priority,
            department=department,
            constraints=constraints or [],
        )
        self._registry[agent_name] = goal
        if depends_on:
            self._collab_graph[agent_name] = depends_on
        logger.info("ControlPlane: registered %s (priority=%d)", agent_name, priority)
        return goal

    def unregister_agent(self, agent_name: str) -> bool:
        removed = self._registry.pop(agent_name, None)
        self._collab_graph.pop(agent_name, None)
        return removed is not None

    def list_agents(self) -> list[dict]:
        return [
            {
                "name": g.agent_name,
                "goals": g.goals,
                "kpis": g.kpis,
                "priority": g.priority,
                "department": g.department,
            }
            for g in self._registry.values()
        ]

    # ──────────────────────────────────────────────────────────────────
    # Conflict detection
    # ──────────────────────────────────────────────────────────────────

    _CONFLICTING_KEYWORDS: dict[str, list[str]] = {
        "cost":     ["spend", "invest", "grow", "expand", "increase budget"],
        "speed":    ["thorough", "careful", "slow", "review", "verify"],
        "privacy":  ["share", "centralise", "aggregate", "log", "export"],
        "autonomy": ["approve", "human", "manual", "confirm", "review"],
    }

    def detect_conflicts(self) -> list[Conflict]:
        """
        Scan the agent registry for goal conflicts.
        Uses keyword heuristics + cross-agent KPI comparison.
        Returns newly detected conflicts (also appended to internal log).
        """
        agents = list(self._registry.values())
        new_conflicts: list[Conflict] = []

        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                a, b = agents[i], agents[j]
                clashes_a, clashes_b = [], []

                for axis, opposing_words in self._CONFLICTING_KEYWORDS.items():
                    a_text = " ".join(a.goals + a.kpis).lower()
                    b_text = " ".join(b.goals + b.kpis).lower()
                    a_has_axis = axis in a_text
                    b_opposes  = any(w in b_text for w in opposing_words)
                    b_has_axis = axis in b_text
                    a_opposes  = any(w in a_text for w in opposing_words)

                    if (a_has_axis and b_opposes) or (b_has_axis and a_opposes):
                        clashes_a.extend([g for g in a.goals if axis in g.lower()])
                        clashes_b.extend([g for g in b.goals if any(w in g.lower() for w in opposing_words)])

                if clashes_a or clashes_b:
                    severity = (
                        "high" if (a.priority <= 3 or b.priority <= 3)
                        else "medium"
                    )
                    conflict = Conflict(
                        conflict_id=str(uuid.uuid4())[:8],
                        agents=[a.agent_name, b.agent_name],
                        description=(
                            f"{a.agent_name} and {b.agent_name} have opposing objectives."
                        ),
                        conflicting_goals={
                            a.agent_name: clashes_a or a.goals[:1],
                            b.agent_name: clashes_b or b.goals[:1],
                        },
                        severity=severity,
                    )
                    self._conflicts.append(conflict)
                    new_conflicts.append(conflict)

        return new_conflicts

    # ──────────────────────────────────────────────────────────────────
    # Supreme Court Mediation
    # ──────────────────────────────────────────────────────────────────

    def mediate(
        self,
        conflict: Conflict | str,
        business_kpis: dict | None = None,
    ) -> Resolution:
        """
        AI-powered mediation.  The Master AI acts as Supreme Court —
        it weighs each agent's goals against the business's top KPIs
        and issues a binding policy resolution.

        Parameters
        ----------
        conflict       : Conflict object or conflict_id string.
        business_kpis  : e.g. {"primary": "net_profit", "secondary": "nps_score"}
        """
        if isinstance(conflict, str):
            conflict = next((c for c in self._conflicts if c.conflict_id == conflict), None)
            if not conflict:
                raise ValueError(f"Conflict '{conflict}' not found.")

        business_kpis = business_kpis or {"primary": "net_profit", "secondary": "customer_satisfaction"}

        # Build agents' full profiles
        agent_profiles = {}
        for name in conflict.agents:
            g = self._registry.get(name)
            if g:
                agent_profiles[name] = {
                    "goals": g.goals,
                    "kpis": g.kpis,
                    "priority": g.priority,
                    "constraints": g.constraints,
                }

        prompt = f"""You are the Supreme Court AI for a multi-agent system.
Two or more agents have conflicting goals and you must issue a binding resolution.

BUSINESS KPIs (highest authority):
{json.dumps(business_kpis, indent=2)}

CONFLICT:
{conflict.description}
Severity: {conflict.severity}

AGENT PROFILES:
{json.dumps(agent_profiles, indent=2)}

CONFLICTING GOALS:
{json.dumps(conflict.conflicting_goals, indent=2)}

Issue a binding Supreme Court resolution. Return ONLY valid JSON:
{{
  "verdict": "<binding policy — 2-3 sentences>",
  "winning_kpi": "<which business KPI guided the decision>",
  "recommended_actions": ["<action for agent 1>", "<action for agent 2>"],
  "reasoning": "<judicial reasoning — cite the business KPI and why it takes precedence>",
  "override_map": {{
    "<agent_name>": "<new directive for this agent>"
  }}
}}"""

        raw = self.ai_adapter.chat([
            {"role": "system", "content": "You are a judicial AI mediator. Return valid JSON only."},
            {"role": "user", "content": prompt},
        ])

        data = self._parse_json(raw)
        resolution = Resolution(
            conflict_id=conflict.conflict_id,
            verdict=data.get("verdict", raw[:300]),
            winning_kpi=data.get("winning_kpi", business_kpis.get("primary", "net_profit")),
            affected_agents=conflict.agents,
            recommended_actions=data.get("recommended_actions", []),
            reasoning=data.get("reasoning", ""),
            override_map=data.get("override_map", {}),
        )
        self._resolutions.append(resolution)
        logger.info("ControlPlane: mediated conflict %s → verdict issued", conflict.conflict_id)
        return resolution

    # ──────────────────────────────────────────────────────────────────
    # Escalation
    # ──────────────────────────────────────────────────────────────────

    def escalate(
        self,
        agent_name: str,
        issue: str,
        context: str = "",
        severity: str = "medium",
    ) -> EscalationTicket:
        """Create a human-review escalation ticket."""
        ticket = EscalationTicket(
            ticket_id=str(uuid.uuid4())[:8],
            agent_name=agent_name,
            issue=issue,
            context=context,
            severity=severity,
        )
        self._escalations.append(ticket)
        logger.warning("ControlPlane: escalation %s from %s — %s", ticket.ticket_id, agent_name, issue)
        return ticket

    def acknowledge_escalation(self, ticket_id: str) -> bool:
        for t in self._escalations:
            if t.ticket_id == ticket_id:
                t.status = "acknowledged"
                return True
        return False

    def resolve_escalation(self, ticket_id: str) -> bool:
        for t in self._escalations:
            if t.ticket_id == ticket_id:
                t.status = "resolved"
                return True
        return False

    # ──────────────────────────────────────────────────────────────────
    # Status Board
    # ──────────────────────────────────────────────────────────────────

    def status_board(self) -> dict:
        """Return the full multi-agent status board."""
        open_tickets  = [t for t in self._escalations if t.status == "open"]
        open_conflicts = [
            c for c in self._conflicts
            if not any(r.conflict_id == c.conflict_id for r in self._resolutions)
        ]
        return {
            "agents_registered": len(self._registry),
            "total_conflicts_detected": len(self._conflicts),
            "unresolved_conflicts": len(open_conflicts),
            "open_escalations": len(open_tickets),
            "resolutions_issued": len(self._resolutions),
            "departments": list({g.department for g in self._registry.values()}),
            "high_priority_agents": [
                g.agent_name for g in self._registry.values() if g.priority <= 3
            ],
        }

    def resolution_history(self) -> list[dict]:
        return [
            {
                "conflict_id": r.conflict_id,
                "verdict": r.verdict[:120],
                "winning_kpi": r.winning_kpi,
                "agents": r.affected_agents,
                "resolved_at": r.resolved_at,
            }
            for r in self._resolutions
        ]

    def open_conflicts(self) -> list[dict]:
        resolved_ids = {r.conflict_id for r in self._resolutions}
        return [
            {
                "conflict_id": c.conflict_id,
                "agents": c.agents,
                "description": c.description,
                "severity": c.severity,
                "goals": c.conflicting_goals,
            }
            for c in self._conflicts
            if c.conflict_id not in resolved_ids
        ]

    def open_escalations(self) -> list[dict]:
        return [
            {
                "ticket_id": t.ticket_id,
                "agent": t.agent_name,
                "issue": t.issue,
                "severity": t.severity,
                "status": t.status,
            }
            for t in self._escalations
            if t.status in ("open", "acknowledged")
        ]

    def collaboration_matrix(self) -> dict[str, list[str]]:
        """Return the dependency graph between agents."""
        return dict(self._collab_graph)

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> dict:
        import re
        for pattern in (r"```(?:json)?\s*([\s\S]+?)```", r"\{[\s\S]+\}"):
            m = re.search(pattern, text)
            if m:
                fragment = m.group(1) if "```" in pattern else m.group()
                try:
                    return json.loads(fragment)
                except json.JSONDecodeError:
                    pass
        return {}
