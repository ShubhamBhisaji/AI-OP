"""
self_healer.py — Autonomous Self-Healing Debugger for AetheerAI.

When a sub-agent fails after all self-correction retries, the
SelfHealingDebugger intercepts the error silently, asks the Master AI
to diagnose the root cause and generate a "patch" (a new strategy and
revised instructions), then redeploys the agent with the patched approach.
The human never sees transient failures — only healed results or an honest
final error after max healing cycles.

Feature 1 — Zero-Downtime Recursive Healing:
    - Detects failed results using the same heuristics as WorkflowEngine.
    - Calls the Master AI to produce ROOT_CAUSE + PATCH_INSTRUCTIONS.
    - Re-runs the agent with a patched task (up to MAX_HEALING_CYCLES times).
    - Records every healing cycle in MemoryManager for observability.
    - Both sync (heal) and async (heal_async) variants available.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Maximum autonomous healing attempts before surfacing the error to the user.
MAX_HEALING_CYCLES: int = 2

_DIAGNOSIS_PROMPT = """\
You are the Master AI debugging a sub-agent failure.

Agent name   : {agent_name}
Agent role   : {agent_role}
Original task: {task}
Error output :
{error}

Diagnose the ROOT CAUSE of this failure, then produce a PATCH — a new set of
step-by-step instructions for the agent that avoids the same mistake.

