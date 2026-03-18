"""
MemoryManager — Persistent and session memory for AetheerAI — An AI Master!!.
Supports key-value storage, list appending, JSON file persistence,
and optional semantic (vector) search via ChromaDB.

Fix 4 — Advanced Memory Management:
    When chromadb is installed (`pip install chromadb`), the manager
    automatically maintains a vector collection alongside the key-value
    store.  Agents can call `semantic_search(query, n_results)` to recall
    relevant past results via RAG — without needing to scan every key.

    If chromadb is not installed the manager degrades gracefully to the
    original flat key-value store with no loss of existing functionality.

Fix 6 — Memory Isolation (Namespacing):
    All operations accept an optional `namespace` parameter (default
    "global").  Keys are stored as "<namespace>:<key>" so agents operating
    under their own namespace cannot accidentally read or search another
    agent's memories.  Call `memory.scoped(agent_name)` to obtain a
    ScopedMemory helper that automatically injects the namespace — the rest
    of the codebase never has to think about it.

    The "global" namespace is explicitly shared; use it for team-level or
    system-wide state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── PyInstaller-aware path resolution (🔴 Fix 4) ──────────────────────────────
# When frozen as a .exe, __file__ points into sys._MEIPASS (temp dir).
# Mutable data files (the store, chroma db) must live next to the .exe instead.
def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Running as PyInstaller .exe — put data next to the executable
        return Path(sys.executable).parent / "aetheerai_data"
    # Normal execution — data lives alongside this source file
    return Path(__file__).parent

_MEMORY_FILE = _data_dir() / "memory_store.json"
_SCHEMA_VERSION = 2

_ENV_REQUIRE_VECTOR = "AETHEERAI_REQUIRE_VECTOR_MEMORY"
_ENV_RETENTION_DAYS = "AETHEERAI_MEMORY_RETENTION_DAYS"
_ENV_CLEANUP_INTERVAL_SEC = "AETHEERAI_MEMORY_CLEANUP_INTERVAL_SEC"
_ENV_BACKUP_INTERVAL_SEC = "AETHEERAI_MEMORY_BACKUP_INTERVAL_SEC"
_ENV_BACKUP_KEEP = "AETHEERAI_MEMORY_BACKUP_KEEP"


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("MemoryManager: invalid int for %s='%s', using %d", name, raw, default)
        return default
    return max(minimum, value)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}

# ── ChromaDB SQLite3 compatibility fix (🔴 Fix 5) ─────────────────────────────
# ChromaDB requires sqlite3 >= 3.35.0. Many Windows Python installs ship with
# an older version. Override it with pysqlite3-binary before chromadb loads.
try:
    __import__("pysqlite3")
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass  # pysqlite3-binary not installed; chromadb will use the system sqlite3

# ── Optional ChromaDB vector store ────────────────────────────────────────────
try:
    import chromadb  # type: ignore
    from chromadb.config import Settings as _CSettings  # type: ignore
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


class MemoryManager:
    """
    Dual-mode memory: in-memory dict + optional JSON persistence.
    Optional semantic vector memory via ChromaDB (Fix 4).

    Keys can hold any JSON-serializable value.
    Use `append` for list-based history keys (e.g. chat history).
    Use `semantic_search` for RAG-style recall of past task results.
    """

    def __init__(self, persist: bool = True, enable_vector: bool = True):
        self._store: dict[str, Any] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._persist = persist
        self._vector_collection = None

        data_dir = _data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        self._backup_dir = data_dir / "memory_backups"

        self._retention_days = _env_int(_ENV_RETENTION_DAYS, default=30, minimum=0)
        self._cleanup_interval_sec = _env_int(_ENV_CLEANUP_INTERVAL_SEC, default=120, minimum=0)
        self._backup_interval_sec = _env_int(_ENV_BACKUP_INTERVAL_SEC, default=3600, minimum=0)
        self._backup_keep = _env_int(_ENV_BACKUP_KEEP, default=24, minimum=1)
        self._require_vector_memory = _env_bool(_ENV_REQUIRE_VECTOR, default=False)
        self._last_cleanup_ts: float = 0.0
        self._last_backup_ts: float = 0.0

        # BLOCKER-6: Isolation mode — when enabled, only registered namespaces
        # are allowed, preventing agents from accidentally cross-reading memory.
        self._isolation_mode: bool = False
        self._registered_namespaces: set[str] = {"global"}  # global always allowed

        # OPT-3: Debounced flush — batch writes within a 500 ms window so rapid
        # consecutive saves don't each trigger a full fsync cycle.
        self._dirty: bool = False
        self._flush_lock = threading.Lock()
        self._flush_timer: threading.Timer | None = None

        if persist and _MEMORY_FILE.exists():
            self._load()

        # ── Initialise ChromaDB vector store (Fix 4) ─────────────────
        if enable_vector and _CHROMA_AVAILABLE:
            try:
                # Bug 2 fix: use _data_dir() so chroma persists next to the .exe,
                # never inside _MEIPASS (which PyInstaller deletes on shutdown).
                chroma_dir = str(data_dir / "chroma_store")
                client = chromadb.PersistentClient(
                    path=chroma_dir,
                    settings=_CSettings(anonymized_telemetry=False),
                )
                self._vector_collection = client.get_or_create_collection(
                    name="aetheerai_memory",
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(
                    "MemoryManager: ChromaDB vector store ready (%d docs).",
                    self._vector_collection.count(),
                )
            except Exception as exc:
                logger.warning("MemoryManager: ChromaDB init failed — %s", exc)
                self._vector_collection = None
        elif enable_vector and not _CHROMA_AVAILABLE:
            logger.info(
                "MemoryManager: chromadb not installed — vector search unavailable. "
                "Install with: pip install chromadb"
            )

        if self._require_vector_memory and self._vector_collection is None:
            raise RuntimeError(
                "MemoryManager: semantic memory is required but ChromaDB is unavailable. "
                "Install chromadb or unset AETHEERAI_REQUIRE_VECTOR_MEMORY."
            )

        self._repair_metadata()
        self.cleanup(force=True)
        self._repair_vector_index()

    # ------------------------------------------------------------------
    # Namespace helpers (Fix 6)
    # ------------------------------------------------------------------

    @staticmethod
    def _ns_key(key: str, namespace: str) -> str:
        """Build a namespaced storage key: '<namespace>:<key>'."""
        if namespace == "global" or not namespace:
            return key
        return f"{namespace}:{key}"

    def set_isolation_mode(self, enabled: bool) -> None:
        """BLOCKER-6: Enable/disable strict namespace isolation.

        When enabled, only namespaces that have been explicitly registered via
        ``register_namespace()`` are permitted.  Attempts to access an
        unregistered namespace raise ``PermissionError``.
        """
        self._isolation_mode = enabled
        logger.info("MemoryManager: isolation mode %s.", "ENABLED" if enabled else "disabled")

    def register_namespace(self, namespace: str) -> None:
        """BLOCKER-6: Whitelist a namespace so it can be used under isolation mode."""
        self._registered_namespaces.add(namespace)
        logger.debug("MemoryManager: registered namespace '%s'.", namespace)

    def _assert_namespace(self, namespace: str) -> None:
        """Raise PermissionError if isolation mode is active and namespace is unknown."""
        if self._isolation_mode and namespace not in self._registered_namespaces:
            raise PermissionError(
                f"MemoryManager: access to unregistered namespace '{namespace}' "
                "is blocked (isolation mode is active). "
                "Call register_namespace() first."
            )

    def scoped(self, namespace: str) -> "ScopedMemory":
        """
        Return a ScopedMemory proxy that automatically injects *namespace*
        into every operation.  Use this within agent contexts so agents can
        never accidentally read each other's private memories::

            mem = memory_manager.scoped(agent.name)
            mem.save("last_result", value)          # stored as "AgentName:last_result"
            mem.semantic_search("python error")     # only searches AgentName docs
        """
        return ScopedMemory(manager=self, namespace=namespace)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def save(
        self,
        key: str,
        value: Any,
        namespace: str = "global",
        ttl_seconds: int | None = None,
    ) -> None:
        """Store or overwrite a value by key inside *namespace*."""
        self._assert_namespace(namespace)  # BLOCKER-6
        ns_key = self._ns_key(key, namespace)
        self._store[ns_key] = value
        self._touch_meta(ns_key, value=value, namespace=namespace, ttl_seconds=ttl_seconds)
        self._schedule_flush()  # OPT-3: debounced instead of immediate
        self._vector_index(ns_key, value, namespace=namespace)
        self._maybe_run_cleanup()

    def load(self, key: str, default: Any = None, namespace: str = "global") -> Any:
        """Retrieve a value by key from *namespace*, returning *default* if absent."""
        self._assert_namespace(namespace)  # BLOCKER-6
        ns_key = self._ns_key(key, namespace)
        marker = object()
        value = self._store.get(ns_key, marker)
        if value is marker:
            return default
        if self._is_expired(ns_key):
            self.delete(key, namespace=namespace)
            return default
        self._maybe_run_cleanup()
        return value

    def append(
        self,
        key: str,
        value: Any,
        namespace: str = "global",
        ttl_seconds: int | None = None,
    ) -> None:
        """Append a value to a list stored at *key* in *namespace*."""
        self._assert_namespace(namespace)  # BLOCKER-6
        ns_key = self._ns_key(key, namespace)
        existing = self._store.get(ns_key, [])
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(value)
        self._store[ns_key] = existing
        self._touch_meta(ns_key, value=existing, namespace=namespace, ttl_seconds=ttl_seconds)
        self._schedule_flush()  # OPT-3
        self._vector_index(ns_key, existing, namespace=namespace)
        self._maybe_run_cleanup()

    def delete(self, key: str, namespace: str = "global") -> bool:
        """Remove a key from *namespace*. Returns True if it existed."""
        self._assert_namespace(namespace)  # BLOCKER-6
        ns_key = self._ns_key(key, namespace)
        if ns_key in self._store:
            del self._store[ns_key]
            self._meta.pop(ns_key, None)
            self._vector_delete(ns_key)
            self._schedule_flush()  # OPT-3
            return True
        return False

    def clear(self) -> None:
        """Wipe all memory (in-memory, persisted file, and vector store)."""
        self._store.clear()
        self._meta.clear()
        self._flush()
        if self._vector_collection is not None:
            try:
                # ChromaDB: delete all documents by fetching all ids
                all_ids = self._vector_collection.get()["ids"]
                if all_ids:
                    self._vector_collection.delete(ids=all_ids)
            except Exception as exc:
                logger.warning("MemoryManager: failed to clear vector store: %s", exc)
        logger.info("MemoryManager: all memory cleared.")

    def keys(self) -> list[str]:
        self._maybe_run_cleanup()
        return list(self._store.keys())

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the entire memory store."""
        self._maybe_run_cleanup()
        return dict(self._store)

    def semantic_status(self) -> dict[str, Any]:
        """Return semantic-memory backend and policy status for observability."""
        vector_docs = 0
        if self._vector_collection is not None:
            try:
                vector_docs = int(self._vector_collection.count())
            except Exception:
                vector_docs = -1
        return {
            "backend": "chromadb" if self._vector_collection is not None else "keyword_fallback",
            "vector_available": self._vector_collection is not None,
            "vector_required": self._require_vector_memory,
            "vector_docs": vector_docs,
            "retention_days": self._retention_days,
            "cleanup_interval_sec": self._cleanup_interval_sec,
            "backup_interval_sec": self._backup_interval_sec,
            "backup_keep": self._backup_keep,
        }

    def cleanup(self, force: bool = False) -> dict[str, int]:
        """Prune expired keys, stale metadata, and orphaned vector entries."""
        now = time.time()
        if (
            not force
            and self._cleanup_interval_sec > 0
            and (now - self._last_cleanup_ts) < self._cleanup_interval_sec
        ):
            return {"expired_removed": 0, "stale_meta_removed": 0, "stale_vector_removed": 0}

        expired_removed = 0
        stale_meta_removed = 0

        for ns_key in list(self._store.keys()):
            if self._is_expired(ns_key, now=now):
                self._store.pop(ns_key, None)
                self._meta.pop(ns_key, None)
                self._vector_delete(ns_key)
                expired_removed += 1

        for ns_key in list(self._meta.keys()):
            if ns_key not in self._store:
                self._meta.pop(ns_key, None)
                stale_meta_removed += 1

        stale_vector_removed = self._prune_stale_vector_docs()

        if expired_removed or stale_meta_removed:
            self._schedule_flush()

        self._last_cleanup_ts = now

        if expired_removed or stale_meta_removed or stale_vector_removed:
            logger.info(
                "MemoryManager.cleanup: expired=%d stale_meta=%d stale_vector=%d",
                expired_removed,
                stale_meta_removed,
                stale_vector_removed,
            )

        return {
            "expired_removed": expired_removed,
            "stale_meta_removed": stale_meta_removed,
            "stale_vector_removed": stale_vector_removed,
        }

    def create_backup(self, reason: str = "manual") -> Path | None:
        """Force-create a memory backup snapshot and prune old backup files."""
        if not self._persist:
            return None
        self._flush(backup=False)
        return self._maybe_backup(force=True, reason=reason)

    def all(self, namespace: str = "global") -> dict[str, Any]:
        """Return all key/value pairs visible in a namespace.

        For non-global namespaces, returned keys are de-prefixed so callers
        can work with bare logical keys.
        """
        self._assert_namespace(namespace)
        self._maybe_run_cleanup()
        if namespace == "global":
            return dict(self._store)

        prefix = f"{namespace}:"
        out: dict[str, Any] = {}
        for key, value in self._store.items():
            if key.startswith(prefix):
                out[key[len(prefix):]] = value
        return out

    def recent(self, namespace: str = "global", limit: int = 20) -> list[dict[str, Any]]:
        """Return up to *limit* most recent task-history entries for a namespace."""
        self._assert_namespace(namespace)
        self._maybe_run_cleanup()
        history = self.load("task_history", default=[], namespace=namespace)
        if not isinstance(history, list):
            return []
        return list(history[-max(1, limit):])

    def remember_task(
        self,
        *,
        namespace: str,
        task: str,
        output: str,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a task execution entry and index it for semantic recall."""
        self._assert_namespace(namespace)
        entry = {
            "task": task,
            "output": output[:5000],
            "success": success,
            "metadata": metadata or {},
        }
        self.append("task_history", entry, namespace=namespace)
        self.save("last_task_result", entry, namespace=namespace)

    def retrieval_context(self, query: str, namespace: str = "global", n_results: int = 3) -> str:
        """Return a compact text context assembled from semantic memory hits."""
        hits = self.semantic_search(query=query, n_results=n_results, namespace=namespace)
        if not hits:
            return ""
        lines: list[str] = []
        for idx, hit in enumerate(hits, start=1):
            key = str(hit.get("key", ""))
            val = str(hit.get("value", ""))
            lines.append(f"{idx}. {key}: {val[:400]}")
        return "\n".join(lines)

    def __contains__(self, key: str) -> bool:
        return key in self._store

    # ------------------------------------------------------------------
    # Semantic / vector search (Fix 4)
    # ------------------------------------------------------------------

    def semantic_search(
        self,
        query: str,
        n_results: int = 5,
        namespace: str = "global",
        where: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find the most semantically similar stored memories to *query*.

        Requires chromadb to be installed.  Falls back to a simple
        substring keyword search when the vector store is unavailable.

        Parameters
        ----------
        query     : Natural-language query string.
        n_results : Maximum number of results to return.
        namespace : Restrict results to this namespace (Fix 6).
                    Pass "global" or leave as default to search all namespaces.
        where     : Additional ChromaDB metadata filter dict (merged with
                    the namespace filter automatically).

        Returns
        -------
        List of dicts: [{"key": ..., "value": ..., "distance": ...}, ...]
        """
        # ── Build the effective metadata filter (Fix 6) ───────────────
        self._maybe_run_cleanup()
        effective_where: dict | None = None
        if namespace and namespace != "global":
            effective_where = {"namespace": {"$eq": namespace}}
            if where:
                # Merge caller's filter with the namespace restriction
                effective_where = {"$and": [effective_where, where]}
        elif where:
            effective_where = where

        # ── Vector path ───────────────────────────────────────────────
        if self._vector_collection is not None:
            try:
                count = self._vector_collection.count()
                if count == 0:
                    return []
                k = min(n_results, count)
                query_kwargs: dict[str, Any] = {
                    "query_texts": [query],
                    "n_results": k,
                    "include": ["documents", "metadatas", "distances"],
                }
                if effective_where:
                    query_kwargs["where"] = effective_where
                results = self._vector_collection.query(**query_kwargs)
                hits = []
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    hits.append({
                        "key": meta.get("key", ""),
                        "value": doc,
                        "distance": round(dist, 4),
                    })
                return hits
            except Exception as exc:
                logger.warning("MemoryManager: vector search failed — %s", exc)

        # ── Fallback: substring keyword search (namespace-aware) ──────
        logger.debug("MemoryManager: falling back to keyword search.")
        lower_q = query.lower()
        prefix = f"{namespace}:" if namespace and namespace != "global" else None
        matches = [
            {"key": k, "value": str(v), "distance": None}
            for k, v in self._store.items()
            if (prefix is None or k.startswith(prefix))
            and (lower_q in k.lower() or lower_q in str(v).lower())
        ]
        return matches[:n_results]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _flush(self, backup: bool = True) -> None:
        if not self._persist:
            return
        # Atomic write: write to .tmp then rename so an interrupted write never
        # leaves the store file blank or partially written (Bug 2 fix)
        tmp = Path(str(_MEMORY_FILE) + ".tmp")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "saved_at": time.time(),
            "store": self._store,
            "meta": self._meta,
        }
        try:
            tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, _MEMORY_FILE)
            if backup:
                self._maybe_backup()
        except OSError as exc:
            logger.error("MemoryManager: failed to persist memory: %s", exc)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _schedule_flush(self) -> None:
        """OPT-3: Debounced flush — coalesce rapid saves into one disk write (500 ms)."""
        if not self._persist:
            return
        with self._flush_lock:
            self._dirty = True
            if self._flush_timer is not None:
                self._flush_timer.cancel()
            self._flush_timer = threading.Timer(0.5, self._deferred_flush)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def _deferred_flush(self) -> None:
        """OPT-3: Runs on a background thread after the debounce window expires."""
        with self._flush_lock:
            self._flush_timer = None
            if not self._dirty:
                return
            self._dirty = False
        self._flush()  # actual disk write — outside the lock to avoid contention

    def _load(self) -> None:
        try:
            raw = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("store"), dict):
                self._store = dict(raw["store"])
                raw_meta = raw.get("meta", {})
                self._meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
            elif isinstance(raw, dict):
                # Backward compatibility with pre-schema flat files.
                self._store = dict(raw)
                self._meta = {}
            else:
                self._store = {}
                self._meta = {}
            logger.info("MemoryManager: loaded %d key(s) from store.", len(self._store))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("MemoryManager: failed to load memory: %s", exc)
            self._store = {}
            self._meta = {}

    def _vector_index(self, key: str, value: Any, namespace: str = "global") -> None:
        """Index a key-value pair in the vector store with namespace metadata (Fix 6)."""
        if self._vector_collection is None:
            return
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        # ChromaDB requires non-empty documents
        if not text or not text.strip():
            return
        try:
            self._vector_collection.upsert(
                ids=[key],
                documents=[text[:2000]],  # cap document size to 2 000 chars
                metadatas=[{"key": key, "namespace": namespace}],
            )
        except Exception as exc:
            logger.debug("MemoryManager: vector index failed for key '%s': %s", key, exc)

    def _vector_delete(self, key: str) -> None:
        if self._vector_collection is None:
            return
        try:
            self._vector_collection.delete(ids=[key])
        except Exception as exc:
            logger.debug("MemoryManager: vector delete failed for key '%s': %s", key, exc)

    def _prune_stale_vector_docs(self) -> int:
        if self._vector_collection is None:
            return 0
        try:
            all_ids = self._vector_collection.get().get("ids", [])
            stale_ids = [doc_id for doc_id in all_ids if doc_id not in self._store]
            if stale_ids:
                self._vector_collection.delete(ids=stale_ids)
            return len(stale_ids)
        except Exception as exc:
            logger.debug("MemoryManager: stale vector prune failed: %s", exc)
            return 0

    def _repair_vector_index(self) -> dict[str, int]:
        if self._vector_collection is None:
            return {"indexed": 0, "stale_removed": 0}

        indexed = 0
        for key, value in self._store.items():
            namespace = self._meta.get(key, {}).get("namespace")
            if not isinstance(namespace, str) or not namespace:
                namespace = key.split(":", 1)[0] if ":" in key else "global"
            self._vector_index(key, value, namespace=namespace)
            indexed += 1

        stale_removed = self._prune_stale_vector_docs()
        if indexed or stale_removed:
            logger.info(
                "MemoryManager: vector consistency repair indexed=%d stale_removed=%d",
                indexed,
                stale_removed,
            )
        return {"indexed": indexed, "stale_removed": stale_removed}

    def _repair_metadata(self) -> None:
        now = time.time()
        repaired = 0
        for key, value in list(self._store.items()):
            existing = self._meta.get(key, {})
            if not isinstance(existing, dict):
                existing = {}

            namespace = existing.get("namespace")
            if not isinstance(namespace, str) or not namespace:
                namespace = key.split(":", 1)[0] if ":" in key else "global"
                repaired += 1

            updated_at = existing.get("updated_at")
            if not isinstance(updated_at, (int, float)):
                updated_at = now
                repaired += 1

            checksum = existing.get("checksum")
            expected_checksum = self._value_checksum(value)
            if checksum != expected_checksum:
                checksum = expected_checksum
                repaired += 1

            expires_at = existing.get("expires_at")
            if expires_at is not None and not isinstance(expires_at, (int, float)):
                expires_at = None
                repaired += 1

            self._meta[key] = {
                "namespace": namespace,
                "updated_at": updated_at,
                "checksum": checksum,
                "expires_at": expires_at,
            }

        for key in list(self._meta.keys()):
            if key not in self._store:
                self._meta.pop(key, None)
                repaired += 1

        if repaired:
            logger.info("MemoryManager: repaired metadata for %d key(s).", repaired)

    def _touch_meta(
        self,
        ns_key: str,
        *,
        value: Any,
        namespace: str,
        ttl_seconds: int | None = None,
    ) -> None:
        now = time.time()
        expires_at: float | None = None
        if ttl_seconds is not None and ttl_seconds > 0:
            expires_at = now + float(ttl_seconds)
        elif ns_key in self._meta:
            existing_expiry = self._meta[ns_key].get("expires_at")
            if isinstance(existing_expiry, (int, float)):
                expires_at = float(existing_expiry)

        self._meta[ns_key] = {
            "namespace": namespace,
            "updated_at": now,
            "checksum": self._value_checksum(value),
            "expires_at": expires_at,
        }

    def _is_expired(self, ns_key: str, now: float | None = None) -> bool:
        now_ts = now if now is not None else time.time()
        meta = self._meta.get(ns_key, {})
        if not isinstance(meta, dict):
            return False

        expires_at = meta.get("expires_at")
        if isinstance(expires_at, (int, float)) and float(expires_at) <= now_ts:
            return True

        if self._retention_days <= 0:
            return False

        updated_at = meta.get("updated_at")
        if not isinstance(updated_at, (int, float)):
            return False

        retention_window = self._retention_days * 24 * 60 * 60
        return (now_ts - float(updated_at)) > retention_window

    @staticmethod
    def _value_checksum(value: Any) -> str:
        try:
            text = json.dumps(value, sort_keys=True, default=str)
        except Exception:
            text = str(value)
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

    def _maybe_run_cleanup(self) -> None:
        if self._cleanup_interval_sec <= 0:
            return
        now = time.time()
        if (now - self._last_cleanup_ts) >= self._cleanup_interval_sec:
            self.cleanup(force=True)

    def _maybe_backup(self, force: bool = False, reason: str = "scheduled") -> Path | None:
        if not self._persist:
            return None
        if not _MEMORY_FILE.exists():
            return None
        if self._backup_interval_sec <= 0 and not force:
            return None

        now = time.time()
        if (
            not force
            and self._last_backup_ts > 0
            and (now - self._last_backup_ts) < self._backup_interval_sec
        ):
            return None

        self._backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = self._backup_dir / f"memory_store-{int(now * 1000)}.json"
        try:
            backup_path.write_text(_MEMORY_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            self._last_backup_ts = now
            logger.debug("MemoryManager: backup created (%s, reason=%s)", backup_path.name, reason)
        except OSError as exc:
            logger.warning("MemoryManager: backup creation failed: %s", exc)
            return None

        backups = sorted(
            self._backup_dir.glob("memory_store-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in backups[self._backup_keep:]:
            try:
                stale.unlink()
            except OSError:
                pass

        return backup_path


# ---------------------------------------------------------------------------
# ScopedMemory — namespace-bound proxy  (Fix 6)
# ---------------------------------------------------------------------------

class ScopedMemory:
    """
    A thin proxy around MemoryManager that automatically injects a fixed
    namespace into every operation.

    Agents should use this rather than calling the global manager directly::

        mem = kernel.memory.scoped(agent.name)
        mem.save("result", "done")           # stored as "AgentName:result"
        mem.semantic_search("python error")  # only sees AgentName documents

    The "global" namespace is the shared team/system space — accessible via
    ``kernel.memory.scoped("global")`` or directly through ``kernel.memory``.
    """

    def __init__(self, manager: MemoryManager, namespace: str) -> None:
        self._m = manager
        self._ns = namespace

    @property
    def namespace(self) -> str:
        return self._ns

    def save(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self._m.save(key, value, namespace=self._ns, ttl_seconds=ttl_seconds)

    def load(self, key: str, default: Any = None) -> Any:
        return self._m.load(key, default, namespace=self._ns)

    def append(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self._m.append(key, value, namespace=self._ns, ttl_seconds=ttl_seconds)

    def delete(self, key: str) -> bool:
        return self._m.delete(key, namespace=self._ns)

    def semantic_search(
        self,
        query: str,
        n_results: int = 5,
        extra_filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Search only within this agent's own memory namespace."""
        return self._m.semantic_search(
            query,
            n_results=n_results,
            namespace=self._ns,
            where=extra_filter,
        )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._m.recent(namespace=self._ns, limit=limit)

    def remember_task(
        self,
        *,
        task: str,
        output: str,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._m.remember_task(
            namespace=self._ns,
            task=task,
            output=output,
            success=success,
            metadata=metadata,
        )

    def retrieval_context(self, query: str, n_results: int = 3) -> str:
        return self._m.retrieval_context(query=query, namespace=self._ns, n_results=n_results)

    def keys(self) -> list[str]:
        """Return bare keys (without namespace prefix) stored in this scope."""
        prefix = f"{self._ns}:" if self._ns != "global" else ""
        return [
            k[len(prefix):] if prefix and k.startswith(prefix) else k
            for k in self._m.keys()
            if not prefix or k.startswith(prefix)
        ]

    def __contains__(self, key: str) -> bool:
        return self._m._ns_key(key, self._ns) in self._m

