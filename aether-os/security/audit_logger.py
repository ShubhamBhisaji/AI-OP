"""audit_logger.py - append-only JSONL audit logging for sensitive actions."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """Thread-safe append-only JSONL logger."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> "AuditLogger":
        root = Path(__file__).resolve().parents[1]
        path = root / "memory" / "audit_log.jsonl"
        return cls(path)

    def log(self, event: dict[str, Any]) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
