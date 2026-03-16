"""
state_checkpoint.py — "Time-Travel" Debugging & State Checkpointing.

Problem: Long-running agentic workflows fail mid-way (step 10 of 12).
Restarting from Step 1 wastes tokens, time, and money.

Solution: CheckpointManager writes a JSON snapshot after every pipeline
step. Operators can then:
  1. List all checkpoints for a workflow session.
  2. Rewind to any prior step.
  3. Optionally edit the task/data at that step.
  4. Resume execution from the rewound point.
  5. Branch — run the same session with different inputs (A/B testing).

Storage
-------
Checkpoints are stored as JSON files under:
  workspace/.checkpoints/<session_id>/step_<N>_<agent>_<ts>.json

The storage directory is configurable; it defaults to
  AetheerAI/workspace/.checkpoints/
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_STORE = Path(__file__).parent.parent / "workspace" / ".checkpoints"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class StepCheckpoint:
    """
    Immutable snapshot of one pipeline step.

    Attributes
    ----------
    checkpoint_id : Globally unique identifier (UUID4).
    session_id    : Groups all steps belonging to one pipeline run.
    step          : 1-based step index within the session.
    total_steps   : Total number of steps expected (None if unknown).
    agent_name    : Agent that produced this result.
    task          : The task/prompt given to the agent at this step.
    result        : The agent's output at this step.
    timestamp     : Unix epoch float.
    metadata      : Arbitrary extra info (eval scores, token usage, etc.).
    """
    checkpoint_id: str
    session_id:    str
    step:          int
    total_steps:   int | None
    agent_name:    str
    task:          str
    result:        str
    timestamp:     float
    metadata:      dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StepCheckpoint":
        return cls(**d)

    def summary(self) -> str:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))
        total = f"/{self.total_steps}" if self.total_steps else ""
        return (
            f"[{ts}] Step {self.step}{total} | Agent: {self.agent_name} | "
            f"ID: {self.checkpoint_id[:8]}…"
        )


# ---------------------------------------------------------------------------
# CheckpointStore — low-level JSON persistence
# ---------------------------------------------------------------------------

class CheckpointStore:
    """
    Persists and retrieves StepCheckpoints as JSON files on disk.

    Directory layout::
        <root>/<session_id>/step_<N>_<agent>_<ts_ms>.json
    """

    def __init__(self, root_dir: Path | str | None = None) -> None:
        self.root = Path(root_dir or _DEFAULT_STORE)
        self.root.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def _checkpoint_file(self, cp: StepCheckpoint) -> Path:
        safe_agent = "".join(c if c.isalnum() else "_" for c in cp.agent_name)[:30]
        ts_ms = int(cp.timestamp * 1000)
        return (
            self._session_dir(cp.session_id)
            / f"step_{cp.step:04d}_{safe_agent}_{ts_ms}.json"
        )

    # ── Write ─────────────────────────────────────────────────────────

    def save(self, cp: StepCheckpoint) -> None:
        session_dir = self._session_dir(cp.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        path = self._checkpoint_file(cp)
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(cp.to_dict(), indent=2), encoding="utf-8")
            os.replace(tmp, path)   # atomic on all platforms
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        logger.debug("Checkpoint saved: %s", path.name)

    # ── Read ──────────────────────────────────────────────────────────

    def list_sessions(self) -> list[str]:
        """Return all session IDs that have at least one checkpoint."""
        if not self.root.exists():
            return []
        return sorted(
            p.name for p in self.root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def list_checkpoints(self, session_id: str) -> list[StepCheckpoint]:
        """Return all checkpoints for a session, ordered by step number."""
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return []
        cps = []
        for path in sorted(session_dir.glob("step_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cps.append(StepCheckpoint.from_dict(data))
            except Exception as exc:
                logger.warning("Could not load checkpoint %s: %s", path.name, exc)
        return sorted(cps, key=lambda c: c.step)

    def get_by_id(self, checkpoint_id: str) -> StepCheckpoint | None:
        """Search all sessions for a checkpoint with the given ID."""
        for session_id in self.list_sessions():
            for cp in self.list_checkpoints(session_id):
                if cp.checkpoint_id == checkpoint_id:
                    return cp
        return None

    def get_latest(self, session_id: str) -> StepCheckpoint | None:
        cps = self.list_checkpoints(session_id)
        return cps[-1] if cps else None

    # ── Delete ────────────────────────────────────────────────────────

    def delete_session(self, session_id: str) -> int:
        """Delete all checkpoints for a session. Returns count of deleted files."""
        import shutil
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return 0
        count = len(list(session_dir.glob("step_*.json")))
        shutil.rmtree(session_dir, ignore_errors=True)
        return count

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        cp = self.get_by_id(checkpoint_id)
        if cp is None:
            return False
        path = self._checkpoint_file(cp)
        path.unlink(missing_ok=True)
        return True


# ---------------------------------------------------------------------------
# CheckpointManager — high-level API
# ---------------------------------------------------------------------------

class CheckpointManager:
    """
    High-level checkpointing API used by WorkflowEngine and the kernel.

    Manages session lifecycle and provides convenient rewind/branch operations.
    """

    def __init__(self, store: CheckpointStore | None = None) -> None:
        self._store = store or CheckpointStore()
        self._current_session: str | None = None

    # ── Session management ────────────────────────────────────────────

    def new_session(self) -> str:
        """Start a new checkpoint session and return its ID."""
        session_id = str(uuid.uuid4())
        self._current_session = session_id
        logger.info("CheckpointManager: new session %s.", session_id[:8])
        return session_id

    @property
    def current_session(self) -> str | None:
        return self._current_session

    def ensure_session(self) -> str:
        if self._current_session is None:
            return self.new_session()
        return self._current_session

    # ── Save ──────────────────────────────────────────────────────────

    def checkpoint(
        self,
        agent_name: str,
        task: str,
        result: str,
        step: int,
        total_steps: int | None = None,
        metadata: dict | None = None,
        session_id: str | None = None,
    ) -> StepCheckpoint:
        """
        Save a checkpoint for the current pipeline step.

        Parameters
        ----------
        agent_name  : Name of the agent that just completed.
        task        : Task/prompt that was run.
        result      : Agent output.
        step        : 1-based step number.
        total_steps : Total steps in the pipeline (optional).
        metadata    : Extra info to attach (e.g. {"eval_score": 9}).
        session_id  : Override the active session (creates new if None).
        """
        sid = session_id or self.ensure_session()
        cp = StepCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            session_id=sid,
            step=step,
            total_steps=total_steps,
            agent_name=agent_name,
            task=task,
            result=result,
            timestamp=time.time(),
            metadata=metadata or {},
        )
        self._store.save(cp)
        logger.info("Checkpoint saved: step %d | agent '%s' | id=%s", step, agent_name, cp.checkpoint_id[:8])
        return cp

    # ── Rewind / branch ───────────────────────────────────────────────

    def rewind_to(
        self,
        checkpoint_id: str,
        revised_task: str | None = None,
    ) -> StepCheckpoint:
        """
        Load a prior checkpoint. Optionally supply a *revised_task* to edit
        the input at that point before resuming execution.

        Returns a StepCheckpoint with the (optionally edited) task.
        Callers should re-run the agent from this checkpoint's step.
        """
        cp = self._store.get_by_id(checkpoint_id)
        if cp is None:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found.")

        if revised_task is not None:
            # Return a modified copy — do NOT overwrite the original snapshot
            import copy
            cp = copy.replace(cp,  # dataclasses.replace
                              task=revised_task,
                              checkpoint_id=str(uuid.uuid4()),  # new ID for the branch
                              timestamp=time.time())
            logger.info(
                "Rewind to step %d (agent '%s') with revised task.",
                cp.step, cp.agent_name,
            )
        else:
            logger.info("Rewind to step %d (agent '%s').", cp.step, cp.agent_name)

        return cp

    def branch(self, checkpoint_id: str, revised_task: str | None = None) -> str:
        """
        Create a new session branching from a specific checkpoint.
        Returns the new session_id. Use rewind_to() to get the starting state.
        """
        cp = self._store.get_by_id(checkpoint_id)
        if cp is None:
            raise KeyError(f"Checkpoint '{checkpoint_id}' not found.")
        new_session_id = str(uuid.uuid4())
        self._current_session = new_session_id
        logger.info(
            "Branch: new session %s from checkpoint %s (step %d).",
            new_session_id[:8], checkpoint_id[:8], cp.step,
        )
        return new_session_id

    # ── Query delegates ───────────────────────────────────────────────

    def list_sessions(self) -> list[str]:
        return self._store.list_sessions()

    def list_checkpoints(self, session_id: str | None = None) -> list[StepCheckpoint]:
        sid = session_id or self._current_session
        if sid is None:
            return []
        return self._store.list_checkpoints(sid)

    def get_checkpoint(self, checkpoint_id: str) -> StepCheckpoint | None:
        return self._store.get_by_id(checkpoint_id)

    def delete_session(self, session_id: str) -> int:
        return self._store.delete_session(session_id)

    def session_summary(self, session_id: str | None = None) -> dict:
        sid = session_id or self._current_session
        if sid is None:
            return {"session_id": None, "steps": 0, "checkpoints": []}
        cps = self._store.list_checkpoints(sid)
        return {
            "session_id": sid,
            "steps": len(cps),
            "latest_step": cps[-1].step if cps else None,
            "latest_agent": cps[-1].agent_name if cps else None,
            "checkpoints": [c.summary() for c in cps],
        }
