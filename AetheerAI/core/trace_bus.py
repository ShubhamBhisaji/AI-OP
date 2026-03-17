"""
TraceBus — Real-time agent execution event collector for AetheerAI.

Every time an agent starts/finishes a task, calls a tool, passes a message
to another agent, or hits an error, it emits a TraceEvent here.

The Streamlit "Assembly Line" page reads the live event stream and renders
a flowchart showing which agents are talking to each other, which are
waiting, and where bottlenecks occur.

Design
------
- In-process singleton (one per Python process / Streamlit session).
- Thread-safe ring-buffer of events (default: 2000 events max).
- No external dependencies — pure stdlib.
- Agents / WorkflowEngine call `TraceBus.current().emit(...)` anywhere.

Event types
-----------
  agent_start     — agent received a task
  agent_end       — agent completed (success or error)
  tool_call       — agent invoked a tool
  tool_result     — tool returned output
  agent_message   — agent sent a message to another agent
  orchestrator    — orchestrator made a routing decision
  checkpoint      — HITL checkpoint triggered
  error           — unhandled error in workflow
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════
# Event model
# ═══════════════════════════════════════════════════════════════════════════

EVENT_TYPES = (
    "agent_start",
    "agent_end",
    "tool_call",
    "tool_result",
    "agent_message",
    "orchestrator",
    "checkpoint",
    "error",
)

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_WAITING = "waiting"


@dataclass
class TraceEvent:
    event_id: str
    event_type: str               # one of EVENT_TYPES
    agent_name: str               # source agent
    timestamp: float = field(default_factory=time.time)
    status: str = STATUS_RUNNING  # running / success / error / waiting
    task: str = ""                # short task description
    detail: str = ""              # extra detail (tool name, message body etc.)
    target_agent: str = ""        # for agent_message: recipient agent name
    tool_name: str = ""           # for tool_call / tool_result
    duration_ms: float = 0.0      # for agent_end / tool_result
    parent_id: str = ""           # for building the trace tree
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "agent_name": self.agent_name,
            "timestamp": self.timestamp,
            "status": self.status,
            "task": self.task,
            "detail": self.detail,
            "target_agent": self.target_agent,
            "tool_name": self.tool_name,
            "duration_ms": round(self.duration_ms, 1),
            "parent_id": self.parent_id,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════════════════════
# TraceBus singleton
# ═══════════════════════════════════════════════════════════════════════════


class TraceBus:
    """
    Thread-safe ring-buffer event bus for live agent tracing.

    Usage
    -----
        bus = TraceBus.current()
        bus.emit("agent_start", agent_name="Analyst", task="Summarise Q1 report")
        bus.emit("tool_call", agent_name="Analyst", tool_name="pdf_tool")

    Reading events
    --------------
        events = bus.events_since(since_ts=1700000000.0)
        snapshot = bus.snapshot()   # full list of current ring-buffer
    """

    _instance: TraceBus | None = None
    _lock = threading.Lock()

    def __init__(self, max_events: int = 2_000):
        self._max_events = max_events
        self._events: deque[TraceEvent] = deque(maxlen=max_events)
        self._counter = 0
        self._io_lock = threading.Lock()

    # ── Singleton access ──────────────────────────────────────────────

    @classmethod
    def current(cls) -> "TraceBus":
        """Return the process-wide singleton, creating it on first access."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton (useful in tests)."""
        with cls._lock:
            cls._instance = None

    # ── Emit ──────────────────────────────────────────────────────────

    def emit(
        self,
        event_type: str,
        agent_name: str,
        *,
        status: str = STATUS_RUNNING,
        task: str = "",
        detail: str = "",
        target_agent: str = "",
        tool_name: str = "",
        duration_ms: float = 0.0,
        parent_id: str = "",
        metadata: dict | None = None,
    ) -> TraceEvent:
        """
        Record a trace event and return it (so callers can use the event_id).
        """
        with self._io_lock:
            self._counter += 1
            evt_id = f"evt-{self._counter:06d}"

        event = TraceEvent(
            event_id=evt_id,
            event_type=event_type,
            agent_name=agent_name,
            status=status,
            task=task,
            detail=detail,
            target_agent=target_agent,
            tool_name=tool_name,
            duration_ms=duration_ms,
            parent_id=parent_id,
            metadata=metadata or {},
        )
        with self._io_lock:
            self._events.append(event)
        return event

    def update_status(self, event_id: str, status: str, duration_ms: float = 0.0) -> None:
        """
        Update the status and optional duration of an already-emitted event.
        Useful for marking agent_start as success/error once the task finishes.
        """
        with self._io_lock:
            for evt in reversed(self._events):
                if evt.event_id == event_id:
                    evt.status = status
                    if duration_ms:
                        evt.duration_ms = duration_ms
                    return

    # ── Reading ───────────────────────────────────────────────────────

    def snapshot(self) -> list[dict]:
        """Return a point-in-time copy of all buffered events as dicts."""
        with self._io_lock:
            return [e.to_dict() for e in self._events]

    def events_since(self, since_ts: float) -> list[dict]:
        """Return all events after `since_ts` (epoch float)."""
        with self._io_lock:
            return [e.to_dict() for e in self._events if e.timestamp > since_ts]

    def latest(self, n: int = 50) -> list[dict]:
        """Return the `n` most recent events."""
        with self._io_lock:
            events = list(self._events)
        return [e.to_dict() for e in events[-n:]]

    def clear(self) -> None:
        """Flush all buffered events."""
        with self._io_lock:
            self._events.clear()
            self._counter = 0

    def stats(self) -> dict:
        """Return summary statistics over the current buffer."""
        with self._io_lock:
            events = list(self._events)

        agents: dict[str, dict] = {}
        tools_called: dict[str, int] = {}
        errors = 0

        for e in events:
            if e.agent_name not in agents:
                agents[e.agent_name] = {"tasks": 0, "errors": 0, "tools": 0}
            if e.event_type == "agent_start":
                agents[e.agent_name]["tasks"] += 1
            if e.event_type == "error" or e.status == STATUS_ERROR:
                agents[e.agent_name]["errors"] += 1
                errors += 1
            if e.event_type == "tool_call":
                agents[e.agent_name]["tools"] += 1
                tools_called[e.tool_name] = tools_called.get(e.tool_name, 0) + 1

        return {
            "total_events": len(events),
            "agents": agents,
            "tools_called": tools_called,
            "total_errors": errors,
        }

    # ── Graph builder (for Streamlit flowchart) ───────────────────────

    def build_graph(self) -> dict:
        """
        Build a node/edge graph from the current event stream
        suitable for rendering with streamlit-agraph or plain HTML/JS.

        Returns
        -------
        {
            "nodes": [{"id": str, "label": str, "status": str, "type": str}],
            "edges": [{"from": str, "to": str, "label": str}],
        }
        """
        with self._io_lock:
            events = list(self._events)

        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        seen_edges: set[tuple] = set()

        for evt in events:
            # Track agent nodes
            if evt.agent_name and evt.agent_name not in nodes:
                nodes[evt.agent_name] = {
                    "id": evt.agent_name,
                    "label": evt.agent_name,
                    "status": STATUS_WAITING,
                    "type": "agent",
                }

            # Update node status
            if evt.agent_name in nodes:
                if evt.event_type == "agent_start":
                    nodes[evt.agent_name]["status"] = STATUS_RUNNING
                elif evt.event_type == "agent_end":
                    nodes[evt.agent_name]["status"] = evt.status

            # Agent → Tool edges
            if evt.event_type == "tool_call" and evt.tool_name:
                tool_id = f"tool:{evt.tool_name}"
                if tool_id not in nodes:
                    nodes[tool_id] = {
                        "id": tool_id,
                        "label": evt.tool_name,
                        "status": STATUS_RUNNING,
                        "type": "tool",
                    }
                edge_key = (evt.agent_name, tool_id, "calls")
                if edge_key not in seen_edges:
                    edges.append({"from": evt.agent_name, "to": tool_id, "label": "calls"})
                    seen_edges.add(edge_key)

            if evt.event_type == "tool_result" and evt.tool_name:
                tool_id = f"tool:{evt.tool_name}"
                if tool_id in nodes:
                    nodes[tool_id]["status"] = evt.status

            # Agent → Agent message edges
            if evt.event_type == "agent_message" and evt.target_agent:
                if evt.target_agent not in nodes:
                    nodes[evt.target_agent] = {
                        "id": evt.target_agent,
                        "label": evt.target_agent,
                        "status": STATUS_WAITING,
                        "type": "agent",
                    }
                edge_key = (evt.agent_name, evt.target_agent, "→")
                if edge_key not in seen_edges:
                    edges.append({"from": evt.agent_name, "to": evt.target_agent, "label": "→"})
                    seen_edges.add(edge_key)

        return {"nodes": list(nodes.values()), "edges": edges}
