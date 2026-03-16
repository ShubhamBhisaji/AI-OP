"""code_formatter — Format, clean, and transform Python source code.

Uses black (preferred) → autopep8 → built-in AST-based formatter as fallback.
"""
from __future__ import annotations
import ast, re, sys, textwrap, logging

logger = logging.getLogger(__name__)


def code_formatter(source: str, action: str = "format", options: str = "") -> str:
    """
    Format and transform Python source code.

    source  : Python source code string.
    action  : format | sort_imports | remove_comments | add_docstring |
              extract_function | minify | check | to_snippet | check_style
    options : Comma-separated key=value pairs.
              format        → line_length=88 (default)
              extract_function → name=my_func,start=10,end=20 (line range to extract)
              to_snippet    → lang=python (for display in Markdown code block)

    Actions:
        format           : Format with black → autopep8 → basic indent normalizer.
        sort_imports     : Sort import statements (stdlib → third-party → local).
        remove_comments  : Strip comment lines and inline comments.
        add_docstring    : Add placeholder docstrings to functions missing them.
        extract_function : Extract a line range into a named function stub.
        minify           : Remove blank lines and compress whitespace (for one-liners).
        check            : Dry-run format check — report if code needs formatting.
        to_snippet       : Wrap code in a Markdown fenced code block.
        check_style      : List style violations (PEP 8 basics) with line numbers.
    """
    if not source or not isinstance(source, str):
        return "Error: 'source' must be a non-empty string."

    action = (action or "format").strip().lower()
    opts   = _parse_opts(options)

    if action == "format":
        return _format(source, int(opts.get("line_length", 88)))

    if action == "sort_imports":
        return _sort_imports(source)

    if action == "remove_comments":
        return _remove_comments(source)

    if action == "add_docstring":
        return _add_docstrings(source)

    if action == "extract_function":
        name  = opts.get("name", "extracted_function")
        start = int(opts.get("start", 1))
        end   = int(opts.get("end", len(source.splitlines())))
        return _extract_function(source, name, start, end)

    if action == "minify":
        return _minify(source)

    if action == "check":
        return _check_format(source, int(opts.get("line_length", 88)))

    if action == "to_snippet":
        lang = opts.get("lang", "python")
        return f"```{lang}\n{source.rstrip()}\n```"

    if action == "check_style":
        return _check_style(source)

    return (
        f"Unknown action '{action}'. Use: format, sort_imports, remove_comments, "
        "add_docstring, extract_function, minify, check, to_snippet, check_style."
    )


# ── format ────────────────────────────────────────────────────────────────────

def _format(source: str, line_length: int = 88) -> str:
    # Try black
    try:
        import black  # type: ignore
        mode   = black.Mode(line_length=line_length)
        result = black.format_str(source, mode=mode)
        return f"[Formatted with black (line_length={line_length})]\n\n{result}"
    except ImportError:
        pass
    except Exception as e:
        return f"black formatting error: {e}"

    # Try autopep8
    try:
        import autopep8  # type: ignore
        result = autopep8.fix_code(source, options={"max_line_length": line_length})
        return f"[Formatted with autopep8 (line_length={line_length})]\n\n{result}"
    except ImportError:
        pass
    except Exception as e:
        return f"autopep8 formatting error: {e}"

    # Fallback: basic normalizer
    return _basic_format(source)


def _basic_format(source: str) -> str:
    """Normalize indentation to 4 spaces and trim trailing whitespace."""
    lines = source.splitlines()
    fixed = []
    for line in lines:
        # Normalize tab indentation to 4 spaces
        stripped = line.lstrip("\t")
        tab_count = len(line) - len(stripped)
        fixed.append("    " * tab_count + stripped.rstrip())
    # Remove excess blank lines (max 2 consecutive)
    out: list[str] = []
    blank_run = 0
    for line in fixed:
        if not line.strip():
            blank_run += 1
            if blank_run <= 2:
                out.append(line)
        else:
            blank_run = 0
            out.append(line)
    result = "\n".join(out).rstrip() + "\n"
    return f"[Formatted with built-in normalizer (install black for full formatting)]\n\n{result}"


