"""
AETHER OS — Example: "Build a Simple Website" Workflow
=======================================================
Demonstrates the full AETHER pipeline:

  User submits a high-level goal
      ↓
  CEO Agent decomposes it into tasks
      ↓
  Specialist agents (Developer, Researcher, Marketer) execute in sequence
      ↓
  CEO Agent synthesises the final deliverable

How to run
----------
  # Ensure your .env has a valid AI key, then from AetheerAI/:
  python examples/build_website.py

  # Override provider:
  AI_PROVIDER=github AI_MODEL=gpt-4.1 python examples/build_website.py
"""

from __future__ import annotations

import os
import sys

# ── Make AetheerAI importable when running from the examples/ subdirectory ────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.env_loader import load_env
load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core.aetheerai_kernel import AetheerAiKernel
from agents.ceo_agent import CEOAgent, ProjectResult

# ─────────────────────────────────────────────────────────────────────────────

def print_banner():
    print("\n" + "═" * 60)
    print("  AETHER OS — Autonomous Multi-Agent Platform")
    print("  Example: Build a Simple Website")
    print("═" * 60)


def print_result(result: ProjectResult):
    print(f"\n{'─' * 60}")
    print(f"WORKFLOW ID : {result.workflow_id}")
    print(f"STATUS      : {result.status.upper()}")
    print(f"TASKS       : {result.completed_tasks}/{result.total_tasks} completed"
          f"  |  {result.failed_tasks} failed"
          f"  |  replanned={result.replanned}")
    print(f"SPEND       : ${result.spent_usd:.4f}")
    print(f"ELAPSED     : {result.elapsed_seconds:.1f}s")

    print(f"\n{'─' * 60}")
    print("TASK BREAKDOWN:")
    for task in result.tasks:
        icon = "✓" if task.status == "completed" else ("✗" if task.status == "failed" else "○")
        print(f"  {icon} [{task.agent_type.upper():12s}] {task.title}  (status={task.status})")
        if task.error:
            print(f"       ↳ ERROR: {task.error[:120]}")

    print(f"\n{'─' * 60}")
    print("FINAL DELIVERABLE:\n")
    print(result.final_summary)
    print("═" * 60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    print_banner()

    # ── Boot the kernel ──────────────────────────────────────────────────────
    provider = os.getenv("AI_PROVIDER", "openai")
    model    = os.getenv("AI_MODEL", "gpt-4o")
    print(f"\nBooting AETHER OS (provider={provider} model={model})...\n")

    kernel = AetheerAiKernel(ai_provider=provider, model=model)

    ceo = CEOAgent(
        kernel,
        max_tasks=20,
        max_cost_usd=5.0,
        max_runtime_seconds=300,
        max_retries=2,
    )

    # ── Define the project goal ─────────────────────────────────────────────
    goal = """
    Build a simple but professional landing page website for a SaaS product
    called "TaskFlow" — a project management tool for remote teams.

    Requirements:
    1. Research: Look up best practices for SaaS landing pages and identify
       the top 3 conversion-focused design patterns.

    2. Development: Write a complete single-file HTML/CSS/JS landing page with:
       - Hero section (headline + sub-headline + CTA button)
       - Features section (3 key features with icons)
       - Pricing section (3 tiers: Free, Pro $29/mo, Enterprise)
       - Footer with links
       Make it mobile-responsive using pure CSS (no frameworks).

    3. Marketing: Write compelling copy for the hero section and feature
       descriptions. Include an SEO meta-description for the page.

    4. Operations: Save the final HTML file to workspace/taskflow_landing.html
       and write a brief deployment instructions file to
       workspace/taskflow_deploy.md.
    """.strip()

    print(f"GOAL:\n{goal}\n")
    print("─" * 60)
    print("CEO Agent is planning tasks...\n")

    # ── Run the project ─────────────────────────────────────────────────────
    result = ceo.run(goal, context={"project": "TaskFlow", "audience": "remote teams"})

    # ── Print results ───────────────────────────────────────────────────────
    print_result(result)

    # ── Persist summary ─────────────────────────────────────────────────────
    summary_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "workspace",
        "build_website_summary.txt",
    )
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"Goal:\n{goal}\n\n")
        f.write(f"Status: {result.status}\n")
        f.write(f"Tasks: {result.completed_tasks}/{result.total_tasks}\n\n")
        f.write("Final Deliverable:\n")
        f.write(result.final_summary)
    print(f"Summary saved to: {summary_path}\n")


if __name__ == "__main__":
    main()
