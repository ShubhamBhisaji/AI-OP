"""
CommandInterface — CLI for the Aether AI Operating System.
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
            sys.stdout.write("⠋")
            sys.stdout.write("\r")
            sys.stdout.flush()
            self._frames = self._FRAMES
        except UnicodeEncodeError:
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
  ___       _   _
 / _ \     | | | |
/ /_\ \ ___| |_| |__   ___ _ __
|  _  |/ _ \ __| '_ \ / _ \ '__|
| | | |  __/ |_| | | |  __/ |
\_| |_/\___|\__|_| |_|\___|_|

  AI Operating System  v1.0.0
  Type 'help' for commands.
"""

HELP_TEXT = """
Commands:
  create_agent <name>              Create a new agent (uses built-in preset if available)
  create_agent <name> <role>       Create a custom agent with a given role
  list_agents                      List all created agents
  delete_agent <name>              Delete an agent permanently
  open_agent <name>                Open an agent in its own dedicated CMD window
  export_agent <name>              Export agent as a standalone runnable folder
  upgrade_agent <name>             Upgrade an agent's skills
  run_agent <name> <task...>       Run an agent on a task (inline)
  agent_info <name>                Show profile and performance of an agent
  build_application <app_name>     Build an application using a team of agents
  chat <message...>                Chat directly with the AI
  switch_ai <provider> [model]     Switch AI provider (openai/claude/gemini/ollama/huggingface)
  memory_list                      List all memory keys
  memory_get <key>                 Retrieve a memory value
  memory_clear                     Clear all memory
  help                             Show this help message
  exit / quit                      Exit Aether OS
"""


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
                print("\nExiting Aether OS. Goodbye.")
                break
            if not raw:
                continue
            self._dispatch(raw)

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def _dispatch(self, raw: str) -> None:
        parts = raw.split(maxsplit=2)
        cmd = parts[0].lower()
        args = parts[1:]

        handlers = {
            "create_agent": self._cmd_create_agent,
            "list_agents": self._cmd_list_agents,
            "delete_agent": self._cmd_delete_agent,
            "open_agent": self._cmd_open_agent,
            "export_agent": self._cmd_export_agent,
            "upgrade_agent": self._cmd_upgrade_agent,
            "run_agent": self._cmd_run_agent,
            "agent_info": self._cmd_agent_info,
            "build_application": self._cmd_build_application,
            "chat": self._cmd_chat,
            "switch_ai": self._cmd_switch_ai,
            "memory_list": self._cmd_memory_list,
            "memory_get": self._cmd_memory_get,
            "memory_clear": self._cmd_memory_clear,
            "help": lambda _: print(HELP_TEXT),
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
        }

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
        role = args[1] if len(args) > 1 else None
        agent = self.kernel.create_agent(name=name, role=role)
        print(f"Created: {agent}")
        print(f"  Tip: type 'open_agent {name}' to open a dedicated window for this agent.")

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
        subprocess.Popen(
            [py, script, name, "--provider", provider, "--model", model],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            cwd=project_root,
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
        provider = args[0]
        model = args[1] if len(args) > 1 else None
        self.kernel.ai_adapter.switch(provider=provider, model=model)
        print(f"Switched to provider '{provider}', model '{self.kernel.ai_adapter.model}'.")

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
        print("Shutting down Aether OS. Goodbye.")
        self._running = False
        sys.exit(0)
