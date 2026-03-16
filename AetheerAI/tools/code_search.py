"""code_search — Search through source code files across a directory tree."""
from __future__ import annotations
import ast, re, os, fnmatch, logging
from pathlib import Path

logger = logging.getLogger(__name__)

_TEXT_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rb", ".php", ".rs", ".swift", ".kt", ".scala", ".sh",
    ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".md",
    ".txt", ".xml", ".sql",
}
_MAX_FILES   = 500
_MAX_RESULTS = 200


def code_search(
    action: str,
    path: str = ".",
    query: str = "",
    pattern: str = "*.py",
) -> str:
    """
    Search source code files in a directory.

    action  : find_function | find_class | find_import | grep | list_functions |
              list_classes  | list_files  | find_todos  | find_definition | xref
    path    : Root directory to search (default: current directory).
    query   : Name or text to search for (function name, class name, text, etc.).
    pattern : Glob file filter  (default: *.py).  Use *.* for all text files.

    Actions:
        find_function  : Find all definitions of a function/method by name.
        find_class     : Find all class definitions matching the name.
        find_import    : Find files that import a given module or symbol.
        grep           : Full-text search — show matching lines with context.
        list_functions : List every function/method in matching files.
        list_classes   : List every class in matching files.
        list_files     : List all code files with line counts.
        find_todos     : Collect TODO/FIXME/HACK/NOTE comments across project.
        find_definition: Find where a name (function/class/variable) is defined.
        xref           : Show every file that references (calls/uses) a given name.
    """
    if not action or not isinstance(action, str):
        return "Error: 'action' is required."

    action  = action.strip().lower()
    root    = Path((path or ".").strip()).resolve()
    query   = (query or "").strip()
    pattern = (pattern or "*.py").strip()

    if not root.exists():
        return f"Error: Path not found — {root}"
    if not root.is_dir():
        return f"Error: Not a directory — {root}"

    files = _collect_files(root, pattern)

    if action == "list_files":
        return _list_files(files, root)

    if not query and action not in ("list_functions", "list_classes", "find_todos", "list_files"):
        return f"Error: 'query' is required for action '{action}'."

    if action == "find_function":    return _find_def(files, root, query, (ast.FunctionDef, ast.AsyncFunctionDef))
    if action == "find_class":       return _find_def(files, root, query, (ast.ClassDef,))
    if action == "find_import":      return _find_import(files, root, query)
    if action == "grep":             return _grep(files, root, query)
    if action == "list_functions":   return _list_defs(files, root, (ast.FunctionDef, ast.AsyncFunctionDef), "Functions")
    if action == "list_classes":     return _list_defs(files, root, (ast.ClassDef,), "Classes")
    if action == "find_todos":       return _find_todos(files, root)
    if action == "find_definition":  return _find_definition(files, root, query)
    if action == "xref":             return _xref(files, root, query)

    return (
        f"Unknown action '{action}'. Use: find_function, find_class, find_import, grep, "
        "list_functions, list_classes, list_files, find_todos, find_definition, xref."
    )


# ── file collection ───────────────────────────────────────────────────────────

def _collect_files(root: Path, pattern: str) -> list[Path]:
    files: list[Path] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden dirs and common noise dirs
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in (
                    "node_modules", "__pycache__", ".git", ".venv", "venv",
                    "dist", "build", ".tox", ".mypy_cache",
                )
            ]
            for fname in filenames:
                if fnmatch.fnmatch(fname, pattern):
                    fp = Path(dirpath) / fname
                    if fp.suffix.lower() in _TEXT_EXTS or pattern != "*.py":
                        files.append(fp)
                    if len(files) >= _MAX_FILES:
                        return files
    except PermissionError:
        pass
    return files


def _read_source(fp: Path) -> str | None:
    try:
        return fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _try_parse(src: str) -> ast.Module | None:
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


# ── actions ───────────────────────────────────────────────────────────────────

def _list_files(files: list[Path], root: Path) -> str:
    if not files:
        return "No matching files found."
    lines = [f"Found {len(files)} file(s):\n"]
    total_lines = 0
    for fp in files:
        src = _read_source(fp)
        lc  = src.count("\n") + 1 if src else 0
        total_lines += lc
        rel = _rel(fp, root)
        lines.append(f"  {lc:6} lines  {rel}")
    lines.append(f"\nTotal: {total_lines} lines across {len(files)} files")
    return "\n".join(lines)


def _find_def(files: list[Path], root: Path, query: str, node_types: tuple) -> str:
    results: list[str] = []
    q_lower = query.lower()
    for fp in files:
        src = _read_source(fp)
        if not src:
            continue
        tree = _try_parse(src)
        if not tree:
            continue
        src_lines = src.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, node_types) and node.name.lower() == q_lower:
                snippet = src_lines[node.lineno - 1] if node.lineno <= len(src_lines) else ""
                doc = (ast.get_docstring(node) or "").split("\n")[0][:60]
                results.append(
                    f"  {_rel(fp, root)}:{node.lineno}\n"
                    f"    {snippet.strip()}"
                    + (f"\n    └ {doc}" if doc else "")
                )
        if len(results) >= _MAX_RESULTS:
            break
    if not results:
        return f"No definition of '{query}' found."
    return f"Definition(s) of '{query}' ({len(results)}):\n" + "\n".join(results)


