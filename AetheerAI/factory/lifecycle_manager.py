"""
AgentLifecycleManager — Production-grade agent lifecycle for AetheerAI.

Closes the gaps between "create agents from presets" and a true AI-OS:

  Lifecycle States
  ----------------
  warm     — recently active, resources allocated, ready for immediate dispatch
  idle     — created but not recently used, resources conserved
  cold     — inactive for a long time, candidate for cleanup
  retired  — explicitly decommissioned, no new tasks dispatched

  Capability Discovery
  --------------------
  Each agent builds a capability profile from its skills, tools, and performance
  history.  discover_capabilities(name) returns a scored map that other systems
  (orchestrator, planning engine) can use to pick the best agent for a task.

  Dynamic Skill Composition
  -------------------------
  compose_skills(name, extra_skills) adds runtime skills without recreating the
  agent.  Useful when a task requires a skill the agent wasn't trained for.

  Automatic Specialization
  ------------------------
  After enough task completions, auto_specialize(name) asks the AI to suggest
  new skills or tools that would improve the agent based on its history, and
  applies them.

  Smart Dispatch
  --------------
  find_best_agent(task_description) scores all warm/idle agents semantically
  and returns the name of the best match, or None if no suitable agent exists.
  This closes the "capability discovery" gap entirely.
"""

from __future__ import annotations

import json
import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LIFECYCLE_STORE = Path(__file__).parent.parent / "registry" / "lifecycle_store.json"

# Seconds without activity before transitioning state
_WARM_TO_IDLE_SEC: int = 300       # 5 minutes
_IDLE_TO_COLD_SEC: int = 3_600     # 1 hour

# Minimum completions before auto-specialize is triggered
_SPECIALIZE_THRESHOLD: int = 5

_SPECIALIZE_PROMPT = """\
You are an AI agent optimizer.  Based on this agent's performance history,
suggest improvements as a JSON object.

Agent name : {name}
Agent role : {role}
Current skills: {skills}
Current tools : {tools}
Task history (last 20): {history}

Return ONLY valid JSON:
{{
  "add_skills": ["skill_name"],
  "add_tools": ["tool_name"],
  "reasoning": "one sentence"
}}

Rules:
- Only suggest skills/tools that are genuinely useful given the history.
- Limit add_skills and add_tools to 3 items each.
- Do NOT remove existing skills or tools.
"""

_SCORE_PROMPT = """\
You are a capability matching AI.  Score how well this agent can handle the given task.

Task: {task}
Agent role: {role}
Agent skills: {skills}
Agent tools: {tools}

Return ONLY valid JSON:
{{
  "score": <0.0 to 1.0>,
  "reasoning": "one sentence"
}}
"""


@dataclass
class LifecycleRecord:
    name: str
    state: str = "idle"           # warm | idle | cold | retired
    last_active: float = field(default_factory=time.time)
    task_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    avg_duration_sec: float = 0.0
    task_history: list[dict[str, Any]] = field(default_factory=list)
    composed_skills: list[str] = field(default_factory=list)
    specialization_applied: bool = False
    # ── Version tracking ──────────────────────────────────────────────
    current_version: str = ""          # semver of the currently deployed spec
    version_history: list[dict[str, Any]] = field(default_factory=list)  # upgrade audit trail

    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "last_active": self.last_active,
            "task_count": self.task_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "avg_duration_sec": round(self.avg_duration_sec, 2),
            "success_rate": round(self.success_rate(), 3),
            "composed_skills": list(self.composed_skills),
            "specialization_applied": self.specialization_applied,
            "task_history": self.task_history[-20:],  # keep last 20
            "current_version": self.current_version,
            "version_history": self.version_history[-50:],  # keep last 50 upgrades
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LifecycleRecord":
        rec = cls(name=d["name"])
        rec.state = d.get("state", "idle")
        rec.last_active = d.get("last_active", time.time())
        rec.task_count = d.get("task_count", 0)
        rec.success_count = d.get("success_count", 0)
        rec.fail_count = d.get("fail_count", 0)
        rec.avg_duration_sec = d.get("avg_duration_sec", 0.0)
        rec.composed_skills = list(d.get("composed_skills", []))
        rec.specialization_applied = bool(d.get("specialization_applied", False))
        rec.task_history = list(d.get("task_history", []))
        rec.current_version = d.get("current_version", "")
        rec.version_history = list(d.get("version_history", []))
        return rec


