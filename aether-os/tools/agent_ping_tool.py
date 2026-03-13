"""
agent_ping_tool — Pattern 2: Direct Agent-to-Agent Communication.

Allows any agent to call another registered agent mid-task and receive
their response before continuing.  The WorkflowEngine reference
(_engine) is injected by ToolManager.inject_engine() at kernel startup.
The calling agent's name (_agent_name) is injected by ToolManager.call().

Anti-patterns guarded
---------------------
• Circular ping-pong : A→B→A is detected and rejected immediately.
• Timeouts           : Each cross-agent call is capped at 120 seconds.
• Missing context    : Raises clear errors when engine is not wired.
"""
from __future__ import annotations

import threading

# ---------------------------------------------------------------------------
# Circular-call guard
# Keyed on "caller_name->target_name" so A can still reach C even while C
# pings B, but A→B→A is rejected.
# ---------------------------------------------------------------------------
_PING_STACK: set[str] = set()
_PING_LOCK = threading.Lock()


def ping_agent(
    target_agent_name: str,
    message: str,
    _engine=None,
    _agent_name: str | None = None,
) -> str:
    """
    Send a message to another registered agent and return their response.

    Parameters
    ----------
    target_agent_name : Name of the agent to contact.
    message           : The request / question to send.
    _engine           : WorkflowEngine — injected by ToolManager.inject_engine().
    _agent_name       : Caller's agent name — injected automatically by ToolManager.call().
    """
    if _engine is None:
        return (
            "❌ Error: WorkflowEngine context is missing. "
            "The ping_agent tool was not initialised correctly — "
            "ensure AetherKernel.tool_manager.inject_engine() has been called."
        )

    target_agent = _engine.registry.get(target_agent_name)
    if target_agent is None:
        registered = ", ".join(_engine.registry.list_names()) or "(none)"
        return (
            f"❌ Error: Agent '{target_agent_name}' not found in registry. "
            f"Registered agents: {registered}"
        )

    caller = _agent_name or "UnknownAgent"
    interaction_key = f"{caller}->{target_agent_name}"

    with _PING_LOCK:
        if interaction_key in _PING_STACK:
            return (
                f"❌ Circular communication detected: '{caller}' cannot ping "
                f"'{target_agent_name}' — that agent is already in the current "
                f"call chain. Resolve this yourself instead."
            )
        _PING_STACK.add(interaction_key)

    try:
        prompt = (
            f"URGENT REQUEST FROM TEAM MEMBER ({caller}):\n"
            f"{message}\n\n"
            f"Provide the required information clearly and concisely."
        )

        import asyncio

        response: str
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already inside an async event loop (e.g., called from an async tool)
                # — schedule the coroutine on the SAME loop from a thread-safe future.
                import concurrent.futures
                future = asyncio.run_coroutine_threadsafe(
                    _engine.execute_async(target_agent, prompt), loop
                )
                response = future.result(timeout=120)
            else:
                response = loop.run_until_complete(
                    _engine.execute_async(target_agent, prompt)
                )
        except RuntimeError:
            # No event loop available — fall back to the synchronous executor
            response = _engine.execute(target_agent, prompt)

        return f"Response from {target_agent_name}:\n{response}"

    except TimeoutError:
        return (
            f"❌ Timeout: '{target_agent_name}' did not respond within 120 seconds."
        )
    except Exception as exc:
        return f"❌ Error communicating with '{target_agent_name}': {exc}"
    finally:
        with _PING_LOCK:
            _PING_STACK.discard(interaction_key)
