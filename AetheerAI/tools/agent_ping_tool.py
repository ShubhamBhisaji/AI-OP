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
#
# Uses threading.local() so each thread (workflow) maintains its own call
# stack — concurrent workflows no longer share state and cannot falsely
# block each other's legitimate pings.
# ---------------------------------------------------------------------------
_PING_LOCAL = threading.local()


def _get_ping_stack() -> set[str]:
    """Return the per-thread ping stack, creating it on first access."""
    if not hasattr(_PING_LOCAL, "stack"):
        _PING_LOCAL.stack = set()
    return _PING_LOCAL.stack


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
            "ensure AetheerAiKernel.tool_manager.inject_engine() has been called."
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

    ping_stack = _get_ping_stack()
    if interaction_key in ping_stack:
        return (
            f"❌ Circular communication detected: '{caller}' cannot ping "
            f"'{target_agent_name}' — that agent is already in the current "
            f"call chain. Resolve this yourself instead."
        )
    ping_stack.add(interaction_key)

    try:
        prompt = (
            f"URGENT REQUEST FROM TEAM MEMBER ({caller}):\n"
            f"{message}\n\n"
            f"Provide the required information clearly and concisely."
        )

        import asyncio

        response: str
        try:
            loop = asyncio.get_running_loop()
            # Already inside a running event loop — schedule on the same loop
            # from a thread-safe future to avoid nesting run_until_complete.
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                _engine.execute_async(target_agent, prompt), loop
            )
            response = future.result(timeout=120)
        except RuntimeError:
            # No running event loop — start one via asyncio.run(), or fall back
            # to the synchronous executor if that also fails.
            try:
                response = asyncio.run(
                    _engine.execute_async(target_agent, prompt)
                )
            except Exception:
                response = _engine.execute(target_agent, prompt)

        return f"Response from {target_agent_name}:\n{response}"

    except TimeoutError:
        return (
            f"❌ Timeout: '{target_agent_name}' did not respond within 120 seconds."
        )
    except Exception as exc:
        return f"❌ Error communicating with '{target_agent_name}': {exc}"
    finally:
        _get_ping_stack().discard(interaction_key)
