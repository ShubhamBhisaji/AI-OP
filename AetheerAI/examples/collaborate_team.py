"""Example: run a real multi-agent collaboration session."""

from __future__ import annotations

import json
import os
import sys

# Allow running as: python examples/collaborate_team.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.aetheerai_kernel import AetheerAiKernel


def ensure_demo_agents(kernel: AetheerAiKernel) -> list[str]:
    specs = [
        ("collab_dev", "coding_agent"),
        ("collab_research", "research_agent"),
        ("collab_marketing", "marketing_agent"),
    ]

    names: list[str] = []
    for name, preset in specs:
        if kernel.registry.get(name) is None:
            agent = kernel.factory.create(name=name, role=preset)
            agent.attach_runtime(
                ai_adapter=kernel.ai_adapter,
                workflow_engine=kernel.workflow_engine,
                tool_manager=kernel.tool_manager,
            )
            agent.attach_memory(kernel.memory)
        names.append(name)
    return names


def main() -> None:
    kernel = AetheerAiKernel()
    team = ensure_demo_agents(kernel)

    session = kernel.collaborate(
        goal="Plan and draft a simple product landing page with technical, research, and copy perspectives.",
        agent_names=team,
        rounds=2,
    )

    print(f"Session: {session['session_id']}")
    print(f"Status:  {session['status']}")
    print(f"Turns:   {len(session.get('turns', []))}")
    print("\nFinal synthesis:\n")
    print(session.get("final_synthesis", ""))
    print("\nCompact transcript:")
    for turn in session.get("turns", [])[:6]:
        print(
            f"- round {turn['round']} | {turn['agent']}: "
            f"{str(turn.get('contribution', ''))[:120]}"
        )

    print("\nJSON preview:")
    print(json.dumps({k: session[k] for k in ["session_id", "goal", "status", "team"]}, indent=2))


if __name__ == "__main__":
    main()
