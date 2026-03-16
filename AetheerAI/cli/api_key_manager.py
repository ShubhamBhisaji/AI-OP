"""
api_key_manager — Interactive helper for adding / updating AI provider API keys.
Writes keys to the .env file and loads them into the running process immediately.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_FILE = Path(__file__).parent.parent / ".env"

# provider -> (env_var, display_name, get_key_url, default_model)
PROVIDERS: dict[str, tuple[str, str, str, str]] = {
    "openai": (
        "OPENAI_API_KEY",
        "OpenAI",
        "https://platform.openai.com/api-keys",
        "gpt-4o",
    ),
    "claude": (
        "ANTHROPIC_API_KEY",
        "Anthropic Claude",
        "https://console.anthropic.com/settings/keys",
        "claude-sonnet-4.6",
    ),
    "gemini": (
        "GEMINI_API_KEY",
        "Google Gemini",
        "https://aistudio.google.com/apikey",
        "gemini-2.5-flash-lite",
    ),
    "huggingface": (
        "HF_API_KEY",
        "HuggingFace",
        "https://huggingface.co/settings/tokens",
        "mistralai/Mistral-7B-Instruct-v0.2",
    ),
    "github": (
        "GITHUB_TOKEN",
        "GitHub Models (Copilot Pro)",
        "https://github.com/settings/tokens",
        "claude-sonnet-4.6",
    ),
}


def run_add_api(args: list[str], ai_adapter=None) -> None:
    """
    Interactive add/update of an AI provider API key.

    Usage:
        add_api                   → interactive menu
        add_api openai            → directly set OpenAI key
        add_api gemini <key>      → set Gemini key silently
        add_api list              → show current key status
    """
    if args and args[0].lower() == "list":
        _show_status()
        return

    # Resolve provider
    provider: str | None = None
    inline_key: str | None = None

    if args:
        provider = args[0].lower()
        if len(args) > 1:
            inline_key = args[1]

    if provider and provider not in PROVIDERS:
        print(f"\n  Unknown provider '{provider}'.")
        print(f"  Supported: {', '.join(PROVIDERS)}\n")
        return

    if not provider:
        _show_status()
        print()
        choices = list(PROVIDERS.keys())
        for i, p in enumerate(choices, 1):
            env_var, display, _, _ = PROVIDERS[p]
            current = os.environ.get(env_var, "")
            status = "✓ set" if current and "your_" not in current else "  not set"
            print(f"  {i}.  {display:<30}  {status}")
        print()
        raw = input("  Enter number or provider name (or Enter to cancel): ").strip()
        if not raw:
            return
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                provider = choices[idx]
            else:
                print("  Invalid choice.")
                return
        else:
            provider = raw.lower()
            if provider not in PROVIDERS:
                print(f"  Unknown provider '{provider}'.")
                return

    env_var, display, url, default_model = PROVIDERS[provider]
    current = os.environ.get(env_var, "")
    has_key = bool(current and "your_" not in current)

    print(f"\n  Provider  : {display}")
    print(f"  Env var   : {env_var}")
    print(f"  Get key   : {url}")
    if has_key:
        masked = current[:8] + "..." + current[-4:] if len(current) > 12 else "****"
        print(f"  Current   : {masked}  (already set)")
        overwrite = input("  Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("  Unchanged.\n")
            return

    if inline_key:
        key = inline_key.strip()
    else:
        print()
        key = input(f"  Paste your {display} API key: ").strip()

    if not key:
        print("  No key entered. Unchanged.\n")
        return

    # Write to .env
    _write_key_to_env(env_var, key)

    # Load into current process immediately
    os.environ[env_var] = key

    # Hot-swap the adapter if provided
    if ai_adapter is not None:
        try:
            ai_adapter.switch(provider=provider)
            print(f"\n  ✓ Key saved and AI switched to {display} ({ai_adapter.model})")
        except Exception as exc:
            print(f"\n  ✓ Key saved to .env (switch failed: {exc})")
    else:
        print(f"\n  ✓ {env_var} saved to .env")

    print(f"  To use: switch_ai {provider}  or  switch_ai {provider} <model>")
    print(f"  Default model: {default_model}\n")


def _show_status() -> None:
    print(f"\n  {'Provider':<28} {'Env Variable':<22} {'Status'}")
    print(f"  {'-'*28} {'-'*22} {'-'*12}")
    for provider, (env_var, display, url, default_model) in PROVIDERS.items():
        val = os.environ.get(env_var, "")
        if val and "your_" not in val:
            masked = val[:6] + "..." + val[-4:] if len(val) > 10 else "****"
            status = f"✓ {masked}"
        else:
            status = "  not set"
        print(f"  {display:<28} {env_var:<22} {status}")
    print()


def _write_key_to_env(env_var: str, key: str) -> None:
    """Write or update a key in the .env file."""
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _ENV_FILE.exists():
        content = _ENV_FILE.read_text(encoding="utf-8")
        # Replace existing line
        pattern = re.compile(rf"^{re.escape(env_var)}=.*$", re.MULTILINE)
        if pattern.search(content):
            new_content = pattern.sub(f"{env_var}={key}", content)
            _ENV_FILE.write_text(new_content, encoding="utf-8")
            return
        # Append if not found
        sep = "" if content.endswith("\n") else "\n"
        _ENV_FILE.write_text(content + sep + f"{env_var}={key}\n", encoding="utf-8")
    else:
        _ENV_FILE.write_text(f"{env_var}={key}\n", encoding="utf-8")
