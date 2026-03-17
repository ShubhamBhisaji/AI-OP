"""
hello_agent.py — The absolute minimum working example.

What this shows:
  1. Boot the system (one line)
  2. Create an agent from a built-in preset (one line)
  3. Give it a task and get a result (one line)

Run:
  cd AetheerAI
  python examples/hello_agent.py

  # Use a specific provider:
  python examples/hello_agent.py --provider claude
  python examples/hello_agent.py --provider ollama --model llama3
"""
from __future__ import annotations

import argparse
import os
import sys

# Make AetheerAI importable when running from the examples/ subdirectory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.env_loader import load_env
load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core.aetheerai_kernel import AetheerAiKernel


def main() -> None:
    parser = argparse.ArgumentParser(description="AetheerAI — hello_agent example")
    parser.add_argument("--provider", default="github",  help="AI provider (github/openai/claude/gemini/ollama)")
    parser.add_argument("--model",    default="gpt-4.1", help="Model name")
    args = parser.parse_args()

    # ── 1. Boot the system ────────────────────────────────────────────
    print(f"\nBooting AetheerAI ({args.provider} / {args.model})...")
    kernel = AetheerAiKernel(ai_provider=args.provider, model=args.model)

    # ── 2. Create an agent from a built-in preset ─────────────────────
    #
    # Available presets:
    #   research_agent   — web research, fact-checking, reports
    #   coding_agent     — build, review, refactor code
    #   marketing_agent  — copywriting, SEO, campaigns
    #   automation_agent — scripts, workflows, repeatable tasks
    #   ceo_agent        — decomposes goals, delegates to sub-agents
    #
    kernel.create_agent(name="my_researcher", role="research_agent")
    print("Agent 'my_researcher' created.\n")

    # ── 3. Give it a task and print the result ────────────────────────
    task = "Explain the top 3 advantages of multi-agent AI systems in 3 bullet points."
    print(f"Task: {task}\n")
    print("─" * 60)

    result = kernel.run_agent("my_researcher", task)
    print(result)
    print("─" * 60)

    # ── What to try next ─────────────────────────────────────────────
    print("\nNext steps:")
    print("  Pipeline (A→B→C): see examples/build_website.py")
    print("  Collaboration:    see examples/collaborate_team.py")
    print("  All patterns:     read FLOW.md\n")


if __name__ == "__main__":
    main()