class AgentLifecycleManager:
    """
    Manages the full lifecycle and capabilities of all registered agents.

    Inject into AgentFactory and Orchestrator for smart dispatch and
    auto-improvement.
    """

    def __init__(self, registry, ai_adapter=None) -> None:
        self.registry = registry
        self.ai = ai_adapter
        self._records: dict[str, LifecycleRecord] = {}
        self._lock = threading.Lock()
        self._load()
        # Background state-decay thread
        self._decay_thread = threading.Thread(target=self._state_decay_loop, daemon=True)
        self._decay_thread.start()

    # ── State transitions ──────────────────────────────────────────────────

    def activate(self, agent_name: str) -> str:
        """Mark an agent as warm (recently active)."""
        rec = self._get_or_create(agent_name)
        with self._lock:
            if rec.state == "retired":
                return "retired"
            rec.state = "warm"
            rec.last_active = time.time()
        self._save()
        return "warm"

    def deactivate(self, agent_name: str) -> str:
        """Transition a warm agent to idle."""
        rec = self._get_or_create(agent_name)
        with self._lock:
            if rec.state == "warm":
                rec.state = "idle"
        self._save()
        return rec.state

    def retire(self, agent_name: str, reason: str = "") -> None:
        """Permanently decommission an agent."""
        rec = self._get_or_create(agent_name)
        with self._lock:
            rec.state = "retired"
        logger.info("LifecycleManager: agent '%s' retired. Reason: %s", agent_name, reason or "(none)")
        self._save()

    def get_state(self, agent_name: str) -> str:
        rec = self._records.get(agent_name)
        return rec.state if rec else "unknown"

    def list_by_state(self, state: str) -> list[str]:
        """Return names of all agents in a given lifecycle state."""
        with self._lock:
            return [name for name, rec in self._records.items() if rec.state == state]

    # ── Performance tracking ───────────────────────────────────────────────

    def record_performance(
        self,
        agent_name: str,
        *,
        task_type: str,
        success: bool,
        duration_sec: float = 0.0,
        notes: str = "",
    ) -> None:
        """Record a task completion (success or failure) for an agent."""
        rec = self._get_or_create(agent_name)
        with self._lock:
            rec.task_count += 1
            if success:
                rec.success_count += 1
            else:
                rec.fail_count += 1
            # Running weighted average duration
            n = rec.task_count
            rec.avg_duration_sec = ((rec.avg_duration_sec * (n - 1)) + duration_sec) / n
            rec.task_history.append({
                "task_type": task_type,
                "success": success,
                "duration_sec": round(duration_sec, 2),
                "notes": notes[:200],
                "ts": time.time(),
            })
            if len(rec.task_history) > 100:
                rec.task_history = rec.task_history[-100:]
            rec.last_active = time.time()
            rec.state = "warm"
        self._save()

        # Trigger specialization check
        if rec.success_count >= _SPECIALIZE_THRESHOLD and not rec.specialization_applied and self.ai:
            try:
                self.auto_specialize(agent_name)
            except Exception as exc:
                logger.warning("LifecycleManager: auto_specialize failed for %s: %s", agent_name, exc)

    # ── Capability discovery ───────────────────────────────────────────────

    def discover_capabilities(self, agent_name: str) -> dict[str, Any]:
        """
        Return a capability profile for an agent:
            skills, tools, performance, specializations, state.
        """
        rec = self._get_or_create(agent_name)
        agent = self.registry.get(agent_name)
        profile = agent.profile if agent else {}

        base_skills = list(profile.get("skills", []))
        composed = list(rec.composed_skills)
        all_skills = list(dict.fromkeys(base_skills + composed))

        return {
            "name": agent_name,
            "role": profile.get("role", "Unknown"),
            "state": rec.state,
            "skills": all_skills,
            "tools": list(profile.get("tools", [])),
            "permission_level": profile.get("permission_level", 1),
            "performance": {
                "task_count": rec.task_count,
                "success_rate": round(rec.success_rate(), 3),
                "avg_duration_sec": round(rec.avg_duration_sec, 2),
            },
        }

    def all_capabilities(self) -> list[dict[str, Any]]:
        """Return capability profiles for all non-retired agents."""
        names = [
            n for n, r in self._records.items()
            if r.state != "retired"
        ]
        # Also include registered agents not yet in lifecycle records
        if hasattr(self.registry, "list_agents"):
            for name in self.registry.list_agents():
                if name not in names:
                    names.append(name)
        return [self.discover_capabilities(n) for n in names]

    # ── Dynamic skill composition ──────────────────────────────────────────

    def compose_skills(self, agent_name: str, extra_skills: list[str]) -> list[str]:
        """
        Add runtime skills to an agent without recreating it.
        Returns the updated full skill list.
        """
        rec = self._get_or_create(agent_name)
        with self._lock:
            for skill in extra_skills:
                if skill and skill not in rec.composed_skills:
                    rec.composed_skills.append(skill)
        self._save()
        cap = self.discover_capabilities(agent_name)
        logger.info("LifecycleManager: composed skills for '%s': %s", agent_name, cap["skills"])
        return cap["skills"]

    def remove_composed_skill(self, agent_name: str, skill: str) -> None:
        """Remove a dynamically composed skill."""
        rec = self._get_or_create(agent_name)
        with self._lock:
            if skill in rec.composed_skills:
                rec.composed_skills.remove(skill)
        self._save()

    # ── Version tracking ──────────────────────────────────────────────────

    def record_upgrade(
        self,
        agent_name: str,
        to_version: str,
        from_version: str = "",
        update_type: str = "unknown",
        changes: list[str] | None = None,
    ) -> None:
        """
        Record that an agent was upgraded to a new version.

        Called by LifecycleUpdater after a successful UpdateChannel.apply_update().
        """
        rec = self._get_or_create(agent_name)
        with self._lock:
            entry: dict[str, Any] = {
                "from": from_version or rec.current_version,
                "to": to_version,
                "update_type": update_type,
                "changes": list(changes or []),
                "ts": time.time(),
            }
            rec.version_history.append(entry)
            if len(rec.version_history) > 50:
                rec.version_history = rec.version_history[-50:]
            rec.current_version = to_version
        self._save()
        logger.info(
            "LifecycleManager: agent '%s' version %s → %s (%s).",
            agent_name, from_version or "(unknown)", to_version, update_type,
        )

    def record_rollback(
        self,
        agent_name: str,
        to_version: str,
        from_version: str = "",
    ) -> None:
        """Record that an agent was rolled back to a previous version."""
        rec = self._get_or_create(agent_name)
        with self._lock:
            entry: dict[str, Any] = {
                "from": from_version or rec.current_version,
                "to": to_version,
                "update_type": "rollback",
                "changes": [f"Rolled back to {to_version}"],
                "ts": time.time(),
            }
            rec.version_history.append(entry)
            if len(rec.version_history) > 50:
                rec.version_history = rec.version_history[-50:]
            rec.current_version = to_version
        self._save()
        logger.warning(
            "LifecycleManager: agent '%s' rolled back %s → %s.",
            agent_name, from_version or "(unknown)", to_version,
        )

    def get_version(self, agent_name: str) -> str:
        """Return the current deployed version of an agent (empty string if unversioned)."""
        rec = self._records.get(agent_name)
        return rec.current_version if rec else ""

    def get_version_history(
        self, agent_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return the upgrade/rollback history for an agent, newest first."""
        rec = self._records.get(agent_name)
        if rec is None:
            return []
        return list(reversed(rec.version_history[-limit:]))

    # ── Automatic specialization ───────────────────────────────────────────

    def auto_specialize(self, agent_name: str) -> dict[str, Any]:
        """
        Ask the AI to suggest new skills and tools for this agent based on
        its task history, then apply them.
        """
        if self.ai is None:
            return {"error": "No AI adapter available for specialization."}

        rec = self._get_or_create(agent_name)
        agent = self.registry.get(agent_name)
        if agent is None:
            return {"error": f"Agent '{agent_name}' not found in registry."}

        profile = agent.profile
        prompt = _SPECIALIZE_PROMPT.format(
            name=agent_name,
            role=profile.get("role", ""),
            skills=json.dumps(profile.get("skills", []) + rec.composed_skills),
            tools=json.dumps(profile.get("tools", [])),
            history=json.dumps(rec.task_history[-20:], default=str),
        )

        raw = self.ai.chat([{"role": "user", "content": prompt}])
        try:
            data = self._parse_json(raw)
            new_skills = [str(s) for s in data.get("add_skills", []) if s][:3]
            new_tools = [str(t) for t in data.get("add_tools", []) if t][:3]

            if new_skills:
                self.compose_skills(agent_name, new_skills)
            if new_tools and hasattr(agent, "profile"):
                existing_tools = list(profile.get("tools", []))
                for tool in new_tools:
                    if tool not in existing_tools:
                        existing_tools.append(tool)
                agent.profile["tools"] = existing_tools

            with self._lock:
                rec.specialization_applied = True
            self._save()

            logger.info(
                "LifecycleManager: auto-specialized '%s' — added skills=%s tools=%s",
                agent_name, new_skills, new_tools,
            )
            return {"agent": agent_name, "added_skills": new_skills, "added_tools": new_tools,
                    "reasoning": data.get("reasoning", "")}
        except Exception as exc:
            logger.error("LifecycleManager.auto_specialize parse error: %s", exc)
            return {"error": str(exc)}

    # ── Smart dispatch ─────────────────────────────────────────────────────

    def find_best_agent(self, task_description: str) -> str | None:
        """
        Score all warm/idle agents against the task description and return
        the name of the best match, or None if no agent scores > 0.

        Uses keyword matching (fast, no AI call needed for simple cases).
        Falls back to AI scoring for ambiguous cases.
        """
        candidates = [
            cap for cap in self.all_capabilities()
            if cap["state"] in ("warm", "idle")
        ]
        if not candidates:
            return None

        # Fast keyword scoring
        task_lower = task_description.lower()
        scores: list[tuple[float, str]] = []
        for cap in candidates:
            score = self._keyword_score(task_lower, cap)
            scores.append((score, cap["name"]))

        scores.sort(key=lambda x: x[0], reverse=True)
        best_score, best_name = scores[0]

        # If top score is ambiguous (multiple agents within 0.1 of each other) and AI is available
        top_candidates = [name for s, name in scores if s >= best_score - 0.1]
        if len(top_candidates) > 1 and self.ai is not None:
            return self._ai_score_candidates(task_description, top_candidates) or best_name

        return best_name if best_score > 0 else None

    def _keyword_score(self, task_lower: str, cap: dict[str, Any]) -> float:
        score = 0.0
        for skill in cap.get("skills", []):
            if skill.lower().replace("_", " ") in task_lower:
                score += 0.3
        for tool in cap.get("tools", []):
            if tool.lower().replace("_", " ") in task_lower:
                score += 0.2
        role_words = cap.get("role", "").lower().split()
        for word in role_words:
            if word in task_lower:
                score += 0.1
        # Warm agents get a small priority boost
        if cap.get("state") == "warm":
            score += 0.05
        # Higher success rate is a bonus
        perf = cap.get("performance", {})
        score += perf.get("success_rate", 0.0) * 0.1
        return min(score, 1.0)

    def _ai_score_candidates(self, task: str, candidate_names: list[str]) -> str | None:
        """Ask AI to pick the best agent from a short list."""
        caps = [
            self.discover_capabilities(name) for name in candidate_names
        ]
        candidates_text = json.dumps(
            [{"name": c["name"], "role": c["role"], "skills": c["skills"]} for c in caps],
            indent=2,
        )
        prompt = (
            f"Task: {task[:500]}\n\n"
            f"Candidate agents:\n{candidates_text}\n\n"
            "Which agent is best suited for this task? "
            "Reply with ONLY the agent name (exact string, no explanation)."
        )
        try:
            answer = self.ai.chat([{"role": "user", "content": prompt}]).strip()
            if answer in candidate_names:
                return answer
        except Exception as exc:
            logger.warning("LifecycleManager._ai_score_candidates failed: %s", exc)
        return None

    # ── Convenience ───────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Return a dashboard-friendly summary of all agents."""
        all_states: dict[str, list[str]] = {"warm": [], "idle": [], "cold": [], "retired": []}
        for name, rec in self._records.items():
            bucket = all_states.get(rec.state, [])
            bucket.append(name)
        return {
            "total": len(self._records),
            "by_state": all_states,
            "top_performers": self._top_performers(3),
        }

    def _top_performers(self, n: int) -> list[str]:
        ranked = sorted(
            [(rec.success_rate(), name) for name, rec in self._records.items()
             if rec.task_count >= 3],
            reverse=True,
        )
        return [name for _, name in ranked[:n]]

    # ── Persistence ───────────────────────────────────────────────────────

    def _get_or_create(self, name: str) -> LifecycleRecord:
        with self._lock:
            if name not in self._records:
                self._records[name] = LifecycleRecord(name=name)
        return self._records[name]

    def _save(self) -> None:
        try:
            _LIFECYCLE_STORE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {name: rec.to_dict() for name, rec in self._records.items()}
            _LIFECYCLE_STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("LifecycleManager._save failed: %s", exc)

    def _load(self) -> None:
        if not _LIFECYCLE_STORE.exists():
            return
        try:
            data = json.loads(_LIFECYCLE_STORE.read_text(encoding="utf-8"))
            for name, rec_dict in data.items():
                self._records[name] = LifecycleRecord.from_dict(rec_dict)
        except Exception as exc:
            logger.error("LifecycleManager._load failed: %s", exc)

    # ── Background state decay ─────────────────────────────────────────────

    def _state_decay_loop(self) -> None:
        """Background thread: warm → idle → cold based on inactivity."""
        while True:
            time.sleep(60)
            now = time.time()
            changed = False
            with self._lock:
                for rec in self._records.values():
                    if rec.state == "retired":
                        continue
                    idle = now - rec.last_active
                    if rec.state == "warm" and idle > _WARM_TO_IDLE_SEC:
                        rec.state = "idle"
                        changed = True
                    elif rec.state == "idle" and idle > _IDLE_TO_COLD_SEC:
                        rec.state = "cold"
                        changed = True
            if changed:
                self._save()

    # ── JSON helper ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if "```" in text:
            import re
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if m:
                text = m.group(1)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON object found.")
        return json.loads(text[start:end])
