"""
RiskAssessor — Autonomous risk evaluation layer for AetheerAI.

Closes the governance gaps:
  ❌ No budget controls       → FinancialRisk category with spend estimates
  ❌ No risk assessment layer → Multi-dimensional scoring before execution
  ❌ No permission robustness → Automatic BLOCK/WARN/PASS recommendations

Risk Categories
---------------
  financial    — cost exposure, budget overrun probability
  reputation   — brand/PR damage from outputs
  security     — data leak, injection, credential exposure
  compliance   — regulatory or policy violation
  operational  — service disruption, data corruption, irreversibility

Scoring
-------
Each category is scored 0.0–10.0 by the AI.
  0–3   LOW     → PASS
  4–6   MEDIUM  → WARN (log + surface to user, continue unless blocked)
  7–10  HIGH    → BLOCK (halt execution, require explicit override)

Overall score = weighted average across categories.
The final recommendation is the worst single-category decision.

Security
--------
- All inputs are capped at 3 000 chars before sending to AI.
- AI output is parsed as JSON; malformed responses default to WARN.
- Audit trail: every assessment is appended to memory/risk_log.jsonl.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RISK_LOG = Path(__file__).parent.parent / "memory" / "risk_log.jsonl"
_RISK_LOG.parent.mkdir(parents=True, exist_ok=True)

_MAX_INPUT_LEN: int = 3_000


class RiskLevel(str, Enum):
    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"


class RiskAction(str, Enum):
    PASS  = "PASS"
    WARN  = "WARN"
    BLOCK = "BLOCK"


# Map score ranges → level and recommended action
def _score_to_level(score: float) -> tuple[RiskLevel, RiskAction]:
    if score >= 7.0:
        return RiskLevel.HIGH, RiskAction.BLOCK
    if score >= 4.0:
        return RiskLevel.MEDIUM, RiskAction.WARN
    return RiskLevel.LOW, RiskAction.PASS


@dataclass
class CategoryScore:
    category: str
    score: float          # 0.0–10.0
    reasoning: str
    level: RiskLevel
    action: RiskAction


@dataclass
class RiskReport:
    assessment_id: str
    agent_name: str
    action: str
    context: str
    categories: list[CategoryScore] = field(default_factory=list)
    overall_score: float = 0.0
    overall_level: RiskLevel = RiskLevel.LOW
    recommendation: RiskAction = RiskAction.PASS
    summary: str = ""
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "agent_name":    self.agent_name,
            "action":        self.action,
            "context":       self.context,
            "overall_score": round(self.overall_score, 2),
            "overall_level": self.overall_level.value,
            "recommendation": self.recommendation.value,
            "summary":       self.summary,
            "assessed_at":   self.assessed_at,
            "categories": [
                {
                    "category":  c.category,
                    "score":     round(c.score, 2),
                    "reasoning": c.reasoning,
                    "level":     c.level.value,
                    "action":    c.action.value,
                }
                for c in self.categories
            ],
        }

    def is_blocked(self) -> bool:
        return self.recommendation == RiskAction.BLOCK

    def is_warned(self) -> bool:
        return self.recommendation == RiskAction.WARN


# ── Prompt templates ───────────────────────────────────────────────────────

_ASSESS_PROMPT = """\
You are an AI risk assessment engine for an autonomous multi-agent system.

Evaluate the RISK of the following agent action across all five categories.

AGENT  : {agent_name}
ACTION : {action}
CONTEXT: {context}

Score each category from 0.0 (no risk) to 10.0 (catastrophic risk).
Be practical — consider what could actually go wrong given this specific action.

Return ONLY valid JSON — no markdown, no commentary:
{{
  "categories": [
    {{
      "category":  "financial",
      "score":     <0.0-10.0>,
      "reasoning": "<one concise sentence>"
    }},
    {{
      "category":  "reputation",
      "score":     <0.0-10.0>,
      "reasoning": "<one concise sentence>"
    }},
    {{
      "category":  "security",
      "score":     <0.0-10.0>,
      "reasoning": "<one concise sentence>"
    }},
    {{
      "category":  "compliance",
      "score":     <0.0-10.0>,
      "reasoning": "<one concise sentence>"
    }},
    {{
      "category":  "operational",
      "score":     <0.0-10.0>,
      "reasoning": "<one concise sentence>"
    }}
  ],
  "summary": "<two sentences describing the primary risk concern and overall verdict>"
}}

Scoring guide:
  0–2  : negligible / no realistic risk
  3–4  : low risk, manageable with standard care
  5–6  : medium risk, warrants attention
  7–8  : high risk, should be reviewed before proceeding
  9–10 : critical / catastrophic, must be blocked