Respond in EXACTLY this format (no other text):
ROOT_CAUSE: <one sentence>
PATCH_INSTRUCTIONS: <revised instructions, max 300 words>
"""


class HealingCycle:
    """Immutable record of one healing attempt."""

    __slots__ = ("error", "root_cause", "patch")

    def __init__(self, error: str, root_cause: str, patch: str) -> None:
        self.error = error
        self.root_cause = root_cause
        self.patch = patch


class HealingRecord:
    """Tracks all healing cycles for a single failed task."""

    def __init__(self, agent_name: str, task: str) -> None:
        self.agent_name = agent_name
        self.task = task
        self.cycles: list[HealingCycle] = []

    def add(self, error: str, root_cause: str, patch: str) -> None:
        self.cycles.append(HealingCycle(error, root_cause, patch))

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "task": self.task[:500],
            "cycles": [
                {"root_cause": c.root_cause, "patch": c.patch[:300]}
                for c in self.cycles
            ],
        }

    def summary(self) -> str:
        lines = [f"Healing record for agent '{self.agent_name}':"]
        for i, c in enumerate(self.cycles, 1):
            lines.append(f"  Cycle {i} — cause: {c.root_cause}")
        return "\n".join(lines)


def _parse_diagnosis(response: str) -> tuple[str, str]:
    """Extract (root_cause, patch) from structured AI response."""
    if not isinstance(response, str) or not response.strip():
        logger.warning("SelfHealer: received empty or non-string AI response.")
        return ("Unknown error pattern", "Retry the original task as-is.")
    root_cause = ""
    patch_lines: list[str] = []
    in_patch = False
    for line in response.splitlines():
        if line.startswith("ROOT_CAUSE:"):
            root_cause = line[len("ROOT_CAUSE:"):].strip()
        elif line.startswith("PATCH_INSTRUCTIONS:"):
            patch_lines.append(line[len("PATCH_INSTRUCTIONS:"):].strip())
            in_patch = True
        elif in_patch:
            patch_lines.append(line)
    patch = "\n".join(patch_lines).strip()
    return (root_cause or "Unknown error pattern", patch or response.strip())


class SelfHealingDebugger:
    """
    Adds a recursive healing layer above WorkflowEngine's self-correction loop.

    Wire into WorkflowEngine by assigning:
        workflow_engine.self_healer = SelfHealingDebugger(ai_adapter, memory)

    WorkflowEngine.execute() and execute_async() will then automatically
    invoke heal() / heal_async() when self-correction exhausts its retries.
    """

    def __init__(
        self,
        ai_adapter,
        memory=None,
        max_healing_cycles: int = MAX_HEALING_CYCLES,
    ) -> None:
        if ai_adapter is None:
            raise ValueError("SelfHealingDebugger: ai_adapter must not be None.")
        if not isinstance(max_healing_cycles, int) or max_healing_cycles < 1:
            raise ValueError(
                "SelfHealingDebugger: max_healing_cycles must be a positive integer, "
                f"got {max_healing_cycles!r}."
            )
        self._ai = ai_adapter
        self._memory = memory
        self._max = max_healing_cycles

    # ------------------------------------------------------------------
    # Synchronous healing
    # ------------------------------------------------------------------

    def heal(
        self,
        agent,
        task: str,
        execute_fn: Callable[[Any, str], str],
        is_error_fn: Callable[[str], bool],
    ) -> str:
        """
        Attempt to heal a failed agent task.

        Parameters
        ----------
        agent        : The BaseAgent instance.
        task         : The original task string.
        execute_fn   : Callable(agent, task) -> str — single AI call, no retries.
        is_error_fn  : Callable(result_str) -> bool — returns True for error results.

        Returns the healed result, or the final error after max cycles.
        """
        if agent is None:
            raise ValueError("SelfHealingDebugger.heal: agent must not be None.")
        if not hasattr(agent, "name") or not hasattr(agent, "role"):
            raise ValueError(
                "SelfHealingDebugger.heal: agent must expose 'name' and 'role' attributes."
            )
        if not isinstance(task, str) or not task.strip():
            raise ValueError("SelfHealingDebugger.heal: task must be a non-empty string.")
        if not callable(execute_fn):
            raise TypeError("SelfHealingDebugger.heal: execute_fn must be callable.")
        if not callable(is_error_fn):
            raise TypeError("SelfHealingDebugger.heal: is_error_fn must be callable.")

        record = HealingRecord(agent_name=agent.name, task=task)
        try:
            current_error = execute_fn(agent, task)
        except Exception as exc:  # noqa: BLE001
            logger.error("SelfHealer: initial execute_fn raised: %s", exc)
            current_error = str(exc)

        for cycle in range(1, self._max + 1):
            if not is_error_fn(current_error):
                logger.info(
                    "SelfHealer: agent '%s' healed successfully on cycle %d.",
                    agent.name, cycle,
                )
                break

            logger.warning(
                "SelfHealer: agent '%s' still failing — running healing cycle %d/%d.",
                agent.name, cycle, self._max,
            )

            root_cause, patch = self._diagnose(agent, task, current_error)
            record.add(error=current_error, root_cause=root_cause, patch=patch)

            patched_task = self._build_patched_task(task, cycle, root_cause, patch)
            try:
                current_error = execute_fn(agent, patched_task)
            except Exception as exc:  # noqa: BLE001
                logger.error("SelfHealer: execute_fn raised on cycle %d: %s", cycle, exc)
                current_error = str(exc)

        self._persist(record, succeeded=not is_error_fn(current_error))
        return current_error

    # ------------------------------------------------------------------
    # Asynchronous healing
    # ------------------------------------------------------------------

    async def heal_async(
        self,
        agent,
        task: str,
        execute_fn,               # async Callable(agent, task) -> str
        is_error_fn: Callable[[str], bool],
    ) -> str:
        """Async version of heal()."""
        if agent is None:
            raise ValueError("SelfHealingDebugger.heal_async: agent must not be None.")
        if not hasattr(agent, "name") or not hasattr(agent, "role"):
            raise ValueError(
                "SelfHealingDebugger.heal_async: agent must expose 'name' and 'role' attributes."
            )
        if not isinstance(task, str) or not task.strip():
            raise ValueError("SelfHealingDebugger.heal_async: task must be a non-empty string.")
        if not callable(execute_fn):
            raise TypeError("SelfHealingDebugger.heal_async: execute_fn must be callable.")
        if not callable(is_error_fn):
            raise TypeError("SelfHealingDebugger.heal_async: is_error_fn must be callable.")

        record = HealingRecord(agent_name=agent.name, task=task)
        try:
            current_error = await execute_fn(agent, task)
        except Exception as exc:  # noqa: BLE001
            logger.error("SelfHealer[async]: initial execute_fn raised: %s", exc)
            current_error = str(exc)

        for cycle in range(1, self._max + 1):
            if not is_error_fn(current_error):
                logger.info(
                    "SelfHealer[async]: agent '%s' healed on cycle %d.",
                    agent.name, cycle,
                )
                break

            logger.warning(
                "SelfHealer[async]: agent '%s' still failing — healing cycle %d/%d.",
                agent.name, cycle, self._max,
            )

            root_cause, patch = await self._diagnose_async(agent, task, current_error)
            record.add(error=current_error, root_cause=root_cause, patch=patch)

            patched_task = self._build_patched_task(task, cycle, root_cause, patch)
            try:
                current_error = await execute_fn(agent, patched_task)
            except Exception as exc:  # noqa: BLE001
                logger.error("SelfHealer[async]: execute_fn raised on cycle %d: %s", cycle, exc)
                current_error = str(exc)

        self._persist(record, succeeded=not is_error_fn(current_error))
        return current_error

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _diagnose(self, agent, task: str, error: str) -> tuple[str, str]:
        prompt = _DIAGNOSIS_PROMPT.format(
            agent_name=agent.name,
            agent_role=agent.role,
            task=task[:800],
            error=error[:2000],
        )
        try:
            response = self._ai.chat(messages=[{"role": "user", "content": prompt}])
        except Exception as exc:  # noqa: BLE001
            logger.error("SelfHealer: AI diagnosis call failed: %s", exc)
            return ("AI diagnosis unavailable", "Retry the original task as-is.")
        return _parse_diagnosis(response)

    async def _diagnose_async(self, agent, task: str, error: str) -> tuple[str, str]:
        prompt = _DIAGNOSIS_PROMPT.format(
            agent_name=agent.name,
            agent_role=agent.role,
            task=task[:800],
            error=error[:2000],
        )
        try:
            response = await self._ai.async_chat(messages=[{"role": "user", "content": prompt}])
        except Exception as exc:  # noqa: BLE001
            logger.error("SelfHealer[async]: AI diagnosis call failed: %s", exc)
            return ("AI diagnosis unavailable", "Retry the original task as-is.")
        return _parse_diagnosis(response)

    @staticmethod
    def _build_patched_task(task: str, cycle: int, root_cause: str, patch: str) -> str:
        return (
            f"{task}\n\n"
            f"[HEALING PATCH — Cycle {cycle}]\n"
            f"Root cause of previous failure: {root_cause}\n"
            f"Revised approach to use instead:\n{patch}"
        )

    def _persist(self, record: HealingRecord, succeeded: bool) -> None:
        if self._memory is None:
            return
        key = (
            f"healing:{record.agent_name}:last_healed"
            if succeeded
            else f"healing:{record.agent_name}:failed"
        )
        try:
            self._memory.save(key=key, value=record.to_dict())
        except Exception as exc:
            logger.warning("SelfHealer: could not persist healing record: %s", exc)
