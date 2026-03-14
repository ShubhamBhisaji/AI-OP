"""
__SYSTEM_NAME__ - AI System launcher
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from core.env_loader import load_env as _lenv

_lenv(os.path.join(_ROOT, ".env"))

_AGENTS = __AGENT_LIST_REPR__
_AGENT_ROLES = __AGENT_ROLES_REPR__


def _print_menu() -> None:
    print("\n" + "=" * 60)
    print("  __SYSTEM_NAME__")
    print(f"  AI System - {len(_AGENTS)} agent(s)")
    print("=" * 60)
    for i, name in enumerate(_AGENTS, 1):
        print(f"  {i}. {name:<20} {_AGENT_ROLES.get(name, '')}")
    print(f"  {len(_AGENTS) + 1}. Exit")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    provider = args.provider or os.environ.get("AETHER_DEFAULT_PROVIDER", "github")
    model = args.model or os.environ.get("AETHER_DEFAULT_MODEL", "").strip() or None

    from cli.agent_window import run_agent_window

    if args.agent:
        if args.agent not in _AGENTS:
            print(f"Unknown agent '{args.agent}'")
            sys.exit(1)
        run_agent_window(args.agent, provider, model)
        return

    while True:
        _print_menu()
        choice = input("\n  Select agent: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if idx == len(_AGENTS):
                break
            if 0 <= idx < len(_AGENTS):
                run_agent_window(_AGENTS[idx], provider, model)
                continue
        lowered = choice.lower()
        if lowered in (a.lower() for a in _AGENTS):
            selected = next(a for a in _AGENTS if a.lower() == lowered)
            run_agent_window(selected, provider, model)
            continue
        if lowered in ("q", "quit", "exit"):
            break


if __name__ == "__main__":
    main()
