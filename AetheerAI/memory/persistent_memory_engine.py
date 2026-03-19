"""persistent_memory_engine.py — Cross-restart memory persistence engine.

Closes GAP 3: Memory Persistence Needs Strengthening.

Agents must retain across restarts:
    - Past interactions (conversation history)
    - Decisions made and their outcomes
    - System state snapshots
    - Learned patterns and preferences
    - Complete work history with searchable context

This engine sits on top of MemoryManager and TieredMemoryManager, adding:
    1. Decision Journal — logs every major decision with context + outcome
    2. Work History Ledger — append-only, searchable record of all work
    3. State Snapshots — periodic agent state checkpoints
    4. Pattern Memory — stores learned patterns/heuristics across sessions
    5. Interaction Log — compressed interaction history for continuity

All data persists to disk as JSON and survives process restarts.

Usage
-----
    engine = PersistentMemoryEngine(agent_name="store_bot")

    # Log a decision
    engine.log_decision(
        action="approve_refund",
        reason="Customer VIP, order < $50",
        outcome="success",
        context={"order_id": "1234", "amount": 45.0},
    )

    # Record work
    engine.record_work(
        task="Process refund for order 1234",
        result="Refund of $45 issued successfully",
        success=True,
    )

    # Save a learned pattern
    engine.learn_pattern(
        name="vip_refund_fast_track",
        description="VIP customers with orders under $50 can be auto-refunded",
        confidence=0.9,
    )

    # Take state snapshot
    engine.snapshot_state({"active_orders": 42, "pending_refunds": 3})

    # Search history
    results = engine.search_history("refund VIP")
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _data_root() -> Path:
    """Resolve persistent data root (PyInstaller-aware)."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "aetheerai_data" / "persistent_memory"
    return Path(__file__).parent / "persistent_data"


# ── Data Types ───────────────────────────────────────────────────────────────

@dataclass
class Decision:
    id: str
    agent_name: str
    action: str
    reason: str
    outcome: str         # "success" | "failure" | "pending" | "escalated"
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Decision":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkEntry:
    id: str
    agent_name: str
    task: str
    result: str
    success: bool
    duration_seconds: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class LearnedPattern:
    id: str
    agent_name: str
    name: str
    description: str
    confidence: float = 0.5     # 0.0 – 1.0
    times_applied: int = 0
    last_applied: float = 0.0
    created_at: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LearnedPattern":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class StateSnapshot:
    id: str
    agent_name: str
    state: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InteractionEntry:
    role: str          # "user" | "agent" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Persistent Memory Engine ────────────────────────────────────────────────

