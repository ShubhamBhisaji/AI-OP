"""
priority_controller.py — Global Priority Controller & Agent Constitution.

Implements a "Constitutional AI" governance layer for multi-agent conflicts.

Problem: In a multi-agent system, agents with opposing objectives will
conflict. A Cost-Saving agent shuts down the server a Scaling agent just
provisioned. Without a referee, the system thrashes or the wrong agent wins.

Solution: A Constitution — a ranked set of business rules. Before any
high-impact agent action executes, the Priority Controller evaluates it
against ALL active rules using the Master AI. Conflicts are resolved by
priority score; ambiguous cases can be escalated to a human.

Key concepts
------------
ConstitutionRule   : One business rule with a priority weight (0–100).
ConstitutionContext: Named operational mode (e.g. "product_launch").
                     Rules can be scoped to specific contexts.
ActionDecision     : Result of evaluating a proposed agent action.
                     Outcome is ALLOW / BLOCK / WARN / ESCALATE.
PriorityController : The referee — evaluates actions, resolves conflicts,
                     and records every decision to the audit log.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

class ActionOutcome(str, Enum):
    ALLOW    = "allow"     # action is permitted
    WARN     = "warn"      # permitted but flagged in audit log
    BLOCK    = "block"     # action is denied; agent receives a refusal message
    ESCALATE = "escalate"  # pause and request human review


@dataclass
class ConstitutionRule:
    """
    A single business rule in the Constitution.

    Attributes
    ----------
    name            : Unique rule identifier (e.g. "uptime_over_cost").
    rule_text       : Plain-English statement of the rule.
    priority        : 0–100.  Higher priority rules override lower ones.
                      Rules with the same priority are ANDed together.
    active_contexts : If non-empty, the rule only fires in these contexts.
                      Empty set means "always active".
    default_outcome : What to do when the AI decides the action conflicts.
    """
    name: str
    rule_text: str
    priority: int = 50
    active_contexts: set[str] = field(default_factory=set)
    default_outcome: ActionOutcome = ActionOutcome.BLOCK

    # ── Preset factory methods ────────────────────────────────────────

    @classmethod
    def uptime_over_cost(cls) -> "ConstitutionRule":
        return cls(
            name="uptime_over_cost",
            rule_text=(
                "Uptime and service availability are always the highest priority. "
                "No cost-saving action may shut down, scale down, or deprovision "
                "any service that is currently serving live user traffic. "
                "Cost-saving can only happen when traffic is below 5% of peak."
            ),
            priority=90,
            active_contexts={"product_launch", "high_traffic"},
            default_outcome=ActionOutcome.BLOCK,
        )

    @classmethod
    def security_first(cls) -> "ConstitutionRule":
        return cls(
            name="security_first",
            rule_text=(
                "No agent may disable security controls, expose credentials, "
                "open unauthenticated network ports, or weaken firewall rules. "
                "Security hardening always takes precedence over convenience or speed."
            ),
            priority=99,
            active_contexts=set(),   # always active
            default_outcome=ActionOutcome.BLOCK,
        )

    @classmethod
    def human_approval_for_billing(cls) -> "ConstitutionRule":
        return cls(
            name="human_approval_for_billing",
            rule_text=(
                "Any action that incurs cloud spend above $50/hour or commits to "
                "recurring billing must be escalated to a human approver before execution."
            ),
            priority=80,
            active_contexts=set(),
            default_outcome=ActionOutcome.ESCALATE,
        )

    @classmethod
    def no_data_deletion_without_backup(cls) -> "ConstitutionRule":
        return cls(
            name="no_data_deletion_without_backup",
            rule_text=(
                "No agent may delete, truncate, or overwrite production data unless "
                "a verified backup exists and its integrity has been confirmed in the "
                "last 24 hours."
            ),
            priority=85,
            active_contexts=set(),
            default_outcome=ActionOutcome.BLOCK,
        )


@dataclass
class ActionDecision:
    """Result of the Priority Controller evaluating a single agent action."""
    agent_name:      str
    action_summary:  str
    outcome:         ActionOutcome
    reasoning:       str
    violated_rule:   str | None = None
    timestamp:       float = field(default_factory=time.time)

    def is_permitted(self) -> bool:
        return self.outcome in (ActionOutcome.ALLOW, ActionOutcome.WARN)

    def to_dict(self) -> dict:
        return {
            "agent_name":     self.agent_name,
            "action_summary": self.action_summary[:300],
            "outcome":        self.outcome.value,
            "reasoning":      self.reasoning[:500],
            "violated_rule":  self.violated_rule,
            "timestamp":      self.timestamp,
        }


@dataclass
class ConflictResolution:
    """Result of resolving two conflicting agent actions."""
    winner:          str          # agent name whose action is permitted
    loser:           str          # agent name whose action is blocked
    winning_action:  str
    losing_action:   str
    reasoning:       str
    priority_delta:  int          # difference in priority scores
    timestamp:       float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_EVALUATE_PROMPT = """\
