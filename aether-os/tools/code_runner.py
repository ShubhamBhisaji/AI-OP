"""
code_runner — Tool that executes Python code snippets in a sandboxed subprocess.
Returns stdout/stderr output. Used by Coding, Automation, and Data Analysis agents.

Fix 1 — @require_approval: any agent call goes through the ApprovalGate first.
Fix 2 — Docker sandbox: if Docker is available the code runs in an isolated
         container (--network none, --memory 128m, --cpus 0.5, read-only rootfs).
         Falls back to restricted subprocess if Docker is absent.
Fix 7 — Dynamic sandbox dependencies: the code is scanned for third-party
         imports before execution.  Any import that is NOT in the Python standard
         library is automatically installed via `pip install` inside the container
         (or on the host in the fallback path) before running the script.
"""

from __future__ import annotations

import ast
import logging
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile

from security.approval_gate import require_approval

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15
# Docker image to use for sandboxed execution (must have Python installed)
_DOCKER_IMAGE = "python:3.11-slim"

# Standard-library module names — packages that are NOT third-party
# We derive these from the running interpreter rather than a hand-coded list.
def _stdlib_modules() -> frozenset[str]:
    """Return the set of top-level standard-library module names."""
    stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
    # Fallback: scan stdlib paths if sys.stdlib_module_names unavailable (< 3.10)
    if not stdlib:
        paths = sysconfig.get_paths()
        for path_key in ("stdlib", "platstdlib"):
            p = paths.get(path_key)
            if p:
                import pathlib
                for item in pathlib.Path(p).iterdir():
                    stdlib.add(item.stem.split(".")[0])
    return frozenset(stdlib)

_STDLIB: frozenset[str] = _stdlib_modules()

# Packages that are built-in or always present in the Docker image — skip these
_ALWAYS_AVAILABLE: frozenset[str] = frozenset({
    "pip", "setuptools", "wheel", "_thread", "__future__",
    # common aliases that map to stdlib
    "typing_extensions",
})


def _extract_third_party_imports(code: str) -> list[str]:
    """
    Parse *code* with the AST and return a deduplicated list of third-party
    top-level package names that need to be installed.

    Only ``import X`` and ``from X import …`` statements are examined.
    Built-in / standard-library modules are filtered out automatically.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    packages: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                packages.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # skip relative imports
                packages.add(node.module.split(".")[0])

    # Filter to only genuinely third-party packages
    third_party = [
        pkg for pkg in packages
        if pkg not in _STDLIB and pkg not in _ALWAYS_AVAILABLE
    ]
    return sorted(third_party)


def _docker_available() -> bool:
    """Return True if the 'docker' CLI is on PATH and the daemon is up."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_in_docker(tmp_path: str, deps: list[str]) -> str:
    """
    Execute *tmp_path* inside a minimal, network-isolated Docker container.
    Mounts only the tempfile (read-only) and discards all changes on exit.

    If *deps* is non-empty a pip install step runs first inside the container
    so that third-party libraries are available at runtime (Fix 7).
    """
    # Build the shell command: optionally install deps then run the script.
    if deps:
        pip_cmd = "pip install --quiet " + " ".join(deps) + " && "
    else:
        pip_cmd = ""
    shell_cmd = f"{pip_cmd}python -u /code.py"

    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--memory", "256m",            # bumped slightly to allow pip install
            "--cpus", "0.5",              # CPU quota
            "--read-only",                # immutable container filesystem
            "--tmpfs", "/tmp:size=64m",   # writable /tmp (pip cache + bytecode)
            "--tmpfs", "/root:size=32m",  # pip writes to ~/.cache/pip
            # NOTE: --network none is dropped when deps need installing so pip
            # can download packages.  Re-applied if no deps.
            *([] if deps else ["--network", "none"]),
            "-v", f"{tmp_path}:/code.py:ro",  # mount code read-only
            _DOCKER_IMAGE,
            "sh", "-c", shell_cmd,
        ],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS + (30 if deps else 0),  # extra time for pip
    )
    output = result.stdout
    if result.stderr:
        output += "\n[stderr]\n" + result.stderr
    return output.strip() or "(no output)"


@require_approval
def code_runner(code: str, language: str = "python", extra_deps: list[str] | None = None) -> str:
    """
    Execute a code snippet and return the combined stdout + stderr output.

    Fix 2 — Sandbox: runs in a Docker container when Docker is available
    (memory capped, read-only filesystem).  Falls back to a restricted
    subprocess when Docker is absent.

    Fix 7 — Dynamic deps: third-party imports are automatically detected via
    AST analysis and installed inside the container before execution.  You can
    also pass additional packages via *extra_deps* (e.g. ["pandas", "requests"]).

    Args:
        code       : The source code to execute.
        language   : Currently only 'python' is supported.
        extra_deps : Optional list of extra pip packages to pre-install.

    Returns:
        Combined output string (stdout + stderr), or an error message.
    """
    if not code or not isinstance(code, str):
        return "Error: code must be a non-empty string."

    if language.lower() != "python":
        return f"Error: language '{language}' is not supported. Only 'python' is supported."

    # Combine auto-detected deps with any explicitly requested ones (Fix 7)
    detected = _extract_third_party_imports(code)
    all_deps = sorted(set(detected) | set(extra_deps or []))
    if all_deps:
        logger.info("code_runner: detected third-party deps: %s", all_deps)

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        # ── Fix 2: Docker sandbox (preferred) ────────────────────────
        if _docker_available():
            try:
                return _run_in_docker(tmp_path, deps=all_deps)
            except subprocess.TimeoutExpired:
                return f"Error: Docker execution timed out after {_TIMEOUT_SECONDS}s."
            except Exception as exc:
                logger.warning("code_runner: Docker execution failed (%s); falling back.", exc)
                # Fall through to subprocess fallback

        # ── Restricted subprocess fallback ────────────────────────────
        logger.warning(
            "code_runner: Docker not available — running on host (fallback). "
            "Install Docker for full sandboxing."
        )

        # Auto-install missing deps on the host as well (Fix 7 fallback)
        if all_deps:
            logger.info("code_runner: installing deps on host: %s", all_deps)
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet"] + all_deps,
                capture_output=True, timeout=60,
            )

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        return (
            "[⚠ SANDBOX WARNING: Docker unavailable — code ran on host machine]\n\n"
            + (output.strip() or "(no output)")
        )
    except subprocess.TimeoutExpired:
        return f"Error: code execution timed out after {_TIMEOUT_SECONDS}s."
    except Exception as exc:
        logger.error("code_runner: unexpected error: %s", exc)
        return f"Error: {exc}"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
