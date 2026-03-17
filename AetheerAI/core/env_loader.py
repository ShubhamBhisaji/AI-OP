"""
env_loader.py — Zero-dependency .env file loader.
Reads KEY=VALUE pairs from a .env file and sets them in os.environ.
Handles quoted values, inline comments, and blank lines.
Does NOT override variables already set in the environment.
"""
from __future__ import annotations
import os
import re
import sys


def load_env(env_path: str | None = None) -> None:
    """
    Load a .env file into os.environ without any third-party packages.
    If env_path is None, looks for .env next to this file's project root.
    """
    if env_path is None:
        if getattr(sys, "frozen", False):
            # PyInstaller .exe — .env lives next to the executable, not in the bundle
            env_path = os.path.join(os.path.dirname(sys.executable), ".env")
        else:
            # Normal execution — .env lives at the project root
            here = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(os.path.dirname(here), ".env")

    if not os.path.isfile(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        # Skip blank lines and comments
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue

        # Strip inline comment (only outside quotes)
        value = rest.strip()
        # Remove surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        else:
            # Strip trailing inline comment: value  # comment
            value = re.sub(r'\s+#.*$', '', value)

        # Only set if not already in environment
        if key not in os.environ:
            os.environ[key] = value


# ── Known provider keys (mirrors _PROVIDER_KEY / _PROVIDERS_MENU in main.py) ──
_PROVIDER_ENV_KEYS = {
    "github":      "GITHUB_TOKEN",
    "openai":      "OPENAI_API_KEY",
    "claude":      "ANTHROPIC_API_KEY",
    "gemini":      "GEMINI_API_KEY",
}

_PLACEHOLDER_VALUES = {
    "your_github_token_here",
    "your_openai_key_here",
    "your_anthropic_key_here",
    "your_gemini_key_here",
    "",
}


def check_env_file(env_path: str | None = None) -> None:
    """
    Validate the .env file at startup and report problems to stderr.

    Checks performed:
      1. Does the .env file exist?
      2. Is at least one provider key set to a non-placeholder value?
      3. Which keys are set / missing / still placeholder?

    Writes a coloured (ANSI) report to stderr so it is visible in both
    CLI and Streamlit server logs without interfering with stdout output.
    """
    if env_path is None:
        if getattr(sys, "frozen", False):
            env_path = os.path.join(os.path.dirname(sys.executable), ".env")
        else:
            here = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(os.path.dirname(here), ".env")

    RED    = "\033[31m"
    YELLOW = "\033[33m"
    GREEN  = "\033[32m"
    CYAN   = "\033[36m"
    RESET  = "\033[0m"
    BOLD   = "\033[1m"

    sep = "─" * 60

    def _err(msg: str) -> None:
        # sys.stderr is None in a frozen windowed .exe (noconsole=True)
        if sys.stderr is not None:
            print(msg, file=sys.stderr)

    _err(f"\n{CYAN}{sep}{RESET}")
    _err(f"{BOLD}  AetheerAI — Environment Check{RESET}")
    _err(f"{CYAN}{sep}{RESET}")

    # ── 1. File existence ─────────────────────────────────────────────────
    if not os.path.isfile(env_path):
        _err(f"\n  {RED}✗ .env file not found{RESET}")
        _err(f"    Expected : {env_path}")
        _err(f"\n  Create it by copying the example:")
        example = os.path.join(os.path.dirname(env_path), ".env.example")
        if os.path.isfile(example):
            _err(f"    {YELLOW}copy .env.example .env{RESET}   (Windows CMD)")
            _err(f"    {YELLOW}cp .env.example .env{RESET}     (bash / PowerShell)")
        else:
            _err(f"    Create a file named  .env  in:  {os.path.dirname(env_path)}")
        _err(f"  At least one provider key must be filled in (see README).")
        _err(f"\n{CYAN}{sep}{RESET}\n")
        return

    # ── 2. Per-key status ─────────────────────────────────────────────────
    any_set = False
    _err("")
    for provider, env_key in _PROVIDER_ENV_KEYS.items():
        val = os.environ.get(env_key, "")
        if val and val not in _PLACEHOLDER_VALUES:
            status = f"{GREEN}✓ SET{RESET}"
            any_set = True
        elif val in _PLACEHOLDER_VALUES - {""}:
            status = f"{YELLOW}✗ still placeholder{RESET}"
        else:
            status = f"{YELLOW}✗ not set{RESET}"
        _err(f"  {env_key:<22} {status}  ({provider})")

    # Ollama is local — no key needed, always show as available
    _err(f"  {'(ollama)':<22} {GREEN}✓ local (no key){RESET}")

    # ── 3. Summary ────────────────────────────────────────────────────────
    _err("")
    if not any_set:
        _err(f"  {RED}⚠  No provider API key is configured.{RESET}")
        _err(f"     Open  {env_path}")
        _err(f"     and fill in at least one key, then restart.")
        _err(f"     (Or choose Ollama — it runs locally with no key.)")
    else:
        _err(f"  {GREEN}✓ Environment OK — at least one provider is ready.{RESET}")

    _err(f"{CYAN}{sep}{RESET}\n")
