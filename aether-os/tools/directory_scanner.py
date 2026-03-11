"""directory_scanner — List, search, and measure directory contents."""
from __future__ import annotations
import os, fnmatch, logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DANGEROUS_SEGMENTS = {"windows", "system32", "syswow64", "program files"}


def directory_scanner(path: str = ".", action: str = "list", pattern: str = "") -> str:
    """
    Explore a directory.

    path    : Directory path (default: current working directory).
    action  : list | tree | find | size
    pattern : Glob pattern for 'find' (e.g. "*.py", "*.txt").

    Actions:
        list : Direct children with type (file/dir) and size.
        tree : Recursive tree view (max depth 4, max 200 entries).
        find : Search for files matching the glob pattern.
        size : Total size of directory contents.
    """
    if not path or not isinstance(path, str):
        path = "."

    action  = (action  or "list").strip().lower()
    pattern = (pattern or "").strip()
    p = Path(path.strip()).resolve()

    lower_parts = [seg.lower() for seg in p.parts]
    if any(seg in _DANGEROUS_SEGMENTS for seg in lower_parts):
        return "Error: Access to system directories is not allowed."

    if not p.exists():
        return f"Error: Path not found — {p}"
    if not p.is_dir():
        return f"Error: Path is not a directory — {p}"

    if action == "list":
        lines = []
        try:
            entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            return "Error: Permission denied."
        for entry in entries:
            kind = "DIR " if entry.is_dir() else "FILE"
            size = ""
            if entry.is_file():
                try:
                    size = f"  ({_human_size(entry.stat().st_size)})"
                except OSError:
                    size = ""
            lines.append(f"[{kind}] {entry.name}{size}")
        return f"Directory: {p}\n" + ("\n".join(lines) if lines else "(empty)")

    if action == "tree":
        lines = [f"{p}"]
        _tree_recurse(p, "", lines, depth=0, max_depth=4, counter=[0], limit=200)
        return "\n".join(lines)

    if action == "find":
        if not pattern:
            return "Error: 'pattern' is required for the 'find' action (e.g. '*.py')."
        matches = []
        try:
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fname in files:
                    if fnmatch.fnmatch(fname, pattern):
                        full = Path(root) / fname
                        matches.append(str(full.relative_to(p)))
                if len(matches) > 500:
                    matches.append("... (truncated at 500 results)")
                    break
        except PermissionError:
            return "Error: Permission denied during walk."
        if not matches:
            return f"No files matching '{pattern}' found under {p}."
        return f"Found {len(matches)} match(es) for '{pattern}':\n" + "\n".join(matches)

    if action == "size":
        total = 0
        count = 0
        try:
            for entry in p.rglob("*"):
                if entry.is_file():
                    try:
                        total += entry.stat().st_size
                        count += 1
                    except OSError:
                        pass
        except PermissionError:
            return "Error: Permission denied."
        return f"Directory : {p}\nFiles     : {count}\nTotal size: {_human_size(total)}"

    return f"Unknown action '{action}'. Use: list, tree, find, size."


def _tree_recurse(path: Path, prefix: str, lines: list, depth: int, max_depth: int, counter: list, limit: int):
    if depth >= max_depth or counter[0] >= limit:
        return
    try:
        entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        lines.append(prefix + "└── [Permission denied]")
        return
    for i, entry in enumerate(entries):
        if counter[0] >= limit:
            lines.append(prefix + "└── ... (truncated)")
            return
        is_last = (i == len(entries) - 1)
        connector = "└── " if is_last else "├── "
        indicator = "/" if entry.is_dir() else ""
        lines.append(prefix + connector + entry.name + indicator)
        counter[0] += 1
        if entry.is_dir():
            extension = "    " if is_last else "│   "
            _tree_recurse(entry, prefix + extension, lines, depth + 1, max_depth, counter, limit)


def _human_size(size: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
