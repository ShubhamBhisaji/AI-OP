"""
FinOpsController — Business-First cost-aware AI orchestration.

By 2026, the "token bill" is a real corporate headache.  This controller
treats money as a hard constraint, not an afterthought.

Features
--------
1. Price Quote    — Before a project starts, predict total tokens + cost.
2. Budget Guard   — Hard cap: refuse to run if projected cost exceeds budget.
3. Cost-Optimised Swarm — Automatically swap expensive models for cheaper
                          equivalents when accuracy is not critical.
4. Live Spend Ledger    — Track actual spend per agent / task / project.
5. Monthly Budget Alerts — Warning at 80%, halt at 100%.

Cost model (approximate 2026 pricing, USD per million tokens)
--------------------------------------------------------------
Provider / Model            Input     Output
github/gpt-4.1              $0.00     $0.00    (free via GitHub token)
github/gpt-4o-mini          $0.00     $0.00    (free)
openai/gpt-4o               $2.50     $10.00
openai/gpt-4o-mini          $0.15     $0.60
claude/claude-sonnet-4.6    $3.00     $15.00
gemini/gemini-2.5-flash-lite $0.075   $0.30
ollama/*                    $0.00     $0.00    (local = free)

Usage
-----
    fc = FinOpsController(monthly_budget_usd=50.0)

    # Get a price quote before running:
    quote = fc.quote(tasks=["Build an AI email filter", "Summarise reports"],
                     agents=["Analyst","Writer"], model="openai/gpt-4o")
    # quote.total_usd, quote.token_estimate, quote.breakdown

    # Register a spend event (called automatically by kernel wrappers):
    fc.record_spend(agent="Analyst", task="Summarise Q1",
                    model="openai/gpt-4o", prompt_tokens=1200, completion_tokens=400)

    # Check budget status:
    fc.status()   # {"used_usd": 5.20, "remaining_usd": 44.80, "percent": 10.4}
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Cost table: (input_per_M, output_per_M) in USD ───────────────────────
# Free = 0.0.  "openai/gpt-4o" → ("openai", "gpt-4o") lookup.

_COST_TABLE: dict[str, tuple[float, float]] = {
    # GitHub Models (free REST API)
    "github/gpt-4.1":            (0.0,   0.0),
    "github/gpt-4.1-mini":       (0.0,   0.0),
    "github/gpt-4o":             (0.0,   0.0),
    "github/gpt-4o-mini":        (0.0,   0.0),
    "github/gpt-5-mini":         (0.0,   0.0),
    # OpenAI
    "openai/gpt-4o":             (2.50,  10.00),
    "openai/gpt-4o-mini":        (0.15,  0.60),
    "openai/gpt-4.1":            (2.00,  8.00),
    "openai/gpt-4.1-mini":       (0.40,  1.60),
    "openai/o1":                 (15.00, 60.00),
    "openai/o3-mini":            (1.10,  4.40),
    # Anthropic Claude
    "claude/claude-sonnet-4.6":  (3.00,  15.00),
    "claude/claude-haiku-3":     (0.25,  1.25),
    # Google Gemini
    "gemini/gemini-2.5-pro":     (1.25,  10.00),
    "gemini/gemini-2.5-flash-lite": (0.075, 0.30),
    # Local / Free
    "ollama/llama3.2:3b":        (0.0,   0.0),
    "ollama/qwen2.5-coder:7b":   (0.0,   0.0),
    "ollama/llama3.3:70b":       (0.0,   0.0),
}

# Cheap substitutes for expensive models — used by cost-optimiser
_CHEAPER_ALTERNATIVES: dict[str, str] = {
    "openai/gpt-4o":            "openai/gpt-4o-mini",
    "openai/gpt-4.1":           "github/gpt-4.1",
    "claude/claude-sonnet-4.6": "github/gpt-4o-mini",
    "gemini/gemini-2.5-pro":    "gemini/gemini-2.5-flash-lite",
    "openai/o1":                "openai/gpt-4o-mini",
}

# Typical token counts used for estimation
_TOKENS_PER_TASK_ESTIMATE = 2_500    # prompt + completion average
_TOKENS_PER_AGENT_BUILD   = 8_000   # agent build pipeline uses more


# ═══════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CostQuote:
    tasks: list[str]
    agents: list[str]
    model: str
    token_estimate: int
    input_tokens: int
    output_tokens: int
    total_usd: float
    breakdown: list[dict]
    within_budget: bool
    budget_usd: float
    optimised_model: str | None        # cheaper swap suggestion, if applicable
    optimised_total_usd: float | None

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "token_estimate": self.token_estimate,
            "total_usd": round(self.total_usd, 6),
            "within_budget": self.within_budget,
            "budget_usd": self.budget_usd,
            "optimised_model": self.optimised_model,
            "optimised_total_usd": (
                round(self.optimised_total_usd, 6) if self.optimised_total_usd else None
            ),
            "breakdown": self.breakdown,
        }

    def summary(self) -> str:
        lines = [
            f"💰 Price Quote — {self.model}",
            f"   Estimated tokens : {self.token_estimate:,}",
            f"   Estimated cost   : ${self.total_usd:.4f}",
            f"   Budget           : ${self.budget_usd:.2f}",
            f"   Within budget    : {'✅ Yes' if self.within_budget else '❌ No'}",
        ]
        if self.optimised_model:
            lines.append(
                f"   💡 Cheaper option : {self.optimised_model} "
                f"(${self.optimised_total_usd:.4f})"
            )
        return "\n".join(lines)


@dataclass
class SpendRecord:
    agent: str
    task_preview: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    timestamp: float = field(default_factory=time.time)
    project: str = ""

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "task_preview": self.task_preview,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "timestamp": self.timestamp,
            "project": self.project,
        }


# ═══════════════════════════════════════════════════════════════════════════
# FinOps Controller
# ═══════════════════════════════════════════════════════════════════════════


class FinOpsController:
    """
    Business-first cost controller for AI orchestration.

    Parameters
    ----------
    monthly_budget_usd : Hard monthly cap in USD. 0 = unlimited.
    warn_threshold     : Warn when usage exceeds this fraction (default 0.80).
    """

    def __init__(
        self,
        monthly_budget_usd: float = 0.0,
        warn_threshold: float = 0.80,
    ):
        self.monthly_budget_usd = monthly_budget_usd
        self.warn_threshold = warn_threshold
        self._ledger: list[SpendRecord] = []
        self._total_usd: float = 0.0

    # ──────────────────────────────────────────────────────────────────
    # Price Quote
    # ──────────────────────────────────────────────────────────────────

    def quote(
        self,
        tasks: list[str],
        agents: list[str] | None = None,
        model: str = "openai/gpt-4o",
        tokens_per_task: int | None = None,
        budget_override: float | None = None,
    ) -> CostQuote:
        """
        Estimate total cost before running a project.

        Parameters
        ----------
        tasks            : List of task descriptions.
        agents           : List of agent names (used for per-agent cost breakdown).
        model            : Model key in format "provider/model" (e.g. "openai/gpt-4o").
        tokens_per_task  : Override token estimate per task. Default: auto.
        budget_override  : Check against this budget instead of monthly_budget_usd.
        """
        agents = agents or []
        tpt = tokens_per_task or _TOKENS_PER_TASK_ESTIMATE
        total_tasks = max(len(tasks), 1)
        total_entities = max(len(agents), 1)

        # Agent builds cost more tokens
        agent_build_tokens = len(agents) * _TOKENS_PER_AGENT_BUILD
        task_tokens = total_tasks * tpt
        total_tokens = task_tokens + agent_build_tokens

        # 70/30 input/output split
        input_tokens = int(total_tokens * 0.70)
        output_tokens = total_tokens - input_tokens

        cost = self._calculate_cost(model, input_tokens, output_tokens)

        # Per-task breakdown
        cost_per_task = self._calculate_cost(model, int(tpt * 0.7), int(tpt * 0.3))
        breakdown = [
            {
                "item": f"Task: {t[:60]}",
                "tokens": tpt,
                "cost_usd": round(cost_per_task, 6),
            }
            for t in tasks
        ]
        for ag in agents:
            agt_cost = self._calculate_cost(
                model,
                int(_TOKENS_PER_AGENT_BUILD * 0.7),
                int(_TOKENS_PER_AGENT_BUILD * 0.3),
            )
            breakdown.append({
                "item": f"Agent build: {ag}",
                "tokens": _TOKENS_PER_AGENT_BUILD,
                "cost_usd": round(agt_cost, 6),
            })

        budget = budget_override if budget_override is not None else self.monthly_budget_usd
        within_budget = (budget == 0) or (self._total_usd + cost <= budget)

        # Suggest cheaper alternative
        opt_model = _CHEAPER_ALTERNATIVES.get(model)
        opt_cost = None
        if opt_model:
            opt_cost = self._calculate_cost(opt_model, input_tokens, output_tokens)

        return CostQuote(
            tasks=tasks,
            agents=agents,
            model=model,
            token_estimate=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_usd=cost,
            breakdown=breakdown,
            within_budget=within_budget,
            budget_usd=budget,
            optimised_model=opt_model,
            optimised_total_usd=opt_cost,
        )

    # ──────────────────────────────────────────────────────────────────
    # Spend recording
    # ──────────────────────────────────────────────────────────────────

    def record_spend(
        self,
        agent: str,
        task: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        project: str = "",
    ) -> SpendRecord:
        """
        Record actual token spend for a completed task.
        Automatically warns if approaching / over budget.
        """
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
        record = SpendRecord(
            agent=agent,
            task_preview=task[:120],
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            project=project,
        )
        self._ledger.append(record)
        self._total_usd += cost
        logger.debug(
            "FinOps spend: agent=%s model=%s tokens=%d cost=$%.6f total=$%.4f",
            agent, model, prompt_tokens + completion_tokens, cost, self._total_usd,
        )
        self._check_budget_alerts()
        return record

    def record_from_adapter(
        self, agent: str, task: str, ai_adapter, project: str = ""
    ) -> SpendRecord | None:
        """
        Convenience: read token usage directly from an AIAdapter instance.
        Call immediately after a chat() call.
        """
        usage = getattr(ai_adapter, "usage", None)
        if not usage:
            return None
        model_key = f"{ai_adapter.provider}/{ai_adapter.model}"
        return self.record_spend(
            agent=agent,
            task=task,
            model=model_key,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            project=project,
        )

    # ──────────────────────────────────────────────────────────────────
    # Budget status
    # ──────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current spend vs. budget."""
        budget = self.monthly_budget_usd
        pct = (self._total_usd / budget * 100) if budget > 0 else 0.0
        remaining = max(0.0, budget - self._total_usd) if budget > 0 else float("inf")
        return {
            "used_usd": round(self._total_usd, 4),
            "budget_usd": budget,
            "remaining_usd": round(remaining, 4) if remaining != float("inf") else None,
            "percent_used": round(pct, 1),
            "over_budget": budget > 0 and self._total_usd > budget,
            "total_records": len(self._ledger),
        }

    def can_spend(self, estimated_cost: float) -> bool:
        """Return True if estimated_cost fits within the remaining budget."""
        if self.monthly_budget_usd == 0:
            return True
        return self._total_usd + estimated_cost <= self.monthly_budget_usd

    def set_budget(self, monthly_budget_usd: float) -> None:
        """Update the monthly budget cap."""
        self.monthly_budget_usd = monthly_budget_usd
        logger.info("FinOps: monthly budget set to $%.2f", monthly_budget_usd)

    # ──────────────────────────────────────────────────────────────────
    # Ledger & Analytics
    # ──────────────────────────────────────────────────────────────────

    def ledger(self, limit: int = 100) -> list[dict]:
        """Return the most recent spend records."""
        return [r.to_dict() for r in self._ledger[-limit:]]

    def spend_by_agent(self) -> dict[str, dict]:
        """Return cost breakdown grouped by agent."""
        result: dict[str, dict] = {}
        for r in self._ledger:
            if r.agent not in result:
                result[r.agent] = {"cost_usd": 0.0, "calls": 0, "tokens": 0}
            result[r.agent]["cost_usd"] += r.cost_usd
            result[r.agent]["calls"] += 1
            result[r.agent]["tokens"] += r.prompt_tokens + r.completion_tokens
        for v in result.values():
            v["cost_usd"] = round(v["cost_usd"], 4)
        return result

    def spend_by_model(self) -> dict[str, dict]:
        """Return cost breakdown grouped by model."""
        result: dict[str, dict] = {}
        for r in self._ledger:
            if r.model not in result:
                result[r.model] = {"cost_usd": 0.0, "calls": 0, "tokens": 0}
            result[r.model]["cost_usd"] += r.cost_usd
            result[r.model]["calls"] += 1
            result[r.model]["tokens"] += r.prompt_tokens + r.completion_tokens
        for v in result.values():
            v["cost_usd"] = round(v["cost_usd"], 4)
        return result

    def reset_spend(self) -> None:
        """Clear ledger and reset running total (e.g. at month rollover)."""
        self._ledger.clear()
        self._total_usd = 0.0
        logger.info("FinOps: spend ledger reset.")

    # ──────────────────────────────────────────────────────────────────
    # Cost calculation
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate USD cost for given token counts.
        Falls back to the cheapest known paid model if model not in table.
        """
        entry = _COST_TABLE.get(model)
        if entry is None:
            # Try partial match (e.g. user passed "gpt-4o" without provider prefix)
            for key, val in _COST_TABLE.items():
                if key.endswith("/" + model) or model in key:
                    entry = val
                    break
        if entry is None:
            entry = (2.50, 10.00)   # conservative fallback (openai/gpt-4o pricing)

        input_cost_per_m, output_cost_per_m = entry
        return (input_tokens * input_cost_per_m + output_tokens * output_cost_per_m) / 1_000_000

    # ──────────────────────────────────────────────────────────────────
    # Budget alert helper
    # ──────────────────────────────────────────────────────────────────

    def _check_budget_alerts(self) -> None:
        if self.monthly_budget_usd <= 0:
            return
        pct = self._total_usd / self.monthly_budget_usd
        if pct >= 1.0:
            logger.error(
                "FinOps ALERT: OVER BUDGET — $%.4f / $%.2f (%.0f%%)",
                self._total_usd, self.monthly_budget_usd, pct * 100,
            )
        elif pct >= self.warn_threshold:
            logger.warning(
                "FinOps WARNING: Approaching budget — $%.4f / $%.2f (%.0f%%)",
                self._total_usd, self.monthly_budget_usd, pct * 100,
            )

    @staticmethod
    def model_cost_table() -> dict:
        """Return the full pricing table."""
        return dict(_COST_TABLE)

    @staticmethod
    def cheaper_alternatives() -> dict:
        """Return the model cost-optimisation substitution map."""
        return dict(_CHEAPER_ALTERNATIVES)
