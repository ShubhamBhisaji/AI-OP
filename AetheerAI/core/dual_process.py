"""
DualProcessEngine — System 1 (Fast) / System 2 (Slow) cognitive architecture.

Inspired by Kahneman's cognitive science model, this engine gives AetheerAI
two modes of operation:

System 1 — Fast (Sub-agent execution layer)
--------------------------------------------
- Uses a "frozen" lightweight model for quick, repetitive tasks
  (data retrieval, formatting, classification, simple Q&A).
- Executes immediately with minimal deliberation.
- Records every outcome in short-term episodic memory.

System 2 — Slow (Curator Agent reflection layer)
-------------------------------------------------
- A background "Curator Agent" periodically reviews the S1 outcome log.
- Detects patterns of repeated mistakes (error_rate > threshold).
- Writes a permanent "lesson" to the agent's Long-Term Memory.
- Optionally generates an updated instruction set for the agent.
- Can propose model upgrades when S1 errors exceed the budget.

The result: AetheerAI literally gets smarter the more you use it —
without any code changes.

Usage
-----
    engine = DualProcessEngine(ai_adapter, memory_manager)

    # System 1 — fast execution (fire-and-forget, auto-logged):
    result = engine.system1_run(
        agent_name="DataFormatter",
        task="Reformat the following CSV into JSON: ...",
        task_type="format",
    )

    # System 2 — curator reflection (call periodically or on schedule):
    report = engine.system2_reflect(agent_name="DataFormatter", min_samples=5)
    # report.lessons — list of permanent lessons written to long-term memory
    # report.updated_instructions — improved instruction string if errors found
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Config defaults ───────────────────────────────────────────────────────

DEFAULT_S1_MODEL = "gpt-4o-mini"   # fast, cheap — frozen for repetitive tasks
DEFAULT_S1_PROVIDER = "github"
ERROR_THRESHOLD = 0.25              # trigger S2 reflection after >25% error rate
MIN_SAMPLES_FOR_REFLECTION = 5     # need at least N outcomes before reflecting
# WARNING-7: Throttle S2 reflection — no more than once per hour per agent to
# prevent recursive self-modification loops and runaway LLM cost.
REFLECTION_COOLDOWN_S: float = 3600.0


# ═══════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class S1Outcome:
    """A single System 1 execution result."""
    agent_name: str
    task_type: str
    task_preview: str           # first 200 chars of task
    success: bool
    output_preview: str         # first 300 chars of output
    error_msg: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "task_type": self.task_type,
            "task_preview": self.task_preview,
            "success": self.success,
            "output_preview": self.output_preview,
            "error_msg": self.error_msg,
            "timestamp": self.timestamp,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class ReflectionReport:
    """System 2 Curator's analysis of S1 outcomes for one agent."""
    agent_name: str
    samples_reviewed: int
    error_rate: float
    needs_update: bool
    lessons: list[str]
    updated_instructions: str
    pattern_summary: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "samples_reviewed": self.samples_reviewed,
            "error_rate": round(self.error_rate, 3),
            "needs_update": self.needs_update,
            "lessons": self.lessons,
            "updated_instructions": self.updated_instructions,
            "pattern_summary": self.pattern_summary,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Dual Process Engine
# ═══════════════════════════════════════════════════════════════════════════


