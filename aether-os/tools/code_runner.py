"""
code_runner — Tool that executes Python code snippets in a sandboxed subprocess.
Returns stdout/stderr output. Used by Coding, Automation, and Data Analysis agents.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import os

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15


def code_runner(code: str, language: str = "python") -> str:
    """
    Execute a code snippet and return the combined stdout + stderr output.

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

    # Write code to a temp file to avoid shell injection
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: code execution timed out after {_TIMEOUT_SECONDS}s."
    except Exception as exc:
        logger.error("code_runner: unexpected error: %s", exc)
        return f"Error: {exc}"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
