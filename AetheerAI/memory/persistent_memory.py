"""persistent_memory.py — Cross-restart memory persistence layer.

Closes GAP 3: Memory Persistence Needs Strengthening.

Agents need to retain across restarts:
  - Past interactions (conversation history)
  - Decisions (what was decided and why)
  - System state (snapshots of runtime state)
  - Learned patterns (what worked, what didn't)
  - Work history (completed tasks, outcomes, timestamps)

This module adds structured persistence on top of the existing MemoryManager
and TieredMemoryManager.  It provides dedicated stores for each memory type
with automatic serialization, indexing, and retrieval.

Usage
-----
    pm = PersistentMemoryStore(agent_name="store_bot")

    # Log a decision
    pm.log_decision("Switched to Stripe for payments", reason="Lower fees", confidence=0.9)

    # Log work history
    pm.log_work("Sent 42 recovery emails", success=True, duration_ms=1200)

    # Record a learned pattern
    pm.learn_pattern("retry_with_backoff", "Retrying with exponential backoff works better for rate-limited APIs")

    # Save a state snapshot
    pm.save_state_snapshot({"active_integrations": 3, "pending_goals": 2})

    # Query across restarts
    decisions = pm.get_decisions(limit=10)
    patterns = pm.get_patterns()
    history = pm.get_work_history(limit=20)
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

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "persistent_store"
_MAX_ENTRIES_PER_STORE = 5000
_MAX_SNAPSHOT_KEEP = 50


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class DecisionRecord:
    """A logged decision with context."""
    id: str
    agent_name: str
    description: str
    reason: str = ""
    confidence: float = 1.0          # 0.0 - 1.0
    alternatives: list[str] = field(default_factory=list)
    outcome: str = ""                # filled in later
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkRecord:
    """A logged work item / task execution."""
    id: str
    agent_name: str
    description: str
    success: bool = True
    result: str = ""
    error: str = ""
    duration_ms: float = 0.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class LearnedPattern:
    """A pattern the agent has learned from experience."""
    id: str
    agent_name: str
    name: str                        # e.g. "retry_with_backoff"
    description: str
    confidence: float = 0.5          # grows with repeated confirmation
    times_applied: int = 0
    times_succeeded: int = 0
    times_failed: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        if self.times_applied == 0:
            return 0.0
        return self.times_succeeded / self.times_applied

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["success_rate"] = self.success_rate
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LearnedPattern":
        data.pop("success_rate", None)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class InteractionRecord:
    """A logged interaction / conversation turn."""
    id: str
    agent_name: str
    role: str              # "user" | "agent" | "system"
    content: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InteractionRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── PersistentMemoryStore ─────────────────────────────────────────────────────

class PersistentMemoryStore:
    """
    Structured persistent memory that survives restarts.

    Stores decisions, work history, learned patterns, interactions,
    and state snapshots in separate JSON files scoped by agent name.

    Parameters
    ----------
    agent_name : Name of the agent this store belongs to.
    data_dir   : Directory for persistent storage (default: memory/persistent_store/).
    """

    def __init__(
        self,
        agent_name: str,
        data_dir: Path | str | None = None,
    ) -> None:
        self.agent_name = agent_name
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._agent_dir = self._data_dir / agent_name
        self._agent_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self._decisions_file = self._agent_dir / "decisions.json"
        self._work_history_file = self._agent_dir / "work_history.json"
        self._patterns_file = self._agent_dir / "patterns.json"
        self._interactions_file = self._agent_dir / "interactions.json"
        self._snapshots_dir = self._agent_dir / "snapshots"

        # In-memory caches (loaded from disk on init)
        self._decisions: list[DecisionRecord] = self._load_list(self._decisions_file, DecisionRecord)
        self._work_history: list[WorkRecord] = self._load_list(self._work_history_file, WorkRecord)
        self._patterns: dict[str, LearnedPattern] = self._load_patterns()
        self._interactions: list[InteractionRecord] = self._load_list(self._interactions_file, InteractionRecord)

        logger.info(
            "PersistentMemoryStore[%s]: loaded %d decisions, %d work items, "
            "%d patterns, %d interactions.",
            agent_name,
            len(self._decisions),
            len(self._work_history),
            len(self._patterns),
            len(self._interactions),
        )

    # ── Decisions ─────────────────────────────────────────────────────────────

    def log_decision(
        self,
        description: str,
        reason: str = "",
        confidence: float = 1.0,
        alternatives: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> DecisionRecord:
        """Log a decision the agent made."""
        record = DecisionRecord(
            id=str(uuid.uuid4()),
            agent_name=self.agent_name,
            description=description,
            reason=reason,
            confidence=max(0.0, min(1.0, confidence)),
            alternatives=list(alternatives or []),
            tags=list(tags or []),
        )
        self._decisions.append(record)
        self._trim_list(self._decisions)
        self._save_list(self._decisions_file, self._decisions)
        return record

    def update_decision_outcome(self, decision_id: str, outcome: str) -> bool:
        """Update the outcome of a previously logged decision."""
        for d in self._decisions:
            if d.id == decision_id:
                d.outcome = outcome
                self._save_list(self._decisions_file, self._decisions)
                return True
        return False

    def get_decisions(
        self,
        limit: int = 20,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent decisions, optionally filtered by tags."""
        results = list(self._decisions)
        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [d for d in results if tag_set & set(t.lower() for t in d.tags)]
        return [d.to_dict() for d in results[-max(1, limit):]]

    # ── Work history ─────────────────────────────────────────────────────────

    def log_work(
        self,
        description: str,
        success: bool = True,
        result: str = "",
        error: str = "",
        duration_ms: float = 0.0,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkRecord:
        """Log a completed work item."""
        record = WorkRecord(
            id=str(uuid.uuid4()),
            agent_name=self.agent_name,
            description=description,
            success=success,
            result=result[:4000],
            error=error[:2000],
            duration_ms=max(0.0, duration_ms),
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        self._work_history.append(record)
        self._trim_list(self._work_history)
        self._save_list(self._work_history_file, self._work_history)
        return record

    def get_work_history(
        self,
        limit: int = 20,
        success_only: bool = False,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent work history."""
        results = list(self._work_history)
        if success_only:
            results = [w for w in results if w.success]
        if tags:
            tag_set = set(t.lower() for t in tags)
            results = [w for w in results if tag_set & set(t.lower() for t in w.tags)]
        return [w.to_dict() for w in results[-max(1, limit):]]

    def work_summary(self) -> dict[str, Any]:
        """Aggregate statistics about work history."""
        total = len(self._work_history)
        succeeded = sum(1 for w in self._work_history if w.success)
        failed = total - succeeded
        avg_duration = (
            sum(w.duration_ms for w in self._work_history) / max(1, total)
        )
        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": round(succeeded / max(1, total), 4),
            "avg_duration_ms": round(avg_duration, 2),
        }

    # ── Learned patterns ─────────────────────────────────────────────────────

    def learn_pattern(
        self,
        name: str,
        description: str,
        confidence: float = 0.5,
        tags: list[str] | None = None,
    ) -> LearnedPattern:
        """Record a new learned pattern or update an existing one."""
        existing = self._patterns.get(name)
        if existing:
            existing.description = description
            existing.confidence = max(0.0, min(1.0, confidence))
            existing.updated_at = time.time()
            if tags:
                existing.tags = list(set(existing.tags + list(tags)))
        else:
            existing = LearnedPattern(
                id=str(uuid.uuid4()),
                agent_name=self.agent_name,
                name=name,
                description=description,
                confidence=max(0.0, min(1.0, confidence)),
                tags=list(tags or []),
            )
        self._patterns[name] = existing
        self._save_patterns()
        return existing

    def record_pattern_outcome(self, name: str, success: bool) -> bool:
        """Record that a pattern was applied with a given outcome."""
        pattern = self._patterns.get(name)
        if pattern is None:
            return False
        pattern.times_applied += 1
        if success:
            pattern.times_succeeded += 1
            pattern.confidence = min(1.0, pattern.confidence + 0.05)
        else:
            pattern.times_failed += 1
            pattern.confidence = max(0.0, pattern.confidence - 0.1)
        pattern.updated_at = time.time()
        self._save_patterns()
        return True

    def get_patterns(
        self,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Retrieve learned patterns above a confidence threshold."""
        results = [
            p for p in self._patterns.values()
            if p.confidence >= min_confidence
        ]
        results.sort(key=lambda p: p.confidence, reverse=True)
        return [p.to_dict() for p in results]

    def get_pattern(self, name: str) -> dict[str, Any] | None:
        pattern = self._patterns.get(name)
        return pattern.to_dict() if pattern else None

    # ── Interactions ─────────────────────────────────────────────────────────

    def log_interaction(
        self,
        role: str,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> InteractionRecord:
        """Log a conversation turn."""
        record = InteractionRecord(
            id=str(uuid.uuid4()),
            agent_name=self.agent_name,
            role=role,
            content=content[:5000],
            context=dict(context or {}),
        )
        self._interactions.append(record)
        self._trim_list(self._interactions)
        self._save_list(self._interactions_file, self._interactions)
        return record

    def get_interactions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent interactions."""
        return [i.to_dict() for i in self._interactions[-max(1, limit):]]

    # ── State snapshots ──────────────────────────────────────────────────────

    def save_state_snapshot(
        self,
        state: dict[str, Any],
        label: str = "",
    ) -> Path:
        """Save a point-in-time snapshot of system state."""
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "agent_name": self.agent_name,
            "label": label,
            "timestamp": time.time(),
            "state": state,
        }
        filename = f"snapshot_{int(time.time() * 1000)}.json"
        path = self._snapshots_dir / filename
        path.write_text(
            json.dumps(snapshot, indent=2, default=str),
            encoding="utf-8",
        )

        # Prune old snapshots
        snapshots = sorted(
            self._snapshots_dir.glob("snapshot_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in snapshots[_MAX_SNAPSHOT_KEEP:]:
            try:
                stale.unlink()
            except OSError:
                pass

        return path

    def get_latest_snapshot(self) -> dict[str, Any] | None:
        """Load the most recent state snapshot."""
        if not self._snapshots_dir.exists():
            return None
        snapshots = sorted(
            self._snapshots_dir.glob("snapshot_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not snapshots:
            return None
        try:
            return json.loads(snapshots[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def list_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        """List available state snapshots (metadata only)."""
        if not self._snapshots_dir.exists():
            return []
        snapshots = sorted(
            self._snapshots_dir.glob("snapshot_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        results = []
        for snap_path in snapshots[:max(1, limit)]:
            try:
                data = json.loads(snap_path.read_text(encoding="utf-8"))
                results.append({
                    "file": snap_path.name,
                    "label": data.get("label", ""),
                    "timestamp": data.get("timestamp", 0),
                })
            except (OSError, json.JSONDecodeError):
                continue
        return results

    # ── Full memory export ───────────────────────────────────────────────────

    def export_all(self) -> dict[str, Any]:
        """Export all persistent memory as a single dict."""
        return {
            "agent_name": self.agent_name,
            "exported_at": time.time(),
            "decisions": [d.to_dict() for d in self._decisions],
            "work_history": [w.to_dict() for w in self._work_history],
            "patterns": [p.to_dict() for p in self._patterns.values()],
            "interactions": [i.to_dict() for i in self._interactions],
            "work_summary": self.work_summary(),
            "latest_snapshot": self.get_latest_snapshot(),
        }

    # ── Internal persistence ─────────────────────────────────────────────────

    def _save_list(self, path: Path, items: list) -> None:
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps([item.to_dict() for item in items], indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("PersistentMemoryStore: save failed for %s: %s", path.name, exc)

    def _load_list(self, path: Path, cls: type) -> list:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [cls.from_dict(item) for item in data]
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("PersistentMemoryStore: load failed for %s: %s", path.name, exc)
            return []

    def _save_patterns(self) -> None:
        try:
            tmp = self._patterns_file.with_suffix(".json.tmp")
            data = {name: p.to_dict() for name, p in self._patterns.items()}
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self._patterns_file)
        except OSError as exc:
            logger.warning("PersistentMemoryStore: save patterns failed: %s", exc)

    def _load_patterns(self) -> dict[str, LearnedPattern]:
        if not self._patterns_file.exists():
            return {}
        try:
            data = json.loads(self._patterns_file.read_text(encoding="utf-8"))
            return {name: LearnedPattern.from_dict(pdata) for name, pdata in data.items()}
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("PersistentMemoryStore: load patterns failed: %s", exc)
            return {}

    @staticmethod
    def _trim_list(items: list, max_size: int = _MAX_ENTRIES_PER_STORE) -> None:
        """Trim a list to max_size by removing oldest entries."""
        while len(items) > max_size:
            items.pop(0)

    def __repr__(self) -> str:
        return (
            f"PersistentMemoryStore(agent={self.agent_name!r}, "
            f"decisions={len(self._decisions)}, "
            f"work_history={len(self._work_history)}, "
            f"patterns={len(self._patterns)})"
        )
