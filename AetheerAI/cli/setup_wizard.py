"""setup_wizard.py — Non-developer guided deployment wizard for AetheerAI.

Addresses UX friction by providing:
  - Visual step-by-step progress (no CLI knowledge required)
  - Auto-detection of available AI providers and system capabilities
  - Plain-English configuration prompts with validation
  - One-click launcher script generation
  - Rollback on failure

Usage
-----
    python -m AetheerAI.cli.setup_wizard            # interactive mode
    python -m AetheerAI.cli.setup_wizard --quiet    # minimal prompts, smart defaults

Programmatic
------------
    from AetheerAI.cli.setup_wizard import SetupWizard
    wizard = SetupWizard()
    wizard.run()
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Visual helpers ────────────────────────────────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_DIM    = "\033[2m"

_WIN = platform.system() == "Windows"


def _c(text: str, color: str) -> str:
    """Wrap text in ANSI color if the terminal supports it."""
    if _WIN and not os.environ.get("TERM"):
        return text          # plain terminals on older Windows
    return f"{color}{text}{_RESET}"


def _ok(msg: str) -> None:
    print(f"  {_c('✔', _GREEN)} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_c('⚠', _YELLOW)} {msg}")


def _err(msg: str) -> None:
    print(f"  {_c('✖', _RED)} {msg}")


def _info(msg: str) -> None:
    print(f"  {_c('ℹ', _CYAN)} {msg}")


def _sep(char: str = "─", width: int = 60) -> None:
    print(f"  {char * width}")


def _header(title: str, step: int, total: int) -> None:
    print()
    _sep()
    print(f"  {_c(f'Step {step}/{total}', _BOLD+_CYAN)}  —  {_c(title, _BOLD)}")
    _sep()
    print()


def _spinner(task: str, check_fn, *args, **kwargs):
    """Run check_fn in a simple blocking spinner UX."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    sys.stdout.write(f"  {frames[i]} {task}…")
    sys.stdout.flush()
    result = check_fn(*args, **kwargs)
    sys.stdout.write(f"\r  {_c('✔', _GREEN)} {task}   \n")
    sys.stdout.flush()
    return result


def _ask(prompt: str, default: str = "", secret: bool = False, validator=None) -> str:
    """Prompt user for input with validation loop."""
    suffix = f" [{_c(default, _DIM)}]" if default and not secret else ""
    full_prompt = f"  {prompt}{suffix}: "
    while True:
        try:
            value = (getpass.getpass(full_prompt) if secret
                     else input(full_prompt).strip())
        except (KeyboardInterrupt, EOFError):
            print("\n")
            _warn("Setup cancelled by user.")
            sys.exit(0)
        value = value.strip() or default
        if validator:
            err = validator(value)
            if err:
                _err(err)
                continue
        return value


def _ask_choice(prompt: str, options: list[tuple[str, str]], default: int = 1) -> int:
    """Present numbered options; return 0-based index."""
    for i, (_, desc) in enumerate(options, 1):
        marker = _c(f"  {i}.", _BOLD+_CYAN)
        print(f"{marker} {desc}")
    while True:
        raw = _ask(f"\n  {prompt}", default=str(default))
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        _err(f"Please enter a number between 1 and {len(options)}.")


