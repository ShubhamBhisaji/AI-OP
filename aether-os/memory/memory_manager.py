"""
MemoryManager — Persistent and session memory for the Aether OS.
Supports key-value storage, list appending, JSON file persistence,
and optional semantic (vector) search via ChromaDB.

Fix 4 — Advanced Memory Management:
    When chromadb is installed (`pip install chromadb`), the manager
    automatically maintains a vector collection alongside the key-value
    store.  Agents can call `semantic_search(query, n_results)` to recall
    relevant past results via RAG — without needing to scan every key.

    If chromadb is not installed the manager degrades gracefully to the
    original flat key-value store with no loss of existing functionality.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_FILE = Path(__file__).parent / "memory_store.json"

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
                chroma_dir = str(Path(__file__).parent / "chroma_store")
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
    # Core operations
    # ------------------------------------------------------------------

    def save(self, key: str, value: Any) -> None:
        """Store or overwrite a value by key. Indexes in vector store if text."""
        self._store[key] = value
        self._flush()
        self._vector_index(key, value)

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
        where     : Optional ChromaDB metadata filter dict.

        Returns
        -------
        List of dicts: [{"key": ..., "value": ..., "distance": ...}, ...]
        """
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
                if where:
                    query_kwargs["where"] = where
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

        # ── Fallback: substring keyword search ────────────────────────
        logger.debug("MemoryManager: falling back to keyword search.")
        lower_q = query.lower()
        matches = [
            {"key": k, "value": str(v), "distance": None}
            for k, v in self._store.items()
            if lower_q in k.lower() or lower_q in str(v).lower()
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

    def _vector_index(self, key: str, value: Any) -> None:
        """Index a key-value pair in the vector store (when available)."""
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
                metadatas=[{"key": key}],
            )
        except Exception as exc:
            logger.debug("MemoryManager: vector index failed for key '%s': %s", key, exc)

