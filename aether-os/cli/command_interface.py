"""
CommandInterface — CLI for AetherAi-A Master AI.
Provides an interactive REPL and supports all core Aether commands.
"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
import threading
import time
import logging

logger = logging.getLogger(__name__)


class Spinner:
    """Displays an animated spinner in the terminal while a task runs."""

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    # Fallback ASCII frames for terminals that don't support Unicode
    _FRAMES_ASCII = ["-", "\\", "|", "/"]

    def __init__(self, message: str = "Thinking"):
        self.message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Detect if the terminal supports Unicode
        try:
            sys.stdout.write("\u280b")
            sys.stdout.write("\r")
            sys.stdout.flush()
            self._frames = self._FRAMES
        except (UnicodeEncodeError, Exception):
            self._frames = self._FRAMES_ASCII

    def _spin(self) -> None:
        for frame in itertools.cycle(self._frames):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r  {frame}  {self.message}...  ")
            sys.stdout.flush()
            time.sleep(0.1)
        # Clear the spinner line
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


BANNER = r"""
    _       _   _                     _    ___ 
   / \  ___| |_| |__   ___ _ __      / \  |_ _|
  / _ \/ _ \ __| '_ \ / _ \ '__|    / _ \  | | 
 / ___ \  __/ |_| | | |  __/ |     / ___ \ | | 
/_/   \_\___|\__|_| |_|\___|_|    /_/   \_\___|

  AetherAi-A Master AI  v1.0.0
  Type 'help' for commands.
"""

HELP_TEXT = """
Commands:
  create_agent <name> [role]       Build a smart agent — Aether researches its core
                                   function, gathers required skills, and writes a
                                   detailed system prompt automatically.
  list_agents                      List all created agents
  delete_agent <name>              Delete an agent permanently
  delete_all_agents                Delete ALL agents permanently
  open_agent <name>                Open an agent in its own dedicated CMD window
  export_agent <name>              Export agent as a standalone runnable folder
                                   (internal AI System sub-agents cannot be exported)
  export_system <name> <a1,a2,...> Export multiple agents as one AI System bundle
  upgrade_agent <name>             Upgrade an agent's skills
  run_agent <name> <task...>       Run an agent on a task (inline)
  agent_info <name>                Show profile and performance of an agent
  build_application <app_name>     Build an application using a team of agents
  run <agent> <app>                Launch a built app (Next.js/React/Python/HTML/.exe)
                                   Opens a new terminal window; auto-detects type
  chat <message...>                Chat directly with the AI
  switch_ai <provider> [model]     Switch AI provider (openai/claude/gemini/ollama/huggingface)
  add_api [provider] [key]         Add or update an AI provider API key
                                   Providers: openai, claude, gemini, huggingface, github
  add_api list                     Show current API key status for all providers
  test_ai                          Test if the current AI provider is working
  memory_list                      List all memory keys
  memory_get <key>                 Retrieve a memory value
  memory_clear                     Clear all memory

  ─── Multi-Agent System ─────────────────────────────────────────────
  create_team <name> <a1,a2,...>   Create a named team of agents
  list_teams                       List all teams
  team_info <name>                 Show team members and their status
  delete_team <name>               Delete a team (agents are kept)
  add_to_team <team> <agent>       Add an agent to a team
  remove_from_team <team> <agent>  Remove an agent from a team

  run_pipeline <team|a1,a2> <task> Sequential chain: each output feeds the next agent
  broadcast <task...>              Send task to ALL agents independently
  vote <question...>               All agents answer; AI synthesizes consensus
  best_of <task...>                All agents attempt; AI picks the best response
  agent_debate <a1> <a2> <topic>   Two agents argue a topic for several rounds
  orchestrate <task...>            AI auto-selects agents + mode for the task
  system_status                    Full dashboard: agents, teams, tools, AI info
  ────────────────────────────────────────────────────────────────────

  ─── AI System (Smart Build) ────────────────────────────────────────
  create_ai_system                 Intelligently design + build a complete AI System:
                                   1. Researches the system's core function
                                   2. Designs a specialised agent roster
                                   3. For EACH sub-agent: researches its function,
                                      gathers skill requirements, writes instructions
                                   4. Compiles sub-agents into a working team
                                   Sub-agents are internal — they cannot be exported.
  ai_system_task <system> <task>   Send a task to an AI System — auto-routes to the
                                   right agent(s) and returns combined output.
  list_ai_systems                  List all saved AI Systems
  ai_system_info <system>          Show full details of an AI System
  ────────────────────────────────────────────────────────────────────

  ─── Ollama (Local AI) ──────────────────────────────────────────────
  ollama_install                   Install Ollama on this machine (Windows)
  ollama_update                    Update Ollama to the latest version
  ollama_pull [model]              Download / update an Ollama model
                                   (shows recommended picker if no model given)
  ollama_models                    List all locally installed Ollama models
  ollama_remove <model>            Delete a locally installed Ollama model
  ────────────────────────────────────────────────────────────────────

  help                             Show this help message
  exit / quit                      Exit AetherAi-A Master AI
