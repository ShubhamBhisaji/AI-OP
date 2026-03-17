"""
utils/log_config.py — Centralised logging configuration for AetheerAI.

Call ``setup_logging()`` once at process startup (main.py, start_api.py,
app.py).  Every module that already does::

    import logging
    logger = logging.getLogger(__name__)

will automatically inherit the handlers and format — no changes required.

Log outputs
-----------
Console          Human-readable coloured output (stderr).
logs/aetheerai.log  Rotating plain-text log — all levels at or above LOG_LEVEL.
logs/error.log   Rotating plain-text log — ERROR and CRITICAL only.

Environment variables
---------------------
LOG_LEVEL    Any stdlib level name (DEBUG/INFO/WARNING/ERROR/CRITICAL).
             Defaults to ``INFO``.
LOG_DIR      Directory for log files.  Defaults to ``<project-root>/logs``.
LOG_JSON     Set to ``1`` / ``true`` / ``yes`` to write JSON lines to the
             rotating files instead of plain text.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time

# ── Constants ──────────────────────────────────────────────────────────────────
_SENTINEL_ATTR = "_aetheerai_logging_configured"

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..")
)

# 10 MB per file, keep 5 backups  →  ≤ 50 MB on disk
_MAX_BYTES: int = 10 * 1024 * 1024
_BACKUP_COUNT: int = 5

# ── ANSI colour helpers (console only) ────────────────────────────────────────
_COLOURS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARNING":  "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[41m",   # red background
    "RESET":    "\033[0m",
}
_USE_COLOUR = sys.stderr.isatty() and os.name != "nt" or (
    os.name == "nt" and os.environ.get("TERM_PROGRAM") in ("vscode", "WindowsTerminal")
    or os.environ.get("FORCE_COLOR") in ("1", "true", "yes")
)


class _ColourFormatter(logging.Formatter):
    """Console formatter: ``HH:MM:SS.mmm  LEVEL  logger.name  message``."""

    _FMT = "{time}  {level_col}{level:<8}{reset}  {dim}{name}{reset}  {msg}{extra}"

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        ms = f"{record.msecs:03.0f}"
        level_col = _COLOURS.get(record.levelname, "") if _USE_COLOUR else ""
        dim = "\033[2m" if _USE_COLOUR else ""
        reset = _COLOURS["RESET"] if _USE_COLOUR else ""

        # Include exception info when present
        extra = ""
        if record.exc_info:
            extra = "\n" + self.formatException(record.exc_info)

        return self._FMT.format(
            time=f"{ts}.{ms}",
            level_col=level_col,
            level=record.levelname,
            dim=dim,
            name=record.name,
            reset=reset,
            msg=record.getMessage(),
            extra=extra,
        )


class _JsonFormatter(logging.Formatter):
    """Rotating-file formatter: one JSON object per line (JSONL)."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "ms": int(record.msecs),
            "level": record.levelname,
            "logger": record.name,
            "file": f"{record.filename}:{record.lineno}",
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _PlainFormatter(logging.Formatter):
    """Rotating-file formatter: plain, grep-friendly text."""

    _FMT = "%(asctime)s  %(levelname)-8s  %(name)s  [%(filename)s:%(lineno)d]  %(message)s"
    _DATEFMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self._FMT, datefmt=self._DATEFMT)


# ── Public API ─────────────────────────────────────────────────────────────────

def setup_logging(
    level: str | int | None = None,
    log_dir: str | None = None,
    json_logs: bool | None = None,
) -> None:
    """Configure the root logger.  Safe to call multiple times — idempotent after first call.

    Parameters
    ----------
    level:
        Logging threshold.  Falls back to ``LOG_LEVEL`` env-var, then ``INFO``.
    log_dir:
        Directory where rotating log files are written.
        Falls back to ``LOG_DIR`` env-var, then ``<project-root>/logs``.
    json_logs:
        Write JSONL to rotating files instead of plain text.
        Falls back to ``LOG_JSON`` env-var.
    """
    root = logging.getLogger()

    # Idempotency guard — only configure once per process
    if getattr(root, _SENTINEL_ATTR, False):
        return
    setattr(root, _SENTINEL_ATTR, True)

    # ── Resolve parameters ─────────────────────────────────────────────────
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()
    if isinstance(level, str):
        level = getattr(logging, level, logging.INFO)

    if log_dir is None:
        log_dir = os.getenv("LOG_DIR", os.path.join(_PROJECT_ROOT, "logs"))

    if json_logs is None:
        json_logs = os.getenv("LOG_JSON", "0").lower() in ("1", "true", "yes")

    # ── Ensure log directory exists ────────────────────────────────────────
    os.makedirs(log_dir, exist_ok=True)

    root.setLevel(level)

    # ── 1. Console handler (stderr) ────────────────────────────────────────
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(_ColourFormatter())
    root.addHandler(console)

    # ── 2. Rotating file handler — all levels ──────────────────────────────
    file_formatter: logging.Formatter = _JsonFormatter() if json_logs else _PlainFormatter()

    all_log_path = os.path.join(log_dir, "aetheerai.log")
    rotating = logging.handlers.RotatingFileHandler(
        all_log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    rotating.setLevel(level)
    rotating.setFormatter(file_formatter)
    root.addHandler(rotating)

    # ── 3. Rotating file handler — errors only ─────────────────────────────
    err_log_path = os.path.join(log_dir, "error.log")
    err_handler = logging.handlers.RotatingFileHandler(
        err_log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(file_formatter)
    root.addHandler(err_handler)

    # ── Silence noisy third-party loggers ─────────────────────────────────
    for _noisy in ("httpx", "httpcore", "urllib3", "asyncio", "multipart"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    root.info(
        "Logging initialised — level=%s  dir=%s  json=%s",
        logging.getLevelName(level),
        log_dir,
        json_logs,
    )


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper: ``logger = get_logger(__name__)``."""
    return logging.getLogger(name)
