"""
Standalone runner for agent: __AGENT_NAME__
Role: __AGENT_ROLE__
Skills: __AGENT_SKILLS__
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)

from core.env_loader import load_env as _lenv

_lenv(os.path.join(_ROOT, ".env"))


def _first_time_setup():
    _env_path = os.path.join(_ROOT, ".env")
    print("\n" + "=" * 60)
    print("  __AGENT_NAME__ | First-time Setup")
    print("=" * 60)
    providers = [
        ("github", "GitHub Models (free, needs GitHub PAT)"),
        ("openai", "OpenAI"),
        ("gemini", "Google Gemini"),
        ("claude", "Anthropic Claude"),
        ("ollama", "Ollama (local)"),
    ]
    defaults = {
        "github": "gpt-4.1",
        "openai": "gpt-4o",
        "gemini": "gemini-1.5-flash",
        "claude": "claude-sonnet-4.6",
        "ollama": "qwen2.5-coder:7b",
    }
    key_env = {
        "github": "GITHUB_TOKEN",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "ollama": None,
    }

    for i, (_p, desc) in enumerate(providers, 1):
        print(f"  {i}. {desc}")
    while True:
        c = input("\n  Enter number (1-5): ").strip()
        if c.isdigit() and 1 <= int(c) <= 5:
            break

    provider = providers[int(c) - 1][0]
    model = input(f"  Model name [{defaults[provider]}]: ").strip() or defaults[provider]

    lines = [
        "# Agent AI configuration\n",
        f"AETHER_DEFAULT_PROVIDER={provider}\n",
        f"AETHER_DEFAULT_MODEL={model}\n",
    ]
    key_name = key_env[provider]
    if key_name:
        key = input(f"  {key_name}: ").strip()
        if key:
            lines.append(f"{key_name}={key}\n")

    with open(_env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    _lenv(_env_path)
    return provider, model


def main():
    parser = argparse.ArgumentParser(description="Agent launcher")
    parser.add_argument("--task", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    provider = args.provider or os.environ.get("AETHER_DEFAULT_PROVIDER", "").strip()
    model = args.model or os.environ.get("AETHER_DEFAULT_MODEL", "").strip() or None

    if not provider:
        provider, model = _first_time_setup()

    from cli.agent_window import run_agent_window

    run_agent_window("__AGENT_NAME__", provider, model)


if __name__ == "__main__":
    main()
