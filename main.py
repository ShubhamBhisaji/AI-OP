"""
main.py — AetheerAI — An AI Master!!
=====================================
THE single entry point for the entire application.

Usage
-----
  python main.py                          # Interactive CLI  (default)
  python main.py --provider claude        # CLI with a specific AI provider
  python main.py --provider ollama --model llama3

  python main.py --gui                    # Streamlit dashboard (browser UI)
  python main.py --api                    # FastAPI / REST server
  python main.py --api --host 127.0.0.1 --port 9000 --reload
  python main.py --launcher               # Silent GUI launcher (splash + browser)

  python main.py --pipeline                               # Process default dataset
  python main.py --pipeline --input data/raw/agent_runs.csv
  python main.py --pipeline --input data/raw/my.csv --format jsonl

Modes at a glance
-----------------
  (default / --cli)   Interactive terminal — chat, run agents, manage tasks
  --gui               Full Streamlit web dashboard at http://localhost:8501
  --api               FastAPI REST server   at http://localhost:8000/docs
  --launcher          Desktop launcher with splash screen (no console)
  --pipeline          Data pipeline: Ingest → Process → Export
"""

from __future__ import annotations

import argparse
import os
import sys
import subprocess

# ── Make AetheerAI/ importable from the project root ─────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
_AETHEER_DIR = os.path.join(_ROOT, "AetheerAI")
for _p in (_ROOT, _AETHEER_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="AetheerAI — An AI Master!!  |  Single unified entry point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── Mode flags (mutually exclusive) ──────────────────────────────────────
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--cli",
        action="store_true",
        default=False,
        help="Interactive CLI mode (default when no mode flag is given)",
    )
    mode.add_argument(
        "--gui",
        action="store_true",
        help="Launch the Streamlit web dashboard (opens at http://localhost:8501)",
    )
    mode.add_argument(
        "--api",
        action="store_true",
        help="Start the FastAPI REST server (docs at http://localhost:8000/docs)",
    )
    mode.add_argument(
        "--launcher",
        action="store_true",
        help="Open the silent desktop launcher with splash screen",
    )
    mode.add_argument(
        "--pipeline",
        action="store_true",
        help="Run the data pipeline: Ingest → Process → Export",
    )

    # ── CLI-mode options ──────────────────────────────────────────────────────
    cli_group = parser.add_argument_group("CLI options")
    cli_group.add_argument(
        "--provider",
        default=None,
        choices=["github", "openai", "claude", "gemini", "ollama", "huggingface"],
        metavar="PROVIDER",
        help="AI provider to use (skips interactive menu). "
             "Choices: github | openai | claude | gemini | ollama | huggingface",
    )
    cli_group.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Model name override (uses provider default if omitted)",
    )

    # ── Pipeline-mode options ──────────────────────────────────────────────────
    pipe_group = parser.add_argument_group("Pipeline options (--pipeline mode)")
    pipe_group.add_argument(
        "--input",
        default=None,
        metavar="FILE",
        help="CSV file to ingest (default: data/raw/agent_runs.csv)",
    )
    pipe_group.add_argument(
        "--format",
        choices=["csv", "jsonl"],
        default="csv",
        dest="output_format",
        metavar="FMT",
        help="Output format for processed data: csv (default) or jsonl",
    )

    # ── API-mode options ──────────────────────────────────────────────────────
    api_group = parser.add_argument_group("API options (--api mode)")
    api_group.add_argument(
        "--host",
        default=None,
        metavar="HOST",
        help="Host/IP to bind to (default: 0.0.0.0 or AETHER_HOST env var)",
    )
    api_group.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="TCP port (default: 8000 or AETHER_PORT env var)",
    )
    api_group.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on source changes (development only)",
    )
    api_group.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of Uvicorn worker processes",
    )

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# Mode runners
# ─────────────────────────────────────────────────────────────────────────────

