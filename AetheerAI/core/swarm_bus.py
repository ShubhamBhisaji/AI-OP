"""
swarm_bus.py — Peer-to-Peer (P2P) Swarm Intelligence Bus.

Problem: In a centralised Master AI model, every tiny inter-agent request
must pass through the orchestrator. This concentrates load, adds latency,
and costs tokens. The Master AI becomes a bottleneck.

Solution: A decentralised SwarmBus — an in-process pub/sub backbone that
lets agents communicate directly without the Master AI in the hot path.

Key patterns
------------
Broadcast:
    An agent publishes a message to a topic. All subscribed agents receive it.
    Example: "project_update" — broadcast to all agents watching that topic.

Volunteer (Capability Matching):
    An agent broadcasts a *need* ("I need a code reviewer").
    Agents registered for that capability respond.
    The SwarmBus picks the best-suited volunteer automatically.

Direct Message:
    Agent A sends a message directly to Agent B by name.

All messages are threadsafe. Async helpers are provided for asyncio contexts.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------

@dataclass
class SwarmMessage:
    """
    A single message on the SwarmBus.

    Attributes
    ----------
    message_id  : UUID4 unique per message.
    topic       : Routing key (e.g. "code_review", "project_update").
    payload     : Arbitrary string content.
    sender      : Agent name (or "broadcast" / "system").
    recipient   : Target agent name, or "*" for broadcast.
    timestamp   : Unix epoch float.
    read_by     : Set of agent names that have consumed this message.
    """
    message_id: str
    topic:      str
    payload:    str
    sender:     str
    recipient:  str = "*"   # "*" = broadcast
    timestamp:  float = field(default_factory=time.time)
    read_by:    set[str] = field(default_factory=set)

    def mark_read(self, agent_name: str) -> None:
        self.read_by.add(agent_name)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "topic":      self.topic,
            "payload":    self.payload[:500],
            "sender":     self.sender,
            "recipient":  self.recipient,
            "timestamp":  self.timestamp,
            "read_by":    sorted(self.read_by),
        }


@dataclass
class AgentCapability:
    """Declares what topics / roles an agent can service."""
    agent_name:  str
    topics:      list[str]
    description: str = ""
    priority:    int = 50   # higher = preferred volunteer


# ---------------------------------------------------------------------------
# VolunteerRequest — broadcast a need and await an offer
# ---------------------------------------------------------------------------

@dataclass
class VolunteerRequest:
    """
    Result of a SwarmBus.request_help() call.

    If a volunteer was found, `volunteer` is set to their agent name.
    `response` is whatever the volunteer replied with (if they replied inline).
    """
    topic:      str
    payload:    str
    sender:     str
    volunteer:  str | None = None
    response:   str | None = None
    resolved:   bool = False


# ---------------------------------------------------------------------------
# SwarmBus
# ---------------------------------------------------------------------------

class SwarmBus:
    """
    In-process, thread-safe pub/sub + capability-matching bus for agents.

    Agents register topics they can handle (capabilities). Other agents post
    messages or broadcast needs. The bus routes messages and tracks unread items.

    Usage
    -----
    bus = SwarmBus()

    # Register what each agent is good at
    bus.register_capabilities("reviewer_agent", ["code_review", "quality_check"])
    bus.register_capabilities("coder_agent",    ["write_code", "debug"])

    # Subscribe to receive messages
    bus.subscribe("reviewer_agent", ["code_review", "project_update"])

    # Broadcast a need
    result = bus.request_help(
        topic="code_review",
        payload="Please review this Python function: ...",
        sender="coder_agent",
    )
    print(f"Volunteer: {result.volunteer}")  # → "reviewer_agent"

    # Read unread messages
    messages = bus.get_messages("reviewer_agent")
    """

    def __init__(self) -> None:
        # topic → set of subscribed agent names
        self._subscriptions: dict[str, set[str]] = {}
        # agent_name → AgentCapability
        self._capabilities: dict[str, AgentCapability] = {}
        # All messages (capped at 5000 for memory safety)
        self._messages: list[SwarmMessage] = []
        # Per-agent inbox queues (thread-safe)
        self._inboxes: dict[str, queue.Queue] = {}
        self._lock = threading.RLock()
        logger.info("SwarmBus initialised.")

    # ── Capability registration ───────────────────────────────────────

    def register_capabilities(
        self,
        agent_name: str,
        topics: list[str],
        description: str = "",
        priority: int = 50,
    ) -> None:
        """
        Register an agent's capabilities (topics it can handle).

        Automatically subscribes the agent to those topics.
        """
        with self._lock:
            self._capabilities[agent_name] = AgentCapability(
                agent_name=agent_name,
                topics=list(topics),
                description=description,
                priority=priority,
            )
            if agent_name not in self._inboxes:
                self._inboxes[agent_name] = queue.Queue()
        self.subscribe(agent_name, topics)
        logger.info(
            "SwarmBus: '%s' registered capabilities: %s.", agent_name, topics
        )

    def deregister(self, agent_name: str) -> None:
        """Remove an agent from the bus entirely."""
        with self._lock:
            self._capabilities.pop(agent_name, None)
            self._inboxes.pop(agent_name, None)
            for subscribers in self._subscriptions.values():
                subscribers.discard(agent_name)
        logger.info("SwarmBus: '%s' deregistered.", agent_name)

    # ── Subscription management ───────────────────────────────────────

    def subscribe(self, agent_name: str, topics: list[str]) -> None:
        """Subscribe an agent to one or more topics."""
        with self._lock:
            if agent_name not in self._inboxes:
                self._inboxes[agent_name] = queue.Queue()
            for topic in topics:
                self._subscriptions.setdefault(topic, set()).add(agent_name)

    def unsubscribe(self, agent_name: str, topics: list[str] | None = None) -> None:
        """
        Unsubscribe an agent from topics.  If topics is None, remove from all.
        """
        with self._lock:
            if topics is None:
                for subs in self._subscriptions.values():
                    subs.discard(agent_name)
            else:
                for topic in topics:
                    self._subscriptions.get(topic, set()).discard(agent_name)

    # ── Messaging ─────────────────────────────────────────────────────

    def post(
        self,
        topic: str,
        payload: str,
        sender: str,
        recipient: str = "*",
    ) -> SwarmMessage:
        """
        Post a message to the bus.  If recipient="*", deliver to all subscribers.
        """
        msg = SwarmMessage(
            message_id=str(uuid.uuid4()),
            topic=topic,
            payload=payload,
            sender=sender,
            recipient=recipient,
        )
        with self._lock:
            self._messages.append(msg)
            if len(self._messages) > 5000:
                self._messages = self._messages[-5000:]

            if recipient == "*":
                targets = set(self._subscriptions.get(topic, set()))
            else:
                targets = {recipient} if recipient in self._inboxes else set()

        # Deliver to agent inboxes (outside lock to reduce contention)
        for target in targets:
            inbox = self._inboxes.get(target)
            if inbox is not None:
                try:
                    inbox.put_nowait(msg)
                except queue.Full:
                    pass  # inbox overflow; message dropped for this agent

        logger.debug(
            "SwarmBus: '%s' posted '%s' to topic '%s' (recipients: %d).",
            sender, payload[:60], topic, len(targets),
        )
        return msg

    def broadcast(self, topic: str, payload: str, sender: str) -> list[str]:
        """
        Broadcast a message to all agents subscribed to *topic*.
        Returns the list of agent names that received the message.
        """
        with self._lock:
            targets = list(self._subscriptions.get(topic, set()))

        self.post(topic=topic, payload=payload, sender=sender, recipient="*")
        return targets

    def direct_message(self, payload: str, sender: str, recipient: str, topic: str = "direct") -> SwarmMessage:
        """Send a message directly to a specific agent."""
        return self.post(topic=topic, payload=payload, sender=sender, recipient=recipient)

    # ── Volunteer / capability matching ──────────────────────────────

    def request_help(
        self,
        topic: str,
        payload: str,
        sender: str,
    ) -> VolunteerRequest:
        """
        Broadcast a need and return the best-matched volunteer.

        Matching logic:
          1. Find all agents registered with this capability topic.
          2. Exclude the sender.
          3. Pick the highest-priority agent.
          4. Deliver the message to their inbox.
        """
        req = VolunteerRequest(topic=topic, payload=payload, sender=sender)

        with self._lock:
            candidates = [
                cap for cap in self._capabilities.values()
                if topic in cap.topics and cap.agent_name != sender
            ]

        if not candidates:
            logger.info("SwarmBus: no volunteers for topic '%s'.", topic)
            return req

        # Sort by priority (highest first), then by name for determinism
        candidates.sort(key=lambda c: (-c.priority, c.agent_name))
        best = candidates[0]

        msg = self.direct_message(
            payload=payload,
            sender=sender,
            recipient=best.agent_name,
            topic=topic,
        )
        req.volunteer = best.agent_name
        req.resolved  = True

        logger.info(
            "SwarmBus: '%s' volunteered for topic '%s' (requested by '%s').",
            best.agent_name, topic, sender,
        )
        return req

    async def request_help_async(
        self,
        topic: str,
        payload: str,
        sender: str,
        workflow_engine=None,
        timeout: float = 30.0,
    ) -> VolunteerRequest:
        """
        Async volunteer request.  If *workflow_engine* is provided, the
        volunteer agent is actually executed on the payload as a task,
        and the result is returned as `VolunteerRequest.response`.
        """
        req = self.request_help(topic=topic, payload=payload, sender=sender)
        if not req.resolved or req.volunteer is None:
            return req

        if workflow_engine is None:
            return req

        # Run the volunteering agent on the payload
        registry = getattr(workflow_engine, "registry", None)
        if registry is None:
            return req

        agent = registry.get(req.volunteer)
        if agent is None:
            return req

        try:
            coro = workflow_engine.execute_async(agent=agent, task=payload)
            response = await asyncio.wait_for(coro, timeout=timeout)
            req.response = str(response)
        except Exception as exc:
            logger.warning("SwarmBus async volunteer execution failed: %s", exc)
            req.response = f"[error: {exc}]"

        return req

    # ── Read messages ─────────────────────────────────────────────────

    def get_messages(
        self,
        agent_name: str,
        unread_only: bool = True,
        max_messages: int = 50,
    ) -> list[SwarmMessage]:
        """
        Drain up to *max_messages* from an agent's inbox.

        When *unread_only* is True (default), only messages the agent
        hasn't yet read are returned and marked as read.
        """
        inbox = self._inboxes.get(agent_name)
        if inbox is None:
            return []

        result: list[SwarmMessage] = []
        while len(result) < max_messages:
            try:
                msg = inbox.get_nowait()
                if unread_only:
                    msg.mark_read(agent_name)
                result.append(msg)
            except queue.Empty:
                break
        return result

    def peek_messages(self, agent_name: str) -> int:
        """Return the number of unread messages waiting for an agent."""
        inbox = self._inboxes.get(agent_name)
        return inbox.qsize() if inbox is not None else 0

    # ── Introspection ─────────────────────────────────────────────────

    def list_capabilities(self) -> dict[str, list[str]]:
        """Return {agent_name: [topic1, topic2, ...]} for all registered agents."""
        with self._lock:
            return {
                name: list(cap.topics)
                for name, cap in self._capabilities.items()
            }

    def list_subscriptions(self) -> dict[str, list[str]]:
        """Return {topic: [agent1, agent2, ...]} for all subscriptions."""
        with self._lock:
            return {
                topic: sorted(agents)
                for topic, agents in self._subscriptions.items()
                if agents
            }

    def recent_messages(self, limit: int = 20) -> list[dict]:
        """Return the last *limit* messages posted to the bus."""
        with self._lock:
            return [m.to_dict() for m in self._messages[-limit:]]

    def stats(self) -> dict:
        with self._lock:
            return {
                "registered_agents": len(self._capabilities),
                "topics": len(self._subscriptions),
                "total_messages": len(self._messages),
                "pending_inboxes": {
                    name: q.qsize()
                    for name, q in self._inboxes.items()
                    if q.qsize() > 0
                },
            }