def _find_import(files: list[Path], root: Path, query: str) -> str:
    results: list[str] = []
    q_lower = query.lower()
    for fp in files:
        src = _read_source(fp)
        if not src:
            continue
        tree = _try_parse(src)
        if not tree:
            # Fallback: text search
            for i, line in enumerate(src.splitlines(), 1):
                if "import" in line.lower() and q_lower in line.lower():
                    results.append(f"  {_rel(fp, root)}:{i}  {line.strip()}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if q_lower in alias.name.lower():
                        results.append(f"  {_rel(fp, root)}:{node.lineno}  import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if q_lower in mod.lower() or any(q_lower in a.name.lower() for a in node.names):
                    names = ", ".join(a.name for a in node.names)
                    results.append(f"  {_rel(fp, root)}:{node.lineno}  from {mod} import {names}")
        if len(results) >= _MAX_RESULTS:
            break
    if not results:
        return f"No files found importing '{query}'."
    return f"Files importing '{query}' ({len(results)}):\n" + "\n".join(results)


def _grep(files: list[Path], root: Path, query: str) -> str:
    results: list[str] = []
    try:
        regex = re.compile(query, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        return f"Error: Invalid regex '{query}': {e}"
    for fp in files:
        src = _read_source(fp)
        if not src:
            continue
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                context_before = lines[max(0, i - 2):i - 1]
                context_after  = lines[i:min(len(lines), i + 1)]
                hit = f"  {_rel(fp, root)}:{i}\n"
                for cl in context_before:
                    hit += f"    {i - 1:4} │ {cl}\n"
                hit += f"  ► {i:4} │ {line}\n"
                for cl in context_after:
                    hit += f"    {i + 1:4} │ {cl}\n"
                results.append(hit)
                if len(results) >= _MAX_RESULTS:
                    return f"Matches for '{query}' ({len(results)}, truncated):\n" + "\n".join(results)
    if not results:
        return f"No matches found for '{query}'."
    return f"Matches for '{query}' ({len(results)}):\n" + "\n".join(results)


def _list_defs(files: list[Path], root: Path, node_types: tuple, label: str) -> str:
    results: list[str] = []
    for fp in files:
        src = _read_source(fp)
        if not src:
            continue
        tree = _try_parse(src)
        if not tree:
            continue
        file_hits = []
        for node in ast.walk(tree):
            if isinstance(node, node_types):
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                file_hits.append(f"    {node.lineno:4}: {prefix}{node.name}")
        if file_hits:
            results.append(f"  {_rel(fp, root)}")
            results += file_hits
    if not results:
        return f"No {label.lower()} found."
    return f"{label} found:\n" + "\n".join(results)


def _find_todos(files: list[Path], root: Path) -> str:
    pattern = re.compile(r"#\s*(TODO|FIXME|HACK|NOTE|XXX|BUG|OPTIMIZE)\b[:\s]*(.*)", re.IGNORECASE)
    results: list[str] = []
    counts: dict[str, int] = {}
    for fp in files:
        src = _read_source(fp)
        if not src:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            m = pattern.search(line)
            if m:
                tag  = m.group(1).upper()
                text = m.group(2).strip()
                counts[tag] = counts.get(tag, 0) + 1
                results.append(f"  [{tag}] {_rel(fp, root)}:{i}  {text}")
    if not results:
        return "No TODO/FIXME/HACK comments found."
    summary = "  ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    return f"Found {len(results)} comment(s)  [{summary}]:\n" + "\n".join(results[:_MAX_RESULTS])


def _find_definition(files: list[Path], root: Path, query: str) -> str:
    """Find where a name is assigned/defined (not just function/class defs)."""
    results: list[str] = []
    q_lower = query.lower()
    patterns = [
        re.compile(rf"^\s*(def|class|async\s+def)\s+{re.escape(query)}\b", re.IGNORECASE),
        re.compile(rf"^\s*{re.escape(query)}\s*[:=]",                       re.IGNORECASE),
        re.compile(rf"^\s*{re.escape(query)}\s*=",                          re.IGNORECASE),
    ]
    for fp in files:
        src = _read_source(fp)
        if not src:
            continue
        for i, line in enumerate(src.splitlines(), 1):
            if any(p.search(line) for p in patterns):
                results.append(f"  {_rel(fp, root)}:{i}  {line.strip()}")
        if len(results) >= _MAX_RESULTS:
            break
    if not results:
        return f"No definition of '{query}' found."
    return f"Definition(s) of '{query}' ({len(results)}):\n" + "\n".join(results)


def _xref(files: list[Path], root: Path, query: str) -> str:
    """Find all references/usages of a name."""
    results: list[str] = []
    pattern = re.compile(rf"\b{re.escape(query)}\b")
    for fp in files:
        src = _read_source(fp)
        if not src:
            continue
        hits = []
        for i, line in enumerate(src.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"    {i:4}: {line.strip()}")
        if hits:
            results.append(f"  {_rel(fp, root)} ({len(hits)} ref(s)):")
            results += hits[:10]
            if len(hits) > 10:
                results.append(f"    ... and {len(hits) - 10} more")
        if len(results) >= _MAX_RESULTS:
            break
    if not results:
        return f"No references to '{query}' found."
    return f"Cross-references to '{query}':\n" + "\n".join(results)


def _rel(fp: Path, root: Path) -> str:
    try:
        return str(fp.relative_to(root))
    except ValueError:
        return str(fp)