class DualProcessEngine:
    """
    System 1 / System 2 cognitive architecture.

    Parameters
    ----------
    ai_adapter     : AIAdapter for S1 execution and S2 reflection.
    memory_manager : MemoryManager for persisting lessons.
    s1_model       : Model name for System 1 (fast/cheap). Default: gpt-4o-mini.
    s1_provider    : Provider for System 1. Default: github.
    error_threshold: Error rate (0–1) that triggers S2 reflection. Default: 0.25.
    """

    def __init__(
        self,
        ai_adapter,
        memory_manager,
        s1_model: str = DEFAULT_S1_MODEL,
        s1_provider: str = DEFAULT_S1_PROVIDER,
        error_threshold: float = ERROR_THRESHOLD,
    ):
        self.ai_adapter = ai_adapter
        self.memory = memory_manager
        self.s1_model = s1_model
        self.s1_provider = s1_provider
        self.error_threshold = error_threshold
        self._outcome_log: dict[str, list[S1Outcome]] = {}   # keyed by agent_name
        self._reflection_log: list[ReflectionReport] = []
        # WARNING-7: Last reflection timestamp per agent (epoch seconds).
        self._last_reflection_ts: dict[str, float] = {}

    # ──────────────────────────────────────────────────────────────────
    # System 1 — Fast Execution
    # ──────────────────────────────────────────────────────────────────

    def system1_run(
        self,
        agent_name: str,
        task: str,
        task_type: str = "general",
        system_prompt: str = "",
        record: bool = True,
    ) -> dict:
        """
        Execute a task using the lightweight System 1 "frozen" model.

        Parameters
        ----------
        agent_name  : Name of the agent executing this task.
        task        : Task text to send to the model.
        task_type   : Category (e.g. "format", "retrieve", "classify").
        system_prompt : Override system prompt for this call.
        record      : Whether to log this outcome (default True).

        Returns
        -------
        dict with keys: agent_name, success, output, duration_ms
        """
        # Temporarily switch to S1 model
        original_provider = self.ai_adapter.provider
        original_model = self.ai_adapter.model
        self.ai_adapter.switch(self.s1_provider, self.s1_model)

        # Load any long-term memory lessons for this agent
        lessons_key = f"dual_process:lessons:{agent_name}"
        try:
            lessons_raw = self.memory.retrieve(lessons_key) or ""
        except Exception:
            lessons_raw = ""

        messages = []
        sp = system_prompt or f"You are {agent_name}, a focused and efficient AI sub-agent."
        if lessons_raw:
            sp += f"\n\n[Long-term lessons from past experience]\n{lessons_raw}"
        messages.append({"role": "system", "content": sp})
        messages.append({"role": "user", "content": task})

        t0 = time.time()
        success = True
        output = ""
        error_msg = ""
        try:
            output = self.ai_adapter.chat(messages)
        except Exception as exc:
            success = False
            error_msg = str(exc)
            output = f"[S1 ERROR] {exc}"
            logger.warning("DualProcess S1 '%s' error: %s", agent_name, exc)
        finally:
            # Restore original model
            self.ai_adapter.switch(original_provider, original_model)

        duration_ms = (time.time() - t0) * 1000

        if record:
            outcome = S1Outcome(
                agent_name=agent_name,
                task_type=task_type,
                task_preview=task[:200],
                success=success,
                output_preview=output[:300],
                error_msg=error_msg,
                duration_ms=duration_ms,
            )
            if agent_name not in self._outcome_log:
                self._outcome_log[agent_name] = []
            self._outcome_log[agent_name].append(outcome)

        return {
            "agent_name": agent_name,
            "success": success,
            "output": output,
            "duration_ms": round(duration_ms, 1),
            "model": f"{self.s1_provider}/{self.s1_model}",
        }

    # ──────────────────────────────────────────────────────────────────
    # System 2 — Slow Reflection (Curator Agent)
    # ──────────────────────────────────────────────────────────────────

    def system2_reflect(
        self,
        agent_name: str,
        min_samples: int = MIN_SAMPLES_FOR_REFLECTION,
        force: bool = False,
    ) -> ReflectionReport:
        """
        The Curator Agent reviews System 1 outcomes and extracts lessons.

        Parameters
        ----------
        agent_name  : Which agent's history to review.
        min_samples : Minimum number of logged outcomes required.
        force       : Run even if error rate is below threshold.

        Returns
        -------
        ReflectionReport with lessons, updated_instructions, error_rate.
        The lessons are automatically persisted to Long-Term Memory.
        """
        outcomes = self._outcome_log.get(agent_name, [])

        # WARNING-7: Enforce per-agent cooldown to prevent runaway S2 invocations.
        if not force:
            last = self._last_reflection_ts.get(agent_name, 0.0)
            elapsed = time.time() - last
            if elapsed < REFLECTION_COOLDOWN_S:
                logger.debug(
                    "DualProcess S2 '%s' throttled — %.0fs remaining in cooldown.",
                    agent_name, REFLECTION_COOLDOWN_S - elapsed,
                )
                return ReflectionReport(
                    agent_name=agent_name,
                    samples_reviewed=len(outcomes),
                    error_rate=0.0,
                    needs_update=False,
                    lessons=[],
                    updated_instructions="",
                    pattern_summary=(
                        f"Reflection cooldown active — "
                        f"{REFLECTION_COOLDOWN_S - elapsed:.0f}s remaining."
                    ),
                )

        if len(outcomes) < min_samples:
            return ReflectionReport(
                agent_name=agent_name,
                samples_reviewed=len(outcomes),
                error_rate=0.0,
                needs_update=False,
                lessons=[],
                updated_instructions="",
                pattern_summary=f"Insufficient data ({len(outcomes)}/{min_samples} samples).",
            )

        # Only review the most recent 50 outcomes to keep the prompt concise
        recent = outcomes[-50:]
        error_rate = sum(1 for o in recent if not o.success) / len(recent)

        if not force and error_rate < self.error_threshold:
            return ReflectionReport(
                agent_name=agent_name,
                samples_reviewed=len(recent),
                error_rate=error_rate,
                needs_update=False,
                lessons=[],
                updated_instructions="",
                pattern_summary=(
                    f"Error rate {error_rate:.1%} is below threshold "
                    f"{self.error_threshold:.1%}. No update needed."
                ),
            )

        # Build curator prompt
        error_examples = [
            f"- Task: {o.task_preview[:100]}\n  Error: {o.error_msg}"
            for o in recent if not o.success
        ][:10]   # cap at 10 examples

        curator_prompt = f"""You are the Curator Agent — a silent observer that reviews an AI sub-agent's performance and extracts lessons.

Agent: {agent_name}
Samples reviewed: {len(recent)}
Error rate: {error_rate:.1%}
Errors observed: {len(error_examples)}

Recent failures:
{chr(10).join(error_examples) if error_examples else '(none in recent window)'}

Your task:
1. Identify the root cause pattern(s) behind the errors.
2. Write 1–3 short, actionable "lessons" this agent should remember permanently.
3. Write an improved system-prompt instruction block for this agent (4–6 sentences).

Respond ONLY with valid JSON in this exact format:
{{
  "pattern_summary": "<one sentence describing the failure pattern>",
  "lessons": ["<lesson 1>", "<lesson 2>"],
  "updated_instructions": "<improved instruction text for the agent>"
}}"""

        try:
            raw = self.ai_adapter.chat([{"role": "user", "content": curator_prompt}])
            parsed = self._parse_json(raw)
        except Exception as exc:
            logger.warning("DualProcess S2 reflection failed: %s", exc)
            parsed = {
                "pattern_summary": f"Curator analysis failed: {exc}",
                "lessons": [],
                "updated_instructions": "",
            }

        lessons = parsed.get("lessons", [])
        updated_instructions = parsed.get("updated_instructions", "")
        pattern_summary = parsed.get("pattern_summary", "")

        # Persist lessons to Long-Term Memory
        if lessons:
            lessons_key = f"dual_process:lessons:{agent_name}"
            existing = self.memory.retrieve(lessons_key) or ""
            new_lessons_text = "\n".join(f"• {l}" for l in lessons)
            combined = (existing.strip() + "\n" + new_lessons_text).strip()
            self.memory.save(lessons_key, combined)
            logger.info(
                "DualProcess S2: wrote %d lessons to long-term memory for '%s'",
                len(lessons), agent_name,
            )

        report = ReflectionReport(
            agent_name=agent_name,
            samples_reviewed=len(recent),
            error_rate=error_rate,
            needs_update=True,
            lessons=lessons,
            updated_instructions=updated_instructions,
            pattern_summary=pattern_summary,
        )
        self._reflection_log.append(report)
        # WARNING-7: Record completion time to enforce per-agent cooldown.
        self._last_reflection_ts[agent_name] = time.time()
        return report

    # ──────────────────────────────────────────────────────────────────
    # Bulk reflect — process all agents
    # ──────────────────────────────────────────────────────────────────

    def reflect_all(
        self,
        min_samples: int = MIN_SAMPLES_FOR_REFLECTION,
    ) -> list[dict]:
        """
        Run S2 Curator reflection over every tracked agent.
        Returns list of ReflectionReport dicts.
        """
        results = []
        for agent_name in list(self._outcome_log):
            report = self.system2_reflect(agent_name, min_samples=min_samples)
            results.append(report.to_dict())
        return results

    # ──────────────────────────────────────────────────────────────────
    # Inspection
    # ──────────────────────────────────────────────────────────────────

    def outcome_stats(self, agent_name: str | None = None) -> dict:
        """Return per-agent outcome statistics."""
        targets = (
            {agent_name: self._outcome_log.get(agent_name, [])}
            if agent_name
            else self._outcome_log
        )
        result = {}
        for name, outcomes in targets.items():
            n = len(outcomes)
            errors = sum(1 for o in outcomes if not o.success)
            result[name] = {
                "total": n,
                "successes": n - errors,
                "errors": errors,
                "error_rate": round(errors / n, 3) if n else 0.0,
                "avg_duration_ms": (
                    round(sum(o.duration_ms for o in outcomes) / n, 1) if n else 0.0
                ),
            }
        return result

    def get_lessons(self, agent_name: str) -> str:
        """Return the current long-term lessons for an agent."""
        try:
            return self.memory.retrieve(f"dual_process:lessons:{agent_name}") or ""
        except Exception:
            return ""

    def clear_lessons(self, agent_name: str) -> None:
        """Erase the long-term lessons for an agent."""
        try:
            self.memory.save(f"dual_process:lessons:{agent_name}", "")
        except Exception:
            pass

    def reflection_history(self) -> list[dict]:
        """Return all past S2 reflection reports."""
        return [r.to_dict() for r in self._reflection_log]

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> dict:
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if match:
            text = match.group(1)
        brace_match = re.search(r"\{[\s\S]+\}", text)
        if brace_match:
            return json.loads(brace_match.group())
        raise ValueError(f"No JSON found in curator response: {text[:200]}")