class PersistentMemoryEngine:
    """
    Cross-restart memory persistence for agents.

    Stores decisions, work history, learned patterns, state snapshots,
    and interaction logs as append-only JSON files that survive restarts.

    Parameters
    ----------
    agent_name    : Agent identifier (scopes all data).
    data_dir      : Root directory for persistent data (default: auto-detected).
    max_snapshots : Maximum state snapshots to retain (oldest pruned).
    max_interactions : Maximum interaction entries to retain.
    """

    def __init__(
        self,
        agent_name: str,
        data_dir: str | Path | None = None,
        max_snapshots: int = 50,
        max_interactions: int = 500,
    ) -> None:
        self.agent_name = agent_name
        self._root = Path(data_dir) if data_dir else _data_root()
        self._agent_dir = self._root / agent_name
        self._agent_dir.mkdir(parents=True, exist_ok=True)

        self._max_snapshots = max_snapshots
        self._max_interactions = max_interactions

        # File paths
        self._decisions_path = self._agent_dir / "decisions.json"
        self._work_path = self._agent_dir / "work_history.json"
        self._patterns_path = self._agent_dir / "learned_patterns.json"
        self._snapshots_path = self._agent_dir / "state_snapshots.json"
        self._interactions_path = self._agent_dir / "interactions.json"

        # In-memory caches (loaded from disk on init)
        self._decisions: list[Decision] = []
        self._work_history: list[WorkEntry] = []
        self._patterns: dict[str, LearnedPattern] = {}
        self._snapshots: list[StateSnapshot] = []
        self._interactions: list[InteractionEntry] = []

        self._load_all()
        logger.info(
            "PersistentMemoryEngine[%s]: loaded %d decisions, %d work entries, "
            "%d patterns, %d snapshots, %d interactions.",
            agent_name,
            len(self._decisions),
            len(self._work_history),
            len(self._patterns),
            len(self._snapshots),
            len(self._interactions),
        )

    # ── 1. Decision Journal ──────────────────────────────────────────────

    def log_decision(
        self,
        action: str,
        reason: str,
        outcome: str = "pending",
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Log a decision to the journal. Returns decision ID."""
        decision = Decision(
            id=str(uuid.uuid4()),
            agent_name=self.agent_name,
            action=action,
            reason=reason,
            outcome=outcome,
            context=context or {},
            tags=tags or [],
        )
        self._decisions.append(decision)
        self._persist(self._decisions_path, [d.to_dict() for d in self._decisions])
        logger.debug("PersistentMemory[%s]: decision logged — %s", self.agent_name, action)
        return decision.id

    def update_decision_outcome(self, decision_id: str, outcome: str) -> bool:
        """Update the outcome of a previously logged decision."""
        for decision in self._decisions:
            if decision.id == decision_id:
                decision.outcome = outcome
                self._persist(self._decisions_path, [d.to_dict() for d in self._decisions])
                return True
        return False

    def get_decisions(
        self,
        action: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query decision journal with optional filters."""
        results = list(self._decisions)
        if action:
            results = [d for d in results if action.lower() in d.action.lower()]
        if outcome:
            results = [d for d in results if d.outcome == outcome]
        return [d.to_dict() for d in results[-limit:]]

    # ── 2. Work History Ledger ───────────────────────────────────────────

    def record_work(
        self,
        task: str,
        result: str,
        success: bool,
        duration_seconds: float = 0.0,
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Record a completed work item. Returns entry ID."""
        entry = WorkEntry(
            id=str(uuid.uuid4()),
            agent_name=self.agent_name,
            task=task,
            result=result[:4000],
            success=success,
            duration_seconds=duration_seconds,
            context=context or {},
            tags=tags or [],
        )
        self._work_history.append(entry)
        self._persist(self._work_path, [w.to_dict() for w in self._work_history])
        return entry.id

    def get_work_history(
        self,
        success: bool | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query work history with optional success filter."""
        results = list(self._work_history)
        if success is not None:
            results = [w for w in results if w.success == success]
        return [w.to_dict() for w in results[-limit:]]

    def work_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about work history."""
        total = len(self._work_history)
        successes = sum(1 for w in self._work_history if w.success)
        failures = total - successes
        avg_duration = (
            sum(w.duration_seconds for w in self._work_history) / total
            if total > 0 else 0
        )
        return {
            "total_tasks": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / total, 4) if total > 0 else 0,
            "avg_duration_seconds": round(avg_duration, 2),
        }

    # ── 3. State Snapshots ───────────────────────────────────────────────

    def snapshot_state(self, state: dict[str, Any]) -> str:
        """Save a point-in-time state snapshot. Returns snapshot ID."""
        snapshot = StateSnapshot(
            id=str(uuid.uuid4()),
            agent_name=self.agent_name,
            state=state,
        )
        self._snapshots.append(snapshot)

        # Prune oldest if over limit
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots = self._snapshots[-self._max_snapshots:]

        self._persist(self._snapshots_path, [s.to_dict() for s in self._snapshots])
        return snapshot.id

    def get_latest_snapshot(self) -> dict[str, Any] | None:
        """Return the most recent state snapshot, or None."""
        if not self._snapshots:
            return None
        return self._snapshots[-1].to_dict()

    def get_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent state snapshots."""
        return [s.to_dict() for s in self._snapshots[-limit:]]

    # ── 4. Pattern Memory ────────────────────────────────────────────────

    def learn_pattern(
        self,
        name: str,
        description: str,
        confidence: float = 0.5,
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Store or update a learned pattern. Returns pattern ID."""
        existing = self._patterns.get(name)
        if existing:
            existing.description = description
            existing.confidence = min(1.0, max(0.0, confidence))
            existing.context = context or existing.context
            existing.tags = tags or existing.tags
            pattern_id = existing.id
        else:
            pattern = LearnedPattern(
                id=str(uuid.uuid4()),
                agent_name=self.agent_name,
                name=name,
                description=description,
                confidence=min(1.0, max(0.0, confidence)),
                context=context or {},
                tags=tags or [],
            )
            self._patterns[name] = pattern
            pattern_id = pattern.id

        self._persist(self._patterns_path, {
            k: v.to_dict() for k, v in self._patterns.items()
        })
        return pattern_id

    def apply_pattern(self, name: str) -> LearnedPattern | None:
        """Mark a pattern as applied (increments counter, updates timestamp)."""
        pattern = self._patterns.get(name)
        if pattern is None:
            return None
        pattern.times_applied += 1
        pattern.last_applied = time.time()
        # Confidence grows slightly each time the pattern is reused
        pattern.confidence = min(1.0, pattern.confidence + 0.02)
        self._persist(self._patterns_path, {
            k: v.to_dict() for k, v in self._patterns.items()
        })
        return pattern

    def get_patterns(
        self,
        min_confidence: float = 0.0,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query learned patterns with optional filters."""
        results = list(self._patterns.values())
        if min_confidence > 0:
            results = [p for p in results if p.confidence >= min_confidence]
        if tag:
            results = [p for p in results if tag in p.tags]
        results.sort(key=lambda p: p.confidence, reverse=True)
        return [p.to_dict() for p in results]

    def forget_pattern(self, name: str) -> bool:
        """Remove a learned pattern."""
        if name in self._patterns:
            del self._patterns[name]
            self._persist(self._patterns_path, {
                k: v.to_dict() for k, v in self._patterns.items()
            })
            return True
        return False

    # ── 5. Interaction Log ───────────────────────────────────────────────

    def log_interaction(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log an interaction entry (user message, agent response, system event)."""
        entry = InteractionEntry(
            role=role,
            content=content[:2000],
            metadata=metadata or {},
        )
        self._interactions.append(entry)

        # Prune oldest if over limit
        if len(self._interactions) > self._max_interactions:
            self._interactions = self._interactions[-self._max_interactions:]

        self._persist(self._interactions_path, [i.to_dict() for i in self._interactions])

    def get_interactions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent interaction history."""
        return [i.to_dict() for i in self._interactions[-limit:]]

    # ── Cross-cutting: Search ────────────────────────────────────────────

    def search_history(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search across all memory types by keyword."""
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        # Search decisions
        for d in self._decisions:
            text = f"{d.action} {d.reason} {d.outcome} {json.dumps(d.context, default=str)}"
            if query_lower in text.lower():
                results.append({"type": "decision", **d.to_dict()})

        # Search work history
        for w in self._work_history:
            text = f"{w.task} {w.result}"
            if query_lower in text.lower():
                results.append({"type": "work", **w.to_dict()})

        # Search patterns
        for p in self._patterns.values():
            text = f"{p.name} {p.description}"
            if query_lower in text.lower():
                results.append({"type": "pattern", **p.to_dict()})

        # Search interactions
        for i in self._interactions:
            if query_lower in i.content.lower():
                results.append({"type": "interaction", **i.to_dict()})

        # Sort by timestamp descending and limit
        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return results[:limit]

    # ── Full status report ───────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return a full memory status report."""
        return {
            "agent_name": self.agent_name,
            "data_dir": str(self._agent_dir),
            "decisions": len(self._decisions),
            "work_entries": len(self._work_history),
            "patterns": len(self._patterns),
            "snapshots": len(self._snapshots),
            "interactions": len(self._interactions),
            "work_stats": self.work_stats(),
            "top_patterns": self.get_patterns(min_confidence=0.7)[:5],
            "latest_snapshot": self.get_latest_snapshot(),
        }

    # ── Persistence helpers ──────────────────────────────────────────────

    def _persist(self, path: Path, data: Any) -> None:
        """Atomic write to JSON file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(data, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("PersistentMemory[%s]: write failed for %s: %s",
                           self.agent_name, path.name, exc)

    def _load_all(self) -> None:
        """Load all persistent data from disk."""
        # Decisions
        self._decisions = self._load_list(self._decisions_path, Decision.from_dict)

        # Work history
        self._work_history = self._load_list(self._work_path, WorkEntry.from_dict)

        # Patterns (stored as dict)
        if self._patterns_path.exists():
            try:
                raw = json.loads(self._patterns_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for name, pdata in raw.items():
                        self._patterns[name] = LearnedPattern.from_dict(pdata)
                elif isinstance(raw, list):
                    for pdata in raw:
                        p = LearnedPattern.from_dict(pdata)
                        self._patterns[p.name] = p
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("PersistentMemory: could not load patterns: %s", exc)

        # Snapshots
        self._snapshots = self._load_list(self._snapshots_path, lambda d: StateSnapshot(**{
            k: v for k, v in d.items() if k in StateSnapshot.__dataclass_fields__
        }))

        # Interactions
        self._interactions = self._load_list(self._interactions_path, lambda d: InteractionEntry(**{
            k: v for k, v in d.items() if k in InteractionEntry.__dataclass_fields__
        }))

    @staticmethod
    def _load_list(path: Path, factory) -> list:
        """Load a JSON array file into a list of dataclass instances."""
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            return [factory(item) for item in raw if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("PersistentMemory: could not load %s: %s", path.name, exc)
            return []

    # ── Export / import ──────────────────────────────────────────────────

    def export_all(self) -> dict[str, Any]:
        """Export all memory data as a single dict (for agent packaging)."""
        return {
            "agent_name": self.agent_name,
            "exported_at": time.time(),
            "decisions": [d.to_dict() for d in self._decisions],
            "work_history": [w.to_dict() for w in self._work_history],
            "patterns": {k: v.to_dict() for k, v in self._patterns.items()},
            "snapshots": [s.to_dict() for s in self._snapshots],
            "interactions": [i.to_dict() for i in self._interactions],
        }

    def import_data(self, data: dict[str, Any]) -> None:
        """Import memory data from an export dict (merge, not replace)."""
        for d in data.get("decisions", []):
            self._decisions.append(Decision.from_dict(d))
        for w in data.get("work_history", []):
            self._work_history.append(WorkEntry.from_dict(w))
        for name, p in data.get("patterns", {}).items():
            if name not in self._patterns:
                self._patterns[name] = LearnedPattern.from_dict(p)
        for s in data.get("snapshots", []):
            self._snapshots.append(StateSnapshot(**{
                k: v for k, v in s.items() if k in StateSnapshot.__dataclass_fields__
            }))
        for i in data.get("interactions", []):
            self._interactions.append(InteractionEntry(**{
                k: v for k, v in i.items() if k in InteractionEntry.__dataclass_fields__
            }))
        # Persist all
        self._persist(self._decisions_path, [d.to_dict() for d in self._decisions])
        self._persist(self._work_path, [w.to_dict() for w in self._work_history])
        self._persist(self._patterns_path, {k: v.to_dict() for k, v in self._patterns.items()})
        self._persist(self._snapshots_path, [s.to_dict() for s in self._snapshots])
        self._persist(self._interactions_path, [i.to_dict() for i in self._interactions])
        logger.info("PersistentMemory[%s]: imported memory data.", self.agent_name)

    def __repr__(self) -> str:
        return (
            f"PersistentMemoryEngine(agent={self.agent_name!r}, "
            f"decisions={len(self._decisions)}, work={len(self._work_history)}, "
            f"patterns={len(self._patterns)}, snapshots={len(self._snapshots)})"
        )
