"""KnowledgeLoader — Inject domain knowledge into AetheerAI agents.

This is NOT machine learning training. It loads company data (documents, text,
URLs) into the agent's memory namespace where it becomes searchable via
MemoryManager's ChromaDB vector search.

Flow:
    1. Load files / text / URLs → chunk into segments
    2. Store in agent's scoped memory namespace
    3. Agent uses semantic_search() during task execution to recall knowledge

Reuses the existing MemoryManager (which already handles ChromaDB, vector
embeddings, persistence, and namespacing).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 500          # characters per chunk
_CHUNK_OVERLAP = 50        # overlap between chunks for context continuity
_MAX_FILE_SIZE = 10_000_000  # 10 MB limit per file
_SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".json", ".csv", ".log", ".yml", ".yaml", ".html"})


class KnowledgeLoader:
    """
    Load domain knowledge into an agent's memory for retrieval-augmented generation.

    Usage
    -----
    loader = KnowledgeLoader(memory_manager)
    loader.load_files("sales_agent", ["/data/products.json", "/data/faq.txt"])
    loader.load_text("sales_agent", "pricing", "Our basic plan starts at $29/mo...")
    results = loader.search("sales_agent", "what is the pricing?")
    """

    def __init__(self, memory_manager: Any) -> None:
        self._memory = memory_manager

    def load_files(self, agent_name: str, file_paths: list[str | Path]) -> dict[str, Any]:
        """Load one or more files into the agent's knowledge base."""
        loaded = []
        errors = []

        for path in file_paths:
            path = Path(path)
            if not path.exists():
                errors.append(f"File not found: {path}")
                continue

            if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                errors.append(f"Unsupported file type: {path.suffix} ({path.name})")
                continue

            if path.stat().st_size > _MAX_FILE_SIZE:
                errors.append(f"File too large (>{_MAX_FILE_SIZE // 1_000_000}MB): {path.name}")
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if path.suffix.lower() == ".json":
                    content = self._flatten_json(content)
                elif path.suffix.lower() == ".csv":
                    content = self._flatten_csv(content)

                chunk_count = self._store_chunked(agent_name, f"file:{path.name}", content)
                loaded.append({"file": path.name, "chunks": chunk_count})
                logger.info("KnowledgeLoader: loaded %s (%d chunks) for agent '%s'",
                            path.name, chunk_count, agent_name)
            except Exception as exc:
                errors.append(f"Error reading {path.name}: {exc}")

        return {"loaded": loaded, "errors": errors}

    def load_text(self, agent_name: str, key: str, content: str) -> dict[str, Any]:
        """Directly inject text content into the agent's knowledge base."""
        if not content.strip():
            return {"error": "Content is empty."}

        chunk_count = self._store_chunked(agent_name, f"text:{key}", content)
        logger.info("KnowledgeLoader: loaded text '%s' (%d chunks) for agent '%s'",
                     key, chunk_count, agent_name)
        return {"key": key, "chunks": chunk_count}

    def load_url(self, agent_name: str, url: str) -> dict[str, Any]:
        """Fetch a URL and store its content in the agent's knowledge base."""
        import urllib.request

        if not url.startswith(("http://", "https://")):
            return {"error": f"Invalid URL: {url}"}

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AetheerAI-KnowledgeLoader/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return {"error": f"Failed to fetch {url}: {exc}"}

        # Strip HTML tags for cleaner text
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return {"error": "URL returned empty content."}

        chunk_count = self._store_chunked(agent_name, f"url:{url[:100]}", text)
        logger.info("KnowledgeLoader: loaded URL '%s' (%d chunks) for agent '%s'",
                     url[:60], chunk_count, agent_name)
        return {"url": url, "chunks": chunk_count}

    def search(self, agent_name: str, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Semantic search through the agent's knowledge base."""
        scope = self._get_scope(agent_name)
        if scope is None or not hasattr(scope, "semantic_search"):
            return []
        try:
            return scope.semantic_search(query, n_results=n_results)
        except Exception as exc:
            logger.warning("KnowledgeLoader: search failed for '%s': %s", agent_name, exc)
            return []

    def list_knowledge(self, agent_name: str) -> list[str]:
        """List all knowledge keys stored for an agent."""
        scope = self._get_scope(agent_name)
        if scope is None:
            return []
        try:
            if hasattr(scope, "keys"):
                return [k for k in scope.keys() if k.startswith(("file:", "text:", "url:"))]
            if hasattr(scope, "list_keys"):
                return [k for k in scope.list_keys() if k.startswith(("file:", "text:", "url:"))]
        except Exception:
            pass
        return []

    def clear_knowledge(self, agent_name: str) -> int:
        """Remove all knowledge entries for an agent. Returns count removed."""
        keys = self.list_knowledge(agent_name)
        scope = self._get_scope(agent_name)
        if scope is None:
            return 0
        removed = 0
        for key in keys:
            try:
                if hasattr(scope, "delete"):
                    scope.delete(key)
                    removed += 1
            except Exception:
                pass
        return removed

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_scope(self, agent_name: str) -> Any:
        """Get or create a scoped memory for the agent."""
        if hasattr(self._memory, "scoped"):
            return self._memory.scoped(agent_name)
        return self._memory

    def _store_chunked(self, agent_name: str, key: str, content: str) -> int:
        """Chunk text and store each chunk under the agent's memory namespace."""
        chunks = self._chunk_text(content)
        scope = self._get_scope(agent_name)
        if scope is None:
            return 0

        for i, chunk in enumerate(chunks):
            chunk_key = f"{key}:chunk_{i:04d}"
            try:
                if hasattr(scope, "save"):
                    scope.save(chunk_key, chunk)
            except Exception as exc:
                logger.debug("KnowledgeLoader: failed to store chunk %s: %s", chunk_key, exc)

        return len(chunks)

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        """Split text into overlapping chunks for vector search."""
        if len(text) <= _CHUNK_SIZE:
            return [text] if text.strip() else []

        chunks = []
        start = 0
        while start < len(text):
            end = start + _CHUNK_SIZE
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - _CHUNK_OVERLAP
        return chunks

    @staticmethod
    def _flatten_json(content: str) -> str:
        """Convert JSON to a readable text representation."""
        try:
            data = json.loads(content)
            return json.dumps(data, indent=2, ensure_ascii=False, default=str)
        except json.JSONDecodeError:
            return content

    @staticmethod
    def _flatten_csv(content: str) -> str:
        """Convert CSV to a readable text representation."""
        try:
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            if not rows:
                return content

            headers = rows[0]
            lines = []
            for row in rows[1:]:
                parts = [f"{h}: {v}" for h, v in zip(headers, row) if v.strip()]
                lines.append(", ".join(parts))
            return "\n".join(lines)
        except Exception:
            return content
