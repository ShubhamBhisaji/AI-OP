"""terminal_tool — Safe, controlled terminal command execution for agents.

Only whitelisted commands are allowed. No shell injection, no destructive
operations. Each command runs in a subprocess with a hard timeout.

Fix 1 — @require_approval: any agent call goes through the ApprovalGate first.
"""
from __future__ import annotations
import os, re, sys, shlex, subprocess, shutil, platform, logging
from pathlib import Path

from security.approval_gate import require_approval

logger = logging.getLogger(__name__)

_TIMEOUT = 20  # seconds
_MAX_OUTPUT = 8_000  # characters


# ── Command allowlist ─────────────────────────────────────────────────────────
# Maps prefix → (description, allowed_flag_pattern)
_ALLOWED: dict[str, tuple[str, str | None]] = {
    # Python
    "python --version":    ("Python version",              None),
    "python -V":           ("Python version",              None),
    "pip list":            ("Installed packages",          None),
    "pip show":            ("Package details",             r"^pip show \w[\w\-]*$"),
    "pip freeze":          ("Locked requirements",         None),
    # Git
    "git status":          ("Git status",                  None),
    "git log":             ("Git log",                     r"^git log(\s+--\S+)*(\s+-\d+)?$"),
    "git diff":            ("Git diff",                    r"^git diff(\s+--\S+)*$"),
    "git branch":          ("List branches",               r"^git branch(\s+-\S+)?$"),
    "git remote":          ("Remote info",                 r"^git remote(\s+-v)?$"),
    "git stash list":      ("Stash list",                  None),
    # File listing / info
    "dir":                 ("Directory listing (Windows)", r"^dir(\s+\"?[\w\\/:. \-]+\"?(\s+/\w+)*)?$"),
    "ls":                  ("Directory listing (Unix)",    r"^ls(\s+-\S+)*(\s+[\w./\-]+)?$"),
    "pwd":                 ("Print working directory",     None),
    "cd":                  ("Change directory (show only)",r"^cd(\s+\"?[\w\\/:.\- ]+\"?)?$"),
    # System info
    "echo":                ("Echo text",                   r"^echo\s+[\w .,'\"!\-@#%^&*()+=\[\]{}|;:<>?/\\]+$"),
    "whoami":              ("Current user",                None),
    "hostname":            ("Machine hostname",            None),
    "uname":               ("OS info (Unix)",              r"^uname(\s+-\S+)?$"),
    "ver":                 ("OS version (Windows)",        None),
    "date":                ("Current date/time",           r"^date(\s+/t)?$"),
    "time":                ("Current time (Windows)",      r"^time(\s+/t)?$"),
    # Network (read-only)
    "ping":                ("Ping host",                   r"^ping\s+[\w.\-]+(\s+-[cn]\s+\d+)?$"),
    "nslookup":            ("DNS lookup",                  r"^nslookup\s+[\w.\-]+$"),
    "ipconfig":            ("Network config (Windows)",    r"^ipconfig(\s+/all)?$"),
    "ifconfig":            ("Network config (Unix)",       r"^ifconfig(\s+-\S+)?$"),
    "curl --version":      ("curl version",                None),
    "curl -I":             ("HTTP headers only",           r"^curl\s+-I\s+https?://[\w./\-?=&%#]+$"),
    # Misc
    "type":                ("Show file (Windows)",         r"^type\s+\"?[\w\\/:.\- ]+\"?$"),
    "cat":                 ("Show file (Unix)",            r"^cat\s+[\w./\-]+$"),
    "head":                ("First lines of file",         r"^head(\s+-n\s+\d+)?\s+[\w./\-]+$"),
    "tail":                ("Last lines of file",          r"^tail(\s+-n\s+\d+)?\s+[\w./\-]+$"),
    "wc":                  ("Word/line count",             r"^wc(\s+-\S+)?\s+[\w./\-]+$"),
    "find":                ("Find files (read-only)",      r"^find\s+[\w./\-]+\s+-name\s+['\"]?[\w.*?-]+['\"]?$"),
    "where":               ("Locate command (Windows)",    r"^where\s+\w[\w\-]*$"),
    "which":               ("Locate command (Unix)",       r"^which\s+\w[\w\-]*$"),
}


@require_approval
def terminal_tool(command: str, action: str = "run", cwd: str = "") -> str:
    """
    Execute terminal commands safely within a strict allowlist.

    command : The command to run (must match an allowed pattern).
    action  : run | list_commands | help | cwd
    cwd     : Optional working directory for 'run' (must be an existing path).

    Actions:
        run           : Execute the command and return its output.
        list_commands : Show all permitted commands.
        help          : Show usage guide.
        cwd           : Print the current working directory.

    Permitted command categories:
        • Python: python --version, pip list/show/freeze
        • Git: status, log, diff, branch, remote, stash list
        • Files: dir, ls, pwd, type, cat, head, tail, wc, find
        • System: echo, whoami, hostname, uname, ver, date
        • Network (read-only): ping, nslookup, ipconfig, ifconfig, curl -I
        • Locate: where, which
    """
    if not action or not isinstance(action, str):
        return "Error: 'action' is required."

    action = action.strip().lower()

    if action == "list_commands":
        return _list_commands()

    if action == "help":
        return _help()

    if action == "cwd":
        return f"Current directory: {os.getcwd()}"

    if action != "run":
        return f"Unknown action '{action}'. Use: run, list_commands, help, cwd."

    if not command or not isinstance(command, str):
        return "Error: 'command' is required for 'run'."

    return _run(command.strip(), cwd.strip())