def _ask_yesno(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    raw = _ask(f"{prompt} ({default_str})", default=("y" if default else "n"))
    return raw.lower().startswith("y")


# ── Validators ────────────────────────────────────────────────────────────────

def _validate_url(val: str) -> str | None:
    if not val:
        return None  # optional
    if val.startswith(("http://", "https://")):
        return None
    return "Must be a full URL starting with http:// or https://"


def _validate_nonempty(val: str) -> str | None:
    if val.strip():
        return None
    return "This field cannot be empty."


# ── System detection ──────────────────────────────────────────────────────────

@dataclass
class SystemInfo:
    python_version: str
    has_git: bool
    has_docker: bool
    has_ollama: bool
    env_file_exists: bool
    config_file_exists: bool
    detected_keys: dict[str, bool] = field(default_factory=dict)


def _detect_system(root: Path) -> SystemInfo:
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    env = _read_env(root / ".env")
    known_env_keys = [
        "GITHUB_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY", "AETHEERAI_DEFAULT_PROVIDER",
    ]
    detected = {k: bool(env.get(k) or os.environ.get(k)) for k in known_env_keys}
    return SystemInfo(
        python_version=py_ver,
        has_git=bool(shutil.which("git")),
        has_docker=bool(shutil.which("docker")),
        has_ollama=bool(shutil.which("ollama")),
        env_file_exists=(root / ".env").exists(),
        config_file_exists=(root / "config.json").exists(),
        detected_keys=detected,
    )


def _read_env(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _write_env(env_path: Path, data: dict[str, str]) -> None:
    lines = [
        "# AetheerAI configuration — generated by setup_wizard.py\n",
        f"# Created: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "#\n",
        "# DO NOT commit this file to source control.\n\n",
    ]
    for key, val in sorted(data.items()):
        lines.append(f"{key}={val}\n")
    env_path.write_text("".join(lines), encoding="utf-8")


# ── AI provider catalogue ─────────────────────────────────────────────────────

_PROVIDERS = [
    # (id,       label,                           env_key,             default_model)
    ("github",  "GitHub Models  (free, needs GitHub PAT)",   "GITHUB_TOKEN",      "gpt-4.1"),
    ("openai",  "OpenAI  (GPT-4o)",                           "OPENAI_API_KEY",    "gpt-4o"),
    ("gemini",  "Google Gemini  (Gemini 1.5 Flash)",          "GEMINI_API_KEY",    "gemini-1.5-flash"),
    ("claude",  "Anthropic Claude  (Claude Sonnet)",          "ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
    ("ollama",  "Ollama  (100% local, no key needed)",        None,                "qwen2.5-coder:7b"),
]

# ── Deployment mode catalogue ─────────────────────────────────────────────────

_DEPLOY_MODES = [
    ("local",    "Run locally on this machine  (simplest)"),
    ("docker",   "Run in Docker container  (recommended for production)"),
    ("cloud",    "Deploy to Vercel / cloud  (needs Vercel CLI)"),
]

# ── Integration prompt catalogue ─────────────────────────────────────────────

_INTEGRATION_PROMPTS: dict[str, list[dict[str, str]]] = {
    "website":   [{"key": "WEBSITE_URL",           "label": "Your website URL",           "secret": "no"},
                  {"key": "WEBSITE_API_KEY",        "label": "Website API key",            "secret": "yes"}],
    "api":       [{"key": "API_BASE_URL",           "label": "API base URL",               "secret": "no"},
                  {"key": "API_KEY",                "label": "API key / bearer token",     "secret": "yes"}],
    "crm":       [{"key": "CRM_BASE_URL",           "label": "CRM base URL",               "secret": "no"},
                  {"key": "CRM_API_KEY",            "label": "CRM API key",                "secret": "yes"}],
    "email":     [{"key": "EMAIL_HOST",             "label": "SMTP host (e.g. smtp.gmail.com)", "secret": "no"},
                  {"key": "EMAIL_PORT",             "label": "SMTP port",    "default": "587", "secret": "no"},
                  {"key": "EMAIL_USER",             "label": "Email address",               "secret": "no"},
                  {"key": "EMAIL_PASSWORD",         "label": "Email password / app password", "secret": "yes"}],
    "slack":     [{"key": "SLACK_BOT_TOKEN",        "label": "Slack bot token (xoxb-…)",   "secret": "yes"},
                  {"key": "SLACK_CHANNEL",          "label": "Default channel (#general)", "secret": "no"}],
    "database":  [{"key": "DATABASE_URL",           "label": "Database URL (postgres://…)", "secret": "yes"}],
    "ecommerce": [{"key": "ECOMMERCE_STORE_URL",    "label": "Store URL",                  "secret": "no"},
                  {"key": "ECOMMERCE_API_KEY",      "label": "Store API key",              "secret": "yes"}],
    "devops":    [{"key": "GITHUB_TOKEN",           "label": "GitHub personal access token", "secret": "yes"}],
    "analytics": [{"key": "ANALYTICS_API_KEY",      "label": "Analytics API key",          "secret": "yes"}],
}

# ── Launcher generation ───────────────────────────────────────────────────────

def _generate_launcher(root: Path, deploy_mode: str, agent_name: str) -> None:
    """Generate a platform-appropriate one-click launcher file."""
    py = sys.executable

    if _WIN:
        bat = root / "Start_Agent.bat"
        bat.write_text(
            f"@echo off\n"
            f"title {agent_name}\n"
            f"echo Starting {agent_name}...\n"
            f'"{py}" run_agent.py\n'
            f"pause\n",
            encoding="utf-8",
        )
        _ok(f"Launcher created: {bat.name}")

    sh = root / "start_agent.sh"
    sh.write_text(
        f"#!/usr/bin/env bash\n"
        f'# One-click launcher for {agent_name}\n'
        f'exec "{py}" run_agent.py "$@"\n',
        encoding="utf-8",
    )
    try:
        sh.chmod(0o755)
    except Exception:
        pass
    _ok(f"Launcher created: {sh.name}")

    if deploy_mode == "docker":
        compose = root / "docker-compose.agent.yml"
        if not compose.exists():
            compose.write_text(
                f"version: '3.9'\nservices:\n  agent:\n"
                f"    build: .\n    env_file: .env\n"
                f"    restart: unless-stopped\n",
                encoding="utf-8",
            )
            _ok(f"Docker Compose file created: {compose.name}")


# ── Health check ──────────────────────────────────────────────────────────────

def _health_check(env: dict[str, str]) -> list[str]:
    """Return list of warning strings; empty list means all OK."""
    warnings: list[str] = []
    provider = env.get("AETHEERAI_DEFAULT_PROVIDER", "")
    if not provider:
        warnings.append("No AI provider selected.")
        return warnings
    key_map = {
        "github":  "GITHUB_TOKEN",
        "openai":  "OPENAI_API_KEY",
        "gemini":  "GEMINI_API_KEY",
        "claude":  "ANTHROPIC_API_KEY",
    }
    required_key = key_map.get(provider)
    if required_key and not env.get(required_key):
        warnings.append(f"Missing API key: {required_key} required for provider '{provider}'.")
    if not env.get("AETHEERAI_DEFAULT_MODEL"):
        warnings.append("No default model set (AETHEERAI_DEFAULT_MODEL).")
    return warnings


# ── Main wizard class ─────────────────────────────────────────────────────────

class SetupWizard:
    """
    Guided non-developer deployment wizard.

    Steps
    -----
    1. Welcome & system scan
    2. Choose AI provider
    3. Configure integrations
    4. Choose deployment mode
    5. Generate launchers & validate
    6. Summary
    """

    TOTAL_STEPS = 6

    def __init__(
        self,
        root: Path | str | None = None,
        quiet: bool = False,
    ) -> None:
        self.root = Path(root) if root else Path(os.path.dirname(
            os.path.abspath(__file__))).parent
        self.quiet = quiet
        self.env: dict[str, str] = {}
        self.config: dict[str, Any] = {}
        self.sysinfo: SystemInfo | None = None
        self._deploy_mode: str = "local"

    # ── Public entry ──────────────────────────────────────────────────────────

    def run(self) -> dict[str, str]:
        """Execute the full wizard and return the written env dict."""
        self._welcome()
        self._step1_system_scan()
        self._step2_ai_provider()
        self._step3_integrations()
        self._step4_deploy_mode()
        self._step5_validate_and_save()
        self._step6_summary()
        return self.env

    # ── Steps ─────────────────────────────────────────────────────────────────

    def _welcome(self) -> None:
        agent_name = self.config.get("name", "AetheerAI")
        print()
        print(_c("  ╔══════════════════════════════════════════╗", _CYAN))
        print(_c(f"  ║   {agent_name:<40}║", _CYAN))
        print(_c("  ║   Guided Setup Wizard                    ║", _CYAN))
        print(_c("  ╚══════════════════════════════════════════╝", _CYAN))
        print()
        print("  This wizard will get you up and running in a few minutes.")
        print("  No command-line experience required.\n")

    def _step1_system_scan(self) -> None:
        _header("System Scan", 1, self.TOTAL_STEPS)

        config_path = self.root / "config.json"
        env_path    = self.root / ".env"

        def _scan():
            cfg = {}
            if config_path.exists():
                try:
                    cfg = json.loads(config_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            self.config = cfg
            self.env = _read_env(env_path)
            self.sysinfo = _detect_system(self.root)

        _spinner("Scanning your system", _scan)

        si = self.sysinfo
        _ok(f"Python {si.python_version}")
        _ok("Git installed") if si.has_git else _warn("Git not found (optional)")
        _ok("Docker installed") if si.has_docker else _info("Docker not found (optional)")
        _ok("Ollama available") if si.has_ollama else _info("Ollama not installed (optional)")

        if si.env_file_exists:
            _ok(".env file found — existing values will be preserved")
        if si.config_file_exists:
            name = self.config.get("name", "unnamed")
            _ok(f"Agent config loaded: {name}")

    def _step2_ai_provider(self) -> None:
        _header("AI Provider", 2, self.TOTAL_STEPS)

        # Auto-detect existing keys
        already_set = []
        for pid, label, env_key, _ in _PROVIDERS:
            if env_key and (self.env.get(env_key) or os.environ.get(env_key or "")):
                already_set.append(pid)

        if already_set:
            _info(f"Detected existing keys for: {', '.join(already_set)}")

        print("  Which AI provider would you like to use?\n")
        options = [(pid, label) for pid, label, _, _ in _PROVIDERS]
        default_idx = next(
            (i for i, (pid, _) in enumerate(options) if pid in already_set), 0)
        idx = _ask_choice("Enter your choice", options, default=default_idx + 1)

        pid, _, env_key, default_model = _PROVIDERS[idx]
        model = _ask("  Model name", default=self.env.get("AETHEERAI_DEFAULT_MODEL", default_model))

        self.env["AETHEERAI_DEFAULT_PROVIDER"] = pid
        self.env["AETHEERAI_DEFAULT_MODEL"] = model

        if env_key:
            existing = self.env.get(env_key) or os.environ.get(env_key) or ""
            if existing:
                _info(f"{env_key} already set; press Enter to keep it.")
            key_val = _ask(
                f"  {env_key}",
                default="(keep)" if existing else "",
                secret=True,
            )
            if key_val and key_val != "(keep)":
                self.env[env_key] = key_val
            elif existing and (not key_val or key_val == "(keep)"):
                self.env[env_key] = existing

        _ok(f"Provider: {pid}  |  Model: {model}")

    def _step3_integrations(self) -> None:
        integrations: list[str] = self.config.get("integrations", [])
        if not integrations:
            return  # nothing to configure

        _header("Integrations", 3, self.TOTAL_STEPS)
        print(f"  This agent uses: {_c(', '.join(integrations), _BOLD)}\n")
        print("  Enter credentials for each service.\n")
        print("  (Press Enter to skip optional fields.)\n")

        for intg in integrations:
            prompts = _INTEGRATION_PROMPTS.get(intg.lower(), [
                {"key": f"{intg.upper()}_API_KEY",
                 "label": f"{intg.title()} API key", "secret": "yes"},
            ])
            print(f"  {_c(f'── {intg.upper()} ──', _BOLD)}")
            for p in prompts:
                key       = p["key"]
                label     = p["label"]
                is_secret = str(p.get("secret", "no")).lower() in ("yes", "true", "1")
                default   = p.get("default", self.env.get(key, ""))
                value = _ask(label, default=default, secret=is_secret)
                if value:
                    self.env[key] = value
            print()

    def _step4_deploy_mode(self) -> None:
        _header("Deployment Mode", 4, self.TOTAL_STEPS)
        print("  How do you want to run your agent?\n")

        si = self.sysinfo
        options = []
        for mode_id, desc in _DEPLOY_MODES:
            if mode_id == "docker" and not si.has_docker:
                options.append((mode_id, f"{desc}  {_c('[Docker not installed]', _DIM)}"))
            else:
                options.append((mode_id, desc))

        idx = _ask_choice("Choose deployment mode", options, default=1)
        self._deploy_mode = _DEPLOY_MODES[idx][0]
        _ok(f"Mode: {self._deploy_mode}")

    def _step5_validate_and_save(self) -> None:
        _header("Validation & Save", 5, self.TOTAL_STEPS)

        # Write .env
        env_path = self.root / ".env"
        _writer_fn = lambda: _write_env(env_path, self.env)
        _spinner("Saving configuration", _writer_fn)
        _ok(f"Saved to: {env_path}")

        # Generate launchers
        _generate_launcher(
            self.root,
            self._deploy_mode,
            self.config.get("name", "AetheerAI"),
        )

        # Health check
        warnings = _health_check(self.env)
        if warnings:
            print()
            for w in warnings:
                _warn(w)
        else:
            _ok("Configuration looks good!")

    def _step6_summary(self) -> None:
        _header("Setup Complete", 6, self.TOTAL_STEPS)
        agent_name = self.config.get("name", "AetheerAI")
        provider   = self.env.get("AETHEERAI_DEFAULT_PROVIDER", "—")
        model      = self.env.get("AETHEERAI_DEFAULT_MODEL", "—")

        print(f"  {_c('All done!', _GREEN+_BOLD)}  Your agent is ready to run.\n")
        print(f"  Agent   : {_c(agent_name, _BOLD)}")
        print(f"  Provider: {provider}  |  Model: {model}")

        _sep()
        if self._deploy_mode == "local":
            if _WIN:
                print(f"  {_c('To start:', _BOLD)}  double-click  Start_Agent.bat")
            else:
                print(f"  {_c('To start:', _BOLD)}  ./start_agent.sh")
        elif self._deploy_mode == "docker":
            print(f"  {_c('To start:', _BOLD)}  docker compose -f docker-compose.agent.yml up")
        else:
            print(f"  {_c('To deploy:', _BOLD)}  vercel deploy")
        _sep()
        print()


# ── CLI entry ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AetheerAI — Guided non-developer setup wizard"
    )
    parser.add_argument(
        "--root", default=None,
        help="Path to agent root directory (default: auto-detect)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Skip optional prompts; use smart defaults",
    )
    args = parser.parse_args()

    wizard = SetupWizard(root=args.root, quiet=args.quiet)
    wizard.run()


if __name__ == "__main__":
    main()
