"""
local_file_tool — Create, read, write, append, copy, move, rename,
delete, and scaffold files/directories anywhere on the local filesystem.

All destructive actions (delete, overwrite) require the caller to pass
confirm="yes" to prevent accidental data loss.

Fix 1 — @require_approval: any agent call goes through the ApprovalGate first.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
from pathlib import Path

from security.approval_gate import require_approval

logger = logging.getLogger(__name__)

# Paths that are always blocked regardless of arguments
_BLOCKED_ROOTS = [
    "C:/Windows", "C:/Windows/System32",
    "C:/Program Files", "C:/Program Files (x86)",
    "/etc", "/bin", "/sbin", "/usr/bin", "/usr/sbin",
    "/boot", "/dev", "/proc", "/sys",
]


@require_approval
def local_file_tool(
    action: str,
    path: str,
    content: str = "",
    dest: str = "",
    confirm: str = "",
    encoding: str = "utf-8",
) -> str:
    """
    Manage local files and directories at any path on disk.

    action   : create | read | write | append | delete | copy | move |
               rename | mkdir | list | exists | info | scaffold | find | tree
    path     : The target file or directory path (absolute or relative).
    content  : File content for create/write/append; JSON template for scaffold.
    dest     : Destination path for copy/move/rename.
    confirm  : Pass "yes" to confirm destructive actions (delete, overwrite).
    encoding : File encoding (default: utf-8).

    Actions:
        create   : Create a new file.  Fails if it already exists (prevents overwrite).
        write    : Write (overwrite) a file.  Requires confirm="yes".
        append   : Append text to a file (creates if missing).
        read     : Read a file and return its content.
        delete   : Delete a file or empty directory.  Requires confirm="yes".
        copy     : Copy a file or directory tree to dest.
        move     : Move/rename a file or directory to dest.
        rename   : Alias for move (rename within the same directory).
        mkdir    : Create a directory (and parents).
        list     : List directory contents.
        exists   : Check whether a path exists.
        info     : Show metadata (size, type, modified time, permissions).
        scaffold : Create a project folder structure.
                   content = JSON like:
                     {"src/__init__.py":"","README.md":"# My project"}
                   Keys are relative paths; values are file contents.
        find     : Search for files matching a glob pattern under path.
                   content = glob pattern, e.g. "*.py" or "**/*.json"
        tree     : Print an ASCII directory tree.
    """
    if not action:
        return "Error: 'action' is required."
    if not path:
        return "Error: 'path' is required."

    action = action.strip().lower()
    target = Path(path).expanduser().resolve()

    if action in ("create", "write", "append", "delete", "move", "rename", "scaffold", "mkdir"):
        blocked, reason = _check_blocked(target)
        if blocked:
            return f"Error: path is in a protected system directory — {reason}"

    dispatch = {
        "create":   _create,
        "write":    _write,
        "append":   _append,
        "read":     _read,
        "delete":   _delete,
        "copy":     _copy,
        "move":     _move,
        "rename":   _move,
        "mkdir":    _mkdir,
        "list":     _list,
        "exists":   _exists,
        "info":     _info,
        "scaffold": _scaffold,
        "find":     _find,
        "tree":     _tree,
    }

    fn = dispatch.get(action)
    if fn is None:
        return (
            f"Unknown action '{action}'. "
            "Use: create, read, write, append, delete, copy, move, rename, "
            "mkdir, list, exists, info, scaffold, find, tree."
        )

    try:
        return fn(target, content=content, dest=dest, confirm=confirm, encoding=encoding)
    except Exception as exc:
        logger.exception("local_file_tool[%s] error on '%s'", action, path)
        return f"Error: {exc}"


# ── Action implementations ────────────────────────────────────────────────────

def _create(target: Path, content, dest, confirm, encoding) -> str:
    if target.exists():
        return f"Error: file already exists: {target}\nUse action='write' with confirm='yes' to overwrite."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding=encoding)
    return f"Created: {target}  ({len(content)} chars)"


def _write(target: Path, content, dest, confirm, encoding) -> str:
    if target.exists() and confirm.strip().lower() != "yes":
        return (
            f"File already exists: {target}\n"
            "Pass confirm='yes' to overwrite it."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding=encoding)
    return f"Written: {target}  ({len(content)} chars)"


def _append(target: Path, content, dest, confirm, encoding) -> str:
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding=encoding) as f:
        f.write(content)
    action_word = "Appended to" if existed else "Created and appended to"
    return f"{action_word}: {target}  (+{len(content)} chars)"


def _read(target: Path, content, dest, confirm, encoding) -> str:
    if not target.exists():
        return f"Error: file not found: {target}"
    if target.is_dir():
        return f"Error: '{target}' is a directory. Use action='list' or 'tree'."
    size = target.stat().st_size
    if size > 1_000_000:
        return f"Error: file is too large to read ({size:,} bytes). Use a file editor."
    text = target.read_text(encoding=encoding, errors="replace")
    return f"=== {target} ({size:,} bytes) ===\n{text}"


def _delete(target: Path, content, dest, confirm, encoding) -> str:
    if not target.exists():
        return f"Error: path not found: {target}"
    if confirm.strip().lower() != "yes":
        kind = "directory" if target.is_dir() else "file"
        return (
            f"This will permanently delete the {kind}: {target}\n"
            "Pass confirm='yes' to proceed."
        )
    if target.is_dir():
        shutil.rmtree(target)
        return f"Deleted directory: {target}"
    else:
        target.unlink()
        return f"Deleted file: {target}"


def _copy(target: Path, content, dest, confirm, encoding) -> str:
    if not dest:
        return "Error: 'dest' path is required for copy."
    if not target.exists():
        return f"Error: source not found: {target}"
    dst = Path(dest).expanduser().resolve()
    blocked, reason = _check_blocked(dst)
    if blocked:
        return f"Error: destination is in a protected directory — {reason}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(str(target), str(dst), dirs_exist_ok=True)
        return f"Copied directory: {target}  →  {dst}"
    else:
        shutil.copy2(str(target), str(dst))
        return f"Copied: {target}  →  {dst}"


def _move(target: Path, content, dest, confirm, encoding) -> str:
    if not dest:
        return "Error: 'dest' path is required for move/rename."
    if not target.exists():
        return f"Error: source not found: {target}"
    dst = Path(dest).expanduser().resolve()
    blocked, reason = _check_blocked(dst)
    if blocked:
        return f"Error: destination is in a protected directory — {reason}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(dst))
    return f"Moved: {target}  →  {dst}"


def _mkdir(target: Path, content, dest, confirm, encoding) -> str:
    target.mkdir(parents=True, exist_ok=True)
    return f"Directory ready: {target}"


def _list(target: Path, content, dest, confirm, encoding) -> str:
    if not target.exists():
        return f"Error: path not found: {target}"
    if not target.is_dir():
        return f"Error: '{target}' is a file, not a directory."
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    if not entries:
        return f"(empty directory)  {target}"
    lines = [f"Directory: {target}", ""]
    dirs  = [e for e in entries if e.is_dir()]
    files = [e for e in entries if e.is_file()]
    for d in dirs:
        lines.append(f"  [DIR]  {d.name}/")
    for f in files:
        sz = f.stat().st_size
        lines.append(f"  {f.name:<40} {_fmt_size(sz):>8}")
    lines.append(f"\n  {len(dirs)} folder(s), {len(files)} file(s)")
    return "\n".join(lines)


def _exists(target: Path, content, dest, confirm, encoding) -> str:
    if target.exists():
        kind = "directory" if target.is_dir() else "file"
        return f"Exists ({kind}): {target}"
    return f"Not found: {target}"


def _info(target: Path, content, dest, confirm, encoding) -> str:
    if not target.exists():
        return f"Error: path not found: {target}"
    s = target.stat()
    import datetime
    mtime = datetime.datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    ctime = datetime.datetime.fromtimestamp(s.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
    permissions = oct(stat.S_IMODE(s.st_mode))
    kind = "Directory" if target.is_dir() else "File"
    lines = [
        f"Path       : {target}",
        f"Type       : {kind}",
        f"Size       : {_fmt_size(s.st_size)} ({s.st_size:,} bytes)",
        f"Modified   : {mtime}",
        f"Created    : {ctime}",
        f"Permissions: {permissions}",
    ]
    if target.is_file():
        suffix = target.suffix.lower()
        lines.append(f"Extension  : {suffix or '(none)'}")
    return "\n".join(lines)


def _scaffold(target: Path, content, dest, confirm, encoding) -> str:
    """
    Create a project folder structure.
    content must be a JSON dict: {"relative/path": "file content", ...}
    Entries ending in "/" create directories.
    """
    import json
    if not content.strip():
        return "Error: 'content' must be a JSON dict of {path: content} pairs."
    try:
        spec: dict = json.loads(content)
    except json.JSONDecodeError as e:
        return f"Error parsing content as JSON: {e}"
    if not isinstance(spec, dict):
        return "Error: content must be a JSON object."

    target.mkdir(parents=True, exist_ok=True)
    created = []
    for rel_path, file_content in spec.items():
        rel_path = rel_path.strip("/\\")
        p = target / rel_path
        blocked, reason = _check_blocked(p)
        if blocked:
            created.append(f"  SKIPPED (protected): {rel_path}")
            continue
        if rel_path.endswith("/") or not Path(rel_path).suffix:
            # treat as directory if no extension or trailing slash
            if not Path(rel_path).suffix:
                p.mkdir(parents=True, exist_ok=True)
                created.append(f"  [DIR]  {rel_path}/")
                continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(file_content), encoding=encoding)
        created.append(f"  [FILE] {rel_path}  ({len(str(file_content))} chars)")

    return f"Scaffold complete: {target}\n" + "\n".join(created)


def _find(target: Path, content, dest, confirm, encoding) -> str:
    if not target.exists():
        return f"Error: path not found: {target}"
    pattern = content.strip() or "**/*"
    matches = sorted(target.glob(pattern))
    if not matches:
        return f"No files matching '{pattern}' under {target}"
    lines = [f"Found {len(matches)} match(es) for '{pattern}' in {target}:"]
    for m in matches[:200]:
        rel = m.relative_to(target)
        sz = _fmt_size(m.stat().st_size) if m.is_file() else "[DIR]"
        lines.append(f"  {rel}  {sz}")
    if len(matches) > 200:
        lines.append(f"  ... and {len(matches)-200} more")
    return "\n".join(lines)


def _tree(target: Path, content, dest, confirm, encoding) -> str:
    if not target.exists():
        return f"Error: path not found: {target}"
    if not target.is_dir():
        return f"Error: '{target}' is not a directory."
    lines: list[str] = [str(target)]
    _build_tree(target, "", lines, max_depth=4, depth=0)
    return "\n".join(lines)


def _build_tree(path: Path, prefix: str, lines: list, max_depth: int, depth: int) -> None:
    if depth >= max_depth:
        lines.append(prefix + "  ...")
        return
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        lines.append(prefix + "  [permission denied]")
        return
    for i, entry in enumerate(entries):
        connector = "└── " if i == len(entries) - 1 else "├── "
        label = entry.name + ("/" if entry.is_dir() else "")
        lines.append(prefix + connector + label)
        if entry.is_dir():
            extension = "    " if i == len(entries) - 1 else "│   "
            _build_tree(entry, prefix + extension, lines, max_depth, depth + 1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def _check_blocked(path: Path) -> tuple[bool, str]:
    path_str = str(path).replace("\\", "/")
    for blocked in _BLOCKED_ROOTS:
        if path_str.lower().startswith(blocked.lower()):
            return True, blocked
    return False, ""
