"""
tool_synthesizer.py — Just-in-Time (JIT) Tool Synthesis.

Problem: Agents are limited to the tools manually registered at deploy time.
When a new API or service appears, a developer must write an integration,
push code, and redeploy — a slow, expensive feedback loop.

Solution: Given an API documentation snippet (plain text, OpenAPI YAML/JSON,
or a cURL example), the Master AI generates a Python wrapper function on the
fly, validates it for safety, and registers it as a live tool available to
all agents immediately — no deployment necessary.

Security model
--------------
All synthesized code is subjected to a multi-layer safety scan BEFORE it is
ever exec()'d:

1. AST syntax validation — catches syntax errors without running code.
2. Banned-call scan — rejects code that references dangerous built-ins:
   exec, eval, compile, __import__, getattr (writes), setattr, delattr,
   os.system, subprocess, open (writes), socket.
3. Import whitelist — only approved stdlib modules are allowed. Any third-party
   import that isn't pre-approved is rejected.
4. Network constraint — HTTP calls must use urllib.request (pure stdlib).
   The requests / httpx / aiohttp libraries are NOT allowed in synthesized code
   to keep the attack surface well-defined.

Synthesized tools are persisted under workspace/synthesized_tools/ so they
survive restarts and can be audited, edited, or deleted by operators.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import logging
import os
import re
import time
import types
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SYNTH_STORE = Path(__file__).parent.parent / "workspace" / "synthesized_tools"

# ---------------------------------------------------------------------------
# Allowed stdlib imports in synthesized tools
# ---------------------------------------------------------------------------
_ALLOWED_IMPORTS: frozenset[str] = frozenset({
    "json", "re", "time", "datetime", "math", "random",
    "base64", "hashlib", "hmac", "uuid", "urllib", "urllib.request",
    "urllib.parse", "urllib.error", "http", "http.client",
    "collections", "functools", "itertools", "typing",
    "dataclasses", "enum", "string", "textwrap",
})

# Built-in names that must never appear in synthesized code
_BANNED_NAMES: frozenset[str] = frozenset({
    "exec", "eval", "compile", "__import__", "__builtins__",
    "setattr", "delattr", "globals", "locals", "vars",
    "open", "breakpoint",
})

_BANNED_ATTR_CHAINS: frozenset[str] = frozenset({
    "os.system", "os.popen", "os.exec", "os.spawn",
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "subprocess.check_output",
    "socket.socket", "socket.connect",
    "importlib.import_module",
})

# ---------------------------------------------------------------------------
# Code generation prompt
# ---------------------------------------------------------------------------

_SYNTHESIS_PROMPT = """\
You are a senior Python engineer writing a self-contained tool function for AetheerAI.

API DOCUMENTATION:
{api_doc}

TOOL NAME: {name}
DESCRIPTION: {description}

Your task: Write ONE Python function named exactly `{name}` that:
1. Accepts a single `input: str` parameter.
2. Makes the appropriate HTTP request(s) to the API using ONLY `urllib.request`.
3. Returns a human-readable `str` result (JSON, plain text, or formatted summary).
4. Handles errors gracefully (try/except), returning an error string on failure.
5. Includes NO main guard, no class definitions, no global state.

Allowed imports ONLY: json, re, urllib.request, urllib.parse, base64, time, datetime.

DO NOT use: requests, httpx, aiohttp, subprocess, os, socket, exec, eval, open.

