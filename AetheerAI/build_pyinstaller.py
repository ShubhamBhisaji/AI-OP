#!/usr/bin/env python3
"""
AetheerAI PyInstaller build helper.
Called by launchers/build_setup_exe.bat to avoid CMD ^ continuation issues.
"""
import os
import sys
import pathlib

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE   = pathlib.Path(__file__).parent.resolve()   # AetheerAI/
OUTPUT = HERE.parent / "output"                    # ../output/
DIST   = OUTPUT / "dist"
BUILD  = OUTPUT / "build"
SPEC   = OUTPUT

# Ensure output dirs exist
for _d in (DIST, BUILD, SPEC, OUTPUT / "agent_output"):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Streamlit location
# ---------------------------------------------------------------------------
try:
    import streamlit as _st
    STREAMLIT = pathlib.Path(_st.__file__).parent
except ImportError:
    print("[ERROR] streamlit not installed. Run: pip install streamlit")
    sys.exit(1)

# Use semicolon separator (Windows os.pathsep) — works with all PyInstaller versions
SEP = ";"


def ad(src, dest):
    """Format an --add-data argument."""
    return f"{src}{SEP}{dest}"


# ---------------------------------------------------------------------------
# PyInstaller arguments
# ---------------------------------------------------------------------------
args = [
    "launcher.py",          # script FIRST — most compatible position
    "--onefile",
    "--windowed",
    "--name", "AetheerAI_Master",
    "--distpath",  str(DIST),
    "--workpath",  str(BUILD),
    "--specpath",  str(SPEC),

    # ---- Streamlit assets ----
    "--add-data", ad(STREAMLIT / "static",     "streamlit/static"),
    "--add-data", ad(STREAMLIT / "runtime",    "streamlit/runtime"),
    "--add-data", ad(STREAMLIT / "components", "streamlit/components"),

    # ---- Source directories ----
    "--add-data", ad(HERE / "app.py",      "."),
    "--add-data", ad(HERE / "agents",      "agents"),
    "--add-data", ad(HERE / "ai",          "ai"),
    "--add-data", ad(HERE / "cli",         "cli"),
    "--add-data", ad(HERE / "core",        "core"),
    "--add-data", ad(HERE / "evals",       "evals"),
    "--add-data", ad(HERE / "factory",     "factory"),
    "--add-data", ad(HERE / "memory",      "memory"),
    "--add-data", ad(HERE / "registry",    "registry"),
    "--add-data", ad(HERE / "security",    "security"),
    "--add-data", ad(HERE / "skills",      "skills"),
    "--add-data", ad(HERE / "templates",   "templates"),
    "--add-data", ad(HERE / "tools",       "tools"),
    "--add-data", ad(HERE / "utils",       "utils"),
    "--add-data", ad(HERE / "workspace",   "workspace"),

    # ---- Runtime output / data files ----
    "--add-data", ad(OUTPUT / "agent_output",                      "agent_output"),
    "--add-data", ad(HERE / "memory"   / "memory_store.json",      "memory"),
    "--add-data", ad(HERE / "registry" / "registry_store.json",    "registry"),

    # ---- Hidden imports ----
    "--hidden-import", "streamlit",
    "--hidden-import", "chromadb",
    "--hidden-import", "chromadb.api",
    "--hidden-import", "openai",
    "--hidden-import", "anthropic",
    "--hidden-import", "yaml",
    "--hidden-import", "dotenv",
    "--hidden-import", "tiktoken",
    "--hidden-import", "tiktoken_ext",
    "--hidden-import", "tiktoken_ext.openai_public",
    "--hidden-import", "pydantic",
    "--hidden-import", "uvicorn",
    "--hidden-import", "requests",
    "--hidden-import", "bs4",
    "--hidden-import", "pandas",
    "--hidden-import", "PIL",
    "--hidden-import", "cryptography",
    "--hidden-import", "threading",
    "--hidden-import", "concurrent.futures",
    "--hidden-import", "litellm",
    "--hidden-import", "litellm.main",
    "--hidden-import", "litellm.utils",
    "--hidden-import", "litellm.exceptions",
    "--hidden-import", "imaplib",
    "--hidden-import", "smtplib",
    "--hidden-import", "email",
    "--hidden-import", "email.mime.text",
    "--hidden-import", "email.mime.multipart",
    "--hidden-import", "email.mime.base",
    "--hidden-import", "email.encoders",
    "--hidden-import", "ssl",
    "--hidden-import", "socket",
    "--hidden-import", "ipaddress",
    "--hidden-import", "csv",
    "--hidden-import", "ast",
    "--hidden-import", "hashlib",
    "--hidden-import", "base64",
    "--hidden-import", "difflib",
    "--hidden-import", "fnmatch",
    "--hidden-import", "stat",
    "--hidden-import", "sysconfig",
    "--hidden-import", "textwrap",
    "--hidden-import", "webbrowser",
    "--hidden-import", "shlex",
    "--hidden-import", "opentelemetry",
    "--hidden-import", "opentelemetry.instrumentation",
    "--hidden-import", "backoff",

    # ---- Submodule collection ----
    "--collect-submodules", "chromadb",
    "--collect-submodules", "tiktoken_ext",
    "--collect-submodules", "streamlit",
    "--collect-submodules", "litellm",

    "--copy-metadata", "streamlit",
]

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
os.chdir(HERE)
print(f"  PyInstaller build starting from: {HERE}")
print(f"  Output directory: {OUTPUT}")
print()

from PyInstaller.__main__ import run as _pyi_run
_pyi_run(args)
