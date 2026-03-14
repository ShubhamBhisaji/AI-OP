"""policy_engine.py - centralized authorization decisions for tool actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    """
    Minimal policy engine for tool execution authorization.

    Policy model:
    - Deny by default for unknown/unregistered tools.
    - Allow registered tools only when caller level satisfies required level.
    - Optional explicit allow/deny overrides by tool name.
    """

    def __init__(self) -> None:
        self._deny_tools: set[str] = set()
        self._allow_tools: set[str] = set()

    def deny_tool(self, tool_name: str) -> None:
        self._deny_tools.add(tool_name)

    def allow_tool(self, tool_name: str) -> None:
        self._allow_tools.add(tool_name)

    def evaluate_tool_call(
        self,
        *,
        tool_name: str,
        tool_registered: bool,
        agent_level: int,
        required_level: int,
    ) -> PolicyDecision:
        if tool_name in self._deny_tools:
            return PolicyDecision(False, f"Tool '{tool_name}' is explicitly denied by policy.")

        if tool_name in self._allow_tools:
            return PolicyDecision(True, f"Tool '{tool_name}' explicitly allowed by policy.")

        if not tool_registered:
            return PolicyDecision(False, f"Tool '{tool_name}' is not registered (deny-by-default).")

        if agent_level < required_level:
            return PolicyDecision(
                False,
                (
                    f"Agent level {agent_level} does not satisfy required level "
                    f"{required_level} for '{tool_name}'."
                ),
            )

        return PolicyDecision(True, "Allowed by default policy for registered tool and level.")
