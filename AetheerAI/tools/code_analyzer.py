"""code_analyzer — Static analysis of Python source code using the AST."""
from __future__ import annotations
import ast, re, textwrap, logging
from pathlib import Path
from collections import Counter

logger = logging.getLogger(__name__)


def code_analyzer(source: str, action: str = "analyze") -> str:
    """
    Perform static analysis on Python source code.

    source : Python source code as a string, OR a path prefixed with 'file:'.
    action : analyze | functions | classes | imports | complexity | todos | stats | lines | deps

    Actions:
        analyze    : Full report — functions, classes, imports, complexity, todos.
        functions  : List all function and method definitions with signature.
        classes    : List all class definitions with their methods.
        imports    : All import statements (modules + aliases).
        complexity : Cyclomatic complexity estimate per function.
        todos      : Find TODO, FIXME, HACK, NOTE, XXX comments.
        stats      : Line counts, blank lines, comment lines, docstrings.
        lines      : Print the source with line numbers (max 200 lines).
        deps       : External (non-stdlib) modules imported.
    """
    if not source or not isinstance(source, str):
        return "Error: 'source' must be a non-empty string or 'file:<path>'."

    action = (action or "analyze").strip().lower()
    raw    = source.strip()

    # Load from file if requested
    if raw.startswith("file:"):
        p = Path(raw[5:].strip())
        if not p.exists():
            return f"Error: File not found — {p}"
        if not p.is_file():
            return f"Error: Not a file — {p}"
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return f"Error: Permission denied reading {p}"

    # Parse AST
    try:
        tree = ast.parse(raw)
    except SyntaxError as e:
        return f"Syntax error in source: {e}"

    src_lines = raw.splitlines()

    # ── Actions ──────────────────────────────────────────────────────────────

    if action == "lines":
        limit = 200
        numbered = [f"{i+1:4} │ {line}" for i, line in enumerate(src_lines[:limit])]
        truncated = f"\n[Truncated at {limit}/{len(src_lines)} lines]" if len(src_lines) > limit else ""
        return "\n".join(numbered) + truncated

    if action == "stats":
        return _stats(src_lines, tree)

    if action == "functions":
        return _functions(tree)

    if action == "classes":
        return _classes(tree)

    if action == "imports":
        return _imports(tree)

    if action == "complexity":
        return _complexity(tree)

    if action == "todos":
        return _todos(src_lines)

    if action == "deps":
        return _deps(tree)

    if action == "analyze":
        parts = [
            "=== STATS ===\n"      + _stats(src_lines, tree),
            "=== FUNCTIONS ===\n"  + _functions(tree),
            "=== CLASSES ===\n"    + _classes(tree),
            "=== IMPORTS ===\n"    + _imports(tree),
            "=== COMPLEXITY ===\n" + _complexity(tree),
            "=== TODOS ===\n"      + _todos(src_lines),
        ]
        return "\n\n".join(parts)

    return f"Unknown action '{action}'. Use: analyze, functions, classes, imports, complexity, todos, stats, lines, deps."


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stats(lines: list[str], tree: ast.AST) -> str:
    total    = len(lines)
    blank    = sum(1 for l in lines if not l.strip())
    comments = sum(1 for l in lines if l.strip().startswith("#"))
    code     = total - blank - comments
    funcs    = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef))
    classes  = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    docstrings = _count_docstrings(tree)
    return (
        f"Total lines  : {total}\n"
        f"Code lines   : {code}\n"
        f"Comment lines: {comments}\n"
        f"Blank lines  : {blank}\n"
        f"Functions    : {funcs}\n"
        f"Classes      : {classes}\n"
        f"Docstrings   : {docstrings}"
    )


def _functions(tree: ast.AST) -> str:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            args   = [a.arg for a in node.args.args]
            sig    = f"{prefix}def {node.name}({', '.join(args)})"
            doc    = (ast.get_docstring(node) or "").split("\n")[0][:60]
            found.append(f"  Line {node.lineno:4}: {sig}" + (f"\n           └ {doc}" if doc else ""))
    return "\n".join(found) if found else "(no functions found)"


