"""knowledge_manager.py — Unified persistent knowledge subsystem.

Wraps the existing KnowledgeLoader with:
- Structured folder layout (documents/, embeddings/, config.json)
- Automatic indexing of documents placed in the documents/ folder
- Manifest-aware loading (reads knowledge.documents from agent_manifest.json)
- Exportable knowledge package (ships WITH the agent)

Folder Layout
-------------
knowledge/
    documents/          ← drop files here; auto-indexed on startup
    embeddings/         ← ChromaDB persistence directory
    config.json         ← tuning parameters (chunk size, model, etc.)

Usage
-----
mgr = KnowledgeManager(agent_name="store_bot", base_dir="knowledge")
mgr.index_documents()          # index everything in documents/
mgr.load_text("store_bot", "custom context", "We ship in 3-5 days…")
results = mgr.search("store_bot", "what is the return policy?")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = {
    "version": "1.0",
    "chunk_size": 500,
    "chunk_overlap": 50,
    "embedding_model": "text-embedding-3-small",
    "vector_store": "chromadb",
    "persist_directory": "knowledge/embeddings",
    "document_directory": "knowledge/documents",
    "supported_extensions": [".txt", ".md", ".json", ".csv", ".pdf", ".html", ".yml"],
    "max_file_size_mb": 10,
    "auto_index_on_load": True,
}


class KnowledgeManager:
    """
    Persistent, portable knowledge subsystem for AetheerAI agents.

    Parameters
    ----------
    agent_name  : Name of the agent that owns this knowledge base.
    base_dir    : Root path of the knowledge folder (default: ./knowledge).
    memory_manager : MemoryManager instance for vector embedding storage.
    """

    def __init__(
        self,
        agent_name: str,
        base_dir: str | Path = "knowledge",
        memory_manager: Any | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.base_dir = Path(base_dir)
        self._memory_manager = memory_manager
        self._config = self._load_config()
        self._ensure_dirs()
        self._loader: Any | None = None  # KnowledgeLoader, initialised lazily

    # ── Directory management ────────────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        (self.base_dir / "documents").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "embeddings").mkdir(parents=True, exist_ok=True)

    @property
    def documents_dir(self) -> Path:
        return self.base_dir / "documents"

    @property
    def embeddings_dir(self) -> Path:
        return self.base_dir / "embeddings"

    @property
    def config_path(self) -> Path:
        return self.base_dir / "config.json"

    # ── Config ───────────────────────────────────────────────────────────────

    def _load_config(self) -> dict[str, Any]:
        config = dict(_DEFAULT_CONFIG)
        cfg_path = self.base_dir / "config.json"
        if cfg_path.exists():
            try:
                loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config.update(loaded)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("KnowledgeManager: could not read config.json: %s", exc)
        return config

    def save_config(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._config, indent=2), encoding="utf-8"
        )

    # ── Loader access ────────────────────────────────────────────────────────

    def _get_loader(self) -> Any:
        if self._loader is None and self._memory_manager is not None:
            try:
                from knowledge.loader import KnowledgeLoader
                self._loader = KnowledgeLoader(self._memory_manager)
            except Exception as exc:
                logger.warning("KnowledgeManager: could not initialise KnowledgeLoader: %s", exc)
        return self._loader

    # ── Document indexing ────────────────────────────────────────────────────

    def index_documents(self) -> dict[str, Any]:
        """
        Scan documents/ and load every supported file into the agent's memory.

        Returns a summary dict with counts of files loaded and skipped.
        """
        extensions = frozenset(self._config.get("supported_extensions", []))
        max_mb = float(self._config.get("max_file_size_mb", 10))
        files: list[Path] = []

        for path in sorted(self.documents_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if extensions and path.suffix.lower() not in extensions:
                logger.debug("KnowledgeManager: skipping unsupported file: %s", path.name)
                continue
            if path.stat().st_size > max_mb * 1_000_000:
                logger.warning("KnowledgeManager: skipping oversized file: %s", path.name)
                continue
            files.append(path)

        if not files:
            logger.info("KnowledgeManager: no documents to index in %s", self.documents_dir)
            return {"loaded": 0, "skipped": 0, "files": []}

        loader = self._get_loader()
        if loader is None:
            logger.warning(
                "KnowledgeManager: no memory manager attached — cannot index documents."
            )
            return {"loaded": 0, "skipped": len(files), "files": [], "error": "no_memory_manager"}

        result = loader.load_files(self.agent_name, files)
        loaded = result.get("loaded", 0)
        skipped = result.get("skipped", 0)
        logger.info(
            "KnowledgeManager: indexed %d file(s) for agent '%s' (%d skipped).",
            loaded, self.agent_name, skipped,
        )
        return result

    def load_text(self, topic: str, text: str) -> dict[str, Any]:
        """Inject a raw text string into the agent's knowledge."""
        loader = self._get_loader()
        if loader is None:
            return {"error": "no_memory_manager"}
        return loader.load_text(self.agent_name, topic, text)

    def load_urls(self, urls: list[str]) -> dict[str, Any]:
        """Crawl and inject web content."""
        loader = self._get_loader()
        if loader is None:
            return {"error": "no_memory_manager"}
        return loader.load_urls(self.agent_name, urls)

    def search(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Semantic search over the agent's knowledge base."""
        loader = self._get_loader()
        if loader is None:
            return []
        try:
            return loader.search(self.agent_name, query, n_results=n_results)
        except Exception as exc:
            logger.warning("KnowledgeManager: search failed: %s", exc)
            return []

    # ── Manifest-aware loading ────────────────────────────────────────────────

    def load_from_manifest(self, manifest: Any) -> dict[str, Any]:
        """
        Load knowledge sources declared in an AgentManifest.

        Reads manifest.knowledge.documents and manifest.knowledge.urls.
        """
        knowledge_block = getattr(manifest, "knowledge", {}) or {}
        doc_paths = knowledge_block.get("documents", [])
        urls = knowledge_block.get("urls", [])
        summary: dict[str, Any] = {"documents": {}, "urls": {}}

        if doc_paths:
            loader = self._get_loader()
            if loader is not None:
                summary["documents"] = loader.load_files(
                    self.agent_name,
                    [Path(p) for p in doc_paths if Path(p).exists()],
                )

        if urls:
            summary["urls"] = self.load_urls(urls)

        return summary

    # ── Export package creation ──────────────────────────────────────────────

    def export_package(self, dest: str | Path) -> list[str]:
        """
        Copy the knowledge package (documents + config) to a destination folder.

        The embeddings/ directory is intentionally excluded — they are
        regenerated at runtime because vector store paths are environment-specific.

        Returns a list of copied file paths.
        """
        import shutil

        dest = Path(dest)
        (dest / "documents").mkdir(parents=True, exist_ok=True)
        copied: list[str] = []

        # Copy config.json
        if self.config_path.exists():
            shutil.copy2(self.config_path, dest / "config.json")
            copied.append("knowledge/config.json")

        # Copy documents
        for doc in sorted(self.documents_dir.iterdir()):
            if doc.is_file() and not doc.name.startswith("."):
                shutil.copy2(doc, dest / "documents" / doc.name)
                copied.append(f"knowledge/documents/{doc.name}")

        # Write a README
        readme = (
            "# Knowledge Package\n\n"
            "This folder ships with the agent and is automatically indexed on first run.\n\n"
            "## Add custom documents\n"
            "Drop `.txt`, `.pdf`, `.csv`, or `.md` files into `documents/` and restart the agent.\n\n"
            "## Embeddings\n"
            "The `embeddings/` directory is generated automatically at runtime.\n"
        )
        (dest / "README.md").write_text(readme, encoding="utf-8")
        copied.append("knowledge/README.md")

        return copied

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        doc_count = sum(
            1 for p in self.documents_dir.iterdir()
            if p.is_file() and not p.name.startswith(".")
        ) if self.documents_dir.exists() else 0
        embedding_count = sum(
            1 for p in self.embeddings_dir.iterdir()
        ) if self.embeddings_dir.exists() else 0
        return {
            "agent": self.agent_name,
            "documents": doc_count,
            "embeddings_present": embedding_count > 0,
            "config": self._config,
        }
