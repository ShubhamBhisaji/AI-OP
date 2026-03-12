"""
main.py — Entry point for AetherAi-A Master AI.

Usage:
    python main.py                        # Interactive CLI mode
    python main.py --provider claude      # Use Claude as the AI backend
    python main.py --provider ollama --model llama3   # Use local Ollama
"""

from __future__ import annotations

import argparse
import sys
import os

# ── Force UTF-8 output on Windows CMD so Unicode chars print correctly ───
try:
    import ctypes as _ctypes
    _ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    _ctypes.windll.kernel32.SetConsoleCP(65001)
except Exception:
    pass
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Make sure the project root is on the path so all module imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Auto-load .env file — stdlib only, no packages needed
from core.env_loader import load_env as _load_env
_load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from core.aether_kernel import AetherKernel
from cli.command_interface import CommandInterface

# ── Credential keys per provider ──────────────────────────────────────────
_PROVIDER_KEY = {
    "github":      ("GITHUB_TOKEN",      "https://github.com/settings/tokens  (no scopes needed)"),
    "openai":      ("OPENAI_API_KEY",    "https://platform.openai.com/api-keys"),
    "claude":      ("ANTHROPIC_API_KEY", "https://console.anthropic.com/settings/keys"),
    "gemini":      ("GEMINI_API_KEY",    "https://aistudio.google.com/app/apikey"),
    "huggingface": ("HF_API_KEY",        "https://huggingface.co/settings/tokens"),
}


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
    print("  AetherAi-A Master AI — First-Run Setup")
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


# ── Provider catalogue shown in the selection menu ───────────────────────────
_PROVIDERS_MENU = [
    # (id,            display_name,   env_key,             default_model,               note)
    ("github",       "GitHub Models", "GITHUB_TOKEN",      "gpt-4.1",                    "free with GitHub account"),
    ("gemini",       "Google Gemini", "GEMINI_API_KEY",     "gemini-2.5-flash-lite",      "free tier available"),
    ("openai",       "OpenAI",        "OPENAI_API_KEY",     "gpt-4o",                     "requires paid account"),
    ("claude",       "Anthropic",     "ANTHROPIC_API_KEY",  "claude-sonnet-4.6",          "requires paid account"),
    ("huggingface",  "HuggingFace",   "HF_API_KEY",         "mistralai/Mistral-7B-Instruct-v0.2", "free tier available"),
    ("ollama",       "Ollama (local)", None,               "llama3",                     "no key — runs on your machine"),
]
_PLACEHOLDER = {"your_github_token_here", "your_openai_key_here",
                "your_anthropic_key_here", "your_gemini_key_here",
                "your_huggingface_token_here", ""}


def _key_status(env_key: str | None) -> str:
    """Return a coloured status string for a provider's API key."""
    if env_key is None:
        return "(local)  "
    val = os.environ.get(env_key, "")
    if val and val not in _PLACEHOLDER:
        return "\033[32m✓ SET\033[0m    "
    return "\033[33m✗ not set\033[0m"


def pick_provider() -> str:
    """Display an interactive AI-provider selection menu and return the chosen provider id."""
    print()
    print("=" * 66)
    print("  AetherAi-A Master AI — Select an AI Provider")
    print("=" * 66)
    print()
    print(f"  {'#':<3} {'Provider':<16} {'Default Model':<38} {'Key Status'}")
    print(f"  {'─'*3} {'─'*16} {'─'*38} {'─'*14}")
    for idx, (pid, name, env_key, model, note) in enumerate(_PROVIDERS_MENU, 1):
        status = _key_status(env_key)
        print(f"  {idx:<3} {name:<16} {model:<38} {status}")
        print(f"      \033[90m{note}\033[0m")
    print()
    print("  Tip: Use 'add_api <provider>' inside Aether to set a key any time.")
    print()

    default_idx = 1
    while True:
        try:
            raw = input(f"  Select provider [1-{len(_PROVIDERS_MENU)}, default={default_idx}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = ""
        if raw == "":
            chosen = _PROVIDERS_MENU[default_idx - 1][0]
            break
        if raw.isdigit() and 1 <= int(raw) <= len(_PROVIDERS_MENU):
            chosen = _PROVIDERS_MENU[int(raw) - 1][0]
            break
        # Accept typing the provider name directly
        raw_lower = raw.lower()
        match = next((p[0] for p in _PROVIDERS_MENU if p[0] == raw_lower or p[1].lower().startswith(raw_lower)), None)
        if match:
            chosen = match
            break
        print(f"  Invalid choice — enter a number between 1 and {len(_PROVIDERS_MENU)}.")

    name = next(p[1] for p in _PROVIDERS_MENU if p[0] == chosen)
    print(f"  \033[32m→ Using {name}\033[0m")
    print("=" * 66)
    print()
    # Persist the chosen provider so startup skips this menu next time
    _save_to_env("AETHER_DEFAULT_PROVIDER", chosen)
    return chosen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aether",
        description="AetherAi-A Master AI",
    )
    parser.add_argument(
        "--provider",
        default=None,                # None = show interactive menu
        choices=["github", "openai", "claude", "gemini", "ollama", "huggingface"],
        help="Skip the provider menu and use this provider directly",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override (uses provider default if not specified)",
    )
    return parser.parse_args()


def _saved_provider_ready() -> str | None:
    """
    Return the saved default provider if it is already configured
    (key present and not a placeholder), else None.
    Ollama is always considered ready (no key needed).
    """
    saved = os.environ.get("AETHER_DEFAULT_PROVIDER", "").strip()
    if not saved:
        return None
    if saved == "ollama":
        return saved
    entry = next((p for p in _PROVIDERS_MENU if p[0] == saved), None)
    if entry is None:
        return None
    _, _, env_key, _, _ = entry
    if env_key is None:
        return saved
    val = os.environ.get(env_key, "")
    if val and val not in _PLACEHOLDER:
        return saved
    return None


def main() -> None:
    args = parse_args()

    if args.provider is not None:
        # Explicit --provider flag: use it directly, skip menu
        provider = args.provider
    else:
        ready = _saved_provider_ready()
        if ready:
            # Already configured — skip menu, go straight in
            name = next((p[1] for p in _PROVIDERS_MENU if p[0] == ready), ready)
            print(f"  \033[32m\u2713 Using saved provider: {name}\033[0m  "
                  f"(run with --provider to change)\n")
            provider = ready
        else:
            # First run or key not yet set — show selection menu
            provider = pick_provider()

    # First-run credential check — prompts the user if no key is set
    check_credentials(provider)

    # Allow the setup flow to swap the provider (e.g. user chose Ollama)
    provider = os.environ.get("AETHER_PROVIDER_OVERRIDE", provider)

    kernel = AetherKernel(ai_provider=provider, model=args.model)
    cli = CommandInterface(kernel=kernel)
    cli.run()


if __name__ == "__main__":
    main()
