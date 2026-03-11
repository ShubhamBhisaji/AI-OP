"""
code_runner — Tool that executes Python code snippets in a sandboxed subprocess.
Returns stdout/stderr output. Used by Coding, Automation, and Data Analysis agents.

Fix 1 — @require_approval: any agent call goes through the ApprovalGate first.
Fix 2 — Docker sandbox: if Docker is available the code runs in an isolated
         container (--network none, --memory 128m, --cpus 0.5, read-only rootfs).
         Falls back to restricted subprocess if Docker is absent.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile

from security.approval_gate import require_approval

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15
# Docker image to use for sandboxed execution (must have Python installed)
_DOCKER_IMAGE = "python:3.11-slim"


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


def _run_in_docker(tmp_path: str) -> str:
    """
    Execute *tmp_path* inside a minimal, network-isolated Docker container.
    Mounts only the tempfile (read-only) and discards all changes on exit.
    """
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network", "none",          # no outbound network
            "--memory", "128m",            # hard memory cap
            "--cpus", "0.5",              # CPU quota
            "--read-only",                # immutable container filesystem
            "--tmpfs", "/tmp:size=32m",   # writable /tmp only (for Python bytecode)
            "-v", f"{tmp_path}:/code.py:ro",  # mount code read-only
            _DOCKER_IMAGE,
            "python", "-u", "/code.py",
        ],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    output = result.stdout
    if result.stderr:
        output += "\n[stderr]\n" + result.stderr
    return output.strip() or "(no output)"


@require_approval
def code_runner(code: str, language: str = "python") -> str:
    """
    Execute a code snippet and return the combined stdout + stderr output.

    Fix 2 — Sandbox: runs in a Docker container when Docker is available
    (network disabled, memory capped, read-only filesystem).  Falls back to
    a restricted subprocess when Docker is absent; a sandbox warning is
    prepended to the output in that case.

    Args:
        code     : The source code to execute.
        language : Currently only 'python' is supported.

    Returns:
        Combined output string (stdout + stderr), or an error message.
    """
    if not code or not isinstance(code, str):
        return "Error: code must be a non-empty string."

    if language.lower() != "python":
        return f"Error: language '{language}' is not supported. Only 'python' is supported."

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
                return _run_in_docker(tmp_path)
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
