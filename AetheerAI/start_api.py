"""
start_api.py — Launch the AetheerAI FastAPI / Uvicorn server.

Usage (from the AetheerAI/ directory):
    python start_api.py                          # default: http://0.0.0.0:8000
    python start_api.py --host 127.0.0.1         # bind to localhost only
    python start_api.py --port 9000              # custom port
    python start_api.py --reload                 # auto-reload on code changes
    python start_api.py --workers 4              # multiple workers (no reload)

Environment variables (can also be set in .env):
    AETHER_HOST      default: 0.0.0.0
    AETHER_PORT      default: 8000
    AETHER_RELOAD    default: false
    LOG_LEVEL        default: info
    CORS_ORIGINS     default: http://localhost:3000
"""

from __future__ import annotations

import argparse
import os
import sys

# ── Ensure the project root is importable ────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.env_loader import load_env as _load_env, check_env_file as _check_env_file

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_load_env(_ENV_PATH)
_check_env_file(_ENV_PATH)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AetheerAI REST API server (FastAPI + Uvicorn)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=os.getenv("AETHER_HOST", "0.0.0.0"),
        help="Host/IP address to bind to (use 127.0.0.1 for localhost-only).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("AETHER_PORT", "8000")),
        help="TCP port to listen on.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("AETHER_RELOAD", "false").lower() in ("1", "true", "yes"),
        help="Enable auto-reload on source changes (development only).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes (incompatible with --reload).",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "info").lower(),
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn log level.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # ── Initialise structured logging before importing anything else ──────
    from utils.log_config import setup_logging
    setup_logging(level=args.log_level.upper())

    import logging
    _log = logging.getLogger("aetheer.start_api")

    if args.reload and args.workers > 1:
        _log.warning("--reload is incompatible with --workers > 1; workers ignored.")
        args.workers = 1

    try:
        import uvicorn
    except ImportError:
        sys.exit(
            "[error] uvicorn is not installed.\n"
            "        Run:  pip install uvicorn[standard]"
        )

    _log.info("AetheerAI REST API starting up")
    _log.info("  Listening : http://%s:%s", args.host, args.port)
    _log.info("  Docs      : http://%s:%s/docs", args.host, args.port)
    _log.info("  ReDoc     : http://%s:%s/redoc", args.host, args.port)
    _log.info("  Health    : http://%s:%s/api/health", args.host, args.port)
    _log.info("  Reload    : %s  Workers: %s  Log level: %s",
              args.reload, args.workers, args.log_level)

    uvicorn.run(
        "api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else None,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
