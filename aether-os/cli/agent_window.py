"""
agent_window.py — Dedicated single-agent REPL window.

Launched automatically by `open_agent <name>` from the main Aether CLI.
Opens in its own CMD window and provides an interactive loop for one agent.

Usage (internal):
    python cli/agent_window.py <agent_name> [--provider github] [--model claude-sonnet-4.6]
"""

from __future__ import annotations

import argparse
import itertools
import os
import re
import sys
import threading
import time
from pathlib import Path

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Auto-load .env file — stdlib only, no packages needed
from core.env_loader import load_env as _load_env
_load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from core.aether_kernel import AetherKernel


# ── File block parser ─────────────────────────────────────────────────────

_FILE_BLOCK = re.compile(
    r"={3,}\s*FILE\s*:\s*(.+?)\s*={3,}\r?\n(.*?)\r?\n={3,}\s*END\s*FILE\s*={3,}",
    re.DOTALL | re.IGNORECASE,
)


def _parse_and_write_files(response: str, base_dir: Path) -> list[str]:
    """Extract === FILE: path === ... === END FILE === blocks and write them."""
    written = []
    for match in _FILE_BLOCK.finditer(response):
        rel = match.group(1).strip().replace("\\", "/").lstrip("/")
        content = match.group(2)
        dest = base_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(str(dest))
    return written


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


# ── Report helpers ─────────────────────────────────────────────────────────

_SEP   = "  " + "─" * 50
_SEP_H = "  " + "═" * 50

def _wrap(text: str, width: int = 56, indent: str = "  ") -> str:
    """Word-wrap text to width, returning indented lines joined by \\n."""
    words = text.split()
    line, lines = "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line); line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    return "\n".join(indent + l for l in lines)

def _level_bar(level: str, tasks: int) -> str:
    """Return a visual progress bar for the agent level."""
    thresholds = {"foundation": (0, 5), "intermediate": (5, 20), "advanced": (20, 20)}
    lo, hi = thresholds.get(level, (0, 5))
    if hi == lo:
        filled = 20
    else:
        filled = min(20, int((tasks - lo) / (hi - lo) * 20))
    bar = "█" * filled + "░" * (20 - filled)
    labels = {"foundation": "FOUNDATION", "intermediate": "INTERMEDIATE", "advanced": "ADVANCED"}
    return f"[{bar}] {labels.get(level, level.upper())}"