def _run_cli(args: argparse.Namespace) -> None:
    """Run the interactive CLI (AetheerAI/main.py logic, in-process)."""
    # Patch sys.argv so AetheerAI/main.py's own argparse sees only CLI flags
    forwarded = [sys.argv[0]]
    if args.provider:
        forwarded += ["--provider", args.provider]
    if args.model:
        forwarded += ["--model", args.model]
    sys.argv = forwarded

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "aetheerai_main",
        os.path.join(_AETHEER_DIR, "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.main()


def _run_gui() -> None:
    """Launch the Streamlit dashboard (subprocess so Streamlit owns the process)."""
    app_path = os.path.join(_AETHEER_DIR, "app.py")
    cmd = [sys.executable, "-m", "streamlit", "run", app_path,
           "--server.headless", "false"]
    print("Starting Streamlit dashboard → http://localhost:8501")
    print("Press Ctrl+C to stop.\n")
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


def _run_api(args: argparse.Namespace) -> None:
    """Launch the FastAPI / Uvicorn REST server (subprocess)."""
    script = os.path.join(_AETHEER_DIR, "start_api.py")
    cmd = [sys.executable, script]
    if args.host:
        cmd += ["--host", args.host]
    if args.port:
        cmd += ["--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")
    if args.workers:
        cmd += ["--workers", str(args.workers)]

    host = args.host or os.getenv("AETHER_HOST", "0.0.0.0")
    port = args.port or int(os.getenv("AETHER_PORT", "8000"))
    print(f"Starting REST API → http://{host}:{port}/docs")
    print("Press Ctrl+C to stop.\n")
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\nAPI server stopped.")


def _run_pipeline(args: argparse.Namespace) -> None:
    """Run the three-stage data pipeline (Ingest → Process → Export)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "data_pipeline",
        os.path.join(_AETHEER_DIR, "core", "data_pipeline.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    # Register before exec so @dataclass can resolve cls.__module__
    sys.modules["data_pipeline"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    pipeline = mod.DataPipeline()

    source = args.input if args.input else os.path.join(
        _ROOT, "data", "raw", "agent_runs.csv"
    )
    result = pipeline.run(source=source, output_format=args.output_format)

    print()
    print("=" * 60)
    print("  AetheerAI Data Pipeline — Results")
    print("=" * 60)
    print(f"  Input        : {source}")
    print(f"  Raw rows     : {result.raw_rows}")
    print(f"  Clean rows   : {result.clean_rows}")
    print(f"  Dropped rows : {result.dropped_rows}")
    if result.output_path:
        print(f"  Output       : {result.output_path}")
    if result.summary:
        s = result.summary
        print(f"  Success rate : {s.get('overall_success_rate', 0):.1%}")
        print(f"  Total cost   : ${s.get('total_cost_usd', 0):.4f}")
        print(f"  Total tokens : {s.get('total_tokens', 0):,}")
        print(f"  Avg latency  : {s.get('avg_latency_ms', 0):.0f} ms")
    fatal = [e for e in result.errors if "not found" in e or "parse error" in e]
    if fatal:
        for msg in fatal:
            print(f"  ERROR: {msg}")
    print("=" * 60)
    print()


def _run_launcher() -> None:
    """Run the silent GUI launcher (AetheerAI/launcher.py, in-process)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "aetheerai_launcher",
        os.path.join(_AETHEER_DIR, "launcher.py"),
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if hasattr(mod, "main"):
        mod.main()
    elif hasattr(mod, "LauncherWindow"):
        mod.LauncherWindow().mainloop()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Determine mode — default is CLI when no mode flag is provided
    if args.gui:
        _run_gui()
    elif args.api:
        _run_api(args)
    elif args.launcher:
        _run_launcher()
    elif args.pipeline:
        _run_pipeline(args)
    else:
        # --cli (explicit) OR no flag at all → interactive CLI
        _run_cli(args)


if __name__ == "__main__":
    main()
