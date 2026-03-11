"""
file_writer — Tool that writes text content to a file on disk.
Agents use this to save generated code, reports, or any text output.

Fix 1 — @require_approval: any agent write goes through the ApprovalGate first.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from security.approval_gate import require_approval

logger = logging.getLogger(__name__)

# All agent-generated files are written under this directory by default
_OUTPUT_DIR = Path(__file__).parent.parent / "agent_output"


@require_approval
def file_writer(filename: str, content: str, output_dir: str | None = None) -> str:
    """
    Write `content` to a file named `filename`.

    Args:
        filename   : Name (or relative path) of the file to write.
        content    : The text content to write.
        output_dir : Optional override for the output directory.
                     Defaults to `aether-os/agent_output/`.

    Returns:
        A string confirming the file path that was written, or an error message.
    """
    if not filename or not isinstance(filename, str):
        return "Error: filename must be a non-empty string."

    # Sanitize: reject absolute paths and path traversal attempts
    clean_name = os.path.normpath(filename)
    if os.path.isabs(clean_name) or clean_name.startswith(".."):
        return f"Error: invalid filename '{filename}'. Must be a relative path."

    base = Path(output_dir) if output_dir else _OUTPUT_DIR
    target = base / clean_name

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info("file_writer: wrote %d chars to '%s'.", len(content), target)
        return f"File written successfully: {target}"
    except OSError as exc:
        logger.error("file_writer: failed to write '%s': %s", target, exc)
        return f"Error writing file: {exc}"
