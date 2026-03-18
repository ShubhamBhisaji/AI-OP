"""Security boundary tests for the tool synthesizer's _validate_source() guardrails.

Ensures that banned names, banned imports, and banned attribute chains are
correctly rejected, while legitimate code passes validation.
"""

from __future__ import annotations

import pytest
import sys
import os

# Make AetheerAI importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.tool_synthesizer import SynthesisSecurityError, _validate_source


# ── Banned built-in names ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["exec", "eval", "compile", "__import__", "open", "breakpoint"])
def test_banned_names_rejected(name: str) -> None:
    source = f"def tool(input: str) -> str:\n    return {name}('hello')\n"
    with pytest.raises(SynthesisSecurityError, match="Banned"):
        _validate_source(source)


# ── Banned imports ────────────────────────────────────────────────────────

@pytest.mark.parametrize("module", ["subprocess", "os", "socket", "requests", "httpx", "aiohttp"])
def test_banned_imports_rejected(module: str) -> None:
    source = f"import {module}\ndef tool(input: str) -> str:\n    return ''\n"
    with pytest.raises(SynthesisSecurityError, match="Disallowed import"):
        _validate_source(source)


@pytest.mark.parametrize("module", ["subprocess", "os", "socket"])
def test_banned_from_imports_rejected(module: str) -> None:
    source = f"from {module} import *\ndef tool(input: str) -> str:\n    return ''\n"
    with pytest.raises(SynthesisSecurityError, match="Disallowed import"):
        _validate_source(source)


# ── Banned attribute chains ───────────────────────────────────────────────

@pytest.mark.parametrize("chain", [
    "os.system('ls')",
    "os.popen('id')",
    "subprocess.run(['ls'])",
    "subprocess.call(['ls'])",
    "subprocess.Popen(['ls'])",
    "socket.socket()",
])
def test_banned_attr_chains_rejected(chain: str) -> None:
    # Need to import the module for the attribute chain to be valid AST
    mod = chain.split(".")[0]
    source = f"import {mod}\ndef tool(input: str) -> str:\n    {chain}\n    return ''\n"
    with pytest.raises(SynthesisSecurityError):
        _validate_source(source)


# ── Allowed imports pass ──────────────────────────────────────────────────

@pytest.mark.parametrize("module", ["json", "re", "urllib.request", "datetime", "base64", "hashlib"])
def test_allowed_imports_pass(module: str) -> None:
    source = f"import {module}\ndef tool(input: str) -> str:\n    return ''\n"
    _validate_source(source)  # should not raise


# ── Clean function passes ────────────────────────────────────────────────

def test_clean_function_passes() -> None:
    source = (
        "import json\n"
        "import urllib.request\n"
        "\n"
        "def my_api_tool(input: str) -> str:\n"
        "    url = 'https://api.example.com/data'\n"
        "    req = urllib.request.Request(url)\n"
        "    try:\n"
        "        with urllib.request.urlopen(req, timeout=10) as resp:\n"
        "            data = json.loads(resp.read())\n"
        "            return json.dumps(data, indent=2)\n"
        "    except Exception as e:\n"
        "        return f'Error: {e}'\n"
    )
    _validate_source(source)  # should not raise


# ── Encoded bypass attempt ───────────────────────────────────────────────

def test_encoded_payload_not_executable() -> None:
    """Even if someone base64-encodes dangerous code, the AST scanner only sees
    the decode call — the decoded string is never exec'd by _validate_source."""
    source = (
        "import base64\n"
        "def tool(input: str) -> str:\n"
        "    payload = base64.b64decode('aW1wb3J0IG9z')\n"
        "    return payload.decode()\n"
    )
    # This should pass — the decoded string 'import os' is data, not code.
    # The synthesizer never exec()s arbitrary decoded strings.
    _validate_source(source)  # should not raise


def test_syntax_error_caught() -> None:
    source = "def tool(input str) -> str:\n    return ''\n"
    with pytest.raises(SynthesisSecurityError, match="Syntax error"):
        _validate_source(source)
