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

import json
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── PyInstaller-aware path resolution (🔴 Fix 4) ──────────────────────────────
# When frozen as a .exe, __file__ points into sys._MEIPASS (temp dir).
# Mutable data files (the store, chroma db) must live next to the .exe instead.
def _data_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Running as PyInstaller .exe — put data next to the executable
        return Path(sys.executable).parent / "aether_data"
    # Normal execution — data lives alongside this source file
    return Path(__file__).parent

_MEMORY_FILE = _data_dir() / "memory_store.json"

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
        self._persist = persist
        self._vector_collection = None

        if persist and _MEMORY_FILE.exists():
            self._load()

        # ── Initialise ChromaDB vector store (Fix 4) ─────────────────
        if enable_vector and _CHROMA_AVAILABLE:
            try:
                # Bug 2 fix: use _data_dir() so chroma persists next to the .exe,
                # never inside _MEIPASS (which PyInstaller deletes on shutdown).
                chroma_dir = str(_data_dir() / "chroma_store")
                client = chromadb.PersistentClient(
                    path=chroma_dir,
                    settings=_CSettings(anonymized_telemetry=False),
                )
                self._vector_collection = client.get_or_create_collection(
                    name="aether_memory",
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

    # ------------------------------------------------------------------
    # Namespace helpers (Fix 6)
    # ------------------------------------------------------------------

    @staticmethod
    def _ns_key(key: str, namespace: str) -> str:
        """Build a namespaced storage key: '<namespace>:<key>'."""
        if namespace == "global" or not namespace:
            return key
        return f"{namespace}:{key}"

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

    def save(self, key: str, value: Any, namespace: str = "global") -> None:
        """Store or overwrite a value by key inside *namespace*."""
        ns_key = self._ns_key(key, namespace)
        self._store[ns_key] = value
        self._flush()
        self._vector_index(ns_key, value, namespace=namespace)

    def load(self, key: str, default: Any = None, namespace: str = "global") -> Any:
        """Retrieve a value by key from *namespace*, returning *default* if absent."""
        return self._store.get(self._ns_key(key, namespace), default)

    def append(self, key: str, value: Any, namespace: str = "global") -> None:
        """Append a value to a list stored at *key* in *namespace*."""
        ns_key = self._ns_key(key, namespace)
        existing = self._store.get(ns_key, [])
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(value)
        self._store[ns_key] = existing
        self._flush()

    def delete(self, key: str, namespace: str = "global") -> bool:
        """Remove a key from *namespace*. Returns True if it existed."""
        ns_key = self._ns_key(key, namespace)
        if ns_key in self._store:
            del self._store[ns_key]
            self._flush()
            return True
        return False

    def clear(self) -> None:
        """Wipe all memory (in-memory, persisted file, and vector store)."""
        self._store.clear()
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
        return list(self._store.keys())

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the entire memory store."""
        return dict(self._store)

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

    def save(self, key: str, value: Any) -> None:
        self._m.save(key, value, namespace=self._ns)

    def load(self, key: str, default: Any = None) -> Any:
        return self._m.load(key, default, namespace=self._ns)

    def append(self, key: str, value: Any) -> None:
        self._m.append(key, value, namespace=self._ns)

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

