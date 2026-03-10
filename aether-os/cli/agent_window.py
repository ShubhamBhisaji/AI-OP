"""
agent_window.py — Dedicated single-agent REPL window.

Launched automatically by `open_agent <name>` from the main Aether CLI.
Opens in its own CMD window and provides an interactive loop for one agent.

Usage (internal):
    python cli/agent_window.py <agent_name> [--provider github] [--model claude-sonnet-4-6]
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
import threading
import time

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

from core.aether_kernel import AetherKernel


# ── Spinner ────────────────────────────────────────────────────────────────

class Spinner:
    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _FRAMES_ASCII = ["-", "\\", "|", "/"]

    def __init__(self, message: str = "Thinking"):
        self.message = message
        self._stop_event = threading.Event()
        self._thread = None
        try:
            sys.stdout.write("⠋\r")
            sys.stdout.flush()
            self._frames = self._FRAMES
        except UnicodeEncodeError:
            self._frames = self._FRAMES_ASCII

    def _spin(self):
        for frame in itertools.cycle(self._frames):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r  {frame}  {self.message}...  ")
            sys.stdout.flush()
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * (len(self.message) + 12) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop_event.set()
        if self._thread:
            self._thread.join()


# ── Agent Window REPL ──────────────────────────────────────────────────────

def _check_scope(kernel, agent, task: str) -> tuple[bool, str]:
    """
    Ask the AI if the task is within the agent's role scope.
    Returns (in_scope: bool, reason: str).
    """
    prompt = (
        f"You are a scope validator. Answer with only YES or NO (one word).\n"
        f"Agent role : {agent.role}\n"
        f"Agent skills: {', '.join(agent.profile.get('skills', []))}\n"
        f"Task       : {task}\n\n"
        f"Is this task directly related to the agent's role and skills?"
    )
    try:
        answer = kernel.ai_adapter.chat([{"role": "user", "content": prompt}]).strip().upper()
        return answer.startswith("YES"), answer
    except Exception:
        return True, "YES"  # fail open if scope check errors


def _banner(agent_name: str, role: str, provider: str, model: str, skills: list) -> str:
    sep = "═" * 52
    skill_str = ", ".join(skills) if skills else "none"
    return f"""
{sep}
  AETHER AGENT — {agent_name.upper()}
  Role     : {role}
  AI       : {provider} / {model}
  Skills   : {skill_str}
  Commands : task  |  upgrade  |  ai_upgrade_skill  |  add_skill  |  info  |  exit
{sep}
"""


def run_agent_window(agent_name: str, provider: str, model: str | None) -> None:
    # Set the CMD window title
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(f"Aether Agent — {agent_name}")
    except Exception:
        pass

    print(f"\n  Loading agent '{agent_name}'...")
    kernel = AetherKernel(ai_provider=provider, model=model)
    agent = kernel.registry.get(agent_name)

    if agent is None:
        print(f"\n  [Error] Agent '{agent_name}' not found in registry.")
        print("  Make sure you created it first with: create_agent " + agent_name)
        input("\n  Press Enter to close...")
        return

    print(_banner(agent_name, agent.role, kernel.ai_adapter.provider, kernel.ai_adapter.model, agent.profile.get("skills", [])))

    history: list[dict] = []

    while True:
        try:
            raw = input(f"  [{agent_name}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting agent window. Goodbye.")
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("exit", "quit"):
            print("  Closing agent window.")
            break

        elif cmd == "info":
            p = agent.profile
            perf = p["performance"]
            print(f"\n  Agent   : {p['name']}")
            print(f"  Role    : {p['role']}")
            print(f"  Version : {p['version']}")
            print(f"  Skills  : {', '.join(p['skills']) or 'none'}")
            print(f"  Tools   : {', '.join(p['tools']) or 'none'}")
            print(f"  Tasks   : {perf['tasks_completed']} done / {perf['tasks_failed']} failed")
            print(f"  Success : {perf['success_rate'] * 100:.1f}%\n")

        elif cmd == "upgrade":
            print(f"\n  Researching best skills for a {agent.role}...")
            with Spinner("AI researching"):
                research = kernel.skill_engine.ai_upgrade(agent_name)

            suggested = research["suggested"]
            reason = research.get("research", "")

            print(f"\n  ─── AI Skill Suggestions ───────────────────────")
            if reason and not reason.startswith("("):
                words = reason.split()
                line, lines = "", []
                for w in words:
                    if len(line) + len(w) + 1 > 56:
                        lines.append(line); line = w
                    else:
                        line = (line + " " + w).strip()
                if line: lines.append(line)
                for l in lines:
                    print(f"  {l}")
                print()

            if suggested:
                print("  Suggested skills:")
                for i, s in enumerate(suggested, 1):
                    print(f"    {i:>2}. {s}")
            else:
                print("  (No new suggestions — agent already has top skills)")

            print(f"  ────────────────────────────────────────────")
            print("  Enter skill names to add (comma-separated),")
            print("  pick numbers from the list, or press Enter to skip:")
            raw_input = input("  > ").strip()

            if not raw_input:
                print("  No skills added.\n")
                continue

            # Parse: numbers refer to suggested list, anything else is a custom name
            chosen = []
            for token in raw_input.split(","):
                token = token.strip()
                if token.isdigit():
                    idx = int(token) - 1
                    if 0 <= idx < len(suggested):
                        chosen.append(suggested[idx])
                    else:
                        print(f"  ⚠  No suggestion #{token} in the list.")
                elif token:
                    chosen.append(token)

            if chosen:
                applied = kernel.skill_engine.apply_skills(agent_name, chosen)
                print(f"\n  ✓ Added {len(applied['skills_added'])} skill(s):")
                for s in applied["skills_added"]:
                    print(f"    + {s}")
                if set(chosen) - set(applied["skills_added"]):
                    already = set(chosen) - set(applied["skills_added"])
                    print(f"  (already had: {', '.join(already)})")
                print(f"  Version → {applied['version']}")
            else:
                print("  No valid skills entered.")
            print()

        elif cmd == "ai_upgrade_skill":
            print(f"\n  Asking AI to research and apply best skills for a {agent.role}...")
            with Spinner("AI researching"):
                research = kernel.skill_engine.ai_upgrade(agent_name)

            suggested = research["suggested"]
            reason = research.get("research", "")

            print(f"\n  ─── AI Auto-Upgrade ────────────────────────────")
            if reason and not reason.startswith("("):
                words = reason.split()
                line, lines = "", []
                for w in words:
                    if len(line) + len(w) + 1 > 56:
                        lines.append(line); line = w
                    else:
                        line = (line + " " + w).strip()
                if line: lines.append(line)
                for l in lines:
                    print(f"  {l}")
                print()

            if not suggested:
                print("  (No new suggestions — agent already has top skills)")
                print()
                continue

            applied = kernel.skill_engine.apply_skills(agent_name, suggested)
            print(f"  ✓ Added {len(applied['skills_added'])} skill(s) automatically:")
            for s in applied["skills_added"]:
                print(f"    + {s}")
            print(f"  Version → {applied['version']}")
            print(f"  ────────────────────────────────────────────────")
            print()

        elif cmd == "add_skill":
            if not arg:
                print("  Usage: add_skill <skill_name>")
                continue
            skill = arg.strip().lower().replace(" ", "_")
            if skill in agent.profile.get("skills", []):
                print(f"  Agent already has skill '{skill}'.")
            else:
                agent.add_skill(skill)
                agent.bump_version()
                kernel.registry._save()
                print(f"  ✓ Skill '{skill}' added. Current skills:")
                for i, s in enumerate(agent.profile["skills"], 1):
                    print(f"    {i:>2}. {s}")
            print()

        elif cmd == "remove_skill":
            if not arg:
                print("  Usage: remove_skill <skill_name>")
                continue
            skill = arg.strip().lower().replace(" ", "_")
            skills = agent.profile.get("skills", [])
            if skill not in skills:
                print(f"  Skill '{skill}' not found.")
            else:
                skills.remove(skill)
                agent.profile["skills"] = skills
                agent.bump_version()
                kernel.registry._save()
                print(f"  ✓ Skill '{skill}' removed.")
            print()

        elif cmd == "task":
            if not arg:
                print("  Usage: task <description of what you want done>")
                continue
            with Spinner("Checking scope"):
                in_scope, _ = _check_scope(kernel, agent, arg)
            if not in_scope:
                print(f"\n  ⚠  That's beyond my capabilities as a {agent.role}.")
                print(f"  I only handle tasks related to: {', '.join(agent.profile.get('skills', [agent.role]))}\n")
                continue
            history.append({"role": "user", "content": arg})
            with Spinner(f"{agent_name} working"):
                response = kernel.workflow_engine.execute(agent=agent, task=arg)
            if str(response).startswith("BEYOND_SCOPE:"):
                reason = str(response)[len("BEYOND_SCOPE:"):].strip()
                print(f"\n  ⚠  That's beyond my capabilities as a {agent.role}: {reason}\n")
            else:
                history.append({"role": "assistant", "content": str(response)})
                print(f"\n  {agent_name}: {response}\n")

        elif cmd == "help":
            print("""
  task <text>        — Give the agent a task to perform
  info               — Show agent profile and stats
  upgrade            — AI researches skills; you choose which to add
  ai_upgrade_skill   — AI researches and applies all suggested skills
  add_skill <name>   — Add a custom skill to this agent
  remove_skill <name>— Remove a skill from this agent
  exit / quit        — Close this window
