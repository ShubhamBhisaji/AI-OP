"""
CommandInterface — CLI for the Aether AI Operating System.
Provides an interactive REPL and supports all core Aether commands.
"""

from __future__ import annotations

import sys
import logging

logger = logging.getLogger(__name__)

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
  upgrade_agent <name>             Upgrade an agent's skills
  run_agent <name> <task...>       Run an agent on a task
  list_agents                      List all registered agents
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
            "upgrade_agent": self._cmd_upgrade_agent,
            "run_agent": self._cmd_run_agent,
            "list_agents": self._cmd_list_agents,
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

    def _cmd_upgrade_agent(self, args: list[str]) -> None:
        if not args:
            print("Usage: upgrade_agent <name>")
            return
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
        result = self.kernel.run_agent(name=name, task=task)
        print(f"\n[{name}] Result:\n{result}\n")

    def _cmd_list_agents(self, _args: list[str]) -> None:
        names = self.kernel.list_agents()
        if not names:
            print("No agents registered.")
            return
        print("Registered agents:")
        for name in names:
            agent = self.kernel.registry.get(name)
            print(f"  • {name} — {agent.role} (v{agent.profile['version']})")

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
        result = self.kernel.build_application(app_name)
        print(f"\nApplication plan:\n{result}\n")

    def _cmd_chat(self, args: list[str]) -> None:
        if not args:
            print("Usage: chat <message...>")
            return
        message = " ".join(args)
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