"""


def _indent(text: str, spaces: int = 2) -> str:
    """Indent every line of text by `spaces` spaces."""
    pad = " " * spaces
    return "\n".join(pad + line for line in (text or "").splitlines())


class CommandInterface:
    def __init__(self, kernel):
        self.kernel = kernel
        self._running = False

    # ------------------------------------------------------------------
    # Main REPL
    # ------------------------------------------------------------------

    def run(self) -> None:
        print(BANNER)
        self._running = True
        while self._running:
            try:
                raw = input("aether> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting AetherAi-A Master AI. Goodbye.")
                break
            if not raw:
                continue
            self._dispatch(raw)

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Natural language intent resolver
    # ------------------------------------------------------------------

    _NL_MAP = [
        # create ai system
        (r'\b(create ai system|build ai system|make ai system|new ai system|'
         r'design ai system|setup ai system|generate ai system|'
         r'create system|build system|make system|new system)\b',
         'create_ai_system', ''),
        # ai system task
        (r'\b(ask system|use system|run system task|system task|'
         r'ai system task|send to system|task for system)\b',
         'ai_system_task', ''),
        # list ai systems
        (r'\b(list (ai )?systems?|show (ai )?systems?|all (ai )?systems?)\b',
         'list_ai_systems', ''),
        # ai system info
        (r'\b(system info|ai system info|about system|inspect system)\b',
         'ai_system_info', ''),
        # create agent
        (r'\b(create agent|make agent|new agent|add agent|build agent)\b',
         'create_agent', ''),
        # list agents
        (r'\b(list agents?|show agents?|all agents?|what agents?|agents list)\b',
         'list_agents', ''),
        # delete agent
        (r'\b(delete agent|remove agent|destroy agent)\b',
         'delete_agent', ''),
        # delete all agents
        (r'\b(delete all agents?|remove all agents?|wipe agents?|clear agents?)\b',
         'delete_all_agents', ''),
        # open agent
        (r'\b(open agent|launch agent|start agent|run agent window)\b',
         'open_agent', ''),
        # export system
        (r'\b(export system|export ai system|package system|bundle system|bundle agents?)\b',
         'export_system', ''),
        # export agent
        (r'\b(export agent|package agent|bundle agent)\b',
         'export_agent', ''),
        # upgrade agent
        (r'\b(upgrade agent|improve agent|level up agent|boost agent)\b',
         'upgrade_agent', ''),
        # agent info
        (r'\b(agent info|agent status|show agent|inspect agent|about agent)\b',
         'agent_info', ''),
        # build application
        (r'\b(build app(lication)?|create app(lication)?|make app(lication)?'
         r'|generate app(lication)?|develop app(lication)?|scaffold app(lication)?)\b',
         'build_application', ''),
        # run application
        (r'\b(run app|launch app|start app|serve app|run it|launch it|start it)\b',
         'run', ''),
        # system status
        (r'\b(system status|dashboard|overview|status|show status)\b',
         'system_status', ''),
        # switch ai
        (r'\b(switch ai|change ai|change model|switch model|'
         r'use openai|use github|use gemini|use claude|use ollama)\b',
         'switch_ai', ''),
        # add api
        (r'\b(add api|api key|set key|configure api|update key)\b',
         'add_api', ''),
        # run pipeline
        (r'\b(pipeline|run pipeline|chain agents?)\b',
         'run_pipeline', ''),
        # broadcast
        (r'\b(broadcast|send to all|all agents? do)\b',
         'broadcast', ''),
        # vote
        (r'\b(vote|consensus|poll agents?)\b',
         'vote', ''),
        # best of
        (r'\b(best of|best response|pick best)\b',
         'best_of', ''),
        # debate
        (r'\b(debate|argue|discussion)\b',
         'agent_debate', ''),
        # orchestrate
        (r'\b(orchestrate|auto.?select|smart run)\b',
         'orchestrate', ''),
        # ollama management
        (r'\b(install ollama|setup ollama|get ollama|download ollama)\b',
         'ollama_install', ''),
        (r'\b(update ollama|upgrade ollama|ollama update|ollama upgrade)\b',
         'ollama_update', ''),
        (r'\b(pull model|download model|ollama pull|install model|get model|update model)\b',
         'ollama_pull', ''),
        (r'\b(ollama models|list models|show models|installed models|local models)\b',
         'ollama_models', ''),
        (r'\b(remove model|delete model|ollama remove|ollama rm|uninstall model)\b',
         'ollama_remove', ''),
        # test ai
        (r'\b(test ai|check ai|ping ai|ai working|is ai working|ai status|'
         r'test connection|check connection|test provider|verify ai)\b',
         'test_ai', ''),
        # chat
        (r'\b(chat|talk|ask|tell me|what is|who is|explain|describe)\b',
         'chat', ''),
        # create team
        (r'\b(create team|make team|new team|form team)\b',
         'create_team', ''),
        # list teams
        (r'\b(list teams?|show teams?|all teams?)\b',
         'list_teams', ''),
        # team info
        (r'\b(team info|team status|inspect team|about team|show team)\b',
         'team_info', ''),
        # delete team
        (r'\b(delete team|remove team|disband team)\b',
         'delete_team', ''),
        # memory
        (r'\b(memory list|list memory|show memory)\b',
         'memory_list', ''),
        (r'\b(memory get|get memory|recall)\b',
         'memory_get', ''),
        (r'\b(memory clear|clear memory|forget all)\b',
         'memory_clear', ''),
        # help
        (r'\b(help|commands|what can you do|show commands|how to)\b',
         'help', ''),
        # exit
        (r'\b(exit|quit|bye|goodbye|close|shut down)\b',
         'exit', ''),
    ]

    def _resolve_nl(self, raw: str) -> tuple[str, list[str]] | None:
        """Try to map natural language input to a (cmd, args) pair.
        Returns None if already a known command."""
        import re
        t = raw.strip().lower()
        # Extract a quoted or CamelCase name as the argument
        name_m = re.search(r'["\']([^"\']+)["\']', raw) or \
                 re.search(r'\b([A-Z][A-Za-z0-9_-]+)\b', raw)
        extracted = name_m.group(1) if name_m else ""
        for pat, mapped_cmd, _ in self._NL_MAP:
            if re.search(pat, t, re.IGNORECASE):
                # Strip the matched keyword; use rest as arg
                leftover = re.sub(pat, '', raw, count=1, flags=re.IGNORECASE).strip(' ,')
                arg_str = leftover if leftover else extracted
                arg_parts = arg_str.split() if arg_str else []
                return mapped_cmd, arg_parts
        return None

    def _dispatch(self, raw: str) -> None:
        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        handlers = {
            "create_agent": self._cmd_create_agent,
            "list_agents": self._cmd_list_agents,
            "delete_agent": self._cmd_delete_agent,
            "delete_all_agents": self._cmd_delete_all_agents,
            "open_agent": self._cmd_open_agent,
            "export_agent": self._cmd_export_agent,
            "export_system": self._cmd_export_system,
            "upgrade_agent": self._cmd_upgrade_agent,
            "run_agent": self._cmd_run_agent,
            "agent_info": self._cmd_agent_info,
            "build_application": self._cmd_build_application,
            "run": self._cmd_run,
            "chat": self._cmd_chat,
            "test_ai": self._cmd_test_ai,
            "switch_ai": self._cmd_switch_ai,
            "add_api": self._cmd_add_api,
            "memory_list": self._cmd_memory_list,
            "memory_get": self._cmd_memory_get,
            "memory_clear": self._cmd_memory_clear,
            # ── Multi-agent system ──────────────────────────────────
            "create_team": self._cmd_create_team,
            "list_teams": self._cmd_list_teams,
            "team_info": self._cmd_team_info,
            "delete_team": self._cmd_delete_team,
            "add_to_team": self._cmd_add_to_team,
            "remove_from_team": self._cmd_remove_from_team,
            "run_pipeline": self._cmd_run_pipeline,
            "broadcast": self._cmd_broadcast,
            "vote": self._cmd_vote,
            "best_of": self._cmd_best_of,
            "agent_debate": self._cmd_agent_debate,
            "orchestrate": self._cmd_orchestrate,
            "system_status": self._cmd_system_status,
            # ── AI System ─────────────────────────────────────────
            "create_ai_system": self._cmd_create_ai_system,
            "ai_system_task":   self._cmd_ai_system_task,
            "list_ai_systems":  self._cmd_list_ai_systems,
            "ai_system_info":   self._cmd_ai_system_info,
            # ── Ollama management ─────────────────────────────────
            "ollama_install":   self._cmd_ollama_install,
            "ollama_update":    self._cmd_ollama_update,
            "ollama_pull":      self._cmd_ollama_pull,
            "ollama_models":    self._cmd_ollama_models,
            "ollama_remove":    self._cmd_ollama_remove,
            # ──────────────────────────────────────────────────────
            "help": lambda _: print(HELP_TEXT),
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
        }

        handler = handlers.get(cmd)
        if handler is None:
            # Try natural language resolution
            resolved = self._resolve_nl(raw)
            if resolved:
                cmd, args = resolved
                handler = handlers.get(cmd)
            if handler is None:
                print(f"Unknown command: '{cmd}'. Type 'help' for a list of commands.")
                return
        try:
            handler(args)
        except Exception as exc:
            print(f"Error: {exc}")
            logger.exception("Command '%s' raised an exception.", cmd)

    # ------------------------------------------------------------------
    # Command implementations
    # ------------------------------------------------------------------

    def _cmd_create_agent(self, args: list[str]) -> None:
        if not args:
            print("Usage: create_agent <name> [role]")
            return
        name = args[0]
        role = " ".join(args[1:]) if len(args) > 1 else None

        if role is None:
            role = input(f"  Role for '{name}' (e.g. Marketing Specialist): ").strip()
            if not role:
                print("  Cancelled — no role provided.")
                return

        W = 54
        print(f"\n  {'─'*W}")
        print(f"  Building Agent: {name}  ({role})")
        print(f"  {'─'*W}")

        _steps = [""]
        def _on_progress(step, total, msg):
            _steps[0] = msg
            # Clear previous line and print new step inline
            sys.stdout.write(f"\r  [{step}/{total}] {msg:<50}")
            sys.stdout.flush()

        with Spinner(f"Researching & building {name}"):
            agent = self.kernel.build_agent(
                name=name, role=role, progress=_on_progress
            )

        print(f"\r  {'─'*W}")
        print(f"\n  AGENT CREATED: {name}")
        print(f"  {'─'*W}")
        print(f"  Role    : {agent.role}")
        print(f"  Skills  : {', '.join(agent.skills[:8])}{'...' if len(agent.skills) > 8 else ''}")
        print(f"  Tools   : {', '.join(agent.tools) if agent.tools else 'none'}")
        if agent.profile.get("instructions"):
            instr = agent.profile["instructions"]
            short = instr[:160].replace("\n", " ")
            print(f"  Prompt  : {short}{'...' if len(instr) > 160 else ''}")
        print(f"\n  Tip: type 'open_agent {name}' to open a dedicated window.")
        print()

    def _cmd_delete_agent(self, args: list[str]) -> None:
        if not args:
            print("Usage: delete_agent <name>")
            return
        name = args[0]
        if self.kernel.registry.get(name) is None:
            print(f"  Agent '{name}' not found.")
            return
        confirm = input(f"  Delete agent '{name}'? This cannot be undone. [y/N]: ").strip().lower()
        if confirm == "y":
            self.kernel.registry.remove(name)
            print(f"  Agent '{name}' deleted.")
        else:
            print("  Cancelled.")

    def _cmd_delete_all_agents(self, args: list[str]) -> None:
        names = self.kernel.list_agents()
        if not names:
            print("  No agents to delete.")
            return
        print(f"  This will permanently delete ALL {len(names)} agent(s):")
        for n in names:
            print(f"    - {n}")
        confirm = input("  Are you sure? Type 'yes' to confirm: ").strip().lower()
        if confirm == "yes":
            deleted = self.kernel.delete_all_agents()
            print(f"  ✓ Deleted {len(deleted)} agent(s).")
        else:
            print("  Cancelled.")

    def _cmd_export_agent(self, args: list[str]) -> None:
        if not args:
            print("Usage: export_agent <name>")
            return
        name = args[0]
        with Spinner(f"Exporting {name}"):
            result = self.kernel.export_agent(name)
        if result.get("error"):
            print(f"  Error: {result['error']}")
            return
        out = result["output_dir"]
        files = result["files"]
        print(f"\n  Exported '{name}' → {out}")
        print(f"  {'─'*44}")
        for i, f in enumerate(files, 1):
            print(f"  {i:>2}.  {f}")
        print(f"  {'─'*44}")
        print(f"  To run: cd \"{out}\" && launch_agent.bat")
        print()
    def _cmd_export_system(self, args: list[str]) -> None:
        if len(args) < 2:
            print("Usage: export_system <SystemName> <agent1,agent2,...>")
            print("  Example: export_system MyAI designer,coder,tester")
            return
        system_name  = args[0]
        agent_names  = [a.strip() for a in " ".join(args[1:]).replace(",", " ").split() if a.strip()]
        if not agent_names:
            print("  No agent names provided.")
            return
        print(f"\n  Exporting AI System '{system_name}' with agents: {', '.join(agent_names)}")
        with Spinner(f"Building {system_name}"):
            result = self.kernel.export_system(system_name, agent_names)
        if result.get("error"):
            print(f"  Error: {result['error']}")
            return
        out = result["output_dir"]
        _sep = "\u2500" * 54
        print(f"\n  \u2713 AI System '{system_name}' exported \u2192 {out}")
        print(f"  {_sep}")
        for a in result["agents"]:
            print(f"    \u2022 {a}  \u2192  launch_{a}.bat")
        print(f"  {_sep}")
        print(f"  Main launcher : launch_system.bat  (agent picker menu)")
        print(f"  First launch  : setup wizard asks for AI provider + key")
        print()
    def _cmd_open_agent(self, args: list[str]) -> None:
        if not args:
            print("Usage: open_agent <name>")
            return
        name = args[0]
        if self.kernel.registry.get(name) is None:
            print(f"  Agent '{name}' not found. Create it first with: create_agent {name}")
            return
        provider = self.kernel.ai_adapter.provider
        model = self.kernel.ai_adapter.model
        py = sys.executable
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_window.py")
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # CREATE_NEW_CONSOLE opens a real new CMD window — no shell quoting needed.
        # PYTHONUTF8=1 forces Python inside the new window to use UTF-8 I/O from startup.
        child_env = os.environ.copy()
        child_env["PYTHONUTF8"] = "1"
        subprocess.Popen(
            [py, script, name, "--provider", provider, "--model", model or ""],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=project_root,
            env=child_env,
        )
        print(f"  Opened agent '{name}' in a new window.")

    def _cmd_upgrade_agent(self, args: list[str]) -> None:
        if not args:
            print("Usage: upgrade_agent <name>")
            return
        with Spinner(f"Upgrading {args[0]}"):
            result = self.kernel.skill_engine.upgrade(args[0])
        print(f"Upgraded '{result['agent']}' to v{result['version']}.")
        if result["skills_added"]:
            print(f"  New skills: {', '.join(result['skills_added'])}")

    def _cmd_run_agent(self, args: list[str]) -> None:
        if len(args) < 2:
            print("Usage: run_agent <name> <task...>")
            return
        name = args[0]
        task = " ".join(args[1:])
        with Spinner(f"{name} working"):
            result = self.kernel.run_agent(name=name, task=task)
        print(f"\n[{name}] Result:\n{result}\n")

    def _cmd_list_agents(self, _args: list[str]) -> None:
        names = self.kernel.list_agents()
        if not names:
            print("\n  No agents created yet. Use: create_agent <name>\n")
            return
        print(f"\n  {'#':<4} {'Name':<22} {'Role':<28} {'Ver':<8} {'Tasks'}")
        print(f"  {'─'*4} {'─'*22} {'─'*28} {'─'*8} {'─'*10}")
        for i, name in enumerate(names, 1):
            agent = self.kernel.registry.get(name)
            perf = agent.profile["performance"]
            done = perf["tasks_completed"]
            failed = perf["tasks_failed"]
            ver = agent.profile["version"]
            print(f"  {i:<4} {name:<22} {agent.role:<28} {ver:<8} {done} done / {failed} failed")
        print()

    def _cmd_agent_info(self, args: list[str]) -> None:
        if not args:
            print("Usage: agent_info <name>")
            return
        report = self.kernel.skill_engine.get_performance_report(args[0])
        print(f"\nAgent Profile: {report['agent']}")
        print(f"  Role     : {report['role']}")
        print(f"  Version  : {report['version']}")
        print(f"  Skills   : {', '.join(report['skills']) or 'none'}")
        print(f"  Tools    : {', '.join(report['tools']) or 'none'}")
        perf = report["performance"]
        print(f"  Tasks    : {perf['tasks_completed']} completed / {perf['tasks_failed']} failed")
        print(f"  Success  : {perf['success_rate'] * 100:.1f}%\n")

    def _cmd_run(self, args: list[str]) -> None:
        if len(args) < 2:
            print("Usage: run <agent_name> <app_name>")
            print("  Looks in projects/<agent>/<app> for the built project.")
            return
        agent_name = args[0]
        app_name   = args[1]
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        run_dir = os.path.join(project_root, "..", "projects", agent_name, app_name)
        run_dir = os.path.normpath(run_dir)
        if not os.path.isdir(run_dir):
            print(f"  Error: No project '{app_name}' found for agent '{agent_name}'.")
            print(f"  Expected: {run_dir}")
            return
        # Delegate to the shared launcher
        _launch_app(app_name, run_dir)

    def _cmd_build_application(self, args: list[str]) -> None:
        if not args:
            print("Usage: build_application <app_name>")
            return
        app_name = " ".join(args)
        result: dict = {}

        # Print header
        print(f"\n  Building '{app_name}'...")
        print(f"  {'─' * 40}")

        def _on_progress(step, total, filename, ok):
            icon = "✓" if ok else "✗"
            # Pad step number width to total digits
            w = len(str(total))
            print(f"  {step:{w}}.  {icon}  {filename}")

        with Spinner("Waiting for AI"):
            raw_result = self.kernel.build_application(app_name)
            # store for display after spinner exits
            result.update(raw_result)

        # Re-run progress display after spinner clears
        files = result.get("files", [])
        output_dir = result.get("output_dir", "agent_output/" + app_name)
        total = len(files)
        w = len(str(total)) if total else 1
        for i, (rel_path, status) in enumerate(files, start=1):
            icon = "✓" if "successfully" in status else "✗"
            print(f"  {i:{w}}.  {icon}  {rel_path}")

        print(f"  {'─' * 40}")
        print(f"  {total} file(s) → {output_dir}")
        print()

    # ------------------------------------------------------------------
    # Ollama management commands
    # ------------------------------------------------------------------

    @staticmethod
    def _ollama_installed() -> bool:
        import shutil
        return shutil.which("ollama") is not None

    @staticmethod
    def _run_live(cmd: list[str]) -> int:
        """Run a command with live stdout/stderr output. Returns exit code."""
        import subprocess
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )
        for line in proc.stdout:
            print("  " + line, end="")
        proc.wait()
        return proc.returncode

    def _cmd_ollama_install(self, _args: list[str]) -> None:
        import subprocess, shutil
        print()
        # Already installed?
        if self._ollama_installed():
            try:
                v = subprocess.check_output(["ollama", "--version"],
                                            text=True, stderr=subprocess.STDOUT).strip()
            except Exception:
                v = "unknown"
            print(f"  ✓ Ollama is already installed  ({v})")
            print(f"  Tip: run 'ollama_update' to upgrade, or 'ollama_pull' to add models.\n")
            return
        print("  Installing Ollama...")
        print(f"  {'─'*50}")
        # Try winget first (Windows Package Manager)
        if shutil.which("winget"):
            print("  Using winget — this may open a UAC prompt...\n")
            rc = self._run_live(["winget", "install", "--id", "Ollama.Ollama",
                                  "--silent", "--accept-package-agreements",
                                  "--accept-source-agreements"])
            if rc == 0:
                print(f"\n  ✓ Ollama installed successfully via winget.")
                print(f"  Restart your terminal so 'ollama' is on your PATH.")
                print(f"  Then run 'ollama_pull' to download a model.\n")
                return
            print(f"  winget exited with code {rc}. Trying direct download method...\n")
        # Fallback: PowerShell download + silent install
        if shutil.which("powershell"):
            print("  Downloading OllamaSetup.exe via PowerShell...\n")
            import tempfile, os
            tmp = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
            dl = (
                f"Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' "
                f"-OutFile '{tmp}' -UseBasicParsing"
            )
            rc = self._run_live(["powershell", "-NoProfile", "-Command", dl])
            if rc == 0 and os.path.exists(tmp):
                print(f"  Launching installer: {tmp}\n")
                subprocess.Popen([tmp])
                print("  ✓ Installer launched — follow the on-screen prompts.")
                print("  Restart your terminal after installation.\n")
            else:
                print("  Download failed. Please install manually:")
                print("  https://ollama.com/download/windows\n")
        else:
            print("  Neither winget nor PowerShell found.")
            print("  Please download Ollama manually from:")
            print("  https://ollama.com/download/windows\n")

    def _cmd_ollama_update(self, _args: list[str]) -> None:
        import subprocess, shutil
        print()
        if not self._ollama_installed():
            print("  Ollama is not installed. Run 'ollama_install' first.\n")
            return
        try:
            v = subprocess.check_output(["ollama", "--version"],
                                        text=True, stderr=subprocess.STDOUT).strip()
            print(f"  Current version: {v}")
        except Exception:
            pass
        print(f"  {'─'*50}")
        updated = False
        if shutil.which("winget"):
            print("  Updating via winget...\n")
            rc = self._run_live(["winget", "upgrade", "--id", "Ollama.Ollama",
                                  "--silent", "--accept-package-agreements",
                                  "--accept-source-agreements"])
            if rc == 0:
                print("\n  ✓ Ollama updated successfully.")
                updated = True
            else:
                print(f"\n  winget upgrade exited with code {rc}.")
        if not updated:
            # Re-download installer
            if shutil.which("powershell"):
                import tempfile, os
                tmp = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
                print("  Downloading latest OllamaSetup.exe...\n")
                dl = (
                    f"Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' "
                    f"-OutFile '{tmp}' -UseBasicParsing"
                )
                rc = self._run_live(["powershell", "-NoProfile", "-Command", dl])
                if rc == 0 and os.path.exists(tmp):
                    import subprocess as sp
                    sp.Popen([tmp])
                    print("  ✓ Installer launched — follow the on-screen prompts.\n")
                else:
                    print("  Failed. Download manually: https://ollama.com/download/windows\n")
            else:
                print("  Download manually: https://ollama.com/download/windows\n")

    def _cmd_ollama_pull(self, args: list[str]) -> None:
        print()
        if not self._ollama_installed():
            print("  Ollama is not installed. Run 'ollama_install' first.\n")
            return
        from ai.ai_adapter import AIAdapter as _AI
        rec = _AI.OLLAMA_RECOMMENDED
        model = args[0] if args else ""
        if not model:
            print("  Recommended Ollama models:")
            print(f"  {'─'*62}")
            for i, (m, desc) in enumerate(rec, 1):
                print(f"  {i:2}. {desc}")
            print(f"  {'─'*62}")
            _c = input("  Enter number or model name: ").strip()
            if _c.isdigit() and 1 <= int(_c) <= len(rec):
                model = rec[int(_c) - 1][0]
            elif _c:
                model = _c
            else:
                print("  Cancelled.\n")
                return
        print(f"  Pulling '{model}' — this may take a while...\n")
        rc = self._run_live(["ollama", "pull", model])
        if rc == 0:
            print(f"\n  ✓ Model '{model}' ready.")
            print(f"  Switch to it with: switch_ai ollama {model}\n")
        else:
            print(f"\n  Pull failed (exit {rc}). Check model name and try again.\n")

    def _cmd_ollama_models(self, _args: list[str]) -> None:
        import subprocess
        print()
        if not self._ollama_installed():
            print("  Ollama is not installed. Run 'ollama_install' first.\n")
            return
        try:
            out = subprocess.check_output(["ollama", "list"],
                                          text=True, stderr=subprocess.STDOUT,
                                          encoding="utf-8", errors="replace")
            lines = out.strip().splitlines()
            if not lines or (len(lines) == 1 and "NAME" in lines[0]):
                print("  No models installed yet.")
                print("  Run 'ollama_pull' to download one.\n")
                return
            print(f"  {'─'*62}")
            for line in lines:
                print(f"  {line}")
            print(f"  {'─'*62}")
            print(f"  {len(lines)-1} model(s) installed.  "
                  f"Use 'switch_ai ollama <name>' to activate.\n")
        except Exception as exc:
            print(f"  Error running 'ollama list': {exc}\n")

    def _cmd_ollama_remove(self, args: list[str]) -> None:
        import subprocess
        print()
        if not self._ollama_installed():
            print("  Ollama is not installed.\n")
            return
        if not args:
            print("  Usage: ollama_remove <model>\n")
            return
        model = args[0]
        confirm = input(f"  Delete model '{model}'? [y/N]: ").strip().lower()
        if confirm != "y":
            print("  Cancelled.\n")
            return
        rc = self._run_live(["ollama", "rm", model])
        if rc == 0:
            print(f"\n  ✓ Model '{model}' removed.\n")
        else:
            print(f"\n  Failed (exit {rc}). Check the model name with 'ollama_models'.\n")

    def _cmd_test_ai(self, _args: list[str]) -> None:
        """Send a quick ping to the current AI provider and show result."""
        import time
        provider = self.kernel.ai_adapter.provider
        model    = self.kernel.ai_adapter.model
        print(f"\n  Testing AI connection...")
        print(f"  Provider : {provider}")
        print(f"  Model    : {model}")
        print(f"  {'-'*46}")
        try:
            t0 = time.time()
            with Spinner("Connecting"):
                reply = self.kernel.ai_adapter.chat(
                    messages=[{"role": "user",
                                "content": "Reply with exactly three words: AI IS WORKING"}]
                )
            elapsed = time.time() - t0
            short = (reply or "").strip()[:120]
            print(f"  Response : {short}")
            print(f"  Time     : {elapsed:.2f}s")
            print(f"  Status   : ✓  AI is working correctly\n")
        except Exception as exc:
            print(f"  Status   : ✗  Connection failed")
            print(f"  Error    : {exc}\n")
            print("  Tip: run 'switch_ai' to change provider or 'add_api' to update your key.\n")

    def _cmd_chat(self, args: list[str]) -> None:
        if not args:
            print("Usage: chat <message...>")
            return
        message = " ".join(args)
        with Spinner("Aether thinking"):
            response = self.kernel.chat(message)
        print(f"\nAether: {response}\n")

    def _cmd_switch_ai(self, args: list[str]) -> None:
        if not args:
            print("Usage: switch_ai <provider> [model]")
            return
        provider = args[0].lower()
        model = args[1] if len(args) > 1 else None

        # If switching to Ollama and no model specified, show recommended list
        if provider == "ollama" and not model:
            from ai.ai_adapter import AIAdapter as _AI
            rec = _AI.OLLAMA_RECOMMENDED
            print("\n  Recommended Ollama models:")
            print(f"  {'─'*62}")
            for i, (m, desc) in enumerate(rec, 1):
                print(f"  {i:2}. {desc}")
            print(f"  {'─'*62}")
            _choice = input("  Enter number or model name [qwen2.5-coder:7b]: ").strip()
            if _choice.isdigit() and 1 <= int(_choice) <= len(rec):
                model = rec[int(_choice) - 1][0]
            elif _choice:
                model = _choice
            else:
                model = "qwen2.5-coder:7b"

        self.kernel.ai_adapter.switch(provider=provider, model=model)
        print(f"  Switched to provider '{provider}', model '{self.kernel.ai_adapter.model}'.")

    def _cmd_add_api(self, args: list[str]) -> None:
        from cli.api_key_manager import run_add_api
        run_add_api(args, ai_adapter=self.kernel.ai_adapter)

    def _cmd_memory_list(self, _args: list[str]) -> None:
        keys = self.kernel.memory.keys()
        if not keys:
            print("Memory is empty.")
            return
        print("Memory keys:")
        for k in keys:
            print(f"  • {k}")

    def _cmd_memory_get(self, args: list[str]) -> None:
        if not args:
            print("Usage: memory_get <key>")
            return
        value = self.kernel.memory.load(args[0], default="<not found>")
        print(f"{args[0]}: {value}")

    def _cmd_memory_clear(self, _args: list[str]) -> None:
        self.kernel.memory.clear()
        print("Memory cleared.")

    def _cmd_exit(self, _args: list[str]) -> None:
        print("Shutting down AetherAi-A Master AI. Goodbye.")
        self._running = False
        sys.exit(0)

    # ------------------------------------------------------------------
    # Multi-agent  —  Teams
    # ------------------------------------------------------------------

    def _cmd_create_team(self, args: list[str]) -> None:
        if len(args) < 2:
            print("Usage: create_team <name> <agent1,agent2,...>")
            return
        name = args[0]
        agent_names = [a.strip() for a in args[1].split(",") if a.strip()]
        result = self.kernel.create_team(name, agent_names)
        if result.get("error"):
            print(f"  Error: {result['error']}")
            return
        members = result["members"]
        print(f"\n  Team '{name}' created with {len(members)} member(s):")
        for m in members:
            agent = self.kernel.registry.get(m)
            role = agent.role if agent else "(unknown)"
            print(f"    • {m:<22} {role}")
        print()

    def _cmd_list_teams(self, _args: list[str]) -> None:
        all_teams = self.kernel.team_manager.list_all()
        if not all_teams:
            print("  No teams yet.  Use: create_team <name> <a1,a2,...>")
            return
        print(f"\n  {'Team':<22} {'Members'}")
        print(f"  {'─'*22} {'─'*30}")
        for team_name, members in all_teams.items():
            print(f"  {team_name:<22} {', '.join(members)}")
        print()

    def _cmd_team_info(self, args: list[str]) -> None:
        if not args:
            print("Usage: team_info <name>")
            return
        name = args[0]
        members = self.kernel.team_manager.get_team(name)
        if members is None:
            print(f"  Team '{name}' not found.")
            return
        print(f"\n  Team: {name}  ({len(members)} member(s))")
        print(f"  {'─'*50}")
        print(f"  {'Name':<22} {'Role':<28} {'Tasks':<10} {'Success'}")
        print(f"  {'─'*22} {'─'*28} {'─'*10} {'─'*8}")
        for m in members:
            agent = self.kernel.registry.get(m)
            if agent:
                perf = agent.profile["performance"]
                done = perf["tasks_completed"]
                rate = f"{perf['success_rate']*100:.0f}%"
                print(f"  {m:<22} {agent.role:<28} {done:<10} {rate}")
            else:
                print(f"  {m:<22} (not found in registry)")
        print()

    def _cmd_delete_team(self, args: list[str]) -> None:
        if not args:
            print("Usage: delete_team <name>")
            return
        name = args[0]
        if self.kernel.team_manager.get_team(name) is None:
            print(f"  Team '{name}' not found.")
            return
        confirm = input(f"  Delete team '{name}'? Agents are unaffected. [y/N]: ").strip().lower()
        if confirm == "y":
            self.kernel.delete_team(name)
            print(f"  Team '{name}' deleted.")
        else:
            print("  Cancelled.")

    def _cmd_add_to_team(self, args: list[str]) -> None:
        if len(args) < 2:
            print("Usage: add_to_team <team> <agent>")
            return
        result = self.kernel.team_manager.add_member(args[0], args[1])
        if result.get("error"):
            print(f"  Error: {result['error']}")
        else:
            print(f"  Team '{args[0]}' now has: {', '.join(result['members'])}")

    def _cmd_remove_from_team(self, args: list[str]) -> None:
        if len(args) < 2:
            print("Usage: remove_from_team <team> <agent>")
            return
        result = self.kernel.team_manager.remove_member(args[0], args[1])
        if result.get("error"):
            print(f"  Error: {result['error']}")
        else:
            print(f"  Team '{args[0]}' now has: {', '.join(result['members']) or '(empty)'}")

    # ------------------------------------------------------------------
    # Multi-agent  —  Orchestration modes
    # ------------------------------------------------------------------

    def _cmd_run_pipeline(self, args: list[str]) -> None:
        """run_pipeline <team_or_a1,a2,...> <task...>"""
        if len(args) < 2:
            print("Usage: run_pipeline <team_or_agent1,agent2,...> <task...>")
            return
        target = args[0]
        task = " ".join(args[1:])
        try:
            agent_names = self.kernel.team_manager.resolve_agents(target)
        except ValueError as e:
            print(f"  Error: {e}")
            return
        print(f"\n  Pipeline: {' → '.join(agent_names)}")
        print(f"  Task    : {task}")
        print(f"  {'─'*54}")
        with Spinner("Running pipeline"):
            results = self.kernel.run_pipeline(agent_names, task)
        for r in results:
            icon = "✓" if r["success"] else "✗"
            print(f"\n  {icon} Step {r['step']}  [{r['agent']}]")
            print(f"  {'─'*50}")
            print(_indent(r["output"], 2))
        print()

    def _cmd_broadcast(self, args: list[str]) -> None:
        """broadcast <task...>  — all registered agents"""
        if not args:
            print("Usage: broadcast <task...>")
            return
        task = " ".join(args)
        names = self.kernel.list_agents()
        if not names:
            print("  No agents registered.")
            return
        print(f"\n  Broadcasting to {len(names)} agent(s): {', '.join(names)}")
        print(f"  {'─'*54}")
        with Spinner("Broadcasting"):
            results = self.kernel.broadcast(names, task)
        for r in results:
            icon = "✓" if r["success"] else "✗"
            print(f"\n  {icon} [{r['agent']}]")
            print(f"  {'─'*50}")
            print(_indent(r["output"], 2))
        print()

    def _cmd_vote(self, args: list[str]) -> None:
        """vote <question...>  — all agents answer, AI synthesizes"""
        if not args:
            print("Usage: vote <question...>")
            return
        question = " ".join(args)
        names = self.kernel.list_agents()
        if not names:
            print("  No agents registered.")
            return
        print(f"\n  Voting across {len(names)} agent(s)…")
        with Spinner("Collecting votes"):
            result = self.kernel.vote(names, question)
        print(f"\n  Question: {question}")
        print(f"  {'─'*54}")
        for r in result["responses"]:
            icon = "✓" if r["success"] else "✗"
            print(f"\n  {icon} [{r['agent']}]")
            print(_indent(r["output"], 2))
        print(f"\n  {'─'*54}")
        print(f"  CONSENSUS:")
        print(_indent(result["consensus"], 2))
        print()

    def _cmd_best_of(self, args: list[str]) -> None:
        """best_of <task...>  — all agents try, AI picks best"""
        if not args:
            print("Usage: best_of <task...>")
            return
        task = " ".join(args)
        names = self.kernel.list_agents()
        if not names:
            print("  No agents registered.")
            return
        print(f"\n  Best-of across {len(names)} agent(s)…")
        with Spinner("Collecting responses"):
            result = self.kernel.best_of(names, task)
        print(f"\n  Task: {task}")
        print(f"  {'─'*54}")
        for r in result["all"]:
            marker = "★" if r["agent"] == result.get("winner") else "○"
            icon = "✓" if r["success"] else "✗"
            print(f"\n  {marker} {icon} [{r['agent']}]")
            print(_indent(r["output"], 2))
        print(f"\n  {'─'*54}")
        print(f"  WINNER: {result.get('winner', 'N/A')}")
        print(_indent(result.get("verdict", ""), 2))
        print()

    def _cmd_agent_debate(self, args: list[str]) -> None:
        """agent_debate <agent1> <agent2> <topic...>"""
        if len(args) < 3:
            print("Usage: agent_debate <agent1> <agent2> <topic...>")
            return
        agent1, agent2 = args[0], args[1]
        topic = " ".join(args[2:])
        print(f"\n  Debate: {agent1} vs {agent2}")
        print(f"  Topic : {topic}")
        print(f"  {'─'*54}")
        with Spinner("Debating"):
            result = self.kernel.agent_debate(agent1, agent2, topic)
        if result.get("error"):
            print(f"  Error: {result['error']}")
            return
        current_round = 0
        for entry in result["transcript"]:
            if entry["round"] != current_round:
                current_round = entry["round"]
                print(f"\n  ── Round {current_round} ──────────────────")
            print(f"\n  [{entry['agent']}]")
            print(_indent(entry["argument"], 2))
        print(f"\n  {'─'*54}")
        print("  SUMMARY:")
        print(_indent(result["summary"], 2))
        print()

    def _cmd_orchestrate(self, args: list[str]) -> None:
        """orchestrate <task...>  — AI auto-routes to best agents+mode"""
        if not args:
            print("Usage: orchestrate <task...>")
            return
        task = " ".join(args)
        print(f"\n  Orchestrating: {task}")
        with Spinner("Planning & executing"):
            result = self.kernel.orchestrate(task)
        if result.get("error"):
            print(f"  Error: {result['error']}")
            return
        mode = result.get("mode", "?").upper()
        agents = result.get("agents", [])
        reason = result.get("reason", "")
        print(f"\n  Mode   : {mode}")
        print(f"  Agents : {', '.join(agents)}")
        print(f"  Reason : {reason}")
        print(f"  {'─'*54}")
        # Display results depending on mode
        mode_lower = result.get("mode", "")
        if mode_lower == "pipeline":
            for r in result.get("results", []):
                icon = "✓" if r["success"] else "✗"
                print(f"\n  {icon} Step {r['step']} [{r['agent']}]")
                print(_indent(r["output"], 2))
        elif mode_lower in ("vote",):
            for r in result.get("responses", []):
                icon = "✓" if r["success"] else "✗"
                print(f"\n  {icon} [{r['agent']}]")
                print(_indent(r["output"], 2))
            print(f"\n  CONSENSUS:")
            print(_indent(result.get("consensus", ""), 2))
        elif mode_lower == "best_of":
            for r in result.get("all", []):
                marker = "★" if r["agent"] == result.get("winner") else "○"
                print(f"\n  {marker} [{r['agent']}]")
                print(_indent(r["output"], 2))
            print(f"\n  WINNER: {result.get('winner', 'N/A')}")
            print(_indent(result.get("verdict", ""), 2))
        else:  # broadcast
            for r in result.get("results", []):
                icon = "✓" if r["success"] else "✗"
                print(f"\n  {icon} [{r['agent']}]")
                print(_indent(r["output"], 2))
        print()

    def _cmd_system_status(self, _args: list[str]) -> None:
        """Full system dashboard."""
        kernel = self.kernel
        agents = kernel.list_agents()
        teams = kernel.team_manager.list_all()
        tools = kernel.tool_manager.list_tools()
        provider = kernel.ai_adapter.provider
        model = kernel.ai_adapter.model
        mem_keys = kernel.memory.keys()

        W = 56
        print(f"\n  {'═'*W}")
        print(f"  {'AetherAi-A Master AI  —  SYSTEM STATUS':^{W}}")
        print(f"  {'═'*W}")

        # AI
        print(f"\n  AI Provider : {provider}")
        print(f"  Model       : {model}")

        # Agents
        print(f"\n  Agents ({len(agents)}):")
        if agents:
            print(f"  {'Name':<22} {'Role':<24} {'Ver':<7} {'Tasks':<8} {'OK%'}")
            print(f"  {'─'*22} {'─'*24} {'─'*7} {'─'*8} {'─'*6}")
            for name in agents:
                a = kernel.registry.get(name)
                perf = a.profile["performance"]
                rate = f"{perf['success_rate']*100:.0f}%"
                print(f"  {name:<22} {a.role:<24} {a.profile['version']:<7} {perf['tasks_completed']:<8} {rate}")
        else:
            print("    (none)")

        # Teams
        print(f"\n  Teams ({len(teams)}):")
        if teams:
            for tname, members in teams.items():
                print(f"    {tname}: {', '.join(members)}")
        else:
            print("    (none)")

        # Tools
        print(f"\n  Tools ({len(tools)}):")
        tool_line = ""
        for i, t in enumerate(sorted(tools)):
            tool_line += t
            if i < len(tools) - 1:
                tool_line += ", "
        # wrap at ~W chars
        import textwrap
        for line in textwrap.wrap(tool_line, width=W - 4):
            print(f"    {line}")

        # Memory
        print(f"\n  Memory keys : {len(mem_keys)}")

        # AI Systems
        systems = kernel.list_ai_systems()
        print(f"\n  AI Systems ({len(systems)}):")
        if systems:
            for s in systems:
                print(f"    {s['name']:<24} {len(s['agents'])} agents — {s['description'][:40]}")
        else:
            print("    (none)")

        print(f"\n  {'═'*W}\n")

    # ------------------------------------------------------------------
    # AI System commands
    # ------------------------------------------------------------------

    def _cmd_create_ai_system(self, _args: list[str]) -> None:
        """Interactively design + build a complete AI System."""
        print("")
        name = input("  AI System name (e.g. MarketingOS, CodeFactory): ").strip()
        if not name:
            print("  Cancelled — no name provided.")
            return
        description = input("  What does this system do? (describe in 1-3 sentences):\n  > ").strip()
        if not description:
            print("  Cancelled — no description provided.")
            return

        # Check for name collision
        existing = self.kernel.get_ai_system_info(name)
        if existing.get("system_name"):
            yn = input(f"  AI System '{name}' already exists. Overwrite? (y/n): ").strip().lower()
            if yn != "y":
                print("  Cancelled.")
                return

        W = 54
        print(f"\n  {'─'*W}")
        print(f"  Building AI System: {name}")
        print(f"  {'─'*W}")
        print(f"  Phase 1 — Researching core function & architecture")
        print(f"  Phase 2 — Designing agent roster")
        print(f"  Phase 3 — For each sub-agent:")
        print(f"             • Research core function")
        print(f"             • Gather skill requirements")
        print(f"             • Write instructions")
        print(f"  Phase 4 — Compile & save system")
        print(f"  {'─'*W}")
        print(f"  (This builds a thorough system — may take a minute...)\n")

        def _on_progress(step, total, msg):
            sys.stdout.write(f"\r  [{step}/{total}] {msg:<56}")
            sys.stdout.flush()

        with Spinner("Building system"):
            result = self.kernel.create_ai_system(
                name=name, description=description, progress=_on_progress
            )

        # Clear spinner line
        sys.stdout.write("\r" + " " * 72 + "\r")

        if result.get("error"):
            print(f"\n  ERROR: {result['error']}")
            return

        agents = result["agents"]
        print(f"\n  {'─'*W}")
        print(f"  AI SYSTEM BUILT: {name}")
        print(f"  {'─'*W}")
        print(f"  Purpose  : {result.get('purpose', '')}")
        print(f"  Team     : {result['team']}")
        print(f"  Manifest : {result['manifest_path']}")
        print(f"\n  Sub-agents ({len(agents)})  [internal — not individually exportable]:")
        for aname in agents:
            ag = self.kernel.registry.get(aname)
            if ag:
                skill_count = len(ag.skills)
                print(f"    ▸ {aname:<24} {ag.role}  ({skill_count} skills)")
        print(f"\n  Use: ai_system_task {name} <your task>\n")

    def _cmd_ai_system_task(self, args: list[str]) -> None:
        """Run a task through an AI System."""
        if not args:
            print("  Usage: ai_system_task <system_name> <task...>")
            return
        system_name = args[0]
        task = " ".join(args[1:]).strip()
        if not task:
            task = input(f"  Task for {system_name}: ").strip()
        if not task:
            print("  No task provided.")
            return

        W = 54
        print(f"\n  {'─'*W}")
        print(f"  AI SYSTEM: {system_name}")
        print(f"  Task: {task[:60]}{'...' if len(task)>60 else ''}")
        print(f"  {'─'*W}")

        with Spinner(f"Running through {system_name}"):
            result = self.kernel.ai_system_task(system_name, task)

        if result.get("error"):
            print(f"\n  ERROR: {result['error']}")
            return

        agents_used = result.get("agents_used", [])
        strategy    = result.get("strategy", "")
        reason      = result.get("routing_reason", "")

        print(f"  Routed to : {', '.join(agents_used)}  [{strategy}]")
        if reason:
            print(f"  Reason    : {reason}")
        print(f"  {'─'*W}")

        # If multiple agents and pipeline/parallel, show each contribution
        detail = result.get("detail", [])
        if len(detail) > 1:
            for d in detail:
                print(f"\n  ── {d['agent']} ({d['role']}) ──")
                print(_indent(d["output"], 2))
            print(f"\n  ── FINAL OUTPUT ──")

        print()
        print(_indent(result["output"], 2))
        print()

    def _cmd_list_ai_systems(self, _args: list[str]) -> None:
        """List all saved AI Systems."""
        systems = self.kernel.list_ai_systems()
        if not systems:
            print("\n  No AI Systems found. Run: create_ai_system\n")
            return
        W = 54
        print(f"\n  {'─'*W}")
        print(f"  {'AI SYSTEMS':^{W}}")
        print(f"  {'─'*W}")
        for s in systems:
            print(f"  {s['name']:<24} {len(s['agents'])} agents")
            print(f"    {s['description'][:60]}")
            print(f"    Agents: {', '.join(s['agents'])}")
            print()
        print(f"  {'─'*W}\n")

    def _cmd_ai_system_info(self, args: list[str]) -> None:
        """Show full details of an AI System."""
        if not args:
            print("  Usage: ai_system_info <system_name>")
            return
        info = self.kernel.get_ai_system_info(args[0])
        if info.get("error"):
            print(f"  {info['error']}")
            return
        W = 54
        print(f"\n  {'─'*W}")
        print(f"  SYSTEM   : {info['system_name']}")
        print(f"  Purpose  : {info.get('purpose', '')}")
        print(f"  {'─'*W}")
        for a in info.get("agents", []):
            print(f"\n  ▸ {a['name']} — {a['role']}")
            handles = a.get("handles", [])
            if handles:
                print(f"    Handles : {', '.join(handles)}")
            skills = a.get("skills", [])
            print(f"    Skills  : {', '.join(skills[:8])}{'...' if len(skills)>8 else ''}")
            if a.get("instructions"):
                instr_short = a["instructions"][:120]
                print(f"    Instr.  : {instr_short}{'...' if len(a['instructions'])>120 else ''}")
        print(f"\n  {'─'*W}\n")
