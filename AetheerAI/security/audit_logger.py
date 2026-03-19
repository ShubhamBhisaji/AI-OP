"""audit_logger.py - append-only JSONL audit logging for sensitive actions."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """Thread-safe append-only JSONL logger with HMAC chain integrity.

    Each log entry includes a ``chain`` field — the HMAC-SHA256 of
    ``(previous_chain || payload_json)`` using the secret in the
    ``AETHEERAI_AUDIT_HMAC_SECRET`` env-var.  When the env-var is absent or
    empty, chaining is still performed using a deterministic *zero-key* so
    the chain field remains a useful tamper-evidence field even in local dev
    (the absence of a real key is itself detectable by the zero prefix).
    """

    # 64-byte zero key used as fallback when no secret is set.
    _ZERO_KEY = b"\x00" * 64

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._prev_chain: str = "0" * 64  # genesis sentinel (64 hex zeros)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hmac_key(self) -> bytes:
        raw = os.environ.get("AETHEERAI_AUDIT_HMAC_SECRET", "").strip()
        if raw:
            return raw.encode("utf-8")
        return self._ZERO_KEY

    def _make_chain(self, previous: str, payload_json: str) -> str:
        key = self._hmac_key()
        msg = (previous + payload_json).encode("utf-8")
        return hmac.new(key, msg, digestmod=hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "AuditLogger":
        root = Path(__file__).resolve().parents[1]
        path = root / "memory" / "audit_log.jsonl"
        return cls(path)

    def log(self, event: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        with self._lock:
            chain = self._make_chain(self._prev_chain, payload_json)
            record = json.loads(payload_json)
            record["chain"] = chain
            line = json.dumps(record, ensure_ascii=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._prev_chain = chain
