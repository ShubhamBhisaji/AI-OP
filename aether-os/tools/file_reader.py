"""file_reader — Read, inspect, and navigate text files safely."""
from __future__ import annotations
import os, logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories the tool will refuse to escape above
_DANGEROUS_SEGMENTS = {"windows", "system32", "syswow64", "program files"}

def file_reader(path: str, action: str = "read", lines: str = "") -> str:
    """
    Read or inspect a file.

    path   : Absolute or relative path to the file.
    action : read | head | tail | line | exists | info
    lines  : For 'head'/'tail' → number of lines (default 20).
             For 'line' → comma-separated line numbers (e.g. "3,7,10").

    Actions:
        read   : Full file content (max 500 lines, warns if truncated).
        head   : First N lines.
        tail   : Last N lines.
        line   : Specific line number(s).
        exists : True/False.
        info   : Size, line count, encoding hint.
    """
    if not path or not isinstance(path, str):
        return "Error: 'path' must be a non-empty string."

    action = (action or "read").strip().lower()
    p = Path(path.strip())

    # Basic safety check — reject paths that try to navigate dangerous system dirs
    lower_parts = [seg.lower() for seg in p.parts]
    if any(seg in _DANGEROUS_SEGMENTS for seg in lower_parts):
        return "Error: Access to system directories is not allowed."

    if action == "exists":
        return str(p.exists())

    if not p.exists():
        return f"Error: File not found — {p}"
    if not p.is_file():
        return f"Error: Path is not a file — {p}"

    if action == "info":
        size = p.stat().st_size
        try:
            with p.open("r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            enc = "utf-8"
        except UnicodeDecodeError:
            enc = "binary (non-utf-8)"
            line_count = "N/A"
        return (
            f"File  : {p.name}\n"
            f"Path  : {p}\n"
            f"Size  : {_human_size(size)}\n"
            f"Lines : {line_count}\n"
            f"Enc   : {enc}"
        )

    # Read lines
    try:
        content = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"Error reading file: {e}"

    n_lines = _parse_int(lines, default=20)

    if action == "read":
        LIMIT = 500
        if len(content) > LIMIT:
            result = "\n".join(content[:LIMIT])
            return result + f"\n\n[Truncated — showing {LIMIT}/{len(content)} lines]"
        return "\n".join(content) if content else "(empty file)"

    if action == "head":
        return "\n".join(content[:n_lines]) or "(empty file)"

    if action == "tail":
        return "\n".join(content[-n_lines:]) or "(empty file)"

    if action == "line":
        if not lines.strip():
            return "Error: specify line number(s) in the 'lines' parameter."
        try:
            nums = [int(x.strip()) for x in lines.split(",")]
        except ValueError:
            return "Error: 'lines' must be comma-separated integers."
        results = []
        for num in nums:
            if 1 <= num <= len(content):
                results.append(f"Line {num}: {content[num - 1]}")
            else:
                results.append(f"Line {num}: [out of range — file has {len(content)} lines]")
        return "\n".join(results)

    return f"Unknown action '{action}'. Use: read, head, tail, line, exists, info."

def _parse_int(value: str, default: int) -> int:
    try:
        v = int(str(value).strip())
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default

def _human_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