# ── sort imports ──────────────────────────────────────────────────────────────

_STDLIB_MODS = {
    "abc","ast","asyncio","base64","binascii","calendar","cgi","cmath","cmd",
    "code","codecs","collections","colorsys","compileall","concurrent","configparser",
    "contextlib","copy","copyreg","cProfile","csv","ctypes","dataclasses","datetime",
    "decimal","difflib","dis","doctest","email","enum","errno","filecmp","fnmatch",
    "fractions","ftplib","functools","gc","getopt","getpass","glob","gzip","hashlib",
    "heapq","hmac","html","http","idlelib","imaplib","importlib","inspect","io","ipaddress",
    "itertools","json","keyword","linecache","locale","logging","lzma","math","mimetypes",
    "multiprocessing","operator","os","pathlib","pickle","pkgutil","platform","pprint",
    "profile","queue","random","re","reprlib","secrets","select","shelve","shlex","shutil",
    "signal","smtplib","socket","socketserver","sqlite3","ssl","stat","statistics",
    "string","struct","subprocess","sys","tarfile","tempfile","textwrap","threading",
    "time","timeit","token","tokenize","traceback","typing","unicodedata","unittest",
    "urllib","uuid","venv","warnings","weakref","webbrowser","xmlrpc","zipfile","zipimport",
    "zlib","zoneinfo",
}


def _sort_imports(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"Cannot sort imports — syntax error: {e}"

    lines        = source.splitlines(keepends=True)
    import_lines: list[tuple[int, str]] = []  # (lineno_0indexed, text)
    other_lines:  list[tuple[int, str]] = []

    # Collect leading imports (before first non-import, non-docstring code)
    in_header = True
    for node in ast.walk(tree):
        pass  # just ensure parse succeeded

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("import ", "from ")):
            import_lines.append((i, line.rstrip()))
        else:
            break

    if not import_lines:
        return "No import statements found to sort."

    def _import_key(imp: str) -> tuple[int, str]:
        m = re.match(r"^(?:from\s+(\S+)|import\s+(\S+))", imp.strip())
        name = (m.group(1) or m.group(2) or "").split(".")[0] if m else ""
        if name in _STDLIB_MODS:         bucket = 0
        elif imp.strip().startswith("."): bucket = 2
        else:                             bucket = 1
        return (bucket, imp.lower())

    sorted_imports = sorted(import_lines, key=lambda t: _import_key(t[1]))

    # Rebuild source replacing original import block
    all_import_idxs = {i for i, _ in import_lines}
    result_lines: list[str] = []
    sorted_iter = iter(sorted_imports)
    for i, line in enumerate(lines):
        if i in all_import_idxs:
            result_lines.append(next(sorted_iter)[1] + "\n")
        else:
            result_lines.append(line)

    return "[Imports sorted: stdlib → third-party → local]\n\n" + "".join(result_lines)


# ── remove comments ───────────────────────────────────────────────────────────

def _remove_comments(source: str) -> str:
    lines   = source.splitlines(keepends=True)
    in_str  = False
    result  = []
    removed = 0
    for line in lines:
        # Skip full-line comments
        if re.match(r"^\s*#", line):
            removed += 1
            continue
        # Strip inline comments (naive — doesn't handle all string edge cases)
        clean = re.sub(r"\s+#.*$", "", line.rstrip())
        result.append(clean + "\n")
    return f"[Removed {removed} comment line(s)]\n\n" + "".join(result)


# ── add docstrings ────────────────────────────────────────────────────────────