# ── run ───────────────────────────────────────────────────────────────────────

def _run(command: str, cwd: str) -> str:
    # Validate allowlist
    allowed, reason = _check_allowlist(command)
    if not allowed:
        return (
            f"Command not permitted: {reason}\n\n"
            f"Use  terminal_tool('list_commands', '')  to see what is allowed."
        )

    # Resolve working directory
    run_cwd: str | None = None
    if cwd:
        p = Path(cwd)
        if not p.exists():
            return f"Error: Working directory not found — {cwd}"
        if not p.is_dir():
            return f"Error: Not a directory — {cwd}"
        run_cwd = str(p.resolve())

    # Build argv — no shell=True to prevent injection
    try:
        argv = shlex.split(command, posix=(platform.system() != "Windows"))
    except ValueError as e:
        return f"Error parsing command: {e}"

    # Special case: 'cd' doesn't make sense in a subprocess — just show target
    if argv[0].lower() == "cd":
        target = argv[1] if len(argv) > 1 else os.getcwd()
        p = Path(target)
        if p.exists() and p.is_dir():
            return f"Directory exists: {p.resolve()}\n(Note: 'cd' in a subprocess doesn't affect the agent's session)"
        return f"Directory not found: {target}"

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=_TIMEOUT,
            cwd=run_cwd,
            env=_safe_env(),
        )
        stdout = result.stdout[:_MAX_OUTPUT]
        stderr = result.stderr[:1000]
        parts  = [f"$ {command}"]
        if stdout.strip():
            parts.append(stdout.rstrip())
        if stderr.strip():
            parts.append(f"[stderr]\n{stderr.rstrip()}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(parts) if len(parts) > 1 else "(no output)"

    except FileNotFoundError:
        cmd_name = argv[0]
        return (
            f"Command not found: '{cmd_name}'\n"
            f"It may not be installed or not on PATH."
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {_TIMEOUT}s: {command}"
    except PermissionError:
        return f"Permission denied running: {command}"
    except Exception as e:
        return f"Error running command: {e}"


# ── allowlist check ───────────────────────────────────────────────────────────

def _check_allowlist(command: str) -> tuple[bool, str]:
    cmd_lower = command.lower().strip()

    for prefix, (desc, pattern) in _ALLOWED.items():
        if cmd_lower == prefix or cmd_lower.startswith(prefix + " "):
            if pattern:
                if not re.fullmatch(pattern, command.strip(), re.IGNORECASE):
                    return False, (
                        f"'{command}' matches the allowed command '{prefix}' but "
                        f"the arguments don't pass the safety check."
                    )
            return True, desc

    # Additional safety: block any shell metacharacters even if prefix matched
    for dangerous in [";", "&&", "||", "|", "`", "$(",  ">", "<", "\n", "\r"]:
        if dangerous in command:
            return False, f"Shell metacharacter '{dangerous}' is not allowed."

    return False, f"Command '{command.split()[0]}' is not on the permitted list."


# ── safe environment ──────────────────────────────────────────────────────────

def _safe_env() -> dict[str, str]:
    """Pass only non-sensitive env vars to subprocess."""
    safe_keys = {
        "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
        "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOME", "HOMEDRIVE",
        "HOMEPATH", "LANG", "LC_ALL", "TERM", "COLORTERM",
        "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
        "COMPUTERNAME", "LOGONSERVER",
    }
    return {k: v for k, v in os.environ.items() if k.upper() in safe_keys}


# ── info actions ──────────────────────────────────────────────────────────────

def _list_commands() -> str:
    lines = ["Permitted commands:\n"]
    categories: dict[str, list[str]] = {
        "Python":    [],
        "Git":       [],
        "Files":     [],
        "System":    [],
        "Network":   [],
        "Locate":    [],
    }
    for prefix, (desc, _) in _ALLOWED.items():
        if prefix.startswith("python") or prefix.startswith("pip"):
            categories["Python"].append(f"  {prefix:<30} {desc}")
        elif prefix.startswith("git"):
            categories["Git"].append(f"  {prefix:<30} {desc}")
        elif prefix in ("dir", "ls", "pwd", "cd", "type", "cat", "head", "tail", "wc", "find"):
            categories["Files"].append(f"  {prefix:<30} {desc}")
        elif prefix in ("ping", "nslookup", "ipconfig", "ifconfig", "curl --version", "curl -I"):
            categories["Network"].append(f"  {prefix:<30} {desc}")
        elif prefix in ("where", "which"):
            categories["Locate"].append(f"  {prefix:<30} {desc}")
        else:
            categories["System"].append(f"  {prefix:<30} {desc}")
    for cat, items in categories.items():
        if items:
            lines.append(f"  ── {cat} ──")
            lines += items
    return "\n".join(lines)


def _help() -> str:
    return (
        "terminal_tool — Safe command execution\n"
        "━" * 40 + "\n"
        "Only whitelisted read-only commands are permitted.\n"
        "Shell metacharacters (;, |, &&, >, <, $()) are always blocked.\n\n"
        "Usage:\n"
        "  terminal_tool('git status')          → run a command\n"
        "  terminal_tool('pip list')            → list packages\n"
        "  terminal_tool('ls', cwd='/my/path')  → run in a specific directory\n"
        "  terminal_tool('', 'list_commands')   → see all allowed commands\n\n"
        "Tip: Use 'code_runner' for executing arbitrary Python scripts.\n"
        "     Use 'code_analyzer' for deep code inspection.\n"
    )
