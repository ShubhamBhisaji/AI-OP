"""linter_tool — Python code quality checks using AST (no external linter needed).

Optional enhanced checks if installed: pyflakes, pylint, flake8.
"""
from __future__ import annotations
import ast, re, sys, logging
from pathlib import Path

logger = logging.getLogger(__name__)


def linter_tool(source: str, action: str = "full") -> str:
    """
    Check Python code quality.

    source : Python source code string, OR 'file:<path>' to load from disk.
    action : syntax | unused_vars | missing_docs | long_lines | complexity |
             type_hints | bare_excepts | security | full | pyflakes | flake8

    Actions (AST-based, no install needed):
        syntax        : Check for syntax errors only.
        unused_vars   : Detect variables assigned but never used.
        missing_docs  : Functions/classes without docstrings.
        long_lines    : Lines exceeding 79 characters (PEP 8).
        complexity    : Functions with cyclomatic complexity > 10.
        type_hints    : Functions missing parameter or return type annotations.
        bare_excepts  : Bare except clauses (catches everything silently).
        security      : Basic security anti-patterns (eval, exec, shell=True, etc.).
        full          : Run all built-in checks.

    Actions (require external tools):
        pyflakes      : Run pyflakes for undefined names, unused imports, etc.
        flake8        : Run flake8 for PEP 8 style + pyflakes combined.
    """
    if not source or not isinstance(source, str):
        return "Error: 'source' must be a non-empty string or 'file:<path>'."

    action = (action or "full").strip().lower()
    raw    = source.strip()

    # Load from file if needed
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

    if action == "pyflakes":
        return _run_pyflakes(raw)
    if action == "flake8":
        return _run_flake8(raw)

    # Parse AST (needed for all built-in checks)
    try:
        tree = ast.parse(raw)
    except SyntaxError as e:
        return f"Syntax error: {e.msg} (line {e.lineno}, col {e.offset})\n{e.text or ''}"

    src_lines = raw.splitlines()

    checks = {
        "syntax":       lambda: ["  No syntax errors found."],
        "unused_vars":  lambda: _unused_vars(tree, src_lines),
        "missing_docs": lambda: _missing_docs(tree),
        "long_lines":   lambda: _long_lines(src_lines),
        "complexity":   lambda: _complexity(tree),
        "type_hints":   lambda: _type_hints(tree),
        "bare_excepts": lambda: _bare_excepts(tree, src_lines),
        "security":     lambda: _security(tree, src_lines),
    }

    if action in checks:
        issues = checks[action]()
        label  = action.replace("_", " ").title()
        header = f"[ {label} ]"
        count  = sum(1 for l in issues if l.strip() and not l.startswith("  No "))
        if count:
            return f"{header}  —  {count} issue(s) found:\n" + "\n".join(issues)
        return f"{header}\n" + "\n".join(issues)

    if action == "full":
        parts: list[str] = []
        total_issues = 0
        for key, fn in checks.items():
            issues = fn()
            count = sum(1 for l in issues if l.strip() and not l.startswith("  No "))
            total_issues += count
            label  = key.replace("_", " ").title()
            marker = f"  ⚠ {count} issue(s)" if count else "  ✔ OK"
            parts.append(f"[ {label} ]{marker}")
            if count:
                parts += issues
        summary = f"\n{'='*50}\nTotal issues found: {total_issues}"
        return "\n".join(parts) + summary

    return (
        f"Unknown action '{action}'. Use: syntax, unused_vars, missing_docs, "
        "long_lines, complexity, type_hints, bare_excepts, security, full, pyflakes, flake8."
    )


# ── built-in checks ───────────────────────────────────────────────────────────

def _unused_vars(tree: ast.Module, lines: list[str]) -> list[str]:
    """Heuristic: assigned names that never appear again in the same scope."""
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assigned: dict[str, int] = {}  # name → lineno
        used:     set[str]       = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        if target.id not in ("_", "__") and not target.id.startswith("_"):
                            assigned[target.id] = child.lineno
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                used.add(child.id)
        for name, lineno in assigned.items():
            if name not in used:
                issues.append(f"  Line {lineno:4}: '{name}' assigned but never used  [{node.name}()]")
    return issues or ["  No unused variables detected."]


def _missing_docs(tree: ast.Module) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not ast.get_docstring(node):
                kind = "class" if isinstance(node, ast.ClassDef) else "def"
                issues.append(f"  Line {node.lineno:4}: {kind} {node.name}() — no docstring")
    return issues or ["  All functions and classes have docstrings."]


def _long_lines(lines: list[str], limit: int = 79) -> list[str]:
    issues: list[str] = []
    for i, line in enumerate(lines, 1):
        if len(line) > limit:
            issues.append(f"  Line {i:4}: {len(line)} chars  (limit {limit})  {line[:60]}...")
    return issues or [f"  All lines are within {limit} characters."]