def _add_docstrings(source: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"Cannot process — syntax error: {e}"

    lines   = source.splitlines()
    inserts: list[tuple[int, str]] = []  # (after_line_idx, docstring_text)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not ast.get_docstring(node):
                # Find the line after the def/class signature (may span multiple lines)
                body_first = node.body[0].lineno - 1
                indent = re.match(r"^\s*", lines[node.lineno - 1]).group() + "    "
                if isinstance(node, ast.ClassDef):
                    doc = f'{indent}"""TODO: Describe {node.name}."""'
                else:
                    args = [a.arg for a in node.args.args if a.arg != "self"]
                    arg_docs = "".join(f"\n{indent}    {a}: TODO" for a in args)
                    doc = f'{indent}"""TODO: Describe {node.name}.{arg_docs}\n{indent}"""'
                inserts.append((body_first, doc))

    if not inserts:
        return "All functions and classes already have docstrings."

    # Insert from bottom to top so line numbers stay valid
    for line_idx, doc in sorted(inserts, reverse=True):
        lines.insert(line_idx, doc)

    return (
        f"[Added {len(inserts)} docstring placeholder(s)]\n\n"
        + "\n".join(lines)
    )


# ── extract function ──────────────────────────────────────────────────────────

def _extract_function(source: str, name: str, start: int, end: int) -> str:
    lines = source.splitlines()
    if start < 1 or end > len(lines) or start > end:
        return f"Error: Line range {start}–{end} is invalid (file has {len(lines)} lines)."

    body       = lines[start - 1:end]
    # Detect base indentation
    base_indent = re.match(r"^\s*", body[0]).group() if body else ""
    dedented    = textwrap.dedent("\n".join(body))

    stub = (
        f"def {name}():\n"
        f"    \"\"\"TODO: Add docstring.\"\"\"\n"
        + textwrap.indent(dedented, "    ")
        + "\n\n\n# Call site:\n"
        + f"{base_indent}{name}()\n"
    )
    return (
        f"[Extracted lines {start}–{end} → function '{name}']\n\n{stub}"
    )


# ── minify ────────────────────────────────────────────────────────────────────

def _minify(source: str) -> str:
    lines  = source.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.append(stripped)
    return "[Minified (blank lines and leading whitespace removed)]\n\n" + "\n".join(result)


# ── check format ─────────────────────────────────────────────────────────────

def _check_format(source: str, line_length: int = 88) -> str:
    try:
        import black  # type: ignore
        mode = black.Mode(line_length=line_length)
        try:
            formatted = black.format_str(source, mode=mode)
            if formatted == source:
                return "✔ Code is already correctly formatted (black)."
            diff_lines = sum(1 for a, b in zip(source.splitlines(), formatted.splitlines()) if a != b)
            return f"✘ Code needs formatting — approximately {diff_lines} line(s) differ (black)."
        except black.InvalidInput as e:
            return f"black check error: {e}"
    except ImportError:
        pass
    return "black is not installed — cannot do a format check.\nRun:  pip install black"


# ── style check ───────────────────────────────────────────────────────────────

def _check_style(source: str) -> str:
    lines  = source.splitlines()
    issues: list[str] = []

    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        # Trailing whitespace
        if line != stripped:
            issues.append(f"  Line {i:4}: trailing whitespace")
        # Line length
        if len(stripped) > 79:
            issues.append(f"  Line {i:4}: line too long ({len(stripped)} > 79 chars)")
        # Tabs
        if "\t" in line:
            issues.append(f"  Line {i:4}: tab character (use 4 spaces)")
        # Missing space after comma
        if re.search(r",\S", stripped):
            issues.append(f"  Line {i:4}: missing space after comma")
        # Operator spacing
        if re.search(r"\w[+\-*/%]=?\w", stripped) and not re.search(r"['\"]", stripped):
            pass  # Too noisy — skip
        # Double blank lines before top-level def/class
        if re.match(r"^(def |class |async def )", stripped):
            if i >= 2 and lines[i - 2].strip():
                issues.append(f"  Line {i:4}: expected 2 blank lines before top-level {stripped[:20]}...")

    if not issues:
        return "  ✔ No style violations found."
    return f"{len(issues)} style issue(s):\n" + "\n".join(issues[:100])


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_opts(opts: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not opts or not opts.strip():
        return result
    for part in opts.split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip().lower()] = v.strip()
    return result