""")
        else:
            # Treat anything else as a task for convenience
            with Spinner("Checking scope"):
                in_scope, _ = _check_scope(kernel, agent, raw)
            if not in_scope:
                print(f"\n  ⚠  That's beyond my capabilities as a {agent.role}.")
                print(f"  I only handle tasks related to: {', '.join(agent.profile.get('skills', [agent.role]))}\n")
                continue
            history.append({"role": "user", "content": raw})
            with Spinner(f"{agent_name} working"):
                response = kernel.workflow_engine.execute(agent=agent, task=raw)
            if str(response).startswith("BEYOND_SCOPE:"):
                reason = str(response)[len("BEYOND_SCOPE:"):].strip()
                print(f"\n  ⚠  That's beyond my capabilities as a {agent.role}: {reason}\n")
            else:
                history.append({"role": "assistant", "content": str(response)})
                print(f"\n  {agent_name}: {response}\n")

    input("\n  Press Enter to close this window...")


def main():
    parser = argparse.ArgumentParser(prog="agent_window")
    parser.add_argument("agent_name", help="Name of the agent to open")
    parser.add_argument("--provider", default="github")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    # Always cd to project root so registry/memory paths resolve correctly
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)

    try:
        run_agent_window(args.agent_name, args.provider, args.model)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        input("\n  Press Enter to close...")
    except Exception as exc:
        import traceback
        print("\n" + "=" * 60)
        print("  AETHER AGENT — ERROR")
        print("=" * 60)
        print(f"\n  Agent  : {args.agent_name}")
        print(f"  Error  : {exc}\n")
        traceback.print_exc()
        print()
        input("  Press Enter to close this window...")


if __name__ == "__main__":
    main()
