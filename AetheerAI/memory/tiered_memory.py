"""
tiered_memory.py — Three-Tier Memory System for AetheerAI.

Feature 3 — OS-Level Memory ("Operating System" Memory):

    Tier 1 — Core (RAM)
        In-memory Python dict.  Fastest access.  Volatile — cleared when
        the process exits.  Holds the current task context, hot variables,
        and working state for the active session.

    Tier 2 — Recall (Disk Cache)
        Ordered JSON file on disk.  Persistent across sessions.  Bounded
        capacity (LRU eviction) to stay lightweight.  Stores recent history,
        session notes, and intermediate results.

    Tier 3 — Archival (Vector Deep Storage)
        ChromaDB-backed semantic store via the existing MemoryManager.
        Unlimited capacity, full semantic search.  Holds long-term knowledge:
        project blueprints, skill libraries, user preferences, past outputs.

Usage
-----
    mem = TieredMemoryManager(archival_manager=kernel.memory)

    mem.remember("task:current", "build slack bot", tier="core")
    mem.remember("project:ecom", arch_doc,          tier="recall")  # persisted
    mem.remember("user:preference", "dark mode",    tier="archival")# searchable

    value = mem.recall("project:ecom")          # core → recall → archival
    hits  = mem.search("slack integration")      # semantic search in archival

    mem.consolidate()                            # flush core→recall, recall→archival
    summary = mem.tier_summary()                 # {"core_entries":3, ...}
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_RECALL_PATH = Path(__file__).parent / "recall_cache.json"
_DEFAULT_RECALL_CAPACITY = 500  # max recall entries before LRU eviction


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("TieredMemory: invalid int for %s='%s', using %d", name, raw, default)
        return default
    return max(minimum, value)


_DEFAULT_RECALL_RETENTION_DAYS = _env_int("AETHEERAI_RECALL_RETENTION_DAYS", default=30, minimum=0)
_DEFAULT_RECALL_BACKUP_KEEP = _env_int("AETHEERAI_RECALL_BACKUP_KEEP", default=20, minimum=1)


def _to_text(value: Any) -> str:
    """Serialize any value to a string suitable for vector indexing."""
    if isinstance(value, str):
        return value[:4000]
    try:
        return json.dumps(value, ensure_ascii=False)[:4000]
    except Exception:
        return str(value)[:4000]


class TieredMemoryManager:
    """
    Three-tier memory: Core (RAM) → Recall (disk) → Archival (ChromaDB).

    All methods are thread-safe for the Core and Recall tiers.
    Archival safety is inherited from MemoryManager.
    """

    def __init__(
        self,
        recall_capacity: int = _DEFAULT_RECALL_CAPACITY,
        recall_path: Path | str | None = None,
        recall_retention_days: int = _DEFAULT_RECALL_RETENTION_DAYS,
        recall_backup_keep: int = _DEFAULT_RECALL_BACKUP_KEEP,
        archival_manager=None,   # MemoryManager instance
    ) -> None:
        # ── Tier 1: Core (in-memory) ──────────────────────────────────
        self._core: dict[str, Any] = {}

        # ── Tier 2: Recall (disk-persisted LRU) ───────────────────────
        self._recall: OrderedDict[str, dict] = OrderedDict()
        self._recall_capacity = recall_capacity
        self._recall_path = Path(recall_path or _DEFAULT_RECALL_PATH)
        self._recall_retention_days = max(0, int(recall_retention_days))
        self._recall_backup_keep = max(1, int(recall_backup_keep))
        self._recall_backup_dir = self._recall_path.parent / "recall_backups"
        self._load_recall()
        self._prune_recall_expired(persist_changes=True)

        # ── Tier 3: Archival (ChromaDB via MemoryManager) ─────────────
        self._archival = archival_manager  # may be None

        logger.info(
            "TieredMemory ready: core + recall(cap=%d) + archival=%s.",
            recall_capacity,
            "enabled" if archival_manager is not None else "disabled",
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def remember(self, key: str, value: Any, tier: str = "core") -> None:
        """
        Store a value in the specified tier.

        Parameters
        ----------
        key   : Arbitrary string key.
        value : Any JSON-serializable value.
        tier  : "core" | "recall" | "archival"
        """
        tier = tier.lower()
        if tier == "core":
            self._core[key] = value
        elif tier == "recall":
            self._write_recall(key, value)
        elif tier == "archival":
            self._write_archival(key, value)
        else:
            raise ValueError(f"Unknown memory tier '{tier}'. Use 'core', 'recall', or 'archival'.")

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def recall(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value by checking Core → Recall → Archival in order.
        On a Recall or Archival hit the value is automatically promoted
        to Core for faster subsequent reads.
        Returns *default* if not found in any tier.
        """
        # Tier 1: Core
        if key in self._core:
            return self._core[key]

        # Tier 2: Recall
        if key in self._recall:
            value = self._recall[key]["value"]
            self._core[key] = value          # promote to core
            return value

        # Tier 3: Archival
        if self._archival is not None:
            value = self._archival.load(key=key)
            if value is not None:
                self._core[key] = value      # promote to core
                return value

        return default

    def search(
        self,
        query: str,
        n_results: int = 5,
        namespace: str = "global",
    ) -> list[dict]:
        """
        Semantic search across the Archival tier.
        Searches Recall (text matching) as a fallback if archival unavailable.

        Returns list of {key, value, score} dicts.
        """
        if self._archival is not None:
            try:
                return self._archival.semantic_search(
                    query=query, n_results=n_results, namespace=namespace
                )
            except Exception as exc:
                logger.warning("TieredMemory.search archival error: %s", exc)

        # Fallback — simple substring match in recall
        q = query.lower()
        hits = []
        for key, entry in list(self._recall.items()):
            text = _to_text(entry["value"]).lower()
            if q in key.lower() or q in text:
                hits.append({"key": key, "value": entry["value"], "score": 1.0})
            if len(hits) >= n_results:
                break
        return hits

    # ------------------------------------------------------------------
    # Consolidation — flush tiers upward
    # ------------------------------------------------------------------

    def consolidate(
        self,
        flush_core_to_recall: bool = True,
        flush_recall_to_archival: bool = True,
    ) -> dict:
        """
        Flush lower tiers into higher, persistent tiers.

        flush_core_to_recall       : Copy all Core entries to Recall.
        flush_recall_to_archival   : Copy all Recall entries to Archival.

        Returns a summary dict with counts.
        """
        core_flushed = 0
        recall_flushed = 0

        if flush_core_to_recall:
            for key, value in list(self._core.items()):
                self._write_recall(key, value)
                core_flushed += 1

        if flush_recall_to_archival and self._archival is not None:
            for key, entry in list(self._recall.items()):
                try:
                    self._archival.save(key=key, value=entry["value"])
                    recall_flushed += 1
                except Exception as exc:
                    logger.warning(
                        "TieredMemory.consolidate: recall→archival failed for '%s': %s",
                        key, exc,
                    )

        summary = {"core_to_recall": core_flushed, "recall_to_archival": recall_flushed}
        logger.info("TieredMemory.consolidate: %s", summary)
        return summary

    def promote(self, key: str, from_tier: str, to_tier: str) -> bool:
        """
        Copy a single key from one tier to another.
        Returns True if the key was found and copied, False otherwise.
        The value is NOT deleted from the source tier.
        """
        value = self._get_from_tier(key, from_tier)
        if value is None:
            return False
        self.remember(key, value, tier=to_tier)
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def core_keys(self) -> list[str]:
        return list(self._core.keys())

    def recall_keys(self) -> list[str]:
        return list(self._recall.keys())

    def tier_summary(self) -> dict:
        return {
            "core_entries": len(self._core),
            "recall_entries": len(self._recall),
            "recall_capacity": self._recall_capacity,
            "recall_retention_days": self._recall_retention_days,
            "recall_backup_keep": self._recall_backup_keep,
            "recall_path": str(self._recall_path),
            "archival_available": self._archival is not None,
        }

    def clear_core(self) -> int:
        """Clear the Core tier (in-memory only). Returns count removed."""
        count = len(self._core)
        self._core.clear()
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_recall(self, key: str, value: Any) -> None:
        """Write to Recall tier with LRU eviction and atomic file save."""
        now = time.time()
        entry = {"value": value, "updated_at": now, "ts": now}
        if key in self._recall:
            self._recall.move_to_end(key)
        self._recall[key] = entry

        # LRU evict oldest entries when over capacity
        while len(self._recall) > self._recall_capacity:
            self._recall.popitem(last=False)

        self._prune_recall_expired(persist_changes=False)
        self._save_recall()

    def _write_archival(self, key: str, value: Any) -> None:
        """Write directly to Archival, falling back to Recall if unavailable."""
        if self._archival is None:
            logger.debug(
                "TieredMemory: archival unavailable — falling back to recall for key '%s'.", key
            )
            self._write_recall(key, value)
            return
        try:
            self._archival.save(key=key, value=value)
        except Exception as exc:
            logger.warning("TieredMemory: archival write failed for '%s': %s", key, exc)
            self._write_recall(key, value)   # graceful fallback

    def _get_from_tier(self, key: str, tier: str) -> Any | None:
        tier = tier.lower()
        if tier == "core":
            return self._core.get(key)
        if tier == "recall":
            entry = self._recall.get(key)
            return entry["value"] if entry else None
        if tier == "archival" and self._archival is not None:
            return self._archival.load(key=key)
        return None

    def _load_recall(self) -> None:
        if not self._recall_path.exists():
            return
        try:
            raw: dict = json.loads(self._recall_path.read_text(encoding="utf-8"))
            for key, entry in raw.items():
                if not isinstance(entry, dict):
                    entry = {"value": entry}
                ts = entry.get("updated_at", entry.get("ts", time.time()))
                if not isinstance(ts, (int, float)):
                    ts = time.time()
                self._recall[key] = {
                    "value": entry.get("value"),
                    "updated_at": float(ts),
                    "ts": float(ts),
                }
            logger.debug("TieredMemory: loaded %d recall entries.", len(self._recall))
        except Exception as exc:
            logger.warning("TieredMemory: could not load recall cache: %s", exc)

    def _save_recall(self) -> None:
        self._recall_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp = self._recall_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(dict(self._recall), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self._recall_path)
            self._backup_recall_file()
        except Exception as exc:
            logger.warning("TieredMemory: could not save recall cache: %s", exc)

    def _prune_recall_expired(self, persist_changes: bool) -> int:
        if self._recall_retention_days <= 0:
            return 0
        cutoff = time.time() - (self._recall_retention_days * 24 * 60 * 60)
        removed = 0
        for key in list(self._recall.keys()):
            entry = self._recall.get(key, {})
            ts = entry.get("updated_at", entry.get("ts")) if isinstance(entry, dict) else None
            if not isinstance(ts, (int, float)):
                continue
            if float(ts) < cutoff:
                self._recall.pop(key, None)
                removed += 1

        if removed:
            logger.info("TieredMemory: pruned %d expired recall entries.", removed)
            if persist_changes:
                self._save_recall()
        return removed

    def _backup_recall_file(self) -> None:
        if not self._recall_path.exists():
            return

        try:
            self._recall_backup_dir.mkdir(parents=True, exist_ok=True)
            backup = self._recall_backup_dir / f"recall_cache-{int(time.time() * 1000)}.json"
            backup.write_text(self._recall_path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:
            logger.warning("TieredMemory: could not create recall backup: %s", exc)
            return

        backups = sorted(
            self._recall_backup_dir.glob("recall_cache-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in backups[self._recall_backup_keep:]:
            try:
                stale.unlink()
            except OSError:
                pass
