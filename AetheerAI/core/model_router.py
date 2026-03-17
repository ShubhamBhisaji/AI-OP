"""
ModelRouter — Intelligent task-complexity-based AI model selection.

Not all tasks need a $20/month brain. Some just need a 5-cent brain.

The router evaluates each incoming task's complexity and selects the
cheapest model that can reliably execute it:

  SIMPLE   → local / on-device model (Ollama / HuggingFace)
  MODERATE → lightweight cloud model  (gpt-4o-mini, gemini-2.5-flash-lite)
  COMPLEX  → high-reasoning cloud model (gpt-4.1, claude-sonnet, gemini-pro)

Complexity signals
------------------
Keyword scoring  — fast, deterministic, zero API cost (primary gate).
AI scoring       — optional; spends ~50 tokens to ask the AI to rate the task
                   complexity (SIMPLE/MODERATE/COMPLEX).  Use for borderline cases.

Usage
-----
    router = ModelRouter(ai_adapter)

    # Option A — uses keyword heuristic (free, instant):
    result = router.route("Write a haiku about clouds.")
    # result.complexity  →  "SIMPLE"
    # result.provider    →  "ollama"
    # result.model       →  "llama3.2:3b"

    # Option B — uses AI to score (more accurate, tiny cost):
    result = router.route("Design a fault-tolerant multi-region Kubernetes cluster.",
                           use_ai_scoring=True)
    # result.complexity  →  "COMPLEX"
    # result.provider    →  "github"
    # result.model       →  "gpt-4.1"

    # Apply the chosen model to the adapter for the next call:
    router.apply(result)
    response = adapter.chat(messages)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── Complexity tiers ──────────────────────────────────────────────────────

COMPLEXITY_SIMPLE = "SIMPLE"
COMPLEXITY_MODERATE = "MODERATE"
COMPLEXITY_COMPLEX = "COMPLEX"
_COMPLEXITY_RANKS = {COMPLEXITY_SIMPLE: 0, COMPLEXITY_MODERATE: 1, COMPLEXITY_COMPLEX: 2}

# ── Model catalogue per complexity ────────────────────────────────────────
#
# Each tier lists preferred (provider, model) pairs in priority order.
# The first pair whose provider has a valid API key is selected.

_ROUTING_TABLE: dict[str, list[tuple[str, str]]] = {
    COMPLEXITY_SIMPLE: [
        ("ollama", "llama3.2:3b"),              # ultra-fast, minimal hardware
        ("ollama", "qwen2.5-coder:7b"),          # local code tasks
        ("huggingface", "mistralai/Mistral-7B-Instruct-v0.2"),
        ("gemini", "gemini-2.5-flash-lite"),     # cheapest cloud fallback
        ("github", "gpt-4o-mini"),               # GitHub free tier
        ("openai", "gpt-4o-mini"),
    ],
    COMPLEXITY_MODERATE: [
        ("gemini", "gemini-2.5-flash-lite"),     # fast + cheap cloud
        ("github", "gpt-4o-mini"),
        ("openai", "gpt-4o-mini"),
        ("ollama", "qwen2.5-coder:7b"),
        ("github", "gpt-4.1-mini"),
        ("openai", "gpt-4o"),
    ],
    COMPLEXITY_COMPLEX: [
        ("github", "gpt-4.1"),                   # best free-tier model
        ("openai", "gpt-4o"),
        ("claude", "claude-sonnet-4.6"),         # highest reasoning
        ("gemini", "gemini/gemini-2.5-pro"),
        ("openai", "gpt-4o"),
        ("github", "gpt-4o"),
    ],
}

# ── Keyword signals for heuristic scoring ────────────────────────────────

_COMPLEX_SIGNALS = [
    r"\barchitect\b", r"\bagentic\b", r"\bmulti.?agent\b", r"\bkubernetes\b",
    r"\bmicroservice", r"\bfault.tolerant\b", r"\bdistributed\b", r"\bscalable\b",
    r"\bsecurity audit\b", r"\bred.?team\b", r"\bpen.?test\b",
    r"\bdesign\b.{0,60}\bsystem\b", r"\barchitecture\b",
    r"\boptimize\b.{0,60}\bperformance\b", r"\bml pipeline\b",
    r"\bneural\b", r"\bfine.?tun", r"\bdata pipeline\b",
    r"\brefactor.{0,60}\bentire\b", r"\brefactor.{0,60}\bcomplex\b",
    r"\bwrite.{0,30}\bbusiness plan\b", r"\bstrategic\b",
    r"\bcomplex\b", r"\badvanced\b", r"\bsophisticated\b",
    r"\bintegrat.{0,30}\bmultipl", r"\bworkflow\b.{0,40}\bmulti",
]

_SIMPLE_SIGNALS = [
    r"\bhaiku\b", r"\bjoke\b", r"\btranslat\b",
    r"\bsummarise?\b.{0,30}\b(short|brief|one.?line)\b",
    r"\bconvert\b.{0,25}\b(string|text|number|date)\b",
    r"\bformat\b.{0,25}\b(json|csv|xml)\b",
    r"\bcapitali[sz]e\b", r"\btrim\b", r"\bcount\b.{0,20}\bword",
    r"\bsimple\b", r"\bbasic\b", r"\beasy\b",
    r"\bhello world\b", r"\bping\b",
    r"\blist\b.{0,20}\b(all|the)\b.{0,20}\b(file|dir|folder)\b",
    r"\bwhat.{0,10}(is|are)\b.{0,50}\bdefin",
]


# ═══════════════════════════════════════════════════════════════════════════
# Routing result
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class RoutingDecision:
    task: str
    complexity: str         # SIMPLE / MODERATE / COMPLEX
    provider: str
    model: str
    reason: str
    cost_tier: str          # "free-local" / "cheap-cloud" / "premium-cloud"
    scored_by: str          # "heuristic" / "ai"

    def to_dict(self) -> dict:
        return {
            "task_preview": self.task[:120],
            "complexity": self.complexity,
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "cost_tier": self.cost_tier,
            "scored_by": self.scored_by,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Model Router
# ═══════════════════════════════════════════════════════════════════════════


class ModelRouter:
    """
    Evaluates task complexity and selects the most cost-effective AI model.

    Parameters
    ----------
    ai_adapter          : AIAdapter — used for optional AI-based scoring and
                          as the adapter that will be switched on `apply()`.
    prefer_local        : When True, always prefer on-device (Ollama) models
                          for SIMPLE tasks even if cloud keys are available.
    custom_routing_table: Override the built-in routing table.
    """

    def __init__(
        self,
        ai_adapter,
        prefer_local: bool = True,
        custom_routing_table: dict[str, list[tuple[str, str]]] | None = None,
    ):
        self.ai_adapter = ai_adapter
        self.prefer_local = prefer_local
        self._routing_table = custom_routing_table or _ROUTING_TABLE
        self._history: list[RoutingDecision] = []

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def route(
        self,
        task: str,
        use_ai_scoring: bool = False,
        force_complexity: str | None = None,
    ) -> RoutingDecision:
        """
        Evaluate task complexity and return the optimal RoutingDecision.

        Parameters
        ----------
        task             : The task text to evaluate.
        use_ai_scoring   : When True, the AI rates the complexity (more accurate,
                           uses ~50 tokens).  Default is keyword heuristic (free).
        force_complexity : Override complexity with "SIMPLE", "MODERATE", or "COMPLEX".
        """
        if force_complexity:
            complexity = force_complexity.upper()
            if complexity not in _COMPLEXITY_RANKS:
                raise ValueError(f"Invalid complexity '{force_complexity}'.")
            scored_by = "forced"
            reason = f"Complexity manually set to {complexity}."
        elif use_ai_scoring:
            complexity, reason = self._ai_score(task)
            scored_by = "ai"
        else:
            complexity, reason = self._heuristic_score(task)
            scored_by = "heuristic"

        provider, model = self._pick_model(complexity)
        cost_tier = self._cost_tier(provider, model)

        decision = RoutingDecision(
            task=task,
            complexity=complexity,
            provider=provider,
            model=model,
            reason=reason,
            cost_tier=cost_tier,
            scored_by=scored_by,
        )
        self._history.append(decision)
        logger.info(
            "ModelRouter: %s → %s/%s [%s] (%s)",
            complexity, provider, model, cost_tier, scored_by,
        )
        return decision

    def apply(self, decision: RoutingDecision) -> None:
        """
        Hot-swap the AIAdapter to use the model selected by `route()`.
        The adapter's previous provider/model is overwritten.
        """
        self.ai_adapter.switch(decision.provider, decision.model)
        logger.info(
            "ModelRouter applied: %s/%s (tier=%s)",
            decision.provider, decision.model, decision.cost_tier,
        )

    def route_and_apply(
        self,
        task: str,
        use_ai_scoring: bool = False,
        force_complexity: str | None = None,
    ) -> RoutingDecision:
        """Convenience — route + immediately apply the decision."""
        decision = self.route(task, use_ai_scoring=use_ai_scoring, force_complexity=force_complexity)
        self.apply(decision)
        return decision

    def history(self) -> list[dict]:
        """Return the routing decision history as a list of dicts."""
        return [d.to_dict() for d in self._history]

    def stats(self) -> dict:
        """Return aggregate routing stats."""
        from collections import Counter
        counts = Counter(d.complexity for d in self._history)
        models = Counter(f"{d.provider}/{d.model}" for d in self._history)
        return {
            "total_routed": len(self._history),
            "by_complexity": dict(counts),
            "by_model": dict(models),
        }

    # ──────────────────────────────────────────────────────────────────
    # Scoring methods
    # ──────────────────────────────────────────────────────────────────

    def _heuristic_score(self, task: str) -> tuple[str, str]:
        """
        Keyword-based complexity scoring — zero cost, instant.
        Returns (complexity, reason).
        """
        normalized = task.lower()

        complex_hits = [p for p in _COMPLEX_SIGNALS if re.search(p, normalized)]
        simple_hits = [p for p in _SIMPLE_SIGNALS if re.search(p, normalized)]

        # Word-count bonus: very long tasks tend to be complex
        word_count = len(task.split())
        length_bonus = 0
        if word_count > 200:
            length_bonus = 2
        elif word_count > 80:
            length_bonus = 1

        complex_score = len(complex_hits) + length_bonus
        simple_score = len(simple_hits)

        if complex_score >= 2:
            return COMPLEXITY_COMPLEX, (
                f"Complex signals detected: {complex_hits[:3]}; words={word_count}"
            )
        if complex_score == 1 or (simple_score == 0 and word_count > 40):
            return COMPLEXITY_MODERATE, (
                f"Moderate complexity: 1 complex signal or medium length; words={word_count}"
            )
        return COMPLEXITY_SIMPLE, (
            f"Simple task: {simple_hits[:3] or 'no complex signals'}; words={word_count}"
        )

    def _ai_score(self, task: str) -> tuple[str, str]:
        """
        Ask the AI to rate complexity — ~50 tokens spent, more accurate.
        Falls back to heuristic on failure.
        """
        prompt = (
            "Rate the following task's complexity for an AI agent. "
            "Reply with EXACTLY one word: SIMPLE, MODERATE, or COMPLEX.\n\n"
            f"Task: {task[:500]}"
        )
        try:
            raw = self.ai_adapter.chat([{"role": "user", "content": prompt}])
            upper = raw.strip().upper()
            found = re.search(r"\b(SIMPLE|MODERATE|COMPLEX)\b", upper)
            if found:
                complexity = found.group(1)
                return complexity, f"AI scored complexity as {complexity}."
        except Exception as exc:
            logger.warning("ModelRouter AI scoring failed: %s — falling back to heuristic", exc)

        return self._heuristic_score(task)

    # ──────────────────────────────────────────────────────────────────
    # Model selection
    # ──────────────────────────────────────────────────────────────────

    def _pick_model(self, complexity: str) -> tuple[str, str]:
        """
        Select the first (provider, model) pair for which we have credentials.
        Falls back through the routing table until one works.
        """
        import os
        candidates = self._routing_table.get(complexity, [])
        for provider, model in candidates:
            if self._provider_available(provider):
                return provider, model

        # Absolute fallback — GitHub token is almost always present
        if os.environ.get("GITHUB_TOKEN"):
            return "github", "gpt-4o-mini"

        # Last resort — use whatever the current adapter has
        return self.ai_adapter.provider, self.ai_adapter.model

    @staticmethod
    def _provider_available(provider: str) -> bool:
        """Check whether the required credential for a provider is set."""
        import os
        key_map = {
            "openai": "OPENAI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "github": "GITHUB_TOKEN",
            "huggingface": "HF_API_KEY",
            "ollama": None,  # local — always available
        }
        key = key_map.get(provider)
        if key is None:           # ollama — check if running
            return ModelRouter._ollama_running()
        return bool(os.environ.get(key))

    @staticmethod
    def _ollama_running() -> bool:
        """Quick check whether Ollama is running on localhost."""
        import urllib.request
        import urllib.error
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1):
                return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _cost_tier(provider: str, model: str) -> str:
        if provider == "ollama" or provider == "huggingface":
            return "free-local"
        if "mini" in model or "flash" in model or "lite" in model:
            return "cheap-cloud"
        return "premium-cloud"

    @staticmethod
    def complexity_levels() -> list[str]:
        return [COMPLEXITY_SIMPLE, COMPLEXITY_MODERATE, COMPLEXITY_COMPLEX]

    @staticmethod
    def routing_table() -> dict:
        return {k: list(v) for k, v in _ROUTING_TABLE.items()}
