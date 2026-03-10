"""
main.py — Entry point for the Aether AI Operating System.

Usage:
    python main.py                        # Interactive CLI mode
    python main.py --provider claude      # Use Claude as the AI backend
    python main.py --provider ollama --model llama3   # Use local Ollama
"""

from __future__ import annotations

import argparse
import sys
import os

# Make sure the project root is on the path so all module imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Auto-load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from core.aether_kernel import AetherKernel
from cli.command_interface import CommandInterface

# ── Credential keys per provider ──────────────────────────────────────────
_PROVIDER_KEY = {
    "github":      ("GITHUB_TOKEN",     "https://github.com/settings/tokens  (no scopes needed)"),
    "openai":      ("OPENAI_API_KEY",   "https://platform.openai.com/api-keys"),
    "claude":      ("ANTHROPIC_API_KEY","https://console.anthropic.com/settings/keys"),
    "gemini":      ("GEMINI_API_KEY",   "https://aistudio.google.com/app/apikey"),
    "huggingface": ("HF_API_KEY",       "https://huggingface.co/settings/tokens"),
}
_PLACEHOLDER = {"your_github_token_here", "your_openai_key_here",
                "your_anthropic_key_here", "your_gemini_key_here",
                "your_huggingface_token_here", ""}


def _save_to_env(key: str, value: str) -> None:
    """Persist a key=value pair into the project .env file."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        # Also set in current process
        os.environ[key] = value
        print(f"  ✓ Saved {key} to .env")
    except OSError as exc:
        print(f"  ⚠  Could not write .env: {exc}")
        print(f"  Set {key} manually in your .env file.")


def check_credentials(provider: str) -> None:
    """Prompt for an API token on first launch if none is configured."""
    if provider == "ollama":
        return  # Ollama is local — no key needed

    if provider not in _PROVIDER_KEY:
        return

    env_key, get_url = _PROVIDER_KEY[provider]
    current = os.environ.get(env_key, "")

    if current and current not in _PLACEHOLDER:
        return  # Already configured — nothing to do

    print()
    print("=" * 60)
    print("  AETHER OS — First-Run Setup")
    print("=" * 60)
    print()
    print(f"  Provider   : {provider}")
    print(f"  Requires   : {env_key}")
    print(f"  Get yours  : {get_url}")
    print()
    print("  Options:")
    print("    1) Paste your token/API key now (saved to .env)")
    print("    2) Use Ollama instead (free, runs locally — needs ollama installed)")
    print("    3) Skip and continue without AI (tools still work)")
    print()

    choice = input("  Your choice [1/2/3]: ").strip()

    if choice == "1":
        token = input(f"  Paste your {env_key}: ").strip()
        if token and token not in _PLACEHOLDER:
            _save_to_env(env_key, token)
            print()
        else:
            print("  ⚠  No token entered. Continuing without AI.")
    elif choice == "2":
        # Swap the provider to ollama — propagate via environment so kernel picks it up
        os.environ["AETHER_PROVIDER_OVERRIDE"] = "ollama"
        print("  Switching to Ollama (local). Make sure `ollama serve` is running.")
        print()
    else:
        print("  Continuing without a configured AI key.")
        print()

    print("=" * 60)
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aether",
        description="Aether AI Operating System",
    )
    parser.add_argument(
        "--provider",
        default="github",
        choices=["github", "openai", "claude", "gemini", "ollama", "huggingface"],
        help="AI provider to use (default: github — free with GitHub account)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override (uses provider default if not specified)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # First-run credential check — prompts the user if no key is set
    check_credentials(args.provider)

    # Allow the setup flow to swap the provider (e.g. user chose Ollama)
    provider = os.environ.get("AETHER_PROVIDER_OVERRIDE", args.provider)

    kernel = AetherKernel(ai_provider=provider, model=args.model)
    cli = CommandInterface(kernel=kernel)
    cli.run()


if __name__ == "__main__":
    main()