def _print_upgrade_report(research: dict, agent) -> None:
    """Pretty-print the full skill upgrade report."""
    suggested   = research.get("suggested", [])
    reason      = research.get("research", "")
    level       = research.get("level", "foundation")
    missing_f   = research.get("missing_foundation", [])
    rec_tools   = research.get("recommended_tools", [])
    current     = research.get("current_skills", list(agent.skills))
    tasks_done  = agent.profile["performance"].get("tasks_completed", 0)
    success_pct = agent.profile["performance"].get("success_rate", 1.0) * 100

    print(_SEP_H)
    print(f"  {'SKILL UPGRADE REPORT':^48}")
    print(_SEP_H)
    print(f"  Agent  : {agent.profile['name']}")
    print(f"  Role   : {agent.role}")
    print(f"  Tasks  : {tasks_done} completed  |  {success_pct:.0f}% success rate")
    print(f"  Level  : {_level_bar(level, tasks_done)}")
    print(_SEP)

    # Current skills
    if current:
        print(f"  Current skills ({len(current)}):")
        row = ""
        for s in current:
            entry = f"  {s}"
            if len(row) + len(entry) > 54:
                print(f"   {row}")
                row = s
            else:
                row = (row + "  " + s).strip()
        if row:
            print(f"   {row}")
    else:
        print("  Current skills : (none)")

    # Missing foundation alert
    if missing_f:
        print()
        print(f"  ⚠  Foundation gaps ({len(missing_f)}):")
        for s in missing_f:
            print(f"       • {s}")

    print(_SEP)

    # AI rationale
    if reason and not reason.startswith("("):
        print("  Why these skills:")
        print(_wrap(reason, width=54, indent="    "))
        print()
    elif reason.startswith("("):
        print(f"  Note: {reason}")
        print()

    # Suggestions
    if suggested:
        print(f"  Suggested skills ({len(suggested)}):")
        for i, s in enumerate(suggested, 1):
            if s in missing_f:
                tag = "  ★ fills foundation gap"
            else:
                tag = ""
            print(f"    {i:>2}.  {s}{tag}")
    else:
        print("  ✓ No gaps — agent has all skills for this level.")

    # Tools
    if rec_tools:
        print()
        print(f"  Recommended tools:")
        for t in rec_tools:
            print(f"       + {t}")

    print(_SEP_H)


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
  Commands : task  |  create_file  |  plan  |  build  |  run  |  run_debug  |  upgrade
           | add_api  |  switch_ai  |  ai_upgrade_skill  |  add_skill  |  info  |  exit
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

    _project_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # Output goes to AI-OP\projects\ — projects are not nested under the agent name
    workspace_dir = _project_root.parent / "projects"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    print(f"  📂  Files will be saved to:")
    print(f"     {workspace_dir}\n")

    history: list[dict] = []

    while True:
        try:
            # Drain any pending chained commands before prompting user
            if hasattr(run_agent_window, '_pending') and run_agent_window._pending:
                _next_cmd, _next_arg = run_agent_window._pending.pop(0)
                raw = f"{_next_cmd} {_next_arg}".strip()
                print(f"  [{agent_name}]> {raw}  ← (auto-chained)")
            else:
                raw = input(f"  [{agent_name}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting agent window. Goodbye.")
            break

        if not raw:
            continue

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        # ── Intent resolver: map natural language to canonical commands ──────
        # Also detect task chains like "build X then run it" / "build X and debug"
        def _resolve_intent(raw_input: str):
            """Return list of (cmd, arg) tuples from a natural-language prompt."""
            _r = raw_input.strip()
            _rl = _r.lower()

            # Split on chain keywords first
            import re as _re
            _chain_split = _re.split(
                r'\s+(?:then|and then|after that|next|afterwards|,\s*then)\s+',
                _rl, flags=_re.IGNORECASE
            )
            if len(_chain_split) > 1:
                # Resolve each part independently
                result = []
                for _part in _chain_split:
                    _part = _part.strip()
                    # carry over app name if part says "it" / "that" / "the app"
                    _resolved = _resolve_single(_part, result)
                    if _resolved:
                        result.append(_resolved)
                return result
            return [_resolve_single(_rl, [])]

        def _resolve_single(text: str, prior: list):
            """Map one phrase to (cmd, arg). prior = previously resolved (cmd,arg) pairs."""
            t = text.strip().lower()
            # Extract possible app name (first capital-or-quoted token, or from prior)
            import re as _re2
            _name_m  = _re2.search(r'["\']([^"\']+)["\']', text) or \
                        _re2.search(r'\b([A-Z][\w-]+)\b', text)
            _app_arg = _name_m.group(1) if _name_m else ""
            # If text says 'it'/'that'/'the app'/'same' reuse last app name from prior
            if _re2.search(r'\b(it|that|the app|same)\b', t) and prior:
                for _pc, _pa in reversed(prior):
                    if _pa:
                        _app_arg = _pa.split()[0]
                        break

            # Map patterns → canonical command
            _INTENT_MAP = [
                # exit
                (r'\b(exit|quit|bye|close|stop agent)\b',          'exit',          ''),
                # info
                (r'\b(info|status|show info|agent info|who are you)\b', 'info',     ''),
                # run_debug  — must come BEFORE run
                (r'\b(run.?debug|debug.?run|launch.?debug|debug.?launch|'
                 r'run and debug|debug and run|debug it|fix and run|'
                 r'run with debug|auto.?fix|debug mode)\b',         'run_debug',     _app_arg),
                # run
                (r'\b(run|launch|start|execute|open app|serve)\b',  'run',           _app_arg),
                # plan
                (r'\b(plan|create plan|make plan|prd|design|blueprint)\b', 'plan',  ''),
                # build
                (r'\b(build|generate|create|make|scaffold|code it|'
                 r'develop|implement|construct)\b',                 'build',         _app_arg),
                # upgrade / skill upgrade
                (r'\b(upgrade skills?|ai upgrade|boost skills?|'
                 r'learn skills?|improve skills?)\b',               'ai_upgrade_skill', ''),
                (r'\b(upgrade|level up|upskill)\b',                 'upgrade',       ''),
                # add / remove skill
                (r'\b(add skill)\b',                                'add_skill',     ''),
                (r'\b(remove skill|delete skill)\b',                'remove_skill',  ''),
                # switch ai
                (r'\b(switch ai|change ai|change model|switch model|'
                 r'use (openai|github|gemini|claude|huggingface))\b','switch_ai',    ''),
                # add api
                (r'\b(add api|api key|set key|configure api)\b',    'add_api',       ''),
                # create file
                (r'\b(create file|make file|write file|new file)\b', 'create_file',  ''),
                # help
                (r'\b(help|commands|what can you do|show commands)\b', 'help',       ''),
            ]
            import re as _re3
            for _pat, _mapped_cmd, _mapped_arg in _INTENT_MAP:
                if _re3.search(_pat, t):
                    # For commands that need an arg, allow full original text as arg
                    if _mapped_cmd in ('plan','build','run','run_debug','add_skill',
                                       'remove_skill','switch_ai','add_api','create_file'):
                        if not _mapped_arg:
                            # Strip the command keyword; rest is arg
                            _stripped = _re3.sub(_pat, '', text, count=1).strip(' ,-')
                            _mapped_arg = _stripped if _stripped else ''
                    return (_mapped_cmd, _mapped_arg)
            # Nothing matched → fallback to raw split (original behaviour)
            _parts = text.split(maxsplit=1)
            return (_parts[0].lower(), _parts[1] if len(_parts) > 1 else '')

        # Detect if the raw input already starts with a known command keyword
        # (if so, skip intent resolver to avoid re-mapping valid commands)
        _KNOWN_CMDS = {
            'exit','quit','info','upgrade','ai_upgrade_skill','add_skill','remove_skill',
            'create_file','plan','build','run','run_debug','add_api','switch_ai',
            'task','help'
        }
        if cmd not in _KNOWN_CMDS:
            # Parse as natural language
            _intent_chain = _resolve_intent(raw)
            if len(_intent_chain) > 1 or (_intent_chain and _intent_chain[0][0] != cmd):
                # Re-queue each intent as if the user typed them sequentially
                # We do this by pushing them onto a local pending list
                if not hasattr(run_agent_window, '_pending'):
                    run_agent_window._pending = []
                run_agent_window._pending = list(_intent_chain[1:]) + run_agent_window._pending
                cmd, arg = _intent_chain[0]
            else:
                if _intent_chain:
                    cmd, arg = _intent_chain[0]
        elif raw.count(' ') > 0:
            # Even for known commands, check for chain (e.g. "build X then run it")
            import re as _re_chain
            if _re_chain.search(r'\s+(?:then|and then|after that|next)\s+', raw.lower()):
                _intent_chain = _resolve_intent(raw)
                if len(_intent_chain) > 1:
                    if not hasattr(run_agent_window, '_pending'):
                        run_agent_window._pending = []
                    run_agent_window._pending = list(_intent_chain[1:]) + run_agent_window._pending
                    cmd, arg = _intent_chain[0]

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

            _print_upgrade_report(research, agent)

            suggested = research["suggested"]
            missing_f = research.get("missing_foundation", [])

            print("  Enter numbers and/or skill names to add (comma-separated),")
            print("  or press Enter to skip:")
            raw_input = input("  > ").strip()

            if not raw_input:
                print("  No skills added.\n")
                continue

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
                    tag = "  ★" if s in missing_f else ""
                    print(f"    + {s}{tag}")
                skipped = set(chosen) - set(applied["skills_added"])
                if skipped:
                    print(f"  (already had: {', '.join(sorted(skipped))})")
                print(f"  Version → {applied['version']}  |  Total skills: {len(applied['all_skills'])}")
            else:
                print("  No valid skills entered.")
            print()

        elif cmd == "ai_upgrade_skill":
            print(f"\n  Asking AI to research and apply best skills for a {agent.role}...")
            with Spinner("AI researching"):
                research = kernel.skill_engine.ai_upgrade(agent_name)

            _print_upgrade_report(research, agent)

            suggested = research["suggested"]
            missing_f = research.get("missing_foundation", [])
            rec_tools = research.get("recommended_tools", [])

            if not suggested:
                print()
                continue

            applied = kernel.skill_engine.apply_skills(agent_name, suggested)
            print(f"  \u2713 Auto-applied {len(applied['skills_added'])} skill(s):")
            for s in applied["skills_added"]:
                tag = "  \u2605" if s in missing_f else ""
                print(f"    + {s}{tag}")
            if rec_tools:
                print(f"\n  Recommended tools to add next:")
                for t in rec_tools:
                    print(f"    + {t}")
            print(f"  Version \u2192 {applied['version']}  |  Total skills: {len(applied['all_skills'])}")
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

        elif cmd == "create_file":
            if not arg:
                print("  Usage: create_file <path> [description]")
                continue
            parts2 = arg.split(maxsplit=1)
            file_path = parts2[0]
            description = parts2[1] if len(parts2) > 1 else f"a {file_path} file"
            prompt = (
                f"You are a {agent.role}.\n"
                f"Create the file '{file_path}': {description}\n\n"
                f"Output ONLY the file content wrapped exactly like this:\n"
                f"=== FILE: {file_path} ===\n"
                f"<file content here>\n"
                f"=== END FILE ===\n"
                f"No explanation. No extra text outside the block."
            )
            with Spinner(f"Generating {file_path}"):
                response = kernel.ai_adapter.chat([{"role": "user", "content": prompt}])
            written = _parse_and_write_files(response, workspace_dir)
            if not written:
                # Fallback: write raw response as the file
                dest = workspace_dir / file_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(response, encoding="utf-8")
                written = [str(dest)]
            print(f"\n  ✓ File created:")
            for w in written:
                print(f"    {w}")
            # Open the containing folder in Explorer
            try:
                import subprocess as _sp
                _sp.Popen(["explorer", str(Path(written[0]).parent)])
            except Exception:
                pass
            print()

        # ── plan <type> <name> <description...> ──────────────────────────────
        elif cmd == "plan":
            import json as _json
            parts2 = arg.split(maxsplit=2)
            if len(parts2) < 2:
                print("\n  Usage: plan <type> <name> [description]")
                print("  Types : website, apk, exe, desktop, api, bot, cli, game, other")
                print("  Example: plan website mystore an ecommerce store with cart and payments\n")
                continue

            app_type    = parts2[0].lower()
            app_name    = parts2[1]
            description = parts2[2] if len(parts2) > 2 else f"a {app_type} application"
            app_dir     = workspace_dir / app_name
            plan_path   = app_dir / "PLAN.md"
            app_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n  Creating PRD for '{app_name}' ({app_type})...")

            # ── Step 1: AI generates initial PRD ─────────────────────────────────
            prd_prompt = (
                f"You are a senior product manager and software architect.\n"
                f"Write a detailed PRD (Product Requirements Document) in Markdown for:\n\n"
                f"  Name        : {app_name}\n"
                f"  Type        : {app_type}\n"
                f"  Description : {description}\n\n"
                f"Include these sections:\n"
                f"## Overview\n"
                f"## Type\n"
                f"## Tech Stack\n"
                f"  IMPORTANT: Specify the LATEST stable LTS versions for every framework, library, and tool.\n"
                f"  Do NOT use outdated versions. Choose the most current stable release as of today.\n"
                f"## Core Features\n"
                f"## File Structure\n"
                f"  List every file as: `- \`relative/path.ext\` — one-line purpose`\n"
                f"  Do NOT hardcode a minimum file set. List exactly what THIS specific {app_type} needs.\n"
                f"## Build Notes\n"
                f"  Any special build steps, commands, or configurations needed.\n\n"
                f"After the PRD sections, output on a new line:\n"
                f"QUESTIONS:\n"
                f"1. <most important clarifying question>\n"
                f"2. <second question>\n"
                f"3. <third question>\n"
                f"Only ask questions that would meaningfully change the implementation."
            )

            with Spinner("AI creating PRD"):
                prd_response = kernel.ai_adapter.chat([{"role": "user", "content": prd_prompt}])

            # Split PRD body from questions
            prd_text      = prd_response.strip()
            questions_raw = ""
            if "QUESTIONS:" in prd_response:
                prd_text, questions_raw = prd_response.split("QUESTIONS:", 1)
                prd_text      = prd_text.strip()
                questions_raw = questions_raw.strip()

            # Show the PRD (first 28 lines then truncate)
            prd_lines = prd_text.splitlines()
            print(f"\n  {'─'*54}")
            print(f"  DRAFT PRD — {app_name}  ({app_type})")
            print(f"  {'─'*54}")
            for line in prd_lines[:28]:
                print(f"  {line}")
            if len(prd_lines) > 28:
                print(f"  ... ({len(prd_lines) - 28} more lines in PLAN.md)")
            print(f"  {'─'*54}")

            # ── Step 2: Clarifying questions ──────────────────────────────────────
            answers: dict[str, str] = {}
            if questions_raw:
                questions: list[str] = []
                for l in questions_raw.splitlines():
                    m = re.match(r'^\d+[.)]\s+(.+)', l.strip())
                    if m:
                        questions.append(m.group(1).strip())

                if questions:
                    print(f"\n  AI has {len(questions)} clarifying question(s):")
                    for i, q in enumerate(questions, 1):
                        print(f"\n  Q{i}: {q}")
                        ans = input(f"  A{i}: ").strip()
                        answers[q] = ans if ans else "(no preference)"

            # ── Step 3: Refine PRD with answers ──────────────────────────────────
            if answers:
                qa_block = "\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items())
                refine_prompt = (
                    f"You previously wrote this PRD:\n\n{prd_text}\n\n"
                    f"The user answered your questions:\n{qa_block}\n\n"
                    f"Rewrite the complete PRD in Markdown incorporating these answers.\n"
                    f"Keep all sections. Update Tech Stack, Features, and File Structure as needed.\n"
                    f"Output ONLY the refined Markdown PRD. No extra commentary."
                )
                print()
                with Spinner("Refining PRD"):
                    prd_text = kernel.ai_adapter.chat([{"role": "user", "content": refine_prompt}])
                prd_text = prd_text.strip()

            # ── Step 4: Write PLAN.md ─────────────────────────────────────────────
            header = (
                f"# PLAN: {app_name}\n\n"
                f"**Type:** {app_type}  \n"
                f"**Description:** {description}\n"
            )
            clarifications = ""
            if answers:
                clarifications = "\n\n---\n\n## Clarifications\n\n"
                for q, a in answers.items():
                    clarifications += f"**Q:** {q}  \n**A:** {a}\n\n"

            plan_path.write_text(header + "\n" + prd_text + clarifications, encoding="utf-8")

            print(f"\n  ✓ PLAN.md saved: {plan_path}")
            print(f"  Review it, then run:  build {app_name}")
            print()

        # ── build <name> ──────────────────────────────────────────────────────────
        elif cmd == "build":
            import json as _json
            if not arg:
                print("  Usage: build <name>")
                continue
            app_name  = arg.strip().split()[0]
            app_dir   = workspace_dir / app_name
            plan_path = app_dir / "PLAN.md"

            if not plan_path.exists():
                # PLAN.md missing — queue plan then build and restart loop
                print(f"\n  No PLAN.md found for '{app_name}'.")
                _app_type = input(f"  What type of app is '{app_name}'? "
                                  f"(website/api/bot/cli/game/other): ").strip() or "website"
                _desc     = input(f"  Describe '{app_name}' briefly: ").strip() or f"a {_app_type} application"
                print(f"  Running: plan {_app_type} {app_name} {_desc}")
                if not hasattr(run_agent_window, '_pending'):
                    run_agent_window._pending = []
                # Plan runs first (creates PLAN.md), then build reads it
                run_agent_window._pending = [
                    ('plan', f"{_app_type} {app_name} {_desc}"),
                    ('build', app_name),
                ] + run_agent_window._pending
                continue

            plan_content = plan_path.read_text(encoding="utf-8")
            print(f"\n  Building '{app_name}' from PLAN.md...")

            # ── Step 1: AI extracts the file list from the plan ───────────────────
            extract_prompt = (
                f"Read this PRD and extract the complete list of files to create:\n\n"
                f"{plan_content}\n\n"
                f"Output ONLY a JSON array — no other text, no fences:\n"
                f'[{{"file": "relative/path.ext", "purpose": "one sentence"}}, ...]\n'
                f"Include every file listed in the ## File Structure section."
            )
            with Spinner("Reading PLAN.md"):
                file_list_raw = kernel.ai_adapter.chat([{"role": "user", "content": extract_prompt}])

            # Parse JSON file list
            try:
                clean = re.sub(r'^```\w*\n?', '', file_list_raw.strip(), flags=re.MULTILINE)
                clean = clean.replace("```", "").strip()
                file_plan = _json.loads(clean)
                if not isinstance(file_plan, list):
                    raise ValueError("not a list")
            except Exception:
                # Fallback 1: scrape `- \`path\` — purpose` lines from the markdown
                file_plan = []
                for line in plan_content.splitlines():
                    m = re.match(r'\s*[-*]\s+`([^`]+)`\s*[\u2014\-]+\s*(.*)', line)
                    if m:
                        file_plan.append({"file": m.group(1), "purpose": m.group(2)})

                # Fallback 2: extract file paths from a code block inside
                # any ## / ### File Structure section (handles code-block format)
                if not file_plan:
                    struct_m = re.search(
                        r'##[#]?\s+File\s+Structure[^\n]*\n(.*?)(?=\n##|\Z)',
                        plan_content, re.DOTALL | re.IGNORECASE,
                    )
                    if struct_m:
                        struct_block = struct_m.group(1)
                        cb = re.search(r'```[^\n]*\n(.*?)```', struct_block, re.DOTALL)
                        scan_text = cb.group(1) if cb else struct_block
                        for raw_line in scan_text.splitlines():
                            candidate = raw_line.strip().strip('`').replace('\\', '/')
                            # Accept only lines that look like real files (have an extension,
                            # no placeholder dots, not a bare directory)
                            if (re.match(r'^[\w./\-]+\.\w{1,12}$', candidate)
                                    and '...' not in candidate):
                                file_plan.append({"file": candidate, "purpose": ""})

                # Fallback 3: plain bullet / backtick lines anywhere in document
                if not file_plan:
                    for line in plan_content.splitlines():
                        m2 = re.match(r'\s*[-*]\s+`([^`]+\.\w{1,12})`', line)
                        if m2:
                            file_plan.append({"file": m2.group(1), "purpose": ""})

            if not file_plan:
                print("  Could not extract a file list from PLAN.md.")
                print("  Make sure ## File Structure has lines like:")
                print("    - `path/file.ext` — purpose")
                continue

            total = len(file_plan)
            print(f"\n  {total} file(s) to generate:")
            print(f"  {'─'*50}")
            for i, e in enumerate(file_plan, 1):
                print(f"  {i:>3}.  {e['file']}")
            print(f"  {'─'*50}")
            confirm = input("\n  Proceed with build? [Y/n]: ").strip().lower()
            if confirm == "n":
                print("  Build cancelled.\n")
                continue
            print()

            all_written: list[str] = []
            explorer_opened = False

            for idx, entry in enumerate(file_plan, 1):
                rel_path = entry.get("file", f"file{idx}").strip().replace("\\", "/").lstrip("/")
                purpose  = entry.get("purpose", "")
                dest     = app_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)

                print(f"  [{idx}/{total}] {rel_path}", end="", flush=True)

                file_prompt = (
                    f"You are a {agent.role} building the '{app_name}' application.\n\n"
                    f"PROJECT PLAN:\n{plan_content}\n\n"
                    f"Generate the file: {rel_path}\n"
                    f"Purpose: {purpose}\n\n"
                    f"Rules:\n"
                    f"  - Output ONLY the raw file content. No explanation.\n"
                    f"  - No markdown code fences. No === FILE === wrappers.\n"
                    f"  - COMPLETE code — no placeholders, no '...' gaps, no TODO comments.\n"
                    f"  - Reference other project files correctly by their relative paths.\n"
                    f"  - LATEST VERSIONS ONLY: Use the most current stable versions of all npm/pip\n"
                    f"    packages and frameworks. Never use outdated or deprecated versions.\n"
                    f"  - If generating package.json, use exact latest stable semver (e.g. \"^14.2.0\")\n"
                    f"    and include all necessary scripts (dev, build, start, lint).\n"
                )
                with Spinner("  writing"):
                    file_content = kernel.ai_adapter.chat([{"role": "user", "content": file_prompt}])

                # Strip any accidental code fences the AI wraps the whole file in
                fc = file_content.strip()
                fence_match = re.match(r'^```[\w]*\n(.*?)\n?```$', fc, re.DOTALL)
                if fence_match:
                    fc = fence_match.group(1)

                dest.write_text(fc, encoding="utf-8")
                all_written.append(str(dest))
                print(f"\r  [{idx}/{total}] ✓ {rel_path}")

                if not explorer_opened:
                    try:
                        import subprocess as _sp
                        _sp.Popen(["explorer", str(app_dir)])
                        explorer_opened = True
                    except Exception:
                        pass

            # ── Post-build: upgrade npm deps to absolute latest stable versions ──
            import subprocess as _sp_bld
            _pkg_js_path = app_dir / "package.json"
            if _pkg_js_path.exists():
                print(f"\n  Upgrading npm dependencies to latest stable versions...")
                _ncu = _sp_bld.run(
                    "npx --yes npm-check-updates -u",
                    cwd=str(app_dir), shell=True,
                    capture_output=True, text=True
                )
                _ncu_out = (_ncu.stdout + _ncu.stderr).strip()
                if _ncu_out:
                    for _ln in _ncu_out.splitlines()[-20:]:
                        print(f"  {_ln}")
                print(f"  Installing latest dependencies (this may take a minute)...")
                _sp_bld.run("npm install --legacy-peer-deps", cwd=str(app_dir), shell=True)
                print(f"  ✓ Dependencies up to date.")

            print(f"\n  ✓ Build complete — {len(all_written)}/{total} file(s) written")
            print(f"  📂  {app_dir}\n")

        # ── run <name> ────────────────────────────────────────────────────────
        elif cmd == "run":
            import subprocess as _sp
            if not arg:
                print("  Usage: run <app_name>")
                continue
            run_name = arg.strip().split()[0]
            run_dir  = workspace_dir / run_name
            if not run_dir.exists():
                print(f"\n  Error: No project '{run_name}' found at {run_dir}")
                print(f"  Build it first with: build {run_name}\n")
                continue

            # ── Auto-detect app type ─────────────────────────────────────────
            pkg_json   = run_dir / "package.json"
            req_txt    = run_dir / "requirements.txt"
            index_html = run_dir / "index.html"
            # Python entry points
            py_entries = ["app.py", "main.py", "server.py", "run.py", "manage.py"]
            py_file    = next((run_dir / f for f in py_entries if (run_dir / f).exists()), None)
            exe_files  = list(run_dir.glob("*.exe"))

            launch_cmd: str | None = None
            url: str | None = None
            mode = "cmd"  # "cmd" = new CMD window, "browser" = open URL directly

            if pkg_json.exists():
                # Read package.json scripts to pick the right run command
                import json as _json2
                try:
                    pkg = _json2.loads(pkg_json.read_text(encoding="utf-8"))
                except Exception:
                    pkg = {}
                scripts = pkg.get("scripts", {})
                deps    = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                # Install deps first if node_modules missing
                node_modules = run_dir / "node_modules"
                install_step = "" if node_modules.exists() else "npm install && "
                # Framework-specific: Next.js and Vite MUST use dev mode —
                # 'next start' / 'vite preview' require a prior build (.next/BUILD_ID)
                if "next" in deps:
                    url     = "http://localhost:3000"
                    npm_cmd = "npm run dev" if "dev" in scripts else "npx next dev"
                elif "vite" in deps:
                    url     = "http://localhost:5173"
                    npm_cmd = "npm run dev" if "dev" in scripts else "npx vite"
                elif "react-scripts" in deps:
                    url     = "http://localhost:3000"
                    npm_cmd = "npm start"
                elif "vue" in deps:
                    url     = "http://localhost:5173"
                    npm_cmd = "npm run dev" if "dev" in scripts else "npx vite"
                else:
                    url = "http://localhost:3000"
                    # Prefer: dev > start > serve > preview
                    script_order  = ["dev", "start", "serve", "preview"]
                    chosen_script = next((s for s in script_order if s in scripts), None)
                    npm_cmd = f"npm run {chosen_script}" if chosen_script else "npm start"
                launch_cmd = f"cd /d \"{run_dir}\" && {install_step}{npm_cmd}"

            elif py_file is not None:
                # Python app — detect framework
                try:
                    src = py_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    src = ""
                if "flask" in src.lower() or (req_txt.exists() and "flask" in req_txt.read_text().lower()):
                    launch_cmd = f'cd /d "{run_dir}" && python "{py_file.name}"'
                    url = "http://localhost:5000"
                elif "fastapi" in src.lower() or (req_txt.exists() and "fastapi" in req_txt.read_text().lower()):
                    launch_cmd = f'cd /d "{run_dir}" && uvicorn {py_file.stem}:app --reload'
                    url = "http://localhost:8000"
                elif "django" in src.lower() or (py_file.name == "manage.py"):
                    launch_cmd = f'cd /d "{run_dir}" && python manage.py runserver'
                    url = "http://localhost:8000"
                else:
                    launch_cmd = f'cd /d "{run_dir}" && python "{py_file.name}"'

            elif index_html.exists():
                # Pure static site — open in default browser
                mode = "browser"
                url = str(index_html)

            elif exe_files:
                launch_cmd = f'cd /d "{run_dir}" && "{exe_files[0].name}"'

            else:
                print(f"\n  Could not detect how to run '{run_name}'.")
                print(f"  Project folder: {run_dir}")
                print("  Supported: Node/Next.js (package.json), Python, static HTML, .exe\n")
                continue

            # ── Launch ──────────────────────────────────────────────────────
            print(f"\n  Launching '{run_name}'...")
            if url and not url.startswith("http"):
                # Static file path — convert to file URI
                file_uri = "file:///" + url.replace("\\", "/")
                print(f"  Opening: {file_uri}")
                try:
                    import webbrowser
                    webbrowser.open(file_uri)
                except Exception as _e:
                    print(f"  Could not open browser: {_e}")
            elif mode == "cmd" and launch_cmd:
                print(f"  Command: {launch_cmd}")
                if url:
                    print(f"  URL    : {url}   (may take a few seconds to start)")
                try:
                    _sp.Popen(
                        f'cmd /k {launch_cmd}',
                        creationflags=_sp.CREATE_NEW_CONSOLE,
                    )
                    if url:
                        import time as _time, webbrowser as _wb
                        _time.sleep(3)
                        _wb.open(url)
                except Exception as _e:
                    print(f"  Launch failed: {_e}")
                    print(f"  Run manually: {launch_cmd}")
            print()

        # ── run_debug <name> ─────────────────────────────────────────────────────
        elif cmd == "run_debug":
            import subprocess as _sp
            if not arg:
                print("  Usage: run_debug <app_name>")
                continue
            run_name = arg.strip().split()[0]
            run_dir  = workspace_dir / run_name
            if not run_dir.exists():
                print(f"\n  Error: No project '{run_name}' found at {run_dir}")
                print(f"  Build it first with: build {run_name}\n")
                continue

            # ── Detect app type ──────────────────────────────────────────────
            _pkg_json  = run_dir / "package.json"
            _req_txt   = run_dir / "requirements.txt"
            _py_entries = ["app.py", "main.py", "server.py", "run.py", "manage.py"]
            _py_file   = next((run_dir / f for f in _py_entries if (run_dir / f).exists()), None)

            _check_cmd:   list | None = None
            _launch_cmd:  str  | None = None
            _url:         str  | None = None
            _app_kind = "unknown"

            if _pkg_json.exists():
                import json as _json
                _pkg_json_ok = True
                try:
                    _pkg = _json.loads(_pkg_json.read_text(encoding="utf-8"))
                except Exception:
                    _pkg = {}
                    _pkg_json_ok = False
                _scripts = _pkg.get("scripts", {})
                _deps    = {**_pkg.get("dependencies", {}), **_pkg.get("devDependencies", {})}
                # Only auto-install if package.json is valid JSON
                if _pkg_json_ok and not (run_dir / "node_modules").exists():
                    print("  Installing dependencies (first run)...")
                    _sp.run("npm install", cwd=str(run_dir), shell=True)
                # Always set a check command: prefer 'npm run build', fallback to 'npm install'
                # so EJSONPARSE and other npm errors are always captured
                if "build" in _scripts:
                    _check_cmd = ["npm", "run", "build"]
                else:
                    _check_cmd = ["npm", "install"]
                if "next" in _deps:
                    _app_kind   = "next.js"
                    _url        = "http://localhost:3000"
                    _launch_cmd = f'cd /d "{run_dir}" && npm run dev'
                elif "vite" in _deps:
                    _app_kind   = "vite"
                    _url        = "http://localhost:5173"
                    _launch_cmd = f'cd /d "{run_dir}" && npm run dev'
                else:
                    _app_kind   = "node"
                    _url        = "http://localhost:3000"
                    _launch_cmd = f'cd /d "{run_dir}" && npm start'

            elif _py_file:
                _app_kind = "python"
                _src = ""
                try:
                    _src = _py_file.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
                if "flask" in _src.lower() or (_req_txt.exists() and "flask" in _req_txt.read_text().lower()):
                    _url        = "http://localhost:5000"
                    _launch_cmd = f'cd /d "{run_dir}" && python "{_py_file.name}"'
                elif "fastapi" in _src.lower():
                    _url        = "http://localhost:8000"
                    _launch_cmd = f'cd /d "{run_dir}" && uvicorn {_py_file.stem}:app --reload'
                elif "django" in _src.lower() or _py_file.name == "manage.py":
                    _url        = "http://localhost:8000"
                    _launch_cmd = f'cd /d "{run_dir}" && python manage.py runserver'
                else:
                    _launch_cmd = f'cd /d "{run_dir}" && python "{_py_file.name}"'
            else:
                print(f"\n  Could not detect app type for '{run_name}'.\n")
                continue

            # ── Debug / fix loop ─────────────────────────────────────────────
            MAX_ITER   = 20
            _iteration = 0
            _total_fixes = 0
            _clean = False

            print(f"\n  {'═'*56}")
            print(f"  run_debug — {run_name}  [{_app_kind}]")
            print(f"  {'═'*56}")
            print(f"  Fixing until 0 errors found (max {MAX_ITER} rounds).\n")

            while _iteration < MAX_ITER:
                _iteration += 1
                print(f"  ── Round {_iteration}/{MAX_ITER} — checking for errors...")

                _error_output = ""

                if _check_cmd:
                    _res = _sp.run(
                        _check_cmd,
                        cwd=str(run_dir),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        shell=True,
                    )
                    _combined = (_res.stdout or "") + "\n" + (_res.stderr or "")
                    if _res.returncode == 0:
                        print(f"  ✓ Build passed — no errors!\n")
                        _clean = True
                        break
                    _error_output = _combined.strip()

                elif _app_kind == "python" and _py_file:
                    _res = _sp.run(
                        f'python -m py_compile "{_py_file}"',
                        cwd=str(run_dir),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        shell=True,
                    )
                    if _res.returncode == 0:
                        print(f"  ✓ No syntax errors!\n")
                        _clean = True
                        break
                    _error_output = (_res.stdout + "\n" + _res.stderr).strip()

                else:
                    print("  ✓ No static check available — launching directly.\n")
                    _clean = True
                    break

                # ── Show errors ──────────────────────────────────────────────
                _err_lines = [l for l in _error_output.splitlines() if l.strip()]
                print(f"\n  ⚠  {len(_err_lines)} error line(s):")
                print(f"  {'─'*54}")
                for _line in _err_lines[:45]:
                    print(f"  {_line}")
                if len(_err_lines) > 45:
                    print(f"  ... ({len(_err_lines) - 45} more lines)")
                print(f"  {'─'*54}\n")

                # ── Parse affected files from error text ─────────────────────
                _affected: list[Path] = []
                _seen_f: set[str] = set()
                for _m in re.finditer(
                    r'(?:[\./ ]|^)([\w\-/\\]+\.(?:ts|tsx|js|jsx|py|css|json|mjs|cjs))(?::|\s|$)',
                    _error_output,
                ):
                    _rel = _m.group(1).replace("\\", "/").lstrip("./")
                    _p = run_dir / _rel
                    if _p.exists() and _p.is_file() and _rel not in _seen_f:
                        _seen_f.add(_rel)
                        _affected.append(_p)

                # Always include package.json when npm errors mention it
                if ("package.json" in _error_output or "EJSONPARSE" in _error_output
                        or "JSONParseError" in _error_output):
                    _pj = run_dir / "package.json"
                    if _pj.exists() and "package.json" not in _seen_f:
                        _seen_f.add("package.json")
                        _affected.insert(0, _pj)  # check it first

                # Fallback: grab source files if none matched
                if not _affected:
                    _src_exts = {".ts", ".tsx", ".js", ".jsx", ".py", ".css"}
                    for _f in run_dir.rglob("*"):
                        if (_f.suffix in _src_exts
                                and "node_modules" not in _f.parts
                                and ".next" not in _f.parts):
                            _affected.append(_f)
                            if len(_affected) >= 8:
                                break

                # ── Build file context for AI ────────────────────────────────
                _files_ctx = ""
                for _cf in _affected[:6]:
                    try:
                        _fc_text = _cf.read_text(encoding="utf-8", errors="replace")
                        _rel_p   = _cf.relative_to(run_dir).as_posix()
                        _files_ctx += f"\n\n--- FILE: {_rel_p} ---\n{_fc_text[:4000]}"
                        if len(_fc_text) > 4000:
                            _files_ctx += "\n... (truncated)"
                    except Exception:
                        pass

                _fix_prompt = (
                    f"You are a senior {_app_kind} developer debugging the '{run_name}' project.\n\n"
                    f"BUILD ERRORS:\n{_error_output[:3000]}\n"
                    f"\nSOURCE FILES:{_files_ctx}\n\n"
                    f"Fix EVERY error shown above. For each file you change output:\n"
                    f"=== FILE: relative/path/to/file.ext ===\n"
                    f"<complete corrected file content>\n"
                    f"=== END FILE ===\n\n"
                    f"Rules: output COMPLETE file contents (no '...' or placeholders). "
                    f"Only output files that need changes. No text outside FILE blocks."
                )

                print(f"  AI analyzing {len(_affected)} file(s)...")
                with Spinner("AI fixing"):
                    _fix_resp = kernel.ai_adapter.chat([{"role": "user", "content": _fix_prompt}])

                _written_d = _parse_and_write_files(_fix_resp, run_dir)
                if _written_d:
                    _total_fixes += len(_written_d)
                    print(f"  ✓ Fixed {len(_written_d)} file(s):")
                    for _w in _written_d:
                        try:
                            _rw = Path(_w).relative_to(run_dir).as_posix()
                        except Exception:
                            _rw = _w
                        print(f"    ✎  {_rw}")
                    print()
                else:
                    print("  AI returned no fixes — stopping debug loop.\n")
                    break

            if not _clean and _iteration >= MAX_ITER:
                print(f"  ⚠  Reached {MAX_ITER} fix round(s). Review remaining errors above.\n")
            elif _clean:
                if _total_fixes:
                    print(f"  ✓ Debug complete — {_total_fixes} fix(es) applied in {_iteration} round(s).\n")

            # ── Launch ───────────────────────────────────────────────────────
            if _launch_cmd:
                print(f"  Launching '{run_name}'...")
                if _url:
                    print(f"  URL: {_url}  (opening in browser in 4s)")
                try:
                    _sp.Popen(
                        f'cmd /k {_launch_cmd}',
                        creationflags=_sp.CREATE_NEW_CONSOLE,
                    )
                    if _url:
                        import time as _time, webbrowser as _wb
                        _time.sleep(4)
                        _wb.open(_url)
                except Exception as _launch_err:
                    print(f"  Launch failed: {_launch_err}")
                    print(f"  Run manually: {_launch_cmd}")
            print()

        elif cmd == "add_api":
            from cli.api_key_manager import run_add_api
            run_add_api(arg.split() if arg else [], ai_adapter=kernel.ai_adapter)

        elif cmd == "switch_ai":
            parts2 = arg.split(maxsplit=1)
            if not parts2:
                print("  Usage: switch_ai <provider> [model]")
            else:
                provider_sw = parts2[0]
                model_sw = parts2[1] if len(parts2) > 1 else None
                kernel.ai_adapter.switch(provider=provider_sw, model=model_sw)
                print(f"  Switched to {kernel.ai_adapter.provider} / {kernel.ai_adapter.model}")

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
                # Auto-write any embedded FILE blocks
                written = _parse_and_write_files(str(response), workspace_dir)
                if written:
                    display = _FILE_BLOCK.sub("", str(response)).strip()
                    if display:
                        print(f"\n  {agent_name}: {display}")
                    print(f"\n  ✓ Created {len(written)} file(s):")
                    for w in written:
                        print(f"    → {w}")
                    # Open containing folder in Explorer
                    try:
                        import subprocess as _sp
                        _sp.Popen(["explorer", str(Path(written[0]).parent)])
                    except Exception:
                        pass
                    print()
                else:
                    print(f"\n  {agent_name}: {response}\n")

        elif cmd == "help":
            print(f"""
  add_api [provider] [key]         — Add or update an AI provider API key
       Providers: openai, claude, gemini, huggingface, github
       Example: add_api gemini       (interactive)
                add_api list         (show status)
  switch_ai <provider> [model]     — Switch AI provider live

  task <text>                      — Give the agent a task to perform
  create_file <path> [desc]        — Generate and write a single file

  plan <type> <name> [description] — AI writes a PRD, asks clarifying
                                     questions, saves PLAN.md
       Types: website, apk, exe, desktop, api, bot, cli, game, other
       Example: plan website mystore an ecom store

  build <name>                     — Read PLAN.md and generate every
                                     file listed in it, one by one

  run <name>                       — Auto-detect and launch the built
                                     app (Next.js, React, Python,
                                     Flask, FastAPI, Django, HTML, .exe)
                                     Opens in a new terminal window

  run_debug <name>                 — Run + AI live debug: runs build,
                                     captures ALL errors, AI auto-fixes
                                     files & retries up to 5 rounds,
                                     then launches the app

  info                             — Show agent profile and stats
  upgrade                          — AI researches skills; you choose
  ai_upgrade_skill                 — AI researches and auto-applies skills
  add_skill <name>                 — Add a custom skill
  remove_skill <name>              — Remove a skill
  exit / quit                      — Close this window

  Files are written to:  AI-OP\projects\{agent_name}\
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