"""

# Category weights for overall score calculation
_WEIGHTS: dict[str, float] = {
    "financial":   0.25,
    "reputation":  0.15,
    "security":    0.30,
    "compliance":  0.20,
    "operational": 0.10,
}


# ── Assessor ───────────────────────────────────────────────────────────────

class RiskAssessor:
    """
    Evaluate actions before execution and return structured risk reports.

    Usage
    -----
    assessor = RiskAssessor(ai_adapter=kernel.ai_adapter, audit_logger=_audit)
    report = assessor.assess(agent_name="sender", action="Send email to 500 customers")
    if report.is_blocked():
        raise RuntimeError(f"Risk assessment BLOCKED: {report.summary}")
    elif report.is_warned():
        print(f"[RISK WARNING] {report.summary}")
    """

    def __init__(self, ai_adapter, audit_logger=None) -> None:
        self._ai = ai_adapter
        self._audit = audit_logger
        self._history: list[RiskReport] = []

    # ── Public API ────────────────────────────────────────────────────────

    def assess(
        self,
        agent_name: str,
        action: str,
        context: str = "",
    ) -> RiskReport:
        """
        Assess the risk of an agent action synchronously.

        Parameters
        ----------
        agent_name : Name of the agent proposing the action.
        action     : Short description of what the action will do.
        context    : Optional extra context (current task, memory snippets, etc.)

        Returns a RiskReport. Call report.is_blocked() / is_warned() to gate execution.
        """
        import uuid as _uuid

        # Sanitise and cap inputs
        safe_action  = str(action or "")[:_MAX_INPUT_LEN]
        safe_context = str(context or "")[:_MAX_INPUT_LEN]
        safe_agent   = str(agent_name or "unknown")[:200]

        prompt = _ASSESS_PROMPT.format(
            agent_name=safe_agent,
            action=safe_action,
            context=safe_context,
        )

        report = RiskReport(
            assessment_id=_uuid.uuid4().hex,
            agent_name=safe_agent,
            action=safe_action,
            context=safe_context,
        )

        try:
            raw = self._ai.chat([{"role": "user", "content": prompt}])
            data = _parse_json(raw)
            report = self._build_report(report, data)
        except Exception as exc:
            logger.warning("RiskAssessor: AI assessment failed, defaulting to WARN: %s", exc)
            # Safe default — warn on failure rather than blindly pass
            report.overall_score = 5.0
            report.overall_level = RiskLevel.MEDIUM
            report.recommendation = RiskAction.WARN
            report.summary = f"Risk assessment unavailable ({exc}); defaulting to WARN."

        self._history.append(report)
        self._log(report)

        logger.info(
            "RiskAssessor: %s — '%s' → %s (score=%.1f)",
            safe_agent, safe_action[:60], report.recommendation.value, report.overall_score,
        )
        return report

    def assess_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        tool_kwargs: dict[str, Any],
    ) -> RiskReport:
        """Convenience wrapper for assessing a tool call before execution."""
        kwargs_str = json.dumps(tool_kwargs, default=str)[:500]
        action = f"Call tool '{tool_name}' with args: {kwargs_str}"
        return self.assess(agent_name=agent_name, action=action)

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent assessment reports as dicts."""
        return [r.to_dict() for r in self._history[-limit:]]

    def clear_history(self) -> None:
        self._history.clear()

    # ── Internal ──────────────────────────────────────────────────────────

    def _build_report(self, report: RiskReport, data: dict[str, Any]) -> RiskReport:
        cats: list[CategoryScore] = []
        raw_cats = data.get("categories", [])

        for item in raw_cats:
            cat_name = str(item.get("category", "unknown")).lower()
            raw_score = item.get("score", 5.0)
            try:
                score = max(0.0, min(10.0, float(raw_score)))
            except (TypeError, ValueError):
                score = 5.0
            reasoning = str(item.get("reasoning", ""))[:300]
            level, action = _score_to_level(score)
            cats.append(CategoryScore(
                category=cat_name,
                score=score,
                reasoning=reasoning,
                level=level,
                action=action,
            ))

        # Treat malformed or empty model output as an assessment failure.
        # The caller will apply the safe WARN default path.
        if not cats:
            raise ValueError("Risk assessment response missing category scores.")

        # Weighted overall score
        total_weight = 0.0
        weighted_sum = 0.0
        for c in cats:
            w = _WEIGHTS.get(c.category, 0.10)
            weighted_sum += c.score * w
            total_weight += w

        overall = (weighted_sum / total_weight) if total_weight > 0 else 5.0
        overall_level, _ = _score_to_level(overall)

        # Recommendation = worst-case individual action
        worst_action = RiskAction.PASS
        for c in cats:
            if c.action == RiskAction.BLOCK:
                worst_action = RiskAction.BLOCK
                break
            if c.action == RiskAction.WARN:
                worst_action = RiskAction.WARN

        report.categories    = cats
        report.overall_score = overall
        report.overall_level = overall_level
        report.recommendation = worst_action
        report.summary       = str(data.get("summary", ""))[:500]
        return report

    def _log(self, report: RiskReport) -> None:
        """Append the report to the persistent JSONL log."""
        try:
            with _RISK_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(report.to_dict()) + "\n")
        except Exception as exc:
            logger.warning("RiskAssessor: failed to write risk log: %s", exc)

        # Also log to audit logger if wired up
        if self._audit:
            try:
                self._audit.log(
                    event="risk_assessment",
                    data={
                        "assessment_id": report.assessment_id,
                        "agent":         report.agent_name,
                        "action":        report.action[:120],
                        "recommendation": report.recommendation.value,
                        "score":         round(report.overall_score, 2),
                    },
                )
            except Exception:
                pass


# ── Utility ────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict[str, Any]:
    """Robustly extract the first JSON object from an LLM response."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first { ... } block
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}