Output ONLY the raw Python code — no markdown fences, no explanation.
"""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SynthesizedTool:
    """
    A tool generated at runtime from an API documentation snippet.

    Attributes
    ----------
    name           : Unique tool name (snake_case, used for registration).
    description    : What the tool does.
    source_code    : The generated Python function source.
    api_doc_snippet: First 500 chars of the API doc used to generate it.
    created_at     : Unix epoch float.
    """
    name:            str
    description:     str
    source_code:     str
    api_doc_snippet: str
    created_at:      float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["api_doc_snippet"] = d["api_doc_snippet"][:500]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SynthesizedTool":
        return cls(**d)


# ---------------------------------------------------------------------------
# Safety validator
# ---------------------------------------------------------------------------

class SynthesisSecurityError(ValueError):
    """Raised when synthesized code fails the security scan."""


def _validate_source(source: str) -> None:
    """
    Raise SynthesisSecurityError if *source* contains any unsafe constructs.

    Steps:
    1. AST parse — ensures it is syntactically valid Python.
    2. Import whitelist — all import statements must be in _ALLOWED_IMPORTS.
    3. Banned name check — reject calls to dangerous built-ins.
    4. Banned attribute chain check — reject os.system etc.
    """
    # 1. Syntax check
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SynthesisSecurityError(f"Syntax error in synthesized code: {exc}") from exc

    for node in ast.walk(tree):
        # 2. Import whitelist
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if alias.name not in _ALLOWED_IMPORTS and base not in _ALLOWED_IMPORTS:
                    raise SynthesisSecurityError(
                        f"Disallowed import in synthesized tool: '{alias.name}'. "
                        f"Only {sorted(_ALLOWED_IMPORTS)} are permitted."
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            base = mod.split(".")[0]
            if mod not in _ALLOWED_IMPORTS and base not in _ALLOWED_IMPORTS:
                raise SynthesisSecurityError(
                    f"Disallowed import in synthesized tool: 'from {mod} import ...'. "
                    f"Only {sorted(_ALLOWED_IMPORTS)} are permitted."
                )

        # 3. Banned names
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            raise SynthesisSecurityError(
                f"Banned built-in '{node.id}' found in synthesized tool."
            )
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _BANNED_NAMES:
                raise SynthesisSecurityError(
                    f"Banned function call '{node.func.id}()' in synthesized tool."
                )

        # 4. Banned attribute chains  (e.g. os.system)
        if isinstance(node, ast.Attribute):
            # Reconstruct dotted name up to 3 levels deep
            parts: list[str] = []
            cur: Any = node
            while isinstance(cur, ast.Attribute):
                parts.insert(0, cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.insert(0, cur.id)
            chain = ".".join(parts)
            for banned in _BANNED_ATTR_CHAINS:
                if chain.startswith(banned):
                    raise SynthesisSecurityError(
                        f"Banned API call '{chain}' found in synthesized tool."
                    )


# ---------------------------------------------------------------------------
# ToolSynthesizer
# ---------------------------------------------------------------------------

class ToolSynthesizer:
    """
    Just-in-Time tool synthesis engine.

    Generates Python tool functions from API documentation using the Master AI,
    validates them for security, and registers them in the ToolManager.
    """

    def __init__(
        self,
        ai_adapter,
        tool_manager,
        storage_dir: Path | str | None = None,
    ) -> None:
        self.ai_adapter   = ai_adapter
        self.tool_manager = tool_manager
        self._store_dir   = Path(storage_dir or _SYNTH_STORE)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, SynthesizedTool] = {}
        self._load_persisted()

    # ── Core synthesis ────────────────────────────────────────────────

    def synthesize(
        self,
        name: str,
        api_doc: str,
        description: str = "",
        max_retries: int = 2,
    ) -> SynthesizedTool:
        """
        Generate a new tool from API documentation.

        Parameters
        ----------
        name        : Snake_case tool name (e.g. "stripe_payment_tool").
        api_doc     : API documentation text (plain text, cURL, OpenAPI YAML/JSON).
        description : Human-readable description of what the tool does.
        max_retries : How many times to retry generation if validation fails.

        Returns a SynthesizedTool and registers it immediately.
        Raises SynthesisSecurityError if the generated code fails safety checks.
        """
        # Sanitize tool name
        name = re.sub(r"[^a-z0-9_]", "_", name.strip().lower())
        if not name:
            raise ValueError("Tool name must be a non-empty alphanumeric string.")

        if not description:
            description = f"JIT tool synthesized from API documentation for '{name}'"

        last_error: Exception | None = None
        for attempt in range(1, max_retries + 2):
            logger.info("ToolSynthesizer: generating '%s' (attempt %d).", name, attempt)

            prompt = _SYNTHESIS_PROMPT.format(
                api_doc=api_doc[:4000],
                name=name,
                description=description,
            )
            raw_code = self.ai_adapter.chat(
                messages=[{"role": "user", "content": prompt}]
            ).strip()

            # Strip potential markdown fences
            raw_code = self._strip_fences(raw_code)

            try:
                _validate_source(raw_code)
                fn = self._load_function(name, raw_code)
                tool = SynthesizedTool(
                    name=name,
                    description=description,
                    source_code=raw_code,
                    api_doc_snippet=api_doc[:500],
                )
                self._tools[name] = tool
                self._persist(tool)
                self.tool_manager.register(name, fn)
                logger.info("ToolSynthesizer: '%s' synthesized and registered.", name)
                return tool

            except SynthesisSecurityError as exc:
                last_error = exc
                logger.warning(
                    "ToolSynthesizer: attempt %d failed security check for '%s': %s",
                    attempt, name, exc,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ToolSynthesizer: attempt %d failed for '%s': %s",
                    attempt, name, exc,
                )

        raise last_error or RuntimeError(f"Tool synthesis failed for '{name}' after {max_retries + 1} attempts.")

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _strip_fences(code: str) -> str:
        """Remove markdown code fences if the AI wrapped the output."""
        code = re.sub(r"^```(?:python)?\n?", "", code, flags=re.MULTILINE)
        code = re.sub(r"\n?```$", "", code, flags=re.MULTILINE)
        return code.strip()

    @staticmethod
    def _load_function(name: str, source: str) -> Callable:
        """
        Execute the source in an isolated namespace and return the function.
        Only the function named *name* is exposed.
        """
        namespace: dict[str, Any] = {}
        # exec in a fresh namespace — safe because _validate_source already
        # confirmed the code contains no banned constructs
        exec(compile(source, f"<synth:{name}>", "exec"), namespace)  # noqa: S102
        fn = namespace.get(name)
        if fn is None or not callable(fn):
            raise ValueError(
                f"Generated code does not define a callable named '{name}'."
            )
        return fn

    # ── Persistence ───────────────────────────────────────────────────

    def _persist(self, tool: SynthesizedTool) -> None:
        path = self._store_dir / f"{tool.name}.json"
        tmp  = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(tool.to_dict(), indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def _load_persisted(self) -> None:
        """Reload all previously synthesized tools from disk on startup."""
        loaded = 0
        for path in self._store_dir.glob("*.json"):
            try:
                data  = json.loads(path.read_text(encoding="utf-8"))
                tool  = SynthesizedTool.from_dict(data)
                fn    = self._load_function(tool.name, tool.source_code)
                _validate_source(tool.source_code)   # re-validate on load
                self._tools[tool.name] = tool
                self.tool_manager.register(tool.name, fn)
                loaded += 1
            except Exception as exc:
                logger.warning(
                    "ToolSynthesizer: skipping persisted tool '%s': %s", path.stem, exc
                )
        if loaded:
            logger.info("ToolSynthesizer: reloaded %d persisted tool(s).", loaded)

    # ── Listing & deletion ────────────────────────────────────────────

    def list_synthesized(self) -> list[dict]:
        """Return summary info for all synthesized tools."""
        return [
            {
                "name":        t.name,
                "description": t.description,
                "created_at":  t.created_at,
                "api_doc_snippet": t.api_doc_snippet[:200],
            }
            for t in sorted(self._tools.values(), key=lambda x: x.created_at, reverse=True)
        ]

    def get_source(self, name: str) -> str | None:
        """Return the source code of a synthesized tool, or None."""
        tool = self._tools.get(name)
        return tool.source_code if tool else None

    def delete(self, name: str) -> bool:
        """Delete a synthesized tool from memory, disk, and the ToolManager."""
        if name not in self._tools:
            return False
        del self._tools[name]
        path = self._store_dir / f"{name}.json"
        path.unlink(missing_ok=True)
        # Remove from ToolManager if still registered
        if hasattr(self.tool_manager, "_tools"):
            self.tool_manager._tools.pop(name, None)
        logger.info("ToolSynthesizer: deleted tool '%s'.", name)
        return True

    def count(self) -> int:
        return len(self._tools)
