"""
MemoryManager — Persistent and session memory for the Aether OS.
Supports key-value storage, list appending, and JSON file persistence.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_FILE = Path(__file__).parent / "memory_store.json"


class MemoryManager:
    """
    Dual-mode memory: in-memory dict + optional JSON persistence.

    Keys can hold any JSON-serializable value.
    Use `append` for list-based history keys (e.g. chat history).
    """

    def __init__(self, persist: bool = True):
        self._store: dict[str, Any] = {}
        self._persist = persist
        if persist and _MEMORY_FILE.exists():
            self._load()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def save(self, key: str, value: Any) -> None:
        """Store or overwrite a value by key."""
        self._store[key] = value
        self._flush()

    def load(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key, returning `default` if absent."""
        return self._store.get(key, default)

    def append(self, key: str, value: Any) -> None:
        """Append a value to a list stored at `key`."""
        existing = self._store.get(key, [])
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(value)
        self._store[key] = existing
        self._flush()

    def delete(self, key: str) -> bool:
        """Remove a key. Returns True if it existed."""
        if key in self._store:
            del self._store[key]
            self._flush()
            return True
        return False

    def clear(self) -> None:
        """Wipe all memory (in-memory and persisted file)."""
        self._store.clear()
        self._flush()
        logger.info("MemoryManager: all memory cleared.")

    def keys(self) -> list[str]:
        return list(self._store.keys())

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the entire memory store."""
        return dict(self._store)

    def __contains__(self, key: str) -> bool:
        return key in self._store

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _flush(self) -> None:
        if not self._persist:
            return
        try:
            _MEMORY_FILE.write_text(json.dumps(self._store, indent=2, default=str))
        except OSError as exc:
            logger.error("MemoryManager: failed to persist memory: %s", exc)

    def _load(self) -> None:
        try:
            self._store = json.loads(_MEMORY_FILE.read_text())
            logger.info("MemoryManager: loaded %d key(s) from store.", len(self._store))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("MemoryManager: failed to load memory: %s", exc)