def _complexity(tree: ast.Module, threshold: int = 10) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = 1
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler,
                                       ast.With, ast.Assert, ast.comprehension)):
                    cc += 1
                elif isinstance(child, ast.BoolOp):
                    cc += len(child.values) - 1
            if cc > threshold:
                issues.append(f"  Line {node.lineno:4}: {node.name}()  CC={cc}  (threshold {threshold})")
    return issues or [f"  All functions have cyclomatic complexity ≤ {threshold}."]


def _type_hints(tree: ast.Module) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue  # skip private/dunder
        args     = node.args.args
        missing  = [a.arg for a in args if a.annotation is None and a.arg != "self"]
        no_ret   = node.returns is None
        parts: list[str] = []
        if missing:
            parts.append(f"params without annotation: {', '.join(missing)}")
        if no_ret:
            parts.append("no return type annotation")
        if parts:
            issues.append(f"  Line {node.lineno:4}: {node.name}() — {'; '.join(parts)}")
    return issues or ["  All public functions have type hints."]


def _bare_excepts(tree: ast.Module, lines: list[str]) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            lineno = node.lineno
            snippet = lines[lineno - 1].strip() if lineno <= len(lines) else ""
            issues.append(f"  Line {lineno:4}: bare 'except:'  {snippet}")
    return issues or ["  No bare except clauses found."]


def _security(tree: ast.Module, lines: list[str]) -> list[str]:
    """Flag common dangerous patterns."""
    issues: list[str] = []

    dangerous_calls = {
        "eval":     "eval() executes arbitrary code",
        "exec":     "exec() executes arbitrary code",
        "compile":  "compile() can be used to execute arbitrary code",
        "__import__": "__import__() can load arbitrary modules",
    }
    dangerous_attrs = {
        "pickle":   "Pickle can execute arbitrary code on deserialization",
        "marshal":  "Marshal can execute arbitrary code",
    }

    for node in ast.walk(tree):
        # eval/exec/compile calls
        if isinstance(node, ast.Call):
            fname = None
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname in dangerous_calls:
                issues.append(
                    f"  Line {node.lineno:4}: ⚠ {fname}() — {dangerous_calls[fname]}"
                )

        # subprocess shell=True
        if isinstance(node, ast.keyword) and node.arg == "shell":
            if isinstance(node.value, ast.Constant) and node.value.value is True:
                issues.append(
                    f"  Line {node.lineno:4}: ⚠ shell=True — risk of command injection"
                )

    # Source-level pattern checks
    patterns = [
        (r"os\.system\s*\(",    "os.system() — use subprocess with a list instead"),
        (r"random\.random\(\)",  "random.random() is not cryptographically secure — use secrets"),
        (r"hashlib\.md5\b",      "MD5 is cryptographically broken for security use"),
        (r"hashlib\.sha1\b",     "SHA-1 is cryptographically weak for security use"),
        (r"assert\s+",           "assert statements can be disabled with -O; do not use for validation"),
        (r"print\s*\(.*password", "Possible credential leak in print()"),
        (r"print\s*\(.*secret",  "Possible credential leak in print()"),
        (r"print\s*\(.*token",   "Possible credential leak in print()"),
    ]
    for i, line in enumerate(lines, 1):
        for pat, msg in patterns:
            if re.search(pat, line, re.IGNORECASE):
                issues.append(f"  Line {i:4}: ⚠ {msg}")

    return issues or ["  No obvious security issues found."]


# ── external linter runners ───────────────────────────────────────────────────

def _run_pyflakes(source: str) -> str:
    try:
        import pyflakes.api  # type: ignore
        import pyflakes.reporter  # type: ignore
        import io
        buf = io.StringIO()

        class _SimpleReporter:
            def __init__(self):
                self.msgs: list[str] = []
            def unexpectedError(self, filename, msg):
                self.msgs.append(f"Error: {msg}")
            def syntaxError(self, filename, msg, lineno, offset, text):
                self.msgs.append(f"SyntaxError: {msg} at line {lineno}")
            def flake(self, message):
                self.msgs.append(str(message))

        reporter = _SimpleReporter()
        pyflakes.api.check(source, filename="<source>", reporter=reporter)
        if not reporter.msgs:
            return "pyflakes: No issues found."
        return "pyflakes results:\n" + "\n".join(f"  {m}" for m in reporter.msgs)
    except ImportError:
        return "pyflakes is not installed.\nRun:  pip install pyflakes"


def _run_flake8(source: str) -> str:
    import subprocess, tempfile, sys
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                         delete=False, encoding="utf-8") as f:
            f.write(source)
            tmp = f.name
        result = subprocess.run(
            [sys.executable, "-m", "flake8", "--max-line-length=100", tmp],
            capture_output=True, text=True, timeout=15
        )
        import os; os.unlink(tmp)
        out = result.stdout.strip()
        if not out and result.returncode == 0:
            return "flake8: No issues found."
        # Strip temp path from output
        out = re.sub(re.escape(tmp), "<source>", out)
        return "flake8 results:\n" + out
    except FileNotFoundError:
        return "flake8 is not installed.\nRun:  pip install flake8"
    except subprocess.TimeoutExpired:
        return "flake8 timed out."