def _classes(tree: ast.AST) -> str:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases   = [_name_of(b) for b in node.bases]
            base_s  = f"({', '.join(bases)})" if bases else ""
            methods = [
                ("async " if isinstance(m, ast.AsyncFunctionDef) else "") + m.name
                for m in node.body
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            found.append(
                f"  Line {node.lineno:4}: class {node.name}{base_s}\n"
                + ("           Methods: " + ", ".join(methods) if methods else "           (no methods)")
            )
    return "\n".join(found) if found else "(no classes found)"


def _imports(tree: ast.AST) -> str:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                s = alias.name + (f" as {alias.asname}" if alias.asname else "")
                found.append(f"  import {s}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "") for a in node.names
            )
            dots = "." * (node.level or 0)
            found.append(f"  from {dots}{mod} import {names}")
    return "\n".join(found) if found else "(no imports found)"


def _complexity(tree: ast.AST) -> str:
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            cc = 1  # base
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler,
                                       ast.With, ast.Assert, ast.comprehension)):
                    cc += 1
                elif isinstance(child, ast.BoolOp):
                    cc += len(child.values) - 1
            rating = "Low" if cc <= 5 else ("Medium" if cc <= 10 else "High")
            results.append(f"  {node.name:<30} CC={cc:3}  [{rating}]")
    if not results:
        return "(no functions to measure)"
    results.sort(key=lambda s: -int(re.search(r"CC=\s*(\d+)", s).group(1)))
    return "\n".join(results)


def _todos(lines: list[str]) -> str:
    pattern = re.compile(r"#\s*(TODO|FIXME|HACK|NOTE|XXX|BUG)\b[:\s]*(.*)", re.IGNORECASE)
    found = []
    for i, line in enumerate(lines, 1):
        m = pattern.search(line)
        if m:
            tag  = m.group(1).upper()
            text = m.group(2).strip()
            found.append(f"  Line {i:4}: [{tag}] {text}")
    return "\n".join(found) if found else "(no TODO/FIXME/HACK comments found)"


def _deps(tree: ast.AST) -> str:
    # Standard library top-level package names (common subset)
    _STDLIB = {
        "ast","re","os","sys","io","abc","copy","csv","json","math","time","enum",
        "uuid","hmac","html","http","ssl","cgi","xml","email","urllib","socket",
        "struct","array","queue","heapq","bisect","decimal","fractions","random",
        "stat","glob","fnmatch","shutil","tempfile","pathlib","pickle","shelve",
        "sqlite3","hashlib","base64","binascii","codecs","difflib","textwrap",
        "unicodedata","string","pprint","reprlib","types","typing","collections",
        "functools","itertools","operator","weakref","contextlib","dataclasses",
        "logging","warnings","traceback","inspect","gc","threading","multiprocessing",
        "concurrent","asyncio","signal","subprocess","platform","ctypes","site",
        "builtins","importlib","pkgutil","zipimport","zipfile","tarfile","gzip",
        "calendar","datetime","zoneinfo","configparser","argparse","getpass","getopt",
        "unittest","doctest","pdb","profile","cProfile","timeit","token","tokenize",
    }
    external: list[str] = []
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Import):
            name = node.names[0].name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            name = node.module.split(".")[0]
        if name and name not in _STDLIB and name not in external:
            external.append(name)
    if not external:
        return "No external (non-stdlib) dependencies found."
    return "External dependencies:\n" + "\n".join(f"  {d}" for d in sorted(external))


def _count_docstrings(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if ast.get_docstring(node):
                count += 1
    return count


def _name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Name):      return node.id
    if isinstance(node, ast.Attribute): return f"{_name_of(node.value)}.{node.attr}"
    return "?"