You are AetheerAI's Priority Controller — a neutral referee for multi-agent conflicts.

ACTIVE CONSTITUTION RULES (ordered by priority, highest first):
{rules_block}

CURRENT OPERATIONAL CONTEXT: {context}

PROPOSED AGENT ACTION:
Agent : {agent_name}
Action: {action_summary}

Evaluate whether this action is consistent with the Constitution rules.
If it conflicts with ANY rule, state which rule and why.

Respond ONLY in this exact format (no other text):
OUTCOME: <ALLOW|WARN|BLOCK|ESCALATE>
RULE_VIOLATED: <rule name or NONE>
REASONING: <one concise sentence>
"""

_CONFLICT_PROMPT = """\
You are AetheerAI's Priority Controller resolving a direct conflict.

AGENT A: {agent_a} wants to: {action_a}
AGENT B: {agent_b} wants to: {action_b}

These actions are mutually exclusive. The Constitution says:
{rules_block}

Current context: {context}

Which agent's action should proceed? Consider the business priority and context.

Respond ONLY in this exact format:
WINNER: <agent_a|agent_b>
REASONING: <one or two sentences explaining the priority decision>
"""


# ---------------------------------------------------------------------------
# PriorityController
# ---------------------------------------------------------------------------

class PriorityController:
    """
    The Constitutional referee for multi-agent environments.

    Usage
    -----
    # Add rules to the constitution
    ctrl = PriorityController(ai_adapter=kernel.ai_adapter)
    ctrl.add_rule(ConstitutionRule.uptime_over_cost())
    ctrl.add_rule(ConstitutionRule.security_first())

    # Set current operational context
    ctrl.set_context("product_launch")

    # Evaluate a proposed action
    decision = ctrl.evaluate("cost_agent", "Scale down web servers to 1 instance")
    if not decision.is_permitted():
        # Block the action
        ...

    # Resolve a conflict between two agents
    resolution = ctrl.resolve_conflict(
        "cost_agent",    "shutdown db-replica-2",
        "scaling_agent", "keep all replicas running for failover",
    )
    """

    def __init__(
        self,
        ai_adapter,
        audit_logger=None,
    ) -> None:
        self.ai_adapter = ai_adapter
        self._audit = audit_logger
        self._rules: dict[str, ConstitutionRule] = {}
        self._context: str = "default"
        self._history: list[ActionDecision] = []
        self._lock = threading.Lock()
        logger.info("PriorityController initialised (context='default').")

    # ── Rule management ───────────────────────────────────────────────

    def add_rule(self, rule: ConstitutionRule) -> None:
        with self._lock:
            self._rules[rule.name] = rule
        logger.info("Constitution: added rule '%s' (priority=%d).", rule.name, rule.priority)

    def remove_rule(self, name: str) -> bool:
        with self._lock:
            existed = name in self._rules
            self._rules.pop(name, None)
        if existed:
            logger.info("Constitution: removed rule '%s'.", name)
        return existed

    def set_context(self, context: str) -> None:
        self._context = context
        logger.info("Constitution: context switched to '%s'.", context)

    def list_rules(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "name": r.name,
                    "priority": r.priority,
                    "rule_text": r.rule_text,
                    "active_contexts": sorted(r.active_contexts),
                    "default_outcome": r.default_outcome.value,
                }
                for r in sorted(self._rules.values(), key=lambda x: -x.priority)
            ]

    # ── Core evaluation ───────────────────────────────────────────────

    def _active_rules(self) -> list[ConstitutionRule]:
        """Return rules applicable to the current context, sorted by priority desc."""
        result = []
        with self._lock:
            for r in self._rules.values():
                if not r.active_contexts or self._context in r.active_contexts:
                    result.append(r)
        return sorted(result, key=lambda x: -x.priority)

    def _build_rules_block(self, rules: list[ConstitutionRule]) -> str:
        if not rules:
            return "(No constitution rules active — all actions permitted by default)"
        lines = []
        for r in rules:
            ctx = f" [contexts: {', '.join(sorted(r.active_contexts))}]" if r.active_contexts else ""
            lines.append(f"  [{r.priority:3d}] {r.name}{ctx}: {r.rule_text}")
        return "\n".join(lines)

    def evaluate(
        self,
        agent_name: str,
        action_summary: str,
    ) -> ActionDecision:
        """
        Evaluate a proposed agent action against the active Constitution.

        Parameters
        ----------
        agent_name     : Name of the agent proposing the action.
        action_summary : Plain-English description of what the agent wants to do.

        Returns an ActionDecision.  If no rules are active, returns ALLOW.
        """
        active = self._active_rules()

        # Fast-path: nothing to check
        if not active:
            decision = ActionDecision(
                agent_name=agent_name,
                action_summary=action_summary,
                outcome=ActionOutcome.ALLOW,
                reasoning="No constitution rules active.",
            )
            self._record(decision)
            return decision

        prompt = _EVALUATE_PROMPT.format(
            rules_block=self._build_rules_block(active),
            context=self._context,
            agent_name=agent_name,
            action_summary=action_summary,
        )

        try:
            raw = self.ai_adapter.chat(
                messages=[{"role": "user", "content": prompt}]
            ).strip()
        except Exception as exc:
            logger.warning("PriorityController.evaluate AI call failed: %s — defaulting to WARN.", exc)
            raw = "OUTCOME: WARN\nRULE_VIOLATED: NONE\nREASONING: AI evaluation unavailable; action flagged for review."

        outcome, rule_violated, reasoning = self._parse_evaluation(raw, active)
        decision = ActionDecision(
            agent_name=agent_name,
            action_summary=action_summary,
            outcome=outcome,
            reasoning=reasoning,
            violated_rule=rule_violated if rule_violated != "NONE" else None,
        )
        self._record(decision)

        if self._audit:
            try:
                self._audit.log(
                    event="constitution_check",
                    agent=agent_name,
                    details=decision.to_dict(),
                )
            except Exception:
                pass

        return decision

    def _parse_evaluation(
        self,
        raw: str,
        active_rules: list[ConstitutionRule],
    ) -> tuple[ActionOutcome, str, str]:
        outcome = ActionOutcome.WARN
        rule_violated = "NONE"
        reasoning = "No reasoning provided."

        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("OUTCOME:"):
                val = line.split(":", 1)[1].strip().upper()
                try:
                    outcome = ActionOutcome(val.lower())
                except ValueError:
                    pass
            elif line.upper().startswith("RULE_VIOLATED:"):
                rule_violated = line.split(":", 1)[1].strip()
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        # If AI said BLOCK but no rule listed, infer highest-priority rule
        if outcome == ActionOutcome.BLOCK and rule_violated == "NONE" and active_rules:
            rule_violated = active_rules[0].name

        return outcome, rule_violated, reasoning

    def resolve_conflict(
        self,
        agent_a: str,
        action_a: str,
        agent_b: str,
        action_b: str,
    ) -> ConflictResolution:
        """
        Resolve a direct conflict between two agents.

        Both agents want to do mutually exclusive things. The Constitution
        + Master AI determine which action proceeds and which is blocked.
        """
        active = self._active_rules()
        prompt = _CONFLICT_PROMPT.format(
            agent_a=agent_a,
            action_a=action_a,
            agent_b=agent_b,
            action_b=action_b,
            rules_block=self._build_rules_block(active),
            context=self._context,
        )

        try:
            raw = self.ai_adapter.chat(
                messages=[{"role": "user", "content": prompt}]
            ).strip()
        except Exception as exc:
            logger.warning("PriorityController.resolve_conflict AI call failed: %s", exc)
            raw = f"WINNER: agent_a\nREASONING: AI unavailable; defaulting to first-registered agent."

        winner_key = "agent_a"
        reasoning = "No reasoning provided."
        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("WINNER:"):
                winner_key = line.split(":", 1)[1].strip().lower()
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        if winner_key == "agent_b":
            winner, loser = agent_b, agent_a
            winning_action, losing_action = action_b, action_a
        else:
            winner, loser = agent_a, agent_b
            winning_action, losing_action = action_a, action_b

        resolution = ConflictResolution(
            winner=winner,
            loser=loser,
            winning_action=winning_action,
            losing_action=losing_action,
            reasoning=reasoning,
            priority_delta=active[0].priority if active else 0,
        )
        logger.info(
            "Conflict resolved: %s wins (action: '%s…') over %s.",
            winner, winning_action[:60], loser,
        )
        return resolution

    # ── History ───────────────────────────────────────────────────────

    def _record(self, decision: ActionDecision) -> None:
        with self._lock:
            self._history.append(decision)
            # Keep last 1000 decisions in memory
            if len(self._history) > 1000:
                self._history = self._history[-1000:]

    def decision_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [d.to_dict() for d in self._history[-limit:]]

    def blocked_count(self) -> int:
        with self._lock:
            return sum(1 for d in self._history if d.outcome == ActionOutcome.BLOCK)

    def stats(self) -> dict:
        with self._lock:
            total = len(self._history)
            by_outcome: dict[str, int] = {}
            for d in self._history:
                by_outcome[d.outcome.value] = by_outcome.get(d.outcome.value, 0) + 1
        return {
            "total_evaluations": total,
            "active_rules": len(self._rules),
            "current_context": self._context,
            "by_outcome": by_outcome,
        }
